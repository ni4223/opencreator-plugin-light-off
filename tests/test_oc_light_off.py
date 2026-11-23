import importlib.util
import json
import pathlib
import unittest
from unittest import mock

ROOT = pathlib.Path(__file__).resolve().parents[1]
SPEC = importlib.util.spec_from_file_location(
    "oc_light_off", ROOT / "klippy" / "oc_light_off.py")
oc_light_off = importlib.util.module_from_spec(SPEC)
SPEC.loader.exec_module(oc_light_off)

LIGHT_OFF = "SET_LED LED=chamber_led RED=0 GREEN=0 BLUE=0 WHITE=0"
LIGHT_ON = "SET_LED LED=chamber_led RED=1 GREEN=1 BLUE=1 WHITE=1"
ON = {"oc_auto_light": 1}
# Short names for the print_stats events Kalico sends.
EVENTS = {"start": "start_printing", "pause": "paused_printing",
          "complete": "complete_printing", "cancel": "cancelled_printing",
          "error": "error_printing", "reset": "reset"}


class FakeGCmd:
    def __init__(self, **params):
        self.params, self.replies = params, []

    def get_float(self, name, default=None, minval=None, maxval=None):
        return float(self.params.get(name, default))

    def respond_info(self, msg):
        self.replies.append(msg)


class FakeReactor:
    NOW = 0.

    def __init__(self):
        self.callbacks = []
        self.register_timer = mock.Mock()

    def register_callback(self, callback, waketime=NOW):
        self.callbacks.append(callback)

    def run_callbacks(self):
        callbacks, self.callbacks = self.callbacks, []
        for callback in callbacks:
            callback(0.)


class FakePrinter:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.handlers = {}
        self.shutdown = False
        self.reactor = FakeReactor()

    def add_object(self, name, obj):
        self.objects[name] = obj

    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)

    def register_event_handler(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def send_event(self, event, *params):
        for callback in self.handlers.get(event, []):
            callback(*params)

    def get_reactor(self):
        return self.reactor

    def is_shutdown(self):
        return self.shutdown


class AutoLightTest(unittest.TestCase):
    def make(self, saved=None, default=None):
        self.gcode = mock.Mock()
        self.lock = mock.Mock()
        self.lock.test.return_value = False
        self.gcode.get_mutex.return_value = self.lock
        objects = {"gcode": self.gcode, "print_stats": object(),
                   "led chamber_led": object()}
        if saved is not None:
            objects["save_variables"] = mock.Mock(allVariables=dict(saved))
        self.printer = FakePrinter(objects)
        config = mock.Mock()
        config.get_printer.return_value = self.printer
        config.get.side_effect = lambda key, default=None: default
        config.getboolean.side_effect = lambda key, d=None: (
            default if key == "auto_light_default" and default is not None
            else d)
        self.plugin = oc_light_off.load_config(config)
        self.printer.send_event("klippy:ready")
        self.switch = self.printer.lookup_object("output_pin auto_light")

    def events(self, *names):
        """Send print_stats events, then let queued light changes run."""
        for name in names:
            self.printer.send_event("print_stats:" + EVENTS[name])
        self.printer.reactor.run_callbacks()

    def scripts(self):
        return [c.args[0] for c in self.gcode.run_script.call_args_list]

    def test_on_by_default_and_shown_as_output_pin(self):
        self.make(saved={})
        self.assertIsNotNone(self.switch)
        self.assertEqual(self.switch.get_status(0.), {"value": 1.})
        self.events("start", "complete")
        self.assertEqual(self.scripts(), [LIGHT_ON, LIGHT_OFF])

    def test_no_polling(self):
        self.make(saved=ON)
        self.printer.reactor.register_timer.assert_not_called()

    def test_light_on_before_print_start_takes_the_lock(self):
        # start_printing comes just before print start (homing, heating) runs
        # as one long command: SET_LED must run in the event, not after it.
        self.make(saved=ON)
        self.printer.send_event("print_stats:start_printing")
        self.assertEqual(self.scripts(), [LIGHT_ON])
        self.assertEqual(self.printer.reactor.callbacks, [])

    def test_light_waits_while_a_command_holds_the_lock(self):
        # SET_LED inside a command that holds the lock could wait forever.
        self.make(saved=ON)
        self.events("start")
        self.lock.test.return_value = True
        self.printer.send_event("print_stats:complete_printing")
        self.assertEqual(self.scripts(), [LIGHT_ON])
        self.printer.reactor.run_callbacks()
        self.assertEqual(self.scripts(), [LIGHT_ON, LIGHT_OFF])

    def test_turned_off_does_nothing(self):
        self.make(saved={"oc_auto_light": 0})
        self.assertEqual(self.switch.get_status(0.), {"value": 0.})
        self.events("start", "complete")
        self.assertEqual(self.scripts(), [])

    def test_set_pin_turns_off_and_saves(self):
        self.make(saved={})
        cmd = FakeGCmd(VALUE=0)
        self.switch.cmd_set(cmd)
        self.assertFalse(self.switch.enabled)
        self.gcode.run_script_from_command.assert_called_once_with(
            "SAVE_VARIABLE VARIABLE=oc_auto_light VALUE=0")
        self.assertIn("disabled", cmd.replies[0])

    def test_one_switch_and_status_command(self):
        self.make()
        self.gcode.register_mux_command.assert_called_once_with(
            "SET_PIN", "PIN", "auto_light", self.switch.cmd_set)
        names = [c.args[0] for c in self.gcode.register_command.call_args_list]
        self.assertIn("OC_AUTO_LIGHT_STATUS", names)

    def test_set_pin_turns_on_and_saves(self):
        self.make(saved={}, default=False)
        cmd = FakeGCmd(VALUE=1)
        self.switch.cmd_set(cmd)
        self.assertTrue(self.switch.enabled)
        self.gcode.run_script_from_command.assert_called_once_with(
            "SAVE_VARIABLE VARIABLE=oc_auto_light VALUE=1")
        self.assertIn("enabled", cmd.replies[0])

    def test_saved_value_wins_over_default(self):
        self.make(saved={"oc_auto_light": 1}, default=False)
        self.assertTrue(self.switch.enabled)
        self.make(saved={"oc_auto_light": 0}, default=True)
        self.assertFalse(self.switch.enabled)

    def test_light_on_for_next_print_after_any_end(self):
        self.make(saved=ON)
        self.events("start", "complete", "start", "pause", "cancel",
                    "start", "cancel", "error", "start", "pause", "reset",
                    "start")
        self.assertEqual(self.scripts(), [LIGHT_ON, LIGHT_OFF] + [LIGHT_ON] * 4)

    def test_cancel_leaves_light_on(self):
        # CANCEL_PRINT on a running print: paused, then cancelled.
        self.make(saved=ON)
        self.events("start", "pause", "cancel")
        self.assertEqual(self.scripts(), [LIGHT_ON])

    def test_error_leaves_light_on(self):
        # OpenCreator's on_error_gcode is CANCEL_PRINT: cancelled, then error.
        self.make(saved=ON)
        self.events("start", "cancel", "error")
        self.assertEqual(self.scripts(), [LIGHT_ON])

    def test_print_that_cancels_itself_leaves_light_on(self):
        # CANCEL_PRINT from print start (no build plate): cancelled, then
        # complete when virtual_sdcard stops reading the closed file.
        self.make(saved=ON)
        self.events("start", "cancel", "complete")
        self.assertEqual(self.scripts(), [LIGHT_ON])

    def test_pause_and_resume_leave_light_alone(self):
        self.make(saved=ON)
        self.events("start")
        self.events("pause", "start", "pause", "start")
        self.assertEqual(self.scripts(), [LIGHT_ON])

    def test_reset_mid_print_leaves_light_on(self):
        # SDCARD_RESET_FILE on a running print: paused, then reset, no cancel.
        self.make(saved=ON)
        self.events("start", "pause", "reset", "complete")
        self.assertEqual(self.scripts(), [LIGHT_ON])

    def test_reset_before_a_print_does_nothing(self):
        # SDCARD_PRINT_FILE resets print_stats before the print starts.
        self.make(saved=ON)
        self.events("reset", "start")
        self.assertEqual(self.scripts(), [LIGHT_ON])

    def test_no_light_change_without_a_print(self):
        self.make(saved=ON)
        self.events("complete", "reset", "cancel", "pause", "error")
        self.assertEqual(self.scripts(), [])

    def test_turned_on_mid_print_still_turns_off_at_end(self):
        self.make(saved={}, default=False)
        self.events("start")
        self.switch.cmd_set(FakeGCmd(VALUE=1))
        self.events("complete")
        self.assertEqual(self.scripts(), [LIGHT_OFF])

    def test_skips_when_shut_down(self):
        self.make(saved=ON)
        self.printer.shutdown = True
        self.events("start", "complete")
        self.assertEqual(self.scripts(), [])

    def test_set_led_failure_is_logged(self):
        self.make(saved=ON)
        self.gcode.run_script.side_effect = RuntimeError("Unknown LED")
        with self.assertLogs(level="ERROR"):
            self.events("start")
        with self.assertLogs(level="ERROR"):
            self.events("complete")

    def test_status_command(self):
        self.make(saved=ON)
        cmd = FakeGCmd()
        self.plugin.cmd_status(cmd)
        self.assertEqual(cmd.replies, ["Auto light: ON (LED chamber_led)"])

    def test_manifest_files_exist(self):
        m = json.loads((ROOT / "opencreator-plugin.json").read_text())
        for rel in m["klippy_extras"] + [m["klipper_config"]]:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertRegex(m["id"], r"^[a-z0-9_-]{2,41}$")


if __name__ == "__main__":
    unittest.main()

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


class FakeGCmd:
    def __init__(self, **params):
        self.params, self.replies = params, []

    def get_float(self, name, default=None, minval=None, maxval=None):
        return float(self.params.get(name, default))

    def respond_info(self, msg):
        self.replies.append(msg)


class FakePrinter:
    def __init__(self, objects):
        self.objects = dict(objects)
        self.handlers = {}
        self.shutdown = False
        self.reactor = mock.Mock(NOW=0.)

    def add_object(self, name, obj):
        self.objects[name] = obj

    def lookup_object(self, name, default=None):
        return self.objects.get(name, default)

    def register_event_handler(self, event, callback):
        self.handlers.setdefault(event, []).append(callback)

    def send_event(self, event):
        for callback in self.handlers.get(event, []):
            callback()

    def get_reactor(self):
        return self.reactor

    def is_shutdown(self):
        return self.shutdown


class LightOffTest(unittest.TestCase):
    def make(self, saved=None, default=False):
        self.gcode = mock.Mock()
        self.stats = mock.Mock()
        self.state = "standby"
        self.stats.get_status.side_effect = lambda eventtime: {"state": self.state}
        objects = {"gcode": self.gcode, "print_stats": self.stats,
                   "led chamber_led": object()}
        if saved is not None:
            objects["save_variables"] = mock.Mock(allVariables=saved)
        self.printer = FakePrinter(objects)
        config = mock.Mock()
        config.get_printer.return_value = self.printer
        config.get.side_effect = lambda key, default=None: default
        config.getboolean.side_effect = lambda key, d=None: (
            default if key == "light_off_on_end_default" else d)
        self.plugin = oc_light_off.load_config(config)
        self.printer.send_event("klippy:ready")
        self.switch = self.printer.lookup_object("output_pin light_off_on_end")

    def poll_through(self, *states):
        for state in states:
            self.state = state
            self.plugin._poll(0.)

    def light_off_calls(self):
        return [c for c in self.gcode.run_script.call_args_list
                if c.args == (LIGHT_OFF,)]

    def test_off_by_default_and_shown_as_output_pin(self):
        self.make()
        self.assertIsNotNone(self.switch)
        self.assertEqual(self.switch.get_status(0.), {"value": 0.})
        self.poll_through("printing", "complete")
        self.assertEqual(self.light_off_calls(), [])

    def test_registers_set_pin_and_status_commands(self):
        self.make()
        self.gcode.register_mux_command.assert_called_once_with(
            "SET_PIN", "PIN", "light_off_on_end", self.switch.cmd_set)
        names = [c.args[0] for c in self.gcode.register_command.call_args_list]
        self.assertIn("OC_LIGHT_OFF_STATUS", names)

    def test_set_pin_turns_on_and_saves(self):
        self.make(saved={})
        cmd = FakeGCmd(VALUE=1)
        self.switch.cmd_set(cmd)
        self.assertTrue(self.switch.enabled)
        self.gcode.run_script_from_command.assert_called_once_with(
            "SAVE_VARIABLE VARIABLE=oc_light_off_on_end VALUE=1")
        self.assertIn("enabled", cmd.replies[0])

    def test_saved_value_wins_over_default(self):
        self.make(saved={"oc_light_off_on_end": 1}, default=False)
        self.assertTrue(self.switch.enabled)
        self.make(saved={"oc_light_off_on_end": 0}, default=True)
        self.assertFalse(self.switch.enabled)

    def test_light_off_when_print_completes(self):
        self.make(saved={"oc_light_off_on_end": 1})
        self.poll_through("printing", "printing", "complete", "complete")
        self.assertEqual(len(self.light_off_calls()), 1)

    def test_light_off_when_cancelled_while_paused(self):
        self.make(saved={"oc_light_off_on_end": 1})
        self.poll_through("printing", "paused", "cancelled")
        self.assertEqual(len(self.light_off_calls()), 1)

    def test_light_off_on_error_and_on_reset_after_cancel(self):
        self.make(saved={"oc_light_off_on_end": 1})
        self.poll_through("printing", "error")
        self.poll_through("printing", "standby")
        self.assertEqual(len(self.light_off_calls()), 2)

    def test_pause_and_resume_leave_light_alone(self):
        self.make(saved={"oc_light_off_on_end": 1})
        self.poll_through("standby", "printing", "paused", "printing")
        self.assertEqual(self.light_off_calls(), [])

    def test_no_light_off_without_a_print(self):
        self.make(saved={"oc_light_off_on_end": 1})
        self.poll_through("standby", "complete", "standby", "cancelled")
        self.assertEqual(self.light_off_calls(), [])

    def test_skips_when_shut_down(self):
        self.make(saved={"oc_light_off_on_end": 1})
        self.printer.shutdown = True
        self.poll_through("printing", "error")
        self.assertEqual(self.light_off_calls(), [])

    def test_set_led_failure_does_not_stop_polling(self):
        self.make(saved={"oc_light_off_on_end": 1})
        self.gcode.run_script.side_effect = RuntimeError("Unknown LED")
        self.state = "printing"
        self.plugin._poll(0.)
        self.state = "complete"
        with self.assertLogs(level="ERROR"):
            next_wake = self.plugin._poll(5.)
        self.assertEqual(next_wake, 5. + oc_light_off.POLL_SECONDS)

    def test_status_command(self):
        self.make(saved={"oc_light_off_on_end": 1})
        cmd = FakeGCmd()
        self.plugin.cmd_status(cmd)
        self.assertEqual(cmd.replies, ["Light off at print end: ON (LED chamber_led)"])

    def test_manifest_files_exist(self):
        m = json.loads((ROOT / "opencreator-plugin.json").read_text())
        for rel in m["klippy_extras"] + [m["klipper_config"]]:
            self.assertTrue((ROOT / rel).is_file(), rel)
        self.assertRegex(m["id"], r"^[a-z0-9_-]{2,41}$")


if __name__ == "__main__":
    unittest.main()

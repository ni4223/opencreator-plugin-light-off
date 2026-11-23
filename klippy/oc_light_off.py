# Auto light: [oc_light_off]
#
# Turns an LED on when a print starts, and off when it finishes. A cancel or
# an error leaves it on. It listens for Kalico's print_stats events, so it
# does nothing between prints. The on/off switch shows as
# output_pin auto_light (a toggle in Fluidd) and is kept in save_variables,
# like OpenCreator's Misc switches.
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

SWITCH = 'auto_light'
SAVED_KEY = 'oc_' + SWITCH
# Sent by Kalico's print_stats. start_printing also comes on every resume.
START_EVENT = 'print_stats:start_printing'
PAUSE_EVENT = 'print_stats:paused_printing'
# Each ends a print; only a finished one turns the light off. reset is
# SDCARD_RESET_FILE stopping a print without a cancel. OpenCreator's
# on_error_gcode is CANCEL_PRINT, so an error comes as cancelled then error,
# and a print that cancels itself (no build plate) as cancelled then complete:
# the first event ends the print, so the second is ignored.
END_EVENTS = {'complete_printing': True, 'cancelled_printing': False,
              'error_printing': False, 'reset': False}


class OnOffSwitch:
    """An on/off setting shown as output_pin NAME and kept in save_variables.

    A copy of Kalico's Creator5MiscSwitch, so a Kalico update can't break
    this plugin.
    """

    def __init__(self, printer, gcode, name, saved_key, enabled):
        self.printer = printer
        self.gcode = gcode
        self.name = name
        self.saved_key = saved_key
        self.enabled = bool(enabled)
        printer.add_object('output_pin ' + name, self)
        printer.register_event_handler('klippy:ready', self._handle_ready)
        gcode.register_mux_command('SET_PIN', 'PIN', name, self.cmd_set)

    def _handle_ready(self):
        saved = self.printer.lookup_object('save_variables', None)
        if saved is not None:
            value = saved.allVariables.get(self.saved_key)
            if value in (0, 1):
                self.enabled = bool(value)

    def set_enabled(self, enabled):
        enabled = bool(enabled)
        if enabled == self.enabled:
            return
        if self.printer.lookup_object('save_variables', None) is not None:
            self.gcode.run_script_from_command(
                'SAVE_VARIABLE VARIABLE=%s VALUE=%d'
                % (self.saved_key, int(enabled)))
        self.enabled = enabled

    def get_status(self, eventtime):
        return {'value': float(self.enabled)}

    def cmd_set(self, gcmd):
        self.set_enabled(gcmd.get_float('VALUE', 0., minval=0., maxval=1.) > 0.)
        gcmd.respond_info('%s %s' % (
            self.name, 'enabled' if self.enabled else 'disabled'))


class OCLightOff:
    def __init__(self, config):
        self.printer = config.get_printer()
        self.gcode = self.printer.lookup_object('gcode')
        self.led = config.get('led', 'chamber_led')
        self.switch = OnOffSwitch(
            self.printer, self.gcode, SWITCH, SAVED_KEY,
            config.getboolean(SWITCH + '_default', True))
        self.active = self.paused = False
        self.printer.register_event_handler('klippy:ready', self._handle_ready)
        self.printer.register_event_handler(START_EVENT, self._handle_start)
        self.printer.register_event_handler(PAUSE_EVENT, self._handle_pause)
        for name, light_off in END_EVENTS.items():
            self.printer.register_event_handler(
                'print_stats:' + name,
                lambda light_off=light_off: self._handle_end(light_off))
        self.gcode.register_command(
            'OC_AUTO_LIGHT_STATUS', self.cmd_status,
            desc='Report whether the light turns on and off with prints')

    def _handle_ready(self):
        if self.printer.lookup_object('led ' + self.led, None) is None:
            logging.warning('oc_light_off: no [led %s] in the config', self.led)
        if self.printer.lookup_object('print_stats', None) is None:
            logging.warning('oc_light_off: no print_stats; nothing to watch')

    def _handle_start(self):
        if self.paused:  # a resume
            self.paused = False
        elif not self.active:
            self.active = True
            self._queue_light(True, 'Print started')

    def _handle_pause(self):
        if self.active:
            self.paused = True

    def _handle_end(self, light_off):
        # Ignore ends without a print, like the reset before a new print.
        if self.active:
            self.active = self.paused = False
            if light_off:
                self._queue_light(False, 'Print complete')

    def _queue_light(self, on, reason):
        if not self.switch.enabled:
            return
        if not self.gcode.get_mutex().test():
            # Nothing holds the G-code lock, as at print start: virtual_sdcard
            # sends start_printing just before it runs print start (homing,
            # heating) as one long command. SET_LED now, so the light is on
            # before that command takes the lock.
            self._set_light(on, reason)
        else:
            # A command holds the lock and may be the one sending this event,
            # or waiting on the print: SET_LED now could wait for it forever.
            # Run it once the lock is free.
            self.printer.get_reactor().register_callback(
                lambda eventtime: self._set_light(on, reason))

    def _set_light(self, on, reason):
        if self.printer.is_shutdown():
            return
        word = 'on' if on else 'off'
        try:
            self.gcode.run_script(
                'SET_LED LED=%s RED=%d GREEN=%d BLUE=%d WHITE=%d'
                % ((self.led,) + (int(on),) * 4))
            self.gcode.respond_info('%s: %s turned %s' % (reason, self.led, word))
        except Exception:
            logging.exception('oc_light_off: could not turn %s %s', word, self.led)

    def cmd_status(self, gcmd):
        gcmd.respond_info('Auto light: %s (LED %s)' % (
            'ON' if self.switch.enabled else 'OFF', self.led))

    def get_status(self, eventtime):
        return {'enabled': self.switch.enabled, 'led': self.led}


def load_config(config):
    return OCLightOff(config)

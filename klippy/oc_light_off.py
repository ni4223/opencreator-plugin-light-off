# Auto light off: [oc_light_off]
#
# Turns an LED off when a print stops: finished, cancelled or stopped by an
# error. The on/off switch shows as output_pin light_off_on_end (a toggle in
# Fluidd) and is kept in save_variables, like OpenCreator's Misc switches.
#
# This file may be distributed under the terms of the GNU GPLv3 license.
import logging

SWITCH = 'light_off_on_end'
SAVED_KEY = 'oc_' + SWITCH
ACTIVE_STATES = ('printing', 'paused')
POLL_SECONDS = 1.


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
            config.getboolean(SWITCH + '_default', False))
        self.print_stats = None
        self.last_state = None
        self.printer.register_event_handler('klippy:ready', self._handle_ready)
        self.gcode.register_command(
            'OC_LIGHT_OFF_STATUS', self.cmd_status,
            desc='Report whether the light turns off at print end')

    def _handle_ready(self):
        if self.printer.lookup_object('led ' + self.led, None) is None:
            logging.warning('oc_light_off: no [led %s] in the config', self.led)
        self.print_stats = self.printer.lookup_object('print_stats', None)
        if self.print_stats is None:
            logging.warning('oc_light_off: no print_stats; nothing to watch')
            return
        reactor = self.printer.get_reactor()
        reactor.register_timer(self._poll, reactor.NOW)

    def _poll(self, eventtime):
        state = self.print_stats.get_status(eventtime).get('state')
        last, self.last_state = self.last_state, state
        # Any way out of printing/paused is a print end: complete, cancelled,
        # error, or standby when a UI resets the file straight after a cancel.
        if (last in ACTIVE_STATES and state not in ACTIVE_STATES
                and self.switch.enabled):
            self._light_off(state)
        return eventtime + POLL_SECONDS

    def _light_off(self, state):
        if self.printer.is_shutdown():
            return
        try:
            self.gcode.run_script(
                'SET_LED LED=%s RED=0 GREEN=0 BLUE=0 WHITE=0' % self.led)
            self.gcode.respond_info('Print %s: %s turned off' % (state, self.led))
        except Exception:
            logging.exception('oc_light_off: could not turn off %s', self.led)

    def cmd_status(self, gcmd):
        gcmd.respond_info('Light off at print end: %s (LED %s)' % (
            'ON' if self.switch.enabled else 'OFF', self.led))

    def get_status(self, eventtime):
        return {'enabled': self.switch.enabled, 'led': self.led}


def load_config(config):
    return OCLightOff(config)

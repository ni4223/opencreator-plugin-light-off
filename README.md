# Auto light off

An OpenCreator plugin for the Creator 5 / 5 Pro. It turns the chamber light
(`chamber_led`) off when a print ends: finished, cancelled, or stopped by an
error. It's off until you turn it on.

## Turning it on and off

- Fluidd: the `light_off_on_end` toggle, next to switches like
  `park_carriage_on_end`.
- Macros: `OC_LIGHT_OFF_ON_END_ON` and `OC_LIGHT_OFF_ON_END_OFF`, or
  `SET_PIN PIN=light_off_on_end VALUE=1` / `VALUE=0`.
- `OC_LIGHT_OFF_STATUS` says whether it's on.

The setting is kept in save_variables (`oc_light_off_on_end`), so it survives
restarts and plugin updates.

To group the two macros with the other switches, put them in the "On / Off"
category under Fluidd's Settings > Macros.

## How it works

The plugin checks the print state once a second. When the state leaves
printing or paused and the switch is on, it runs:

    SET_LED LED=chamber_led RED=0 GREEN=0 BLUE=0 WHITE=0

That covers a finished print (`complete`), a cancel (`cancelled`), an error
(`error`) and a file reset straight after a cancel (`standby`). Pausing and
resuming don't count. No OpenCreator macro is changed.

## What it doesn't do

- It doesn't turn the light back on when the next print starts.
- After an emergency stop or a Klipper shutdown the light can't be changed,
  so it stays as it was.

## Install

On the printer (SSH):

    oc-plugin install https://github.com/ni4223/opencreator-plugin-light-off.git

Klipper restarts by itself, unless the printer is printing or paused. The
switch starts off, so turn it on as above.

## Update and remove

Updates show up in Fluidd/Mainsail's update manager as
**oc-plugin-light-off-on-end**, or run `oc-plugin update light-off-on-end`.
`oc-plugin remove light-off-on-end` removes it. The on/off setting stays in
save_variables, so a reinstall picks it up again.

## Installing from a folder

To try a copy on the printer without git:

    oc-plugin install /usr/data/light-off

A folder install is a copy, so reinstall it after changes, and it isn't offered
in the update manager. To move to the git install, run
`oc-plugin remove light-off-on-end` first: `oc-plugin install` refuses an id
that is already installed.

## Tests

    python3 -m unittest discover -s tests

## License

GPLv3, like Klipper.

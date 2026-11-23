# Auto light

An OpenCreator plugin for the Creator 5 / 5 Pro. It turns the chamber light
(`chamber_led`) on when a print starts, and off when it finishes. A cancel or
an error leaves it on, so you can see what happened. It's on as soon as it's
installed.

## Turning it on and off

- Fluidd: the `auto_light` toggle, next to switches like
  `park_carriage_on_end`.
- Macros: `OC_AUTO_LIGHT_ON` and `OC_AUTO_LIGHT_OFF`, or
  `SET_PIN PIN=auto_light VALUE=1` / `VALUE=0`.
- `OC_AUTO_LIGHT_STATUS` says whether it's on.

The setting is kept in save_variables (`oc_auto_light`), so it survives
restarts and plugin updates.

To group the two macros with the other switches, put them in the "On / Off"
category under Fluidd's Settings > Macros.

## How it works

It listens for Kalico's print events (OpenCreator runs Kalico), so it does
nothing between prints. While the switch is on:

| Event | Light |
| --- | --- |
| `print_stats:start_printing` (not a resume) | on |
| `print_stats:complete_printing` | off |
| `print_stats:cancelled_printing`, `error_printing`, or `reset` during a print (`SDCARD_RESET_FILE`) | stays as it is |

On: `SET_LED LED=chamber_led RED=1 GREEN=1 BLUE=1 WHITE=1`.
Off: `SET_LED LED=chamber_led RED=0 GREEN=0 BLUE=0 WHITE=0`.

The light comes on as the print starts, before print start homes and heats.
(A light command sent by hand then would wait until print start is done.)

OpenCreator runs `CANCEL_PRINT` on an error, and a print that cancels itself
(like a failed build plate check) ends with a cancel and then a complete. The
first end counts, so neither turns the light off. Pausing and resuming don't
count. No OpenCreator macro is changed.

## What it doesn't do

- It doesn't turn the light on or off at any other time, so you can still
  switch it by hand during a print.
- After an emergency stop or a Klipper shutdown the light can't be changed,
  so it stays as it was.

## Install

On the printer (SSH):

    oc-plugin install https://github.com/ni4223/opencreator-plugin-light-off.git

Klipper restarts by itself, unless the printer is printing or paused. The
switch starts on, so the next print uses it. Turn it off as above if you
want it to leave the light alone.

## Update and remove

Updates show up in Fluidd/Mainsail's update manager as
**oc-plugin-light-off-on-end**, or run `oc-plugin update light-off-on-end`.
`oc-plugin remove light-off-on-end` removes it. The switch setting stays in
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

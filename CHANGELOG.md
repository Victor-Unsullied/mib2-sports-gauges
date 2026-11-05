# Changelog

## Unreleased installer recovery fixes

- Add durable transaction journals, repeatable rollback, local backup recovery, atomic file publication, and installation locks.
- Keep recovery independent of a running HMI and wizard state; verify restored files and a fresh boot before acceptance.
- Add safe retry outcomes, read-only `--inspect`, and `--state-dir` for original installation backups.
- Add offline failure regressions and interruption sweeps. Actual Windows and QNX behavior remains unverified.
- 49 regression tests and 156 simulated interruption cases pass; release ZIP and website remain unchanged.


## v1.0.0 (Initial release)

- Selectable oil and coolant temperature corrections, engine-based power and torque display, gauge visibility and scale settings.
- Web configurator, desktop configurator and guided Windows installer with backup and rollback.
- Untested Train/MU values trigger a warning. The installer checks the files on the unit before writing.
- Earlier fixes worked on a 2015 Golf 7 Highline CXSA manual with a Delphi 874B retrofit, Train MST2_EU_VW_P0635D and MU 0757. The release installer and configurable combinations were checked offline.
- The boost pressure correction is pending.

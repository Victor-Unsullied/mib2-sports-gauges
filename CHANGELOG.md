# Changelog

## v1.0.1

- Untested Train/MU values show a warning before the user confirms. The installer still verifies the actual files on the unit before writing.

## v1.0 — 2026-11-03

First public installer package, following the earlier web preview and internal development versions.

- One `config.xml` format for the web and desktop configurators.
- Small Tk desktop interface at `configure.py`.
- Guided Windows installation at `install.py`, with English/Turkish prompts and English as the default.
- Explicit settings review, risk acknowledgement and confirmation before each stage.
- Original file-identity, boot, observation, backup and rollback checks retained.
- Website ZIP and repository release contain the same program files; only the selected configuration differs.
- Website source moved out of this repository into DevSite.
- Earlier in-car evidence: CXSA / 2015, Delphi 874B, MST2_EU_VW_P0635D, MU 0757, temperature-hook-v3 + Sports v7.
- **v1.0 wizard and selectable combinations: not yet tested in the car.**
- **Boost-pressure correction: not implemented.** No planned date.
- English bug and compatibility report forms in GitHub Issues.

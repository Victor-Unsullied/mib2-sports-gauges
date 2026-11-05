# MIB2 Sports Gauges

**The main branch includes unreleased installer recovery fixes based on v1.0.0.** Read [UNRELEASED.md](UNRELEASED.md) for the changes, offline evidence and remaining Windows/QNX checks. The public v1.0.0 ZIP and website have not been updated.

Selectable Sport HMI fixes for a **Delphi MIB2**, with an offline configurator and a guided Windows installer.

**Current installer: v1.0.0 (experimental).**

> **USE AT YOUR OWN RISK.** This changes the software in your infotainment unit. Your engine/head-unit combination is probably untested. A failed installation can leave the screen and related functions unavailable, or brick the unit. Repair or replacement may be necessary. A backup is not a guarantee of recovery. You accept the risk and responsibility for using this project.

The repository owner developed this patch for a 2015 Golf 7 Highline with the CXSA engine and manual transmission, after a Delphi MIB2 retrofit left some Sport HMI gauges malfunctioning. The patch is shared so owners with other setups can check compatibility.

## What it does

Some cars already report some gauges correctly. **Select fixes for the gauges that are wrong in your car. Do not enable every fix just because it is available.** Gauge visibility and data corrections are separate settings.

| Feature | Status |
| --- | --- |
| Oil temperature correction | Working in the earlier fixed setup |
| Coolant temperature correction | Working in the earlier fixed setup |
| ECU-based torque display and torque-derived power | Working in the earlier fixed setup |
| Gauge selection, power unit, custom scales, optional needle smoothing | Available; all v1.0.0 combinations remain untested in a car |
| Boost-pressure correction | **Not implemented** |

Only the **power unit** is selectable. Existing gauges use the head unit's unit settings. The added torque gauge uses Nm. The optional limits change the displayed scale, not vehicle data.

## Tested versions

| Head unit | Software train | MU | Project version / test scope |
| --- | --- | --- | --- |
| Delphi 874B | MST2_EU_VW_P0635D | 0757 | temperature-hook-v3 + Sports v7; owner-reported in-car result |
| Delphi 874B | MST2_EU_VW_P0635D | 0757 | **v1.0.0:** offline checks; guided installer and selectable combinations not tested in the car |
| All other head units / trains / MU versions | — | — | **Not tested.** Review the installer warning. |

| Engine / model year | Oil | Coolant | Power | Torque | Boost fix |
| --- | --- | --- | --- | --- | --- |
| CXSA 1.4 TSI / 2015 | ✓ | ✓ | ✓ | ✓ | ✗ |
| All other engines / years | Not tested | Not tested | Not tested | Not tested | ✗ Not implemented |

The checkmarks refer to the earlier fixed setup on the owner's car. They are not validation of every v1.0.0 setting. Independent Nm/hp calibration has not been verified. An untested Train/MU prompts a warning. The installer checks the actual files on the unit and stops before writing if they are unrecognized.

## Requirements

- Windows and Python 3.14 from [python.org](https://www.python.org/downloads/windows/), including Tcl/Tk.
- Working local service access to your own unit through a compatible USB–Ethernet adapter. See the [D-Link connection guide](https://utkulekesiz.com/en/blog/mib2-dlink-connection/).
- A safely parked car, stable power, and the ability to recover the unit if something goes wrong.

## Configure

For the recovery fixes described here, download and extract the [main-branch source](https://github.com/Victor-Unsullied/mib2-sports-gauges/archive/refs/heads/main.zip). These changes are development code and remain untested on Windows and the head unit.

The [original v1.0.0 installer](https://utkulekesiz.com/assets/mib2-sports/v1.0.0/mib2-sports-gauges-v1.0.0.zip) is unchanged and **does not include these recovery fixes**.

Open a terminal in the extracted folder and run:

```powershell
python configure.py
```

Select only the fixes you need, enter the Train/MU from your unit, and save `config.xml`.

The [web configurator](https://utkulekesiz.com/en/tools/mib2-sports-gauges/) can also generate settings. Its ZIP still contains the original v1.0.0 program, with **only `config.xml` changed**; it does not include the main-branch recovery fixes. To use its settings with this branch, copy only the generated `config.xml` into the extracted main-branch folder. It does not connect to your car. No private base ZIP is needed.

## Install

```powershell
python install.py
```

1. Choose English or Turkish. Press Enter for English.
2. Review the settings loaded from `config.xml` and confirm them.
3. Read and accept the experimental-software warning.
4. Enter the unit's IPv4 address shown in Green Engineering Menu and its FTP/Telnet service login details. Passwords are hidden and are not written to the configuration or session files.
5. Follow one step at a time. Confirm the normal screen has returned after each restart. Two checks take six minutes each; keep the connection and power on.

The program backs up the existing state before enabling fixes. It stops on a failed check. Never change `config.xml` midway through an installation. Keep the **entire folder**, especially `state/`, with its backups, receipts and logs. Do not share your private `state/` folder.

This candidate writes a checksummed transaction journal before changing live files. It publishes verified staging files with same-directory renames and keeps an exclusive unit lock through the staged installation. Resume from the same state folder; do not run copied active state folders on multiple computers. A connection or login failure before live writes can be retried. An interrupted transaction must be recovered with `--rollback`.

To check files or view the steps without contacting the unit:

```powershell
python install.py --check
python install.py --plan
```

On Windows, `python install.py --inspect` checks the unit's files and HMI through service access without writing files to the unit. It still requires the correct address and credentials.

## Roll back

Use the same folder used for installation:

```powershell
python install.py --rollback
```

The wizard restores the saved previous state and checks the next boot. It uses the saved session even if the current `config.xml` has changed. **Working service access is required. If the unit is unreachable, this program cannot guarantee recovery.** Keep older releases and their state folders before updating.

Recovery in this candidate does not require a running HMI before restoration. It still refuses unknown carrier/UI identities and changed protected files. Repeated `--rollback` calls finish the same recorded recovery target; they do not step backwards through more installation history. A rejected rollback reboot leaves the restored target in place for another attempt.

To use the candidate with an original v1.0 state folder, preserve that folder and select it explicitly:

```powershell
python install.py --rollback --state-dir "C:\path\to\original-install\state"
```

The candidate can import the original remote receipt, or a unique locally hashed backup if that receipt is damaged. Conflicting backups and an active lock owned by another state folder stop recovery. Do not delete receipts or lock files to bypass these checks.

## Report results

Use the public [GitHub Issues tracker](https://github.com/Victor-Unsullied/mib2-sports-gauges/issues/new/choose). Choose **Bug report** for a problem with configuration, installation or gauge behaviour. Choose **Compatibility / support request** to request support for an engine, model year, head unit, Train or MU version, or share existing test results. State the relevant project version and the support required. An installation attempt is not required to open a request, and a request does not guarantee inclusion in a particular release. Submitted issues are visible to everyone.

You can also post successful and unsuccessful results in the [Golftutkusu topic](https://www.golftutkusu.com/topic/29132-golf-7-mib2-sport-hmi-euro-5-araclarda-spor-gostergelerini-calistirma/): engine code, model year, head-unit model, Train, MU, project version and the fixes selected. Remove personal information before sharing logs.

Boost-pressure correction is planned, with no release date.

## Repository layout

```text
install.py        Guided installer and rollback entry point
configure.py      Small offline Tk interface
config.xml        Editable settings, shared with the website
src/              XML model, UI, installer and native patch support
src/native/       Configurable native overlay source
src/core/         Guarded staged runtime and required patch payloads
tests/            Offline checks; no real head-unit connections
```

The website itself is maintained in DevSite and is not included here. A full factory carrier or firmware image is not bundled; the original carrier is read from the unit and checked before any write. Required overlay payloads retain their original hashes. Unknown inputs, changed protected files and mismatched composed output are refused.

See [CHANGELOG.md](CHANGELOG.md) for release history and the [project article](https://utkulekesiz.com/en/blog/mib2-sports-gauges/) for the background and demo video.

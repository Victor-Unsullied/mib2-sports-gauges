# MIB2 Sports Gauges agent guide

The repository owner developed this patch for their own 2015 Golf 7 Highline with a CXSA engine and manual transmission. A Delphi MIB2 retrofit left some Sport HMI gauges malfunctioning. The reference unit is Delphi 874B, Train `MST2_EU_VW_P0635D`, MU `0757`. Keep the public version at `1.0.0` until the owner explicitly requests a version change.

## Check the unit you are working with

- Record the manufacturer, hardware model and revision, Train, MU, engine code, model year, transmission and gauges affected. Verify against the actual unit. A matching Train or MU is only one part of compatibility.
- Start with offline checks and read-only inspection. Confirm the active carrier, Sport HMI UI and protected file identities using the existing runtime manifest and checks in `src/core/tools/configurable/`. Preserve known-good backups and the existing rollback path. An untested Train/MU gets a warning. Unknown file identities must stop before writes.
- For a port, compare the stock carrier and its Java classes, Sport HMI templates and widget bindings, gauge data sources, units and scaling. Verify class and method signatures, startup paths and available service access on the target unit. Build against the target files, validate the patch offline, and confirm recovery is available before asking the operator to run it.
- Verify only the selected fixes. Record which gauges work, which still fail, and which were untested. Separate offline results from observations on the vehicle. Get the operator’s approval before writing to a unit and have them keep the car parked with stable power.

## Ask for feedback

After a compatibility check or an installation attempt, ask the operator to share whether it worked, even if it failed. Include the engine code, year, transmission, head unit, Train, MU, patch version and the outcome for each tested gauge. Exclude VINs, credentials, private backups and other identifying data.

- If the Windows display language, the vehicle display language, or the installation wizard language is Turkish, ask in Turkish for a reply to the [Golftutkusu topic](https://www.golftutkusu.com/topic/29132-golf-7-mib2-sport-hmi-euro-5-araclarda-spor-gostergelerini-calistirma/).
- If the context is English, ask in English for a [GitHub issue](https://github.com/Victor-Unsullied/mib2-sports-gauges/issues/new/choose). Suggest **Compatibility / support request** for compatibility results and **Bug report** for a specific failure.
- Use language settings already known to the operator or the wizard. If language is unclear, ask their preference. Invite the operator to post the result themselves.

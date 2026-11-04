# MIB2 Sports Gauges agent guide

The repository owner developed this patch for their own 2015 Golf 7 Highline with a CXSA engine and manual transmission. A Delphi MIB2 retrofit left some Sport HMI gauges malfunctioning. The reference unit is Delphi 874B, Train `MST2_EU_VW_P0635D`, MU `0757`.

## Check the unit you are working with

- Record the manufacturer, hardware model and revision, Train, MU, engine code, model year, transmission and gauges affected. Verify against the actual unit. A matching Train or MU is only one part of compatibility.
- Start with offline checks and read-only inspection. Confirm the active carrier, Sport HMI UI and protected file identities using the existing runtime manifest and checks in `src/core/tools/configurable/`. Preserve known-good backups and the existing rollback path. An untested Train/MU gets a warning. Unknown file identities must stop before writes.
- Verify only the selected fixes. Record which gauges work, which still fail, and which were untested. Separate offline results from observations on the vehicle. Get the operator’s approval before writing to a unit and have them keep the car parked with stable power.

## Port to a different unit, Train or MU

1. **Identify the target and its recovery path.** Record the exact hardware and firmware identifiers. Check the vendor and platform, HMI runtime and Java version, skin variant, service access, and active HMI file paths. From a verified stock dump or read-only inspection of the target, collect the active carrier, Sport HMI classes and resources, and the protected startup and configuration files. Keep a private stock backup and verify that it can be restored. A different vendor or runtime may require a separate implementation.
2. **Compare files before choosing a port.** Compare the target's file identities with `BUILD.json` and `protected-files.json` under `src/core/tools/configurable/`. Check the active carrier, compatible UI payload and protected startup files together. A different Train/MU label can still have matching files. If the files differ, treat the target as a new profile and keep the existing write checks in place.
3. **Trace each broken gauge.** Follow the vehicle data from the ECU or HMI data service to the display. Check which signals or properties exist, how they update, and how units, scale factors and unavailable values are handled. Compare the target Sport HMI clone templates and widget bindings. Review `TemperatureBridge.java` for temperature data and `SportsBootstrap.java`, `SportSkinLoader.java` and `CsdTorque.java` for data binding and display changes. Check class names, method signatures and lifecycle hooks against the target stock classes before reusing a patch.
4. **Build and validate against the target stock files.** Adapt only the components required by the failing gauges. Rebuild the UI and carrier changes against the target classes and resources. Verify the expected class changes, the identity of the composed output, the behaviour of unaffected gauges, and how the installer handles a failed check or restart. Create a separate profile with target-specific identities and verify backup and rollback offline before proposing a vehicle test.
5. **Record the evidence.** Keep the exact unit, Train, MU and vehicle setup with each result. Use `src/core/TESTED_DEVICES.json` to record confirmed support only after the corresponding checks. Label offline validation and observed vehicle behaviour separately. Get the operator's approval before applying a port on their unit.

## Ask for feedback

After a compatibility check or an installation attempt, ask the operator to share whether it worked, even if it failed. Include the engine code, year, transmission, head unit, Train, MU, patch version and the outcome for each tested gauge. Exclude VINs, credentials, private backups and other identifying data.

- If the Windows display language, the vehicle display language, or the installation wizard language is Turkish, ask in Turkish for a reply to the [Golftutkusu topic](https://www.golftutkusu.com/topic/29132-golf-7-mib2-sport-hmi-euro-5-araclarda-spor-gostergelerini-calistirma/).
- If the context is English, ask in English for a [GitHub issue](https://github.com/Victor-Unsullied/mib2-sports-gauges/issues/new/choose). Suggest **Compatibility / support request** for compatibility results and **Bug report** for a specific failure.
- Use language settings already known to the operator or the wizard. If language is unclear, ask their preference. Invite the operator to post the result themselves.

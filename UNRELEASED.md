# Installer recovery candidate

These main-branch recovery changes are based on v1.0.0 and were prepared on 5 November 2026. Their code and integrity manifest differ from the published v1.0.0 package. The release version, release ZIP and website remain unchanged. Actual Windows and head-unit validation is still pending.

The installer now records the before/after file images, intended recovery target, phase and restart marker before publishing changes. Recovery can reconstruct its state from checksummed local copies or the remote journal. Retrying rollback completes the same transaction, including after the original carrier or receipt has already been restored.

| Audit finding | Candidate behavior |
| --- | --- |
| HMI health blocks restoration | Recovery can start with a stopped HMI. Installation and final acceptance still require healthy HMI checks. Carrier, UI and protected-file identity gates remain. |
| Truncated local state prevents recovery | Atomic local writes, fsync and checksummed mirrors replace direct overwrites. The transaction journal records the recovery state separately from the wizard. |
| Interrupted rollback targets the wrong generation | The rollback target is recorded before mutation and retained after acceptance. Repeated calls are idempotent. |
| Intact local backups are unusable | Journals carry complete file preimages. The candidate imports original v1.0 receipts and unique verified local backup inventories. |
| Logging failure skips restoration | Diagnostics are best-effort. Recovery does not depend on a successful log write or log-file close. |
| Failed first connection poisons the session | The runtime distinguishes failures with no writes or completed restoration from uncertain transactions. The wizard allows retries when it can verify they are safe. |
| Partial staging blocks recovery | Unique transaction stages are disposable. The installer can remove known abandoned stages while holding the unit lock. It publishes active options and receipts from staging files. |
| Concurrent copies interfere | OS file locks protect local state, a persistent unit lock protects the installation, and the previous service shell must have exited before a reconnect resumes writes. |
| Rollback accepts bad status | Acceptance checks exact restored files, a cleared volatile restart marker, a running HMI and applicable native health. Stock does not require a configurable-patch status file. |

The persistent unit token binds this state folder to the unit after first contact. It is an installer token, not a hardware serial number. Legacy recovery without a token retains its saved host binding and validates the known carrier profile and recovery data. Investigate unknown file identities separately before attempting recovery.

The normal Sports phase sequence and six-minute observations are retained. Native payload JARs, gauge settings, firmware identities and composition hashes are unchanged. A new `--inspect` command performs read-only compatibility checks. `--state-dir` lets the candidate use an original installation's backups without replacing its program files.

Run the portable offline suite from this directory:

```text
python -m unittest discover -s tests -v
python tests/sweep_recovery.py
python tests/sweep_local_recovery.py
python install.py --check
```

Offline validation passed: 49 regression tests, 123 interruptions after remote operations, 33 interruptions after durable local writes, and 42 package-file integrity checks. The existing stock composition hash also matched using the macOS test shim for Windows ZIP metadata and compression. Actual Windows execution still needs testing.

The test services prohibit real socket connections. They model remote files, partial uploads, process termination, persistent connection loss, stopped HMI, rejected reboot, storage errors, competing installers and old receipts. The sweeps verify the restored file generation as well as successful completion. These are simulated process interruptions, not electrical power-loss tests.

Before publishing, verify on Windows that file locking, credential entry, FTP passive transfers, Telnet closure and the full wizard behave as expected. On the supported QNX image, verify the remote lock primitive, interrupted service-shell lifetime, same-directory rename and sync durability, and clearing of `/tmp` markers on the requested full reboot. A controlled head-unit trial must demonstrate restoration with the HMI stopped and a failed step. Vehicle writes require explicit operator approval and stable parked power.

The remote lock deliberately uses `ln -i` with standard input redirected from `/dev/null`. QNX `ln` can replace writable destination files even without `-f`. The installer must refuse an existing lock. The candidate validates the lock contents after acquisition and aborts before managed-file changes if acquisition fails. See the [QNX ln documentation](https://qnx.com/developers/docs/6.4.0/neutrino/utilities/l/ln.html). This command behavior and hard-link support on the target persistence filesystem still need to be verified on the device.

Keep active state in one location. A copied state folder on a second computer is not a supported concurrency mechanism. Recovery with working services cannot compensate for destroyed backups, unknown replacement firmware, unavailable storage, or damaged hardware.

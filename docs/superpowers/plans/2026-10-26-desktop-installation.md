# Desktop installation simplification implementation plan

**Goal:** Install and remove separate dataset and service packages without typed commands on supported graphical desktops.

**Architecture:** Retain the dataset manager and add a separate service setup/maintenance window. Native authorization runs fixed, validated worker requests without a root Qt session. Native platform kits include both applications and independent installer artifacts.

**Tech stack:** Python/PyQt6 Widgets, PyInstaller, Inno Setup, systemd, Windows SCM, polkit.

**Spec:** The implementation request in the current task specifies platform targets, separation, preservation, graphical workflow and local-only verification.

## Constraints
- Preserve unrelated README changes; no commits, publication, host installation/service changes, device operations or live dataset acquisition.
- Preserve runtime/package identities, existing config, credentials, program assignments, service scheduling and subscriptions.
- Native GUI builds only on matching environments; unsupported native checks remain explicitly unverified.

## Work and interfaces
- [ ] Add `installers/desktop/authorization.py`: `run_authorized(request, emit, cancel=None)` returns JSON-compatible worker results; `worker_main(request_path)` validates request/dispatches only fixed dataset or service operations. Unix uses pkexec with a session agent and no text fallback; Windows uses native UAC. No arbitrary command interface.
- [ ] Add dataset request reconstruction in `installers/datasets/gui/privileges.py`, route desktop execution through authorization, preserve plan/state/hash revalidation, block removal while EMS service is active or cannot be established stopped.
- [ ] Add separate `installers/desktop/service_main.py`, `service_window.py`, `service_backend.py`: fixed installation, configure, status, start, stop, diagnostics and uninstall actions. Preserve current settings, collect routine fields/secrets graphically, use existing configure/backups and native installers, never program radios.
- [ ] Extend native GUI packaging and add `tools/build_desktop_kit.py`: native binaries, automatic adjacent paths, target-specific installer/checksum verification and source freshness; archive mode/executable handling; compatible Qt pins for Debian 12/Bookworm qualification.
- [ ] Add focused behavioral tests before each implementation; cover unsafe arguments, changed artifacts/plans, auth cancellation, active consumers, retention and failed operations.
- [ ] Update concise desktop instructions and affected guides; repair dataset inclusion claim only within README changes.
- [ ] Run existing GUI/core/configuration tests, new behavior tests, offscreen UI and packaged smoke checks. Build available native Windows applications and service installers after final source changes. Inspect Linux/Pi payloads; report unavailable ARM64/native desktop verification.

## Review focus
- Cancellation must not terminate an active native dataset mutation.
- Root helpers must not accept arbitrary executable paths/command lines from GUI requests.
- Privilege and installer failures must remain visible and block false success.
- Upgrades preserve unspecified settings and credentials.
- Linux Qt launch support does not establish physical Raspberry Pi operation.

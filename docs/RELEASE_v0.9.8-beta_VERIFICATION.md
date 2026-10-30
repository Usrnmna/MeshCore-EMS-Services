# v0.9.8-beta local release verification

This record describes local v0.9.8-beta preparation on October 29, 2026 UTC.
No commit, push, tag, publication, or artifact upload is part of this work.

Windows x64, Linux x86_64, and Raspberry Pi ARM64 artifacts are built from the
current working tree after documentation and configuration checks. Final artifact
paths, hashes, test results, and execution environments are recorded in the local
release directory, `dist/github-release-v0.9.8-beta-20261029`, in `VERIFICATION.zip`
and `SHA256SUMS.txt`. Execution reports identify the actual executable path,
SHA-256 digest, frozen status, platform, and synthetic checks. Results apply only
to those recorded bytes, rather than every installation of this version.

## Source and configuration evidence

- Windows Python 3.13 service suite: 517 tests passed.
- Ubuntu 24.04 WSL Python 3.12 service suite: 517 tests passed.
- Windows tooling baseline: 401 tests, 372 passed and 29 platform/fixture skips.
  Focused packaging checks are rerun after final packaging changes; the evidence
  archive contains their exact counts and any superseding full-suite result.
- Windows and WSL history/helper checks: 46 tests per environment, 45 passed and
  one platform-specific skip. The external source verifier exercised standalone
  Service Setup, unified maintenance, and Dataset Manager with synthetic fixtures.
- Documentation review: 77 maintained Markdown files and 1,495 local links and
  fragments passed the offline gate before the final CI documentation update.
- Git configuration fixtures verified ignore rules, file attributes, and archive
  exclusions on Windows and WSL. Local planning files remain readable and no
  planning files remain tracked.

CI now specifies 12 service combinations and three tooling environments, including
native hosted ARM64. The tooling jobs include nonrelease frozen GUI/helper checks.
These modified workflows have not run on GitHub. The current committed base's
successful hosted run does not validate the uncommitted release changes.

## Packaging and verification boundaries

The supported local build environments use pinned PyQt6 6.7.1, Qt 6.7.3, and
PyInstaller 6.22.3. Linux x86_64 runs inside Debian 12 under WSL; ARM64 uses
Debian 12 under QEMU. Both build roots report glibc 2.36. ARM64 emulation is not
native Raspberry Pi validation.

Collectors, provenance writers, staging checks, and archive checks exclude local
planning documents. Disposable source snapshots omit that directory entirely.
Packaged operational documentation preserves repository-relative paths. References
to separately installed data become explicit paths where the data is not present;
the source EBMUD inventory rows remain unchanged for its refresh parser.

Synthetic tests cover recorder retention/persistence and failures, optional GUI
settings, readonly requests, process deadlines/cancellation, and packaged dispatch.
They use disposable storage and do not operate installed services or live radios.
Optional recording can have observable gaps under overload or storage failure;
admission is not a durability acknowledgement, and uncommitted records can be lost
at shutdown. The verification archive separates source test results from frozen
executable and archive inspection results.

Source tests, frozen executable tests, WSL execution, and ARM64 emulation provide
different evidence. Physical Raspberry Pi/radio operation, live provider access,
native UAC/polkit interaction, reboot behavior, and deployed-service operation
remain unverified unless an explicit result below establishes otherwise.

## ARM64 image-decoder follow-up

The original ARM64 Qt plugins failed actual WebP and TIFF decoding because their
older codec SONAMEs were unavailable. The maintained ARM64 build now rebuilds
only these two plugins from Qt 6.7.3 against pinned Bookworm codec development
libraries. The Qt/PyQt runtime versions remain unchanged. The
[desktop build requirements](../installers/datasets/BUILD.md#arm64-desktop-image-plugins)
describe the preparation and evidence requirements.

The replacement Raspberry Pi kit must be identified by its new archive hash and
packaged image-decoding results in `VERIFICATION.zip`. The Windows and Linux
x86_64 delivery archives retain their earlier bytes and verification scope;
they are not represented as rebuilt or tested against the later ARM64 inputs.
The final follow-up report records actual decoding, loaded-library origins,
dependency closure, checksums, and tests after extraction from the replacement
archive. Earlier ARM64 results remain historical until superseded explicitly.

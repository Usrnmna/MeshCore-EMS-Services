# Local recovery snapshots

This directory stores local recovery ZIPs containing workspace snapshots.
Their contents can include source files, settings, runtime state, and package
exports. Check each archive's contents before restoring files.

Backups may contain local state and are excluded from Git.
Build distributable source packages from the maintained service folders with:

```console
python tools/package_services.py
```

The generated packages are written to `dist/`. For OS service installation,
follow the [installation guide](../INSTALL.md).

# Local recovery snapshots

ZIP files here are historical backups, not current installation packages.
The pre-cleanup snapshot preserves source, settings, and service runtime files
as they existed before workspace organization. It excludes installed Python
environments and the unchanged `data/` reference collection.

The earlier review backup also preserves the superseded root ZIP exports.
Backups may contain local state and are excluded from version control.
Use the current service folders or rebuild `dist/` with:

```console
python tools/package_services.py
```

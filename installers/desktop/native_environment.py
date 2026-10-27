"""Construct native-child environments without caller-controlled code search paths."""
import ctypes
import os
from pathlib import Path


def clean_environment(temporary=None):
    """Keep ordinary locale/network context while excluding interpreter and loader overrides.

    Fixed native installers use private runtimes and checked requirements. Caller
    Python, pip, DLL and PowerShell module paths cannot select privileged code.
    """
    value = dict(os.environ)
    for key in list(value):
        upper = key.upper()
        if upper.startswith(("PYTHON", "PIP_", "LD_", "DYLD_")) or upper in {
                "PSMODULEPATH", "PATH", "SYSTEMROOT", "WINDIR", "COMSPEC", "PROGRAMFILES", "PROGRAMW6432", "PROGRAMDATA",
                "BASH_ENV", "ENV", "SHELLOPTS", "CDPATH", "GCONV_PATH",
                "REQUESTS_CA_BUNDLE", "CURL_CA_BUNDLE", "SSL_CERT_FILE", "SSL_CERT_DIR"} or upper.startswith("BASH_FUNC_"):
            value.pop(key)
    value.update(PYTHONUNBUFFERED="1", PYTHONNOUSERSITE="1", PYTHONDONTWRITEBYTECODE="1", PIP_CONFIG_FILE=os.devnull)
    if temporary is not None:
        for key in list(value):
            if key.upper() in {"TEMP", "TMP", "TMPDIR"}:
                value.pop(key)
        value.update(TEMP=str(temporary), TMP=str(temporary), TMPDIR=str(temporary))
    if os.name == "nt":
        def folder(identifier):
            buffer = ctypes.create_unicode_buffer(32768)
            if ctypes.windll.shell32.SHGetFolderPathW(None, identifier, None, 0, buffer):
                raise OSError("Cannot locate native Windows directories")
            return Path(buffer.value)
        system, programs, data = folder(37), folder(38), folder(35)
        windows = system.parent
        value.update(SystemRoot=str(windows), WINDIR=str(windows), COMSPEC=str(system / "cmd.exe"),
                     ProgramFiles=str(programs), ProgramW6432=str(programs), ProgramData=str(data),
                     PATH=os.pathsep.join(map(str, (system, windows, system / "WindowsPowerShell/v1.0"))),
                     PSModulePath=os.pathsep.join(map(str, (system / "WindowsPowerShell/v1.0/Modules", programs / "WindowsPowerShell/Modules"))))
    else:
        value["PATH"] = "/usr/sbin:/usr/bin:/sbin:/bin"
    return value

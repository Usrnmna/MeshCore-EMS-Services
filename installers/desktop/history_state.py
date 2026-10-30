"""Read-only OS service-state observation inside the isolated history reader."""
import ctypes
from ctypes import wintypes


class ServiceStatusProcess(ctypes.Structure):
    """SCM status fields; native handles and structures remain inside the read child."""
    _fields_ = [(name, wintypes.DWORD) for name in (
        "service_type", "current_state", "controls_accepted", "win32_exit_code",
        "service_exit_code", "check_point", "wait_hint", "process_id", "service_flags")]


def service_state(target):
    """Query only the fixed service; Windows creates no sc.exe descendant.

    POSIX systemctl observation executes within the history reader's dedicated
    process group, which its supervisor terminates on completion or cancellation.
    """
    if target != "windows-x64":
        from installers.datasets.gui.privileges import service_state as observe
        return observe(target)
    api = ctypes.WinDLL("advapi32", use_last_error=True)
    api.OpenSCManagerW.argtypes = [wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenSCManagerW.restype = wintypes.HANDLE
    api.OpenServiceW.argtypes = [wintypes.HANDLE, wintypes.LPCWSTR, wintypes.DWORD]
    api.OpenServiceW.restype = wintypes.HANDLE
    api.QueryServiceStatusEx.argtypes = [wintypes.HANDLE, ctypes.c_int, ctypes.c_void_p,
                                       wintypes.DWORD, ctypes.POINTER(wintypes.DWORD)]
    api.QueryServiceStatusEx.restype = wintypes.BOOL
    api.CloseServiceHandle.argtypes = [wintypes.HANDLE]
    api.CloseServiceHandle.restype = wintypes.BOOL
    manager = api.OpenSCManagerW(None, None, 1)  # SC_MANAGER_CONNECT only.
    if not manager:
        return "unknown"
    try:
        service = api.OpenServiceW(manager, "MeshCoreEMS", 4)  # SERVICE_QUERY_STATUS only.
        if not service:
            return "missing" if ctypes.get_last_error() == 1060 else "unknown"
        try:
            status = ServiceStatusProcess()
            needed = wintypes.DWORD()
            if not api.QueryServiceStatusEx(service, 0, ctypes.byref(status), ctypes.sizeof(status), ctypes.byref(needed)):
                return "unknown"
            return {1: "stopped", 4: "running"}.get(status.current_state, "pending")
        finally:
            api.CloseServiceHandle(service)
    finally:
        api.CloseServiceHandle(manager)

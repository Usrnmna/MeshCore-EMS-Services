"""Read-only native state observation without a Windows command descendant."""
import ctypes
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class HistoryStateTests(unittest.TestCase):
    def test_windows_state_uses_only_query_access_and_closes_native_handles(self):
        from installers.desktop import history_state
        for number, expected in ((1, "stopped"), (4, "running"), (2, "pending")):
            with self.subTest(number=number):
                def query(service, level, buffer, size, needed):
                    ctypes.cast(buffer, ctypes.POINTER(history_state.ServiceStatusProcess)).contents.current_state = number
                    return True
                api = SimpleNamespace(OpenSCManagerW=Mock(return_value=11), OpenServiceW=Mock(return_value=22),
                                      QueryServiceStatusEx=Mock(side_effect=query), CloseServiceHandle=Mock(return_value=True))
                with patch.object(ctypes, "WinDLL", return_value=api, create=True), patch("subprocess.run", side_effect=AssertionError("Unexpected command process")):
                    self.assertEqual(history_state.service_state("windows-x64"), expected)
                self.assertEqual(api.OpenSCManagerW.call_args.args, (None, None, 1))
                self.assertEqual(api.OpenServiceW.call_args.args, (11, "MeshCoreEMS", 4))
                self.assertEqual([call.args for call in api.CloseServiceHandle.call_args_list], [(22,), (11,)])

    def test_missing_windows_service_and_denial_remain_distinct(self):
        from installers.desktop import history_state
        for code, expected in ((1060, "missing"), (5, "unknown")):
            api = SimpleNamespace(OpenSCManagerW=Mock(return_value=11), OpenServiceW=Mock(return_value=0),
                                  QueryServiceStatusEx=Mock(), CloseServiceHandle=Mock(return_value=True))
            with patch.object(ctypes, "WinDLL", return_value=api, create=True), patch.object(ctypes, "get_last_error", return_value=code, create=True):
                self.assertEqual(history_state.service_state("windows-x64"), expected)
            self.assertEqual([call.args for call in api.CloseServiceHandle.call_args_list], [(11,)])


if __name__ == "__main__":
    unittest.main()

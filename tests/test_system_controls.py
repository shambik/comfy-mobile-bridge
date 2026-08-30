import base64
import unittest
from subprocess import CompletedProcess
from unittest.mock import Mock, patch

import backend.main as main_module


class WindowsLockTests(unittest.TestCase):
    def test_lock_uses_direct_api_when_bridge_is_in_active_session(self):
        user32 = Mock()
        user32.LockWorkStation = Mock(return_value=1)
        with patch.object(main_module.os, "name", "nt"), \
             patch.object(main_module, "_target_interactive_session_id", return_value=1), \
             patch.object(main_module, "_process_session_id", return_value=1), \
             patch.object(main_module, "_windows_dll", return_value=user32):
            locked, detail = main_module.lock_windows()

        self.assertTrue(locked)
        self.assertIn("session 1", detail)
        user32.LockWorkStation.assert_called_once_with()

    def test_lock_uses_interactive_task_when_bridge_is_in_session_zero(self):
        with patch.object(main_module.os, "name", "nt"), \
             patch.object(main_module, "_target_interactive_session_id", return_value=1), \
             patch.object(main_module, "_process_session_id", return_value=0), \
             patch.object(main_module, "_launch_interactive_lock_task", return_value=(True, "dispatched")) as dispatch:
            locked, detail = main_module.lock_windows()

        self.assertTrue(locked)
        self.assertEqual(detail, "dispatched")
        dispatch.assert_called_once_with(1)

    def test_target_prefers_active_bridge_session(self):
        with patch.object(main_module, "_active_interactive_session_ids", return_value=[1, 3]), \
             patch.object(main_module, "_process_session_id", return_value=3), \
             patch.object(main_module, "_active_console_session_id", return_value=1):
            self.assertEqual(main_module._target_interactive_session_id(), 3)

    def test_target_prefers_active_console_when_bridge_is_session_zero(self):
        with patch.object(main_module, "_active_interactive_session_ids", return_value=[2, 4]), \
             patch.object(main_module, "_process_session_id", return_value=0), \
             patch.object(main_module, "_active_console_session_id", return_value=4):
            self.assertEqual(main_module._target_interactive_session_id(), 4)

    def test_target_falls_back_to_active_rdp_session(self):
        with patch.object(main_module, "_active_interactive_session_ids", return_value=[2]), \
             patch.object(main_module, "_process_session_id", return_value=0), \
             patch.object(main_module, "_active_console_session_id", return_value=1):
            self.assertEqual(main_module._target_interactive_session_id(), 2)

    def test_interactive_lock_task_uses_scheduler_interactive_token(self):
        result = CompletedProcess([], 0, stdout="started\n", stderr="")
        with patch.object(main_module, "_powershell_executable", return_value="powershell.exe"), \
             patch.object(main_module.subprocess, "run", return_value=result) as run:
            locked, detail = main_module._launch_interactive_lock_task(7)

        self.assertTrue(locked)
        self.assertIn("session 7", detail)
        command = run.call_args.args[0]
        self.assertEqual(command[0], "powershell.exe")
        self.assertIn("-EncodedCommand", command)
        script = base64.b64decode(command[command.index("-EncodedCommand") + 1]).decode("utf-16le")
        self.assertIn("Schedule.Service", script)
        self.assertIn("LogonType = 3", script)
        self.assertIn("AllowDemandStart = $true", script)
        self.assertIn("LockWorkStation", script)
        self.assertIn("$targetSessionId = 7", script)
        self.assertIn("RunEx($null, 4, $targetSessionId, $null)", script)
        self.assertNotIn("__H3_TARGET_SESSION_ID__", script)
        self.assertEqual(run.call_args.kwargs["timeout"], 10)

    def test_interactive_lock_task_does_not_report_success_when_scheduler_fails(self):
        result = CompletedProcess([], 1, stdout="", stderr="access denied\n")
        with patch.object(main_module, "_powershell_executable", return_value="powershell.exe"), \
             patch.object(main_module.subprocess, "run", return_value=result):
            locked, detail = main_module._launch_interactive_lock_task(1)

        self.assertFalse(locked)
        self.assertIn("exit code 1", detail)
        self.assertIn("access denied", detail)


if __name__ == "__main__":
    unittest.main()

"""Linux 单实例分支与真实内核的跨进程竞争验证，可单独用 unittest 运行。"""

import errno
import json
import subprocess
import sys
import tempfile
import time
import unittest
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import Mock, patch
from uuid import uuid4

from backend import single_instance
from backend.single_instance import SingleInstance


class LinuxBranchTests(unittest.TestCase):
    def setUp(self):
        platform = patch.object(single_instance, "sys", SimpleNamespace(platform="linux"))
        platform.start()
        self.addCleanup(platform.stop)
        self.socket = Mock()
        socket_api = SimpleNamespace(AF_UNIX=object(), SOCK_STREAM=object(), socket=Mock(return_value=self.socket))
        sockets = patch.object(single_instance, "socket", socket_api)
        sockets.start()
        self.addCleanup(sockets.stop)
        self.instance = SingleInstance("Xalling.Test")
        self.addCleanup(self.instance.close)

    def test_owner_holds_socket_until_close_and_does_not_start_activation_thread(self):
        self.assertTrue(self.instance.acquire())
        self.socket.bind.assert_called_once_with(b"\0Xalling.Test")
        self.socket.close.assert_not_called()
        activate = Mock()
        self.instance.start(activate)
        activate.assert_not_called()
        self.assertIsNone(self.instance._thread)
        self.instance.close()
        self.instance.close()
        self.socket.close.assert_called_once_with()

    def test_duplicate_launch_closes_its_socket_and_returns_false(self):
        self.socket.bind.side_effect = OSError(errno.EADDRINUSE, "already running")
        self.assertFalse(self.instance.acquire())
        self.assertIsNone(self.instance._linux_socket)
        self.instance.close()
        self.socket.close.assert_called_once_with()

    def test_other_bind_errors_close_socket_and_propagate(self):
        self.socket.bind.side_effect = OSError(errno.EACCES, "permission denied")
        with self.assertRaises(PermissionError):
            self.instance.acquire()
        self.assertIsNone(self.instance._linux_socket)
        self.socket.close.assert_called_once_with()

    def test_socket_creation_error_propagates(self):
        with (
            patch.object(single_instance.socket, "socket", side_effect=OSError(errno.EMFILE, "too many files")),
            self.assertRaises(OSError),
        ):
            self.instance.acquire()
        self.assertIsNone(self.instance._linux_socket)


CHILD = """
import json
import os
import sys
from pathlib import Path
from backend.single_instance import SingleInstance
instance = SingleInstance(sys.argv[1])
try:
    owner = instance.acquire()
    Path(sys.argv[2]).write_text(json.dumps(owner), encoding='utf-8')
    if owner and sys.stdin.read() == 'crash':
        os._exit(0)
finally:
    instance.close()
"""


@unittest.skipUnless(sys.platform == "linux", "需要真实 Linux 内核")
class LinuxKernelTests(unittest.TestCase):
    def setUp(self):
        self.name = f"Xalling.Test.{uuid4()}"

    def test_duplicate_and_restart_after_normal_exit(self):
        primary, duplicate = SingleInstance(self.name), SingleInstance(self.name)
        try:
            self.assertTrue(primary.acquire())
            self.assertFalse(primary._linux_socket.get_inheritable())
            self.assertFalse(duplicate.acquire())
        finally:
            duplicate.close()
            primary.close()
        replacement = SingleInstance(self.name)
        try:
            self.assertTrue(replacement.acquire())
        finally:
            replacement.close()

    def test_concurrent_processes_and_restart_after_crash(self):
        with tempfile.TemporaryDirectory() as directory:
            processes = []
            try:
                for index in range(6):
                    result = Path(directory) / f"{index}.json"
                    process = subprocess.Popen(
                        [sys.executable, "-c", CHILD, self.name, str(result)],
                        stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
                    )
                    processes.append((process, result))
                owners = []
                deadline = time.monotonic() + 10
                for _, result in processes:
                    while True:
                        try:
                            owners.append(json.loads(result.read_text(encoding="utf-8")))
                            break
                        except (FileNotFoundError, json.JSONDecodeError):
                            self.assertLess(time.monotonic(), deadline, "子进程未及时返回结果")
                            time.sleep(0.01)
                self.assertEqual(sum(owners), 1)
                for (process, _), owner in zip(processes, owners, strict=True):
                    stdout, stderr = process.communicate(input="crash" if owner else "", timeout=10)
                    self.assertEqual(process.returncode, 0, stdout + stderr)
                replacement = SingleInstance(self.name)
                try:
                    self.assertTrue(replacement.acquire())
                finally:
                    replacement.close()
            finally:
                for process, _ in processes:
                    if process.poll() is None:
                        process.kill()
                        process.communicate(timeout=5)


if __name__ == "__main__":
    unittest.main()

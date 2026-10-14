"""真实 Windows 系统锁、跨进程竞争、退出回收和窗口唤醒。"""

import json
import subprocess
import sys
import time
from threading import Event
from types import SimpleNamespace
from unittest.mock import Mock
from uuid import uuid4

import pytest

from backend import single_instance
from backend.service.window import WindowService
from backend.single_instance import SW_RESTORE, SingleInstance, activate_window


@pytest.fixture
def instance_name(monkeypatch):
    if sys.platform != "win32":
        pytest.skip("Windows 系统锁")
    # 测试使用独立名称，绝不占用或唤醒用户正在使用的 Xalling。
    monkeypatch.setattr(single_instance, "_allow_existing_window_activation", lambda: None)
    return rf"Global\Xalling.Test.{uuid4()}"


def test_duplicate_signal_survives_startup_and_owner_can_restart(instance_name):
    primary, secondary = SingleInstance(instance_name), SingleInstance(instance_name)
    activated = Event()
    try:
        assert primary.acquire()
        assert not secondary.acquire()
        secondary.close()
        primary.start(activated.set)
        assert activated.wait(2)
        assert primary._thread.is_alive()
    finally:
        secondary.close()
        primary.close()
    assert primary._thread is None
    replacement = SingleInstance(instance_name)
    try:
        assert replacement.acquire()
    finally:
        replacement.close()


def test_repeated_launches_notify_running_owner(instance_name):
    primary = SingleInstance(instance_name)
    activated = Event()
    try:
        assert primary.acquire()
        primary.start(activated.set)
        for _ in range(3):
            activated.clear()
            duplicate = SingleInstance(instance_name)
            try:
                assert not duplicate.acquire()
                assert activated.wait(2)
            finally:
                duplicate.close()
    finally:
        primary.close()


def test_close_before_window_shown_does_not_start_listener(instance_name):
    instance = SingleInstance(instance_name)
    assert instance.acquire()
    instance.close()
    instance.start(Mock())
    assert instance._thread is None


def test_activation_failure_does_not_stop_listener(instance_name):
    primary = SingleInstance(instance_name)
    activated = Event()
    calls = []

    def activate():
        calls.append(True)
        activated.set()
        if len(calls) == 1:
            raise RuntimeError("窗口暂时无法唤醒")

    try:
        assert primary.acquire()
        primary.start(activate)
        for _ in range(2):
            activated.clear()
            duplicate = SingleInstance(instance_name)
            try:
                assert not duplicate.acquire()
                assert activated.wait(2)
            finally:
                duplicate.close()
        assert len(calls) == 2
    finally:
        primary.close()


CHILD = """
import json
import os
import sys
from pathlib import Path
import backend.single_instance as module
module._allow_existing_window_activation = lambda: None
instance = module.SingleInstance(sys.argv[1])
try:
    owner = instance.acquire()
    Path(sys.argv[2]).write_text(json.dumps(owner), encoding='utf-8')
    if owner and sys.stdin.read() == 'crash':
        os._exit(0)
finally:
    instance.close()
"""


def _wait_result(path):
    deadline = time.monotonic() + 10
    while time.monotonic() < deadline:
        if path.is_file():
            try:
                return json.loads(path.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                pass
        time.sleep(0.01)
    pytest.fail(f"子进程未返回单实例结果：{path}")


def test_concurrent_processes_have_one_owner_and_crash_releases_lock(instance_name, tmp_path):
    processes = []
    try:
        for index in range(6):
            result = tmp_path / f"{index}.json"
            process = subprocess.Popen(
                [sys.executable, "-c", CHILD, instance_name, str(result)],
                stdin=subprocess.PIPE, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True,
            )
            processes.append((process, result))
        owners = [_wait_result(result) for _, result in processes]
        assert sum(owners) == 1
        # 所有重复启动已退出；主进程直接崩溃，不执行 close()。
        for (process, _), owner in zip(processes, owners, strict=True):
            stdout, stderr = process.communicate(input="crash" if owner else "", timeout=10)
            assert process.returncode == 0, stdout + stderr
        replacement = SingleInstance(instance_name)
        try:
            assert replacement.acquire()
        finally:
            replacement.close()
    finally:
        for process, _ in processes:
            if process.poll() is None:
                process.kill()
                process.communicate(timeout=5)


@pytest.mark.parametrize("minimized", [False, True])
def test_activation_restores_only_minimized_windows(monkeypatch, minimized):
    api = Mock()
    api.IsIconic.return_value = minimized
    monkeypatch.setattr(single_instance, "_user32", lambda: api)
    activate_window(1234)
    if minimized:
        api.ShowWindowAsync.assert_called_once_with(1234, SW_RESTORE)
    else:
        api.ShowWindowAsync.assert_not_called()
    api.SetForegroundWindow.assert_called_once_with(1234)


def test_window_service_activation_preserves_maximize_state(monkeypatch):
    activate = Mock()
    monkeypatch.setattr("backend.service.window.IS_WINDOWS", True)
    monkeypatch.setattr("backend.service.window.activate_window", activate)
    window = SimpleNamespace(native=SimpleNamespace(Handle=Mock(ToInt64=Mock(return_value=1234))))
    service = WindowService()
    service.bind_window(window)
    service._is_maximized = True
    service.activate()
    activate.assert_called_once_with(1234)
    assert service._is_maximized

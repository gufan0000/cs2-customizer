# -*- coding: utf-8 -*-
"""2.2.0 自启升级自愈:旧路径自动重写、一致时不动、源码运行不劫持。

全程用假 winreg(sys.modules 注入),不碰真实注册表。
"""
import sys
import types

import pytest

from core.utils import autostart


class _FakeKey:
    def __enter__(self):
        return self

    def __exit__(self, *a):
        return False


class _FakeWinreg(types.ModuleType):
    HKEY_CURRENT_USER = object()
    KEY_READ = 1
    KEY_SET_VALUE = 2
    REG_SZ = 1

    def __init__(self):
        super().__init__("winreg")
        self.store = {}

    def OpenKey(self, root, path, reserved, access):
        return _FakeKey()

    def QueryValueEx(self, key, name):
        if name not in self.store:
            raise FileNotFoundError(name)
        return self.store[name], self.REG_SZ

    def SetValueEx(self, key, name, reserved, type_, value):
        self.store[name] = value

    def DeleteValue(self, key, name):
        if name not in self.store:
            raise FileNotFoundError(name)
        del self.store[name]


@pytest.fixture()
def fake_reg(monkeypatch):
    fake = _FakeWinreg()
    monkeypatch.setitem(sys.modules, "winreg", fake)
    return fake


def test_refresh_rewrites_stale_path(fake_reg, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\app\CS2 Customizer 2.3.0.exe", raising=False)
    fake_reg.store[autostart._VALUE_NAME] = r'"C:\app\CS2 Customizer 2.2.0.exe"'  # 旧版本路径
    assert autostart.refresh_if_enabled() is True
    assert fake_reg.store[autostart._VALUE_NAME] == r'"C:\app\CS2 Customizer 2.3.0.exe"'


def test_refresh_noop_when_path_current(fake_reg, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    monkeypatch.setattr(sys, "executable", r"C:\app\CS2 Customizer 2.2.0.exe", raising=False)
    fake_reg.store[autostart._VALUE_NAME] = r'"C:\app\CS2 Customizer 2.2.0.exe"'
    assert autostart.refresh_if_enabled() is False


def test_refresh_noop_when_autostart_not_set(fake_reg, monkeypatch):
    monkeypatch.setattr(sys, "frozen", True, raising=False)
    assert autostart.refresh_if_enabled() is False
    assert autostart._VALUE_NAME not in fake_reg.store  # 不会凭空开启


def test_refresh_never_runs_from_source(fake_reg, monkeypatch):
    """源码开发运行绝不劫持用户配置的 exe 自启项。"""
    monkeypatch.setattr(sys, "frozen", False, raising=False)
    fake_reg.store[autostart._VALUE_NAME] = r'"C:\app\CS2 Customizer 2.2.0.exe"'
    assert autostart.refresh_if_enabled() is False
    assert fake_reg.store[autostart._VALUE_NAME] == r'"C:\app\CS2 Customizer 2.2.0.exe"'

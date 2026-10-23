# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace

import pytest
from packaging.requirements import Requirement


def test_dependency_lock_excludes_unrelated_packages_and_checks_constraints():
    from build_tools.freeze_release_deps import dependency_closure
    packages = {
        "app": SimpleNamespace(version="1.0", requires=["child>=2", 'optional; extra == "feature"']),
        "child": SimpleNamespace(version="2.0", requires=[]),
        "optional": SimpleNamespace(version="3.0", requires=[]),
        "unrelated": SimpleNamespace(version="4.0", requires=[]),
    }
    assert set(dependency_closure([Requirement("app[feature]")], packages.__getitem__)) == {"app", "child", "optional"}
    with pytest.raises(ValueError):
        dependency_closure([Requirement("child>=3")], packages.__getitem__)


def test_flash_commands_are_applied_by_display_owner(monkeypatch):
    import queue
    import threading
    import flash_process as mod
    effect = mod.FlashEffectProcess()
    effect.initialize = lambda *args: None
    effect.is_running = True  # initialize normally starts the event loop
    owner = threading.get_ident()
    handled = []
    effect.update_style = lambda style: handled.append((style, threading.get_ident()))
    monkeypatch.setattr(mod, "FlashEffectProcess", lambda: effect)
    monkeypatch.setattr(mod.pygame, "quit", lambda: None)
    commands = queue.Queue()
    commands.put({"type": "update_style", "style": "test"})
    commands.put({"type": "shutdown"})
    mod.process_function(commands, 1, 1)
    assert handled == [("test", owner)]
    assert not effect.is_running

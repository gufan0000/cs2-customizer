# SPDX-License-Identifier: GPL-3.0-or-later
from types import SimpleNamespace
from pathlib import Path
import shlex

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


@pytest.mark.parametrize("job_name", ["test", "ui-audit"])
def test_ci_uses_release_constraints_and_invalidates_the_dependency_cache(job_name):
    import yaml

    root = Path(__file__).resolve().parents[1]
    workflow = yaml.safe_load((root / ".github/workflows/ci.yml").read_text(encoding="utf-8"))
    steps = workflow["jobs"][job_name]["steps"]
    install = next(step for step in steps if step.get("name") == "Install deps")
    tokens = shlex.split(install["run"])
    assert "-c" in tokens, "CI must test the dependencies shipped in the candidate"
    constraint = tokens[tokens.index("-c") + 1]
    assert constraint == "requirements.lock.txt" and (root / constraint).is_file()
    setup = next(step for step in steps if step.get("uses", "").startswith("actions/setup-python@"))
    assert constraint in setup["with"]["cache-dependency-path"].splitlines()
    assert setup["with"]["python-version"] == "3.13.17"


@pytest.mark.parametrize("version,allowed", [((3, 13, 12), False), ((3, 13, 16), False),
                                           ((3, 13, 17), True), ((3, 13, 18), True),
                                           ((3, 14, 0), False)])
def test_release_python_has_verified_security_fixes(version, allowed):
    from build_tools.freeze_release_deps import check_python_version

    if allowed:
        check_python_version(version)
    else:
        with pytest.raises(ValueError, match="3.13.17"):
            check_python_version(version)


def test_packaging_child_excludes_third_party_path_without_changing_parent(tmp_path, monkeypatch):
    import json
    import os
    import sys
    from build_tools.build_release import pyinstaller_environment, run

    inherited = os.pathsep.join((str(tmp_path / "unrelated-dlls"), os.environ["PATH"]))
    monkeypatch.setenv("PATH", inherited)
    monkeypatch.setenv("AUDIT_BUILD_SENTINEL", "keep-isolation-settings")
    child = tmp_path / "child.py"
    child.write_text(
        "import json, os\nfrom pathlib import Path\n"
        "Path(__file__).with_suffix('.json').write_text(json.dumps({"
        "'path': os.environ['PATH'], 'sentinel': os.environ['AUDIT_BUILD_SENTINEL']}))\n",
        encoding="utf-8",
    )
    run([sys.executable, str(child)], env=pyinstaller_environment(sys.executable))
    observed = json.loads(child.with_suffix(".json").read_text())
    windows = Path(os.environ["SystemRoot"])
    assert observed["path"].split(os.pathsep) == [str(Path(sys.executable).resolve().parent),
                                                str(windows / "System32"), str(windows)]
    assert observed["sentinel"] == "keep-isolation-settings"
    assert os.environ["PATH"] == inherited


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

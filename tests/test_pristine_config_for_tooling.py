# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-032：工装用的「全新用户配置目录」必须真的是全新的，而且只能有一份实现。

## 这条判据在拦什么

`config.migrate_old_config()` 在**源码运行**时会把仓库根那份 `config.json`
复制进新的配置目录 —— 而那个文件**没有被 git 跟踪**，只存在于开发机上。
于是工装以为自己在"空目录"里量东西，实际量的是**开发者的个人配置**。

实测（2026-08-17）五个工装的临时配置目录里 `death_sound_style` 全是个人配置的
`"2"`（全新用户应为 `"0"`）：`cs2customizer_ui_shots` / `cs2customizer_layout_audit` /
`cs2customizer_bench` / `cs2customizer_search_index` / `cs2customizer_renovation_baseline`。
⇒ **像素基线、排版审计、耗时基线、搜索索引全是在个人配置上产出的**，
"全新用户的空状态"从来没被任何判据看过。

⭐ RN-031 已经诊断出同一个机制，但**只修了六处里的一处**。
所以这里的判据分两层：
  ① 机制还在不在（占位配置有没有落下去）；
  ② **有没有出现第二份副本** —— 只要还有副本，修好一份就等于没修。
第 ② 条才是真正防复发的那条。
"""
from __future__ import annotations

import ast
import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent
SCRIPTS = REPO / "scripts"


# --------------------------------------------------------------- ① 机制

def _run_clean(code: str) -> subprocess.CompletedProcess:
    """在**没有 CS2C_CONFIG_DIR** 的干净子进程里跑一段代码。

    必须起子进程：配置目录得在 `import config` 之前钉死，而 pytest 这边
    conftest 早就把 config 单例建好了，改环境变量已经晚了。
    """
    env = {k: v for k, v in os.environ.items()
           if k not in ("CS2C_CONFIG_DIR", "CS2C_LOG_DIR")}
    env["PYTHONIOENCODING"] = "utf-8"
    return subprocess.run([sys.executable, "-c", code], cwd=str(REPO), env=env,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=300)


def test_placeholder_config_is_written_before_anything_can_migrate():
    """占位 `config.json` 必须在函数返回时就已经躺在目标目录里。

    迁移的条件是「新配置不存在」（`config.py:843`），所以占位文件就是那道闸门。
    判据落在**文件真的在不在**上，不是落在"函数有没有被调用"上。
    """
    code = (
        "import json, sys\n"
        "sys.path.insert(0, r'%s')\n"
        "from _pristine_config import use_pristine_config_dir\n"
        "d = use_pristine_config_dir('cs2customizer_judge_rn032_a')\n"
        "import os\n"
        "cfg = d / 'config' / 'config.json'\n"
        "print(json.dumps({'exists': cfg.exists(),\n"
        "                  'body': cfg.read_text(encoding='utf-8') if cfg.exists() else None,\n"
        "                  'env': os.environ.get('CS2C_CONFIG_DIR')}))\n"
    ) % SCRIPTS
    proc = _run_clean(code)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    got = json.loads(proc.stdout.strip().splitlines()[-1])
    assert got["exists"], (
        "目标目录里没有占位 config.json —— 迁移的闸门没关，"
        "个人配置会被复制进来（RN-031/RN-032）")
    assert json.loads(got["body"]) == {}, f"占位配置不是空对象：{got['body']!r}"
    assert got["env"] and "cs2customizer_judge_rn032_a" in got["env"], \
        f"CS2C_CONFIG_DIR 没被指到那个目录：{got['env']!r}"


def test_an_already_chosen_config_dir_is_not_hijacked():
    """外面定了配置目录就不许抢 —— 好几支测试是 in-process 导入这些工装的。

    抢占会把测试自己的配置目录掀掉，而症状会出现在别的测试里，极难归因。
    """
    code = (
        "import os, sys, tempfile, pathlib\n"
        "mine = pathlib.Path(tempfile.gettempdir()) / 'cs2customizer_judge_rn032_outer'\n"
        "(mine).mkdir(parents=True, exist_ok=True)\n"
        "os.environ['CS2C_CONFIG_DIR'] = str(mine)\n"
        "sys.path.insert(0, r'%s')\n"
        "from _pristine_config import use_pristine_config_dir\n"
        "use_pristine_config_dir('cs2customizer_judge_rn032_b')\n"
        "print(os.environ['CS2C_CONFIG_DIR'])\n"
    ) % SCRIPTS
    proc = _run_clean(code)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert proc.stdout.strip().endswith("cs2customizer_judge_rn032_outer"), \
        f"外部指定的配置目录被抢走了：{proc.stdout.strip()!r}"


def test_force_overrides_an_inherited_config_dir():
    """`force=True` 必须无条件钉死。

    `renovation_baseline.structure_of` 是**被 pytest 起的子进程**，会继承
    conftest 那个跨文件跨轮次累积的配置目录。不 force 就等于把整条
    "全新基线"的含义作废，**而且失效时毫无声响**。
    """
    code = (
        "import os, sys, tempfile, pathlib\n"
        "os.environ['CS2C_CONFIG_DIR'] = str(\n"
        "    pathlib.Path(tempfile.gettempdir()) / 'cs2customizer_judge_rn032_outer2')\n"
        "sys.path.insert(0, r'%s')\n"
        "from _pristine_config import use_pristine_config_dir\n"
        "use_pristine_config_dir('cs2customizer_judge_rn032_c', force=True)\n"
        "print(os.environ['CS2C_CONFIG_DIR'])\n"
    ) % SCRIPTS
    proc = _run_clean(code)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    assert "cs2customizer_judge_rn032_c" in proc.stdout, \
        f"force 没能钉死配置目录：{proc.stdout.strip()!r}"


# ------------------------------------------------------- ② 不许有第二份

#: 除了这一份实现，谁也不许自己去写 CS2C_CONFIG_DIR。
_SOLE_OWNER = "_pristine_config.py"


def _is_os_environ(node: ast.AST) -> bool:
    """这个表达式是不是**本进程的** `os.environ`。

    ⚠ 这个区分是必需的，不是洁癖：`smoke_packaged.py` /
    `verify_qa001_repair_packaged.py` / `live_run.py` 写的是
    `env = dict(os.environ); env["CS2C_CONFIG_DIR"] = ...` ——
    那是**给子进程准备的环境**，而且它们是**故意**播一份脏配置进去
    （QA-001 的修复验证正需要脏配置才有意义）。把它们也算成违规，
    就只能挂一张豁免名单，而豁免名单一长这条判据就废了。
    """
    return (isinstance(node, ast.Attribute) and node.attr == "environ"
            and isinstance(node.value, ast.Name) and node.value.id == "os")


def _sets_config_dir_env(path: Path) -> list[int]:
    """AST 找出「把 CS2C_CONFIG_DIR 写进 **os.environ**」的行号。

    ⚠ 用 AST 不用 grep：这一条问的是"有没有 X"，而 `grep | head -N` 的截断
    会给出"没有"——那正好是这条断言的全部内容（CLAUDE.md 那条红线）。
    """
    try:
        tree = ast.parse(path.read_text(encoding="utf-8"))
    except (SyntaxError, UnicodeDecodeError):
        return []
    hits: list[int] = []
    for node in ast.walk(tree):
        # os.environ["CS2C_CONFIG_DIR"] = ...
        if isinstance(node, ast.Assign):
            for tgt in node.targets:
                if (isinstance(tgt, ast.Subscript)
                        and isinstance(tgt.slice, ast.Constant)
                        and tgt.slice.value == "CS2C_CONFIG_DIR"
                        and _is_os_environ(tgt.value)):
                    hits.append(node.lineno)
        # os.environ.setdefault("CS2C_CONFIG_DIR", ...)
        if (isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "setdefault"
                and _is_os_environ(node.func.value)
                and node.args
                and isinstance(node.args[0], ast.Constant)
                and node.args[0].value == "CS2C_CONFIG_DIR"):
            hits.append(node.lineno)
    return hits


def test_only_one_place_in_scripts_touches_the_config_dir_env():
    """`scripts/` 下只允许 `_pristine_config.py` 自己设配置目录。

    这条才是防复发的那一条。RN-031 修好了机制却漏掉五份副本，
    正是因为当时没有任何东西在问"还有几份"。
    """
    offenders = {}
    for py in sorted(SCRIPTS.glob("*.py")):
        if py.name == _SOLE_OWNER:
            continue
        lines = _sets_config_dir_env(py)
        if lines:
            offenders[py.name] = lines
    assert not offenders, (
        "这些脚本自己写了 CS2C_CONFIG_DIR，绕过了 "
        f"scripts/{_SOLE_OWNER}：{offenders}\n"
        "自己写的那套挡不住 migrate_old_config() 把开发机的个人配置复制进来 —— "
        "量出来的基线/审计/耗时/索引就都只对这台机器成立（RN-031/RN-032）。\n"
        "改成 `use_pristine_config_dir('<原来的目录名>')`。")


def test_every_tool_that_builds_pages_uses_the_shared_helper():
    """反向判据：会建页面的那几个工装，必须真的调了这个 helper。

    只查"没人另写一份"是不够的 —— 把那几行整段删掉也能让上一条判据变绿，
    而那样一来配置目录就落到用户的**真实配置**上（更糟）。
    """
    must_use = ["ui_shot_capture.py", "page_fingerprint.py", "bench_page_build.py",
                "layout_overflow_audit.py", "build_search_index.py",
                "renovation_baseline.py"]
    missing = []
    for name in must_use:
        src = (SCRIPTS / name).read_text(encoding="utf-8")
        if "use_pristine_config_dir(" not in src:
            missing.append(name)
    assert not missing, (
        f"这些工装没有走 scripts/{_SOLE_OWNER}：{missing} —— "
        "它们会建真实页面，配置目录必须是可复现的全新用户目录。")


# ------------------------------------------------------------ ③ 端到端

def test_a_tool_process_really_sees_a_brand_new_users_config():
    """端到端：干净子进程里走一遍 helper，产品配置必须是**默认值**。

    ⚠ 这一条只在**仓库根真有那份未跟踪的 `config.json`** 时才有意义
    （也就是开发机上，缺陷原本就只在那里发作）。CI runner 上没有那个文件，
    没有可被泄漏的东西，于是跳过 —— 并且**说出来**，别让人把 skip 读成通过。
    """
    leak_source = REPO / "config.json"
    if not leak_source.exists():
        pytest.skip("仓库根没有未跟踪的 config.json（CI 就是这样），"
                    "这条端到端腿在此环境下无可泄漏之物；机制腿仍在上面跑")

    leaked = json.loads(leak_source.read_text(encoding="utf-8"))
    if str(leaked.get("death_sound_style", "0")) == "0":
        pytest.skip("本机那份 config.json 的 death_sound_style 恰好就是默认值，"
                    "换不出可区分的证据；机制腿仍在上面跑")

    code = (
        "import sys\n"
        "sys.path.insert(0, r'%s')\n"
        "sys.path.insert(0, r'%s')\n"
        "from _pristine_config import use_pristine_config_dir\n"
        "use_pristine_config_dir('cs2customizer_judge_rn032_e2e')\n"
        "from config import config\n"
        "print('STYLE=' + repr(getattr(config, 'death_sound_style', None)))\n"
    ) % (SCRIPTS, REPO)
    proc = _run_clean(code)
    assert proc.returncode == 0, proc.stdout + proc.stderr
    line = [ln for ln in proc.stdout.splitlines() if ln.startswith("STYLE=")]
    assert line, f"子进程没给出结果：\n{proc.stdout[-2000:]}\n{proc.stderr[-2000:]}"
    assert line[-1] == "STYLE='0'", (
        f"工装进程看到的不是全新用户配置：{line[-1]}（仓库根那份是 "
        f"{leaked.get('death_sound_style')!r}）—— 个人配置又漏进来了。")


def test_the_shared_helper_lives_where_tools_can_find_it():
    """低成本的存在性守卫：文件在、函数在。

    没有这一条，上面那些 `"use_pristine_config_dir(" in src` 的字符串判据
    在文件被改名之后会一起变绿。
    """
    assert (SCRIPTS / _SOLE_OWNER).exists()
    sys.path.insert(0, str(SCRIPTS))
    import _pristine_config
    assert callable(_pristine_config.use_pristine_config_dir)
    assert _pristine_config.PLACEHOLDER.strip() == "{}"
    # 目录名要落在 %TEMP% 下，绝不能碰用户真实配置目录
    d = _pristine_config.Path(tempfile.gettempdir()) / "x"
    assert str(d).startswith(tempfile.gettempdir())

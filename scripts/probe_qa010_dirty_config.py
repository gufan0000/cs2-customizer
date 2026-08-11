# -*- coding: utf-8 -*-
"""QA-010 探针：config.json 里一个脏值会不会让整个软件起不来。

`config.py` 的 `load_config` 里 `int(config_data.get("config_snapshot_max_keep") or 20)`
没有类型兜底，而它的 `except` 只兜 `(FileNotFoundError, JSONDecodeError, KeyError)`；
模块级 `config = Config()` 在 import 时就跑 `load_config` —— 于是 `ValueError`/
`TypeError` 一路冒泡，**`import config` 直接炸 → 软件永久起不来、无任何提示**。

逐档试不同类型的脏值，每档都开全新子进程 `import config`，用隔离配置目录。
修好之后重跑这个脚本：所有档位都应该"起得来"。

    python scripts/probe_qa010_dirty_config.py
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
import tempfile
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

work = Path(tempfile.gettempdir()) / "fanpai_dirty_cfg_probe"


def probe(value, label: str) -> tuple[bool, str]:
    cfg_dir = work / "config"
    log_dir = work / "logs"
    for d in (cfg_dir, log_dir):
        d.mkdir(parents=True, exist_ok=True)
    (cfg_dir / "config.json").write_text(
        json.dumps({"config_snapshot_max_keep": value}, ensure_ascii=False),
        encoding="utf-8")
    env = {**os.environ,
           "FANPAI_CONFIG_DIR": str(cfg_dir),
           "FANPAI_LOG_DIR": str(log_dir),
           "PYTHONIOENCODING": "utf-8"}
    p = subprocess.run(
        [sys.executable, "-c",
         "import config; print('IMPORT_OK', config.config.config_snapshot_max_keep)"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=120)
    ok = "IMPORT_OK" in (p.stdout or "")
    detail = (p.stdout or "").strip().splitlines()[-1:] or []
    err = [ln for ln in (p.stderr or "").strip().splitlines()
           if "Error" in ln or "error" in ln]
    msg = (detail[0] if ok else (err[-1] if err else "(无输出)"))
    print(f"  {label:28} → {'起得来' if ok else '**起不来**'}  {msg[:120]}")
    return ok, msg


print("脏值逐档实测（每次都是全新子进程 import config）：\n")
results = {}
for value, label in [
    ("abc", '字符串 "abc"'),
    ("", '空字符串 ""'),
    ([], "空列表 []"),
    ({"a": 1}, "字典"),
    (None, "null"),
    ("20", '数字字符串 "20"'),
    (20, "正常值 20"),
]:
    results[label] = probe(value, label)

bad = [k for k, (ok, _) in results.items() if not ok]
print(f"\n共 {len(results)} 档，其中 **{len(bad)} 档导致 import 失败**: {bad}")

if bad:
    print("\n再问一个更要紧的问题：用户能不能自救？")
    print("  —— 软件起不来，用户看不到任何界面；配置文件在 %LOCALAPPDATA%\\FanTool\\config.json，")
    print("     只能手动找到并删掉/改掉。对普通玩家等于变砖。")
    print("  —— 而且 1420 行的 except 分支（隔离损坏文件 + 回落默认）**根本走不到**，")
    print("     因为 ValueError 不在它捕获的三种异常里。")

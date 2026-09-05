# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""翻新工程：**完整指纹**这条腿也得有人看着（RN-136）。

## 缺陷

基线三件套里，只有**结构投影**那一条进了 CI（字体无关）。
另外两条（含几何的完整指纹、两档像素）是本机判据 —— 而"本机判据"在本仓的
实际含义一直是：**只有人主动敲 `--verify` 时才会被看一眼**。
收工六件套里没有这一格，于是没人敲。

代价是量出来的（2026-08-20 顺手一比）：16 页里 **5 页的指纹早就跟基线对不上**，

    special_sound  260/301 个控件不一致   ← 几乎整页
    voice_output    84/159
    flash           34/264
    viewmodel       14/201
    gun_sound        4/413

而这五页**全部已经关档**。腐烂是后面几轮改共享控件时一路蹭出来的，
没有任何一次改动被拦下来问过一句"你把已关档的页碰歪了"。

⭐ **一条没有判据看着的检查，等于没有这条检查** —— 它写在文档里、脚本也能跑，
但它不会自己跑。同一形状的教训本仓已经攒了三条：
「关档≠这页没问题」「只要还有第二份副本，修好一份等于没修」
「制度自己漏了一项时，遵守它的人不会自动补上」。

## 为什么这条不能进 CI

指纹含 `pos` / `size`，那是**文字排出来的宽度**决定的。runner 的字体跟这台
机器不一样，进 CI 必然天天假红 —— 而一条会假红的判据最后一定会被无视。
所以它只在**有真实字体的本机**跑；`build_tools/run_tests.py` 是推送前的门禁，
它跑得到，这就够了。

⚠ 本判据只在**采基线的那台机器**上跑，别处 skip。

⭐⭐ 第一版的 skip 条件写的是「字体库为空就跳过」，**当天就被 CI 打脸**：
GitHub 的 windows runner **字体多得很**，于是它没 skip，
拿 runner 的字体去比我这台机器采的几何 —— 当场红，
而红的原因跟被判的那次改动毫无关系（RN-140）。

⇒ skip 条件要描述的是**「样本可不可比」**，不是「环境看起来正不正常」。
现在采基线时一并存下环境签名（字体集哈希 / DPI / 缩放，见 `_env.json`），
判据先比签名：**不是同一套环境就 skip，是同一套就必须判。**
"""
from __future__ import annotations

import json
import os
import subprocess
import sys
from pathlib import Path

import pytest
from _denominator import must_scan

REPO = Path(__file__).resolve().parent.parent
BASELINE_DIR = REPO / "tests" / "baselines" / "renovation"
SCRIPTS = REPO / "scripts"

sys.path.insert(0, str(SCRIPTS))

#: `page_fingerprint.py` 的退出码约定（它自己在模块头写死的）。
_OK, _MISMATCH, _ENV_UNFIT = 0, 1, 2


def _pages_with_fingerprint() -> list[str]:
    if not BASELINE_DIR.exists():
        return []
    return sorted(d.name for d in BASELINE_DIR.iterdir()
                  if d.is_dir() and (d / "fingerprint.json").exists())


def _capture_now(pages: list[str], tmp_path: Path):
    """走 `page_fingerprint.py` 的正门取一份当下的指纹。

    非得子进程不可：那支脚本在**模块级**就 `os.environ.pop("QT_QPA_PLATFORM")`
    （它要真实字体）并钉死配置目录。判据要是直接 import 它，
    离屏就被掀掉了 —— 窗口会真的弹到用户脸上。

    ⚠⚠ **子进程的环境要先摘干净。** `use_pristine_config_dir()` 默认是
    「外面已经定了 `CS2C_CONFIG_DIR` 就不接管」—— 那是**故意**的，
    为的是别掀掉 in-process 导入这些脚本的测试自己的配置目录。
    代价是：从 pytest 里起子进程，它会**原样继承 conftest 那个跨文件跨轮次累积
    的配置目录**，于是量到的是"攒了一堆设置的软件"，不是全新用户。

    这个坑第一次踩就当场骗到我：判据一跑红出 11 页，其中 `crosshair`
    二十分钟前刚验过「指纹完全一致」。它**不报错、不警告**，只是悄悄换了个被测对象。
    ⭐ 所以下面不光摘，还要**验证真摘掉了** —— 拿子进程自己打印的日志路径当证据。
    """
    env = dict(os.environ)
    for var in ("CS2C_CONFIG_DIR", "CS2C_LOG_DIR"):
        env.pop(var, None)
    out = tmp_path / "fingerprint_now.json"
    proc = subprocess.run(
        [sys.executable, "scripts/page_fingerprint.py",
         "--pages", ",".join(pages), "--save", str(out)],
        cwd=REPO, capture_output=True, text=True, env=env,
        encoding="utf-8", errors="replace", timeout=900)
    blob = (proc.stdout or "") + (proc.stderr or "")
    assert "cs2customizer_test_logs" not in blob, (
        "取指纹的子进程用的是 **pytest 的配置目录**，不是全新用户目录 —— "
        "量到的东西跟基线的含义根本不是一回事。\n"
        "（`use_pristine_config_dir` 默认不抢占已设好的 CS2C_CONFIG_DIR，"
        "所以起子进程前必须把它摘掉，见本函数注释。）")
    if proc.returncode == _ENV_UNFIT:
        return None, proc
    assert proc.returncode == _OK, (
        f"取指纹失败（退出码 {proc.returncode}）：\n{blob[-2000:]}")
    return json.loads(out.read_text(encoding="utf-8")), proc


ENV_FILE = BASELINE_DIR / "_env.json"


def _env_now(tmp_path) -> dict | None:
    """当下这台机器的环境签名。取不到就返回 None。"""
    # 标记只能抄字面量：那支脚本**模块级就有副作用**（pop 掉 QT_QPA_PLATFORM
    # 去拿真实字体），真 import 会把判据进程的离屏掀掉，窗口弹到用户脸上。
    # 抄了就得钉住，否则它改个名，本判据会**一直 skip 而不报错**。
    marker = "===FINGERPRINT-ENV==="
    src = (SCRIPTS / "page_fingerprint.py").read_text(encoding="utf-8")
    assert f'ENV_MARKER = "{marker}"' in src, (
        "`page_fingerprint.ENV_MARKER` 的字面量变了，本判据取不到签名会一直 skip —— "
        "两边要一起改。")

    env = dict(os.environ)
    for var in ("CS2C_CONFIG_DIR", "CS2C_LOG_DIR"):
        env.pop(var, None)
    proc = subprocess.run([sys.executable, "scripts/page_fingerprint.py", "--emit-env"],
                   cwd=REPO, capture_output=True, text=True, env=env,
                   encoding="utf-8", errors="replace", timeout=300)
    blob = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode != _OK or marker not in blob:
        return None
    return json.loads(blob.split(marker, 1)[1].strip().splitlines()[0])


def test_archived_pages_still_match_their_fingerprint(tmp_path):
    """已关档页的完整指纹不许悄悄漂。"""
    pages = _pages_with_fingerprint()
    if not pages:
        pytest.skip("翻新工程尚未取任何指纹基线")

    if not ENV_FILE.exists():
        pytest.skip(f"基线里没有环境签名（{ENV_FILE.name}），重取一次基线就有了")
    want = json.loads(ENV_FILE.read_text(encoding="utf-8"))
    got = _env_now(tmp_path)
    if got != want:
        # ⚠ 这不是"环境坏了"，是"这台机器量出来的几何跟基线不可比"。
        pytest.skip(f"不是采基线的那台机器，几何不可比：基线 {want} / 本机 {got}")

    now, proc = _capture_now(pages, tmp_path)
    if now is None:
        pytest.skip("字体库为空 —— 几何不可信")

    from _page_structure import diff

    rotted = {}
    # ⭐ 分母是「真的比对过的页」。上面几处 `pytest.skip` 是**出口不是守卫** ——
    #   跳过和通过在门禁上是同一个颜色，所以到了这里必须有东西可比。
    must_scan(pages, "有指纹基线的已关档页")
    for pid in pages:
        base = json.loads(
            (BASELINE_DIR / pid / "fingerprint.json").read_text(encoding="utf-8"))
        must_scan(base, f"{pid} 的指纹基线条目", least=5)
        got = now.get(pid)
        assert got is not None, f"{pid} 这一页没取到指纹，但它有基线 —— 别静默放过"
        d = diff(base, got)
        if d:
            rotted[pid] = d

    assert not rotted, (
        "这些**已关档**页面的完整指纹跟基线对不上了：\n  "
        + "\n  ".join(f"{pid}：{len(d)}/{len(json.loads((BASELINE_DIR / pid / 'fingerprint.json').read_text(encoding='utf-8')))} 处"
                      for pid, d in rotted.items())
        + "\n\n头一页的前几处：\n  "
        + "\n  ".join(next(iter(rotted.values()))[:12])
        + "\n\n说法只有两种：\n"
        "  · 这次改动本不该碰到这些页 —— 那是**跨页波及**，回去看改了什么共享控件。\n"
        "  · 是获批的 B 堆改动 —— 跑 `--capture <页> --accept` 换基线，档案里记裁定号。\n"
        "⚠ 别直接 --accept 了事：这条判据存在的全部意义，"
        "就是逼着「已关档的页被碰歪了」这件事当场说出来。")


def test_the_skip_switch_itself_still_works(tmp_path):
    """skip 只准因为"不是这台机器" —— 反面守卫。

    ⭐ 上一条是「没有坏消息就算过」的判据，而它还带一个 skip 分支。
    这种判据最省事的死法不是变红，是**永远 skip**：
    基线目录改个名、脚本换个退出码，它就再也不判了，而报告里只是多一行浅灰的 s。
    所以这里把两件事正面钉住：基线在、脚本的退出码约定没变。
    """
    if not BASELINE_DIR.exists():
        # 开源仓的排除清单里没有 `tests/baselines/renovation/`（闭源界面截图 +
        # 本机字体采的数，不外发），那边**本来就没有**这条腿要看。
        # ⭐ 判据要落在裁定说的那件事上，不是它在某个仓库里的具体长相（RN-133 的教训）。
        pytest.skip("这个仓没有翻新工程基线目录（开源版按排除清单不含）")
    assert _pages_with_fingerprint(), (
        "基线目录在，里面却一页指纹都没有 —— 上一条判据会直接 skip，"
        "等于翻新工程少了一条腿而没人知道。")

    assert ENV_FILE.exists(), (
        f"基线目录在，却没有 {ENV_FILE.name} —— 上一条判据会永远 skip。"
        "重跑一次 `renovation_baseline.py --capture <页> --accept` 就会补上。")

    src = (SCRIPTS / "page_fingerprint.py").read_text(encoding="utf-8")
    assert "raise SystemExit(2)" in src, (
        "`page_fingerprint.py` 不再用退出码 2 表示「环境不合格」了 —— "
        "上一条判据的 skip 分支会失灵：没字体时它会当成**取指纹失败**报红，"
        "或者更坏，把假几何当成真差异。两边的约定要一起改。")

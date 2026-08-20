# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""翻新工程·基线三件套（总纲 §9.1）。

**动一页之前先把这一页锁进基线**，改完必须对得上 —— "不破功能"靠这个保障，
不靠小心。一条命令拿齐三样，另一条命令验回来。

三样东西，各管一件事，谁也替代不了谁：

  ① **结构指纹**（`page_fingerprint.py`）—— 控件树逐条比对，含几何。
     **字体相关，只能当本机判据。** 脚本自己在字体库为空时就拒绝出具。
  ② **结构投影**（`_page_structure.py`）—— 指纹去掉几何，只留类型/名字/启用态/文案。
     **字体无关，这一份才进 CI**（判据 `tests/test_renovation_baselines.py`）。
  ③ **两档像素**（`ui_shot_capture.py` 完整 + 紧凑）—— 量的是"画出来什么样"。
     几何审计量不到 drawText 画出界、占位文字被切这类问题（V-001/002/005 全是这样）。
     **本机判据，不进 CI**：runner 字体不同，像素上 CI 必然假红。
  ④ 外加**建页耗时**（`bench_page_build.py`）—— 记数，验收时不许劣化 >10%。

**①②的控件数会差几个，这是正常的，别去"修"它**（screen_effects 实测 74 vs 70，
差的是 4 个匿名 `QWidget`）：投影跑在**离屏**、指纹跑在**原生平台**（它要真实字体），
两种平台下 Qt 内部辅助控件的建法本就不同。要紧的不是两者相等，而是**各自可复现** ——
投影同条件连采两次实测 0 差异，而每份基线只跟同样方式采的新样本比。


用法：
    python scripts/renovation_baseline.py --capture screen_effects
    python scripts/renovation_baseline.py --verify  screen_effects
    python scripts/renovation_baseline.py --capture screen_effects --accept  # 改版获批后换基线
退出码：0=通过；1=有差异；2=环境不合格（无真实字体等）。

⚠ **设备页**曾经整类不走这里（构造即注册全局热键/占音频设备）。
RN-059 之后改成：中和条件由 `scripts/_audit_neutralize.py` 统一给出，
热键由 `CS2C_NO_GLOBAL_HOTKEYS` 闸门兜底 ⇒ 六页全部可以正常锁基线。
本脚本只拒绝 `unsafe_pages()`（当前为空），**不静默跳过** —— 静默少拍会被
读成"这几页也锁过了"（UP-096 的教训）。
"""
from __future__ import annotations

import argparse
import json
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
BASELINE_DIR = ROOT / "tests" / "baselines" / "renovation"

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


def _run(args: list[str]) -> tuple[int, str]:
    """跑子进程并**如实回传退出码**。

    ⚠ 绝不把退出码丢在管道里。本仓踩过：门禁脚本的退出码被产品退出链路
    洗成 0，判据于是永远绿。凡是"成不成"的结论，一律取进程级退出码。
    """
    proc = subprocess.run([sys.executable, *args], cwd=ROOT,
                          capture_output=True, text=True, encoding="utf-8",
                          errors="replace", timeout=900)
    return proc.returncode, (proc.stdout or "") + (proc.stderr or "")


def _refuse_device_pages(pages: list[str]) -> None:
    """只拒绝**中和不了**的页。

    RN-005/RN-059 之前这里拒绝的是整个 `DEVICE_OWNING_PAGES`，于是
    flash / viewmodel / voice_output / music 四页**连基线都没有**。
    现在中和条件与热键闸门都在 `scripts/_audit_neutralize.py` 一处，
    `unsafe_pages()` 当前是空集 —— 谁要往回加，就在那个文件里写清理由。
    """
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from _audit_neutralize import unsafe_pages

    blocked = [p for p in pages if p in unsafe_pages()]
    if blocked:
        print(f"!! 拒绝：{', '.join(blocked)} 目前没有可用的中和条件，硬拍会打扰前台。")
        print("   在 scripts/_audit_neutralize.py 里给出中和条件（并写清它挡住了什么）后再来。")
        raise SystemExit(2)


def structure_of(pages: list[str], expert: bool = False) -> dict:
    """**只在专用子进程里调**（见 `_structure_via_subprocess`）。

    离屏建页取结构投影 —— 这一份不需要真实字体。

    `expert` 默认 **False**，跟产品默认一致（RN-134）：基线要锁的是
    **用户看见的那一页**。6 个专家页靠 `_ui_mode.goto()` 的 force 够着，
    不再靠"把整个软件切成专家视图"来兜可达性。

    `pages == ["all"]` 时页面清单**从窗口自己拿**（`win._page_names`），
    免得判据里再抄一份会过期的 27 页名单。
    ⚠ 这一条路会先跑 `neutralize_apply`（否则设备页构造即占设备、打扰前台），
    因此**不适合用来采基线** —— 中和过的配置不是全新用户的配置。
    它只用于"同一批页面、两种界面模式"这种自己跟自己比的场合。
    """
    import os

    # ⚠ **必须是全新的空配置目录，而且要 force 不能 setdefault。**
    # 页面结构是随设置变的（总开关关着的时候，一排控件会置灰、提示语整段换掉）。
    # 第一版没管这个，于是基线在"总开关关闭"下采、判据在 conftest 那个**跨文件跨轮次
    # 累积**的 `cs2customizer_test_config` 下跑，10 处差异全是开关状态引起的假红。
    # 钉死在"全新用户的默认设置"上，基线才有确定的含义。
    # ⚠⚠ **RN-031/RN-032：光把目录清空是不够的。**
    # `config.migrate_old_config()` 在**源码运行**时会把仓库根那份 `config.json`
    # 复制进来（那是给"老版本就地升级"用的迁移路径）。而那个文件**没有被 git 跟踪** ——
    # 它只存在于开发机上。于是所谓"全新空配置目录"抓到的其实是**我的个人配置**：
    # 实测里面有 37 把武器配着风格、`onboarding_completed=True`，
    # 而 CI runner 上一个都没有 ⇒ 结构基线**在别人机器上永远对不上**，
    # 而且红的原因和被判的改动毫无关系（同 RN-021 那次的机器路径，这次是机器数据）。
    #
    # RN-032：这段逻辑原先在六个工装里各写一份，**六份都带同一个病**，
    # 我只修了这一份 ⇒ 像素/审计/耗时/索引全都还在个人配置上产出。
    # 现在收成 `_pristine_config` 一份，谁也别再抄。
    sys.path.insert(0, str(ROOT))
    sys.path.insert(0, str(ROOT / "scripts"))
    from _pristine_config import use_pristine_config_dir

    # force：本进程是**专为取全新基线而起的子进程**，而它是被 pytest 起的，
    # 会继承 conftest 那个跨轮次累积的配置目录 —— 不 force 就静默失效。
    use_pristine_config_dir("cs2customizer_renovation_pristine", force=True)
    os.environ["QT_QPA_PLATFORM"] = "offscreen"
    os.environ["CS2C_SAFE_MODE_ACTIVE"] = "1"
    from PySide6.QtWidgets import QApplication, QSystemTrayIcon

    from _audit_sandbox import sandbox_external_writes
    from _page_structure import structure

    from PySide6.QtCore import Qt

    app = QApplication.instance() or QApplication([])
    QSystemTrayIcon.isSystemTrayAvailable = staticmethod(lambda: False)
    sandbox_external_writes()

    import _ui_mode

    from config import config
    _ui_mode.apply(config, expert)
    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    # 建窗口径与 `page_fingerprint.build()` 逐条对齐（show + 定尺寸）。
    # 不对齐的话两份基线控件数会差几个（实测 74 vs 70），日后没人说得清
    # 是"改动引起的"还是"两套口径本来就不同"—— 那种噪声会把判据的信誉耗光。
    # WA_DontShowOnScreen：窗口永不映射到屏幕，绝不打扰前台。
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    app.processEvents()
    win.setMinimumSize(1200, 800)
    win.resize(1200, 800)
    app.processEvents()
    if list(pages) == ["all"]:
        import _audit_neutralize
        pages = [p for p in win._page_names
                 if p not in _audit_neutralize.unsafe_pages()]
        _audit_neutralize.apply(config, pages)

    out = {}
    try:
        for pid in pages:
            _ui_mode.goto(win, pid)
            app.processEvents()
            page = win.pages.get(pid)
            if page is None:
                print(f"!! 建不出页面 {pid}")
                raise SystemExit(2)
            out[pid] = structure(page)
    finally:
        win.close()
        win.deleteLater()
        app.processEvents()
    return out


_EMIT_MARKER = "===STRUCTURE-JSON==="


def _structure_via_subprocess(pages: list[str], expert: bool = False) -> dict:
    """**取结构投影的唯一正门。**

    非得起个子进程，是因为配置目录必须在 `import config` **之前**钉死，
    而调用方（尤其是 pytest，conftest 早就把 config 目录设成别的了）那时
    config 单例往往已经建好，改环境变量已经晚了。
    子进程是唯一能保证"全新默认配置"的办法。

    顺带一个好处：判据和取基线的工具**走的是同一条路径**，不会出现
    "基线那么采的、判据这么采的"这种谁也说不清的差异。
    """
    argv = ["scripts/renovation_baseline.py", "--emit-structure", ",".join(pages)]
    if expert:
        argv.append("--expert")
    code, out = _run(argv)
    if code != 0 or _EMIT_MARKER not in out:
        raise AssertionError(
            f"取结构投影失败（退出码 {code}）：\n{out[-3000:]}")
    return json.loads(out.split(_EMIT_MARKER, 1)[1])


def capture(pages: list[str], accept: bool) -> int:
    _refuse_device_pages(pages)
    for pid in pages:
        d = BASELINE_DIR / pid
        if d.exists() and not accept:
            print(f"!! {pid} 已有基线。改版获批后换基线请加 --accept；"
                  f"日常验收请用 --verify。")
            return 1
        d.mkdir(parents=True, exist_ok=True)

    print("① 结构投影（进 CI，字体无关）")
    struct = _structure_via_subprocess(pages)
    for pid, items in struct.items():
        (BASELINE_DIR / pid / "structure.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"   {pid:<18} {len(items):>4} 个控件")

    print("② 结构指纹（本机，含几何）")
    code, out = _run(["scripts/page_fingerprint.py", "--pages", ",".join(pages),
                      "--save", str(BASELINE_DIR / "_tmp_fp.json")])
    if code != 0:
        print(out[-2000:])
        return code
    fp = json.loads((BASELINE_DIR / "_tmp_fp.json").read_text(encoding="utf-8"))
    (BASELINE_DIR / "_tmp_fp.json").unlink()
    for pid, items in fp.items():
        (BASELINE_DIR / pid / "fingerprint.json").write_text(
            json.dumps(items, ensure_ascii=False, indent=1), encoding="utf-8")
        print(f"   {pid:<18} {len(items):>4} 个控件")

    # RN-140：把「这份几何是在什么环境下量出来的」一并入库。
    # 指纹的 pos/size 由文字排出来，换台机器就不可比 —— 判据靠这份签名
    # 判断"该不该拿这份基线来判"，而不是靠"有没有字体"这种看起来正常就放行的条件。
    code, out = _run(["scripts/page_fingerprint.py", "--emit-env"])
    from page_fingerprint import ENV_MARKER  # noqa: E402  取标记的唯一真相源
    if code == 0 and ENV_MARKER in out:
        (BASELINE_DIR / "_env.json").write_text(
            out.split(ENV_MARKER, 1)[1].strip() + "\n", encoding="utf-8")
        print(f"   环境签名: {out.split(ENV_MARKER, 1)[1].strip()}")
    else:
        print(f"   !! 环境签名没取到（退出码 {code}）—— 指纹判据会一直 skip，记进档案")

    print("③ 两档像素（本机，不进 CI）")
    shots = BASELINE_DIR / "_shots"
    for compact in (False, True):
        args = ["scripts/ui_shot_capture.py", "--out", str(shots),
                "--pages", ",".join(pages)]
        if compact:
            args.append("--compact")
        code, out = _run(args)
        if code != 0:
            print(out[-2000:])
            return code
    moved = 0
    for png in shots.glob("*.png"):
        mode, _, pid = png.stem.partition("_")
        if pid in pages:
            shutil.move(str(png), BASELINE_DIR / pid / f"{mode}.png")
            moved += 1
    shutil.rmtree(shots, ignore_errors=True)
    print(f"   {moved} 张图入库")

    print("④ 建页耗时")
    code, out = _run(["scripts/bench_page_build.py", "--only", ",".join(pages),
                      "--save", str(BASELINE_DIR / "_tmp_bench.json")])
    if code == 0 and (BASELINE_DIR / "_tmp_bench.json").exists():
        bench = json.loads((BASELINE_DIR / "_tmp_bench.json").read_text(encoding="utf-8"))
        (BASELINE_DIR / "_tmp_bench.json").unlink()
        for pid in pages:
            entry = bench.get(pid) if isinstance(bench, dict) else None
            (BASELINE_DIR / pid / "bench.json").write_text(
                json.dumps(entry, ensure_ascii=False, indent=1), encoding="utf-8")
            print(f"   {pid:<18} {entry}")
    else:
        # 不当成失败，但**必须说出来** —— 静默缺一件会被读成"三件套齐了"
        print(f"   !! 建页基准没取到（退出码 {code}），这一页的耗时棘轮暂缺，记进档案")

    print(f"\n基线已入库 → {BASELINE_DIR}")
    print("⚠ 记得在**同一个提交**里更新 build_tools/oss_sync 的排除清单 ——"
          "排除清单靠人脑列不全，漏一条不报错，真跑 --apply 时会静默删文件。")
    return 0


def verify(pages: list[str]) -> int:
    _refuse_device_pages(pages)
    bad = 0

    print("① 结构投影")
    struct = _structure_via_subprocess(pages)
    sys.path.insert(0, str(ROOT / "scripts"))
    from _page_structure import diff

    for pid in pages:
        base = BASELINE_DIR / pid / "structure.json"
        if not base.exists():
            print(f"   !! {pid} 没有基线，先 --capture")
            bad += 1
            continue
        diffs = diff(json.loads(base.read_text(encoding="utf-8")), struct[pid])
        if diffs:
            bad += 1
            print(f"   ✗ {pid}：{len(diffs)} 处结构差异")
            for d in diffs[:20]:
                print("      " + d)
        else:
            print(f"   ✓ {pid}")

    print("② 结构指纹（含几何）")
    tmp = BASELINE_DIR / "_verify_fp.json"
    merged = {pid: json.loads((BASELINE_DIR / pid / "fingerprint.json")
                              .read_text(encoding="utf-8"))
              for pid in pages if (BASELINE_DIR / pid / "fingerprint.json").exists()}
    tmp.write_text(json.dumps(merged, ensure_ascii=False), encoding="utf-8")
    code, out = _run(["scripts/page_fingerprint.py", "--pages", ",".join(pages),
                      "--compare", str(tmp)])
    tmp.unlink(missing_ok=True)
    print("   " + "\n   ".join(out.strip().splitlines()[-6:]))
    if code == 1:
        bad += 1
    elif code == 2:
        print("   !! 环境不合格（多半是字体库为空），指纹这一腿没验成 —— 不算通过")
        bad += 1

    print("③ 两档像素：本脚本只负责出新图，**看图是人的活**")
    print(f"   基线图在 {BASELINE_DIR}/<page>/[full|compact].png")
    print("   重出一份对比：python scripts/ui_shot_capture.py --out H:/tmp/verify "
          f"--pages {','.join(pages)}  （再加 --compact 出紧凑档）")

    if bad:
        print(f"\n✗ {bad} 项对不上。")
        print("  按总纲 §4⑥：**A 堆一旦对不上等同基线，就自动升 B 走裁定** —— "
              "别在这里自行判断'这个差异无所谓'。")
        return 1
    print("\n✓ 结构与指纹均与基线一致")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser(description="翻新工程·基线三件套")
    ap.add_argument("--capture", metavar="PAGES", help="逗号分隔的页面 id")
    ap.add_argument("--verify", metavar="PAGES")
    ap.add_argument("--accept", action="store_true",
                    help="改版获批后覆盖既有基线（B 堆专用，A 堆绝不该用到）")
    ap.add_argument("--emit-structure", metavar="PAGES",
                    help="内部用：在全新默认配置下吐出结构投影 JSON（见 _structure_via_subprocess）")
    sys.path.insert(0, str(ROOT / "scripts"))
    import _ui_mode
    _ui_mode.add_expert_argument(ap)
    args = ap.parse_args()

    if args.emit_structure:
        pages = [p.strip() for p in args.emit_structure.split(",") if p.strip()]
        _refuse_device_pages(pages)
        data = structure_of(pages, expert=args.expert)
        print(_EMIT_MARKER)
        print(json.dumps(data, ensure_ascii=False))
        return 0

    if args.capture:
        return capture([p.strip() for p in args.capture.split(",") if p.strip()],
                       args.accept)
    if args.verify:
        return verify([p.strip() for p in args.verify.split(",") if p.strip()])
    ap.print_help()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

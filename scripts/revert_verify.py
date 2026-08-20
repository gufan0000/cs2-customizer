#!/usr/bin/env python
# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""判据回退验证台：逐条把产品代码改坏，确认对应判据**真的会变红**。

⚠ 这个文件**跨轮次长期使用**，每轮新增判据都往 `REVERTS` 里添一条。
断点应当是**真实发生过的缺陷**，不要编。

**为什么需要它**：判据"不该绿而绿"比"不该红而红"危险得多——一条假绿的判据
比没有判据更糟，因为它会让人以为这块有人看着。R9-A 就写出过一条假绿的
（用 `"名字" in 源码` 判断"调用了某函数"，而 `import` 行本身含那个名字）。

下面每一处断点都是 R9 期间**真实发生过的缺陷**，不是编出来的：
kill_voice 的 TEST_LEVELS 漏写、压缩头部逐轮堆积、空行逐轮增殖、
`pid=` 里的等号被剥掉、T 型竖杆画成完整十字……

用法：
    python scripts/revert_verify.py            # 全跑
    python scripts/revert_verify.py --only R10
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent

#: ⚠ **版本锚点必须推导，不许手写。**
#: 2026-08-18 抬 2.2.3 → 2.2.4 时，失效体检一次报出 **4 条**断点锚点腐烂
#: （filevers / ProductName / ProductVersion / README 标题），
#: 全是同一个病根：**它们按定义就写着"当前版本号"，所以每次发版必然腐烂**。
#: 拍出来的会腐烂，推导出来的不会 —— 同 RN-090 那条教训。
def _current_version() -> str:
    m = re.search(r'^VERSION\s*=\s*"([^"]+)"',
                  (ROOT / "config.py").read_text(encoding="utf-8"), re.M)
    if not m:
        raise SystemExit("config.py 里找不到 VERSION —— 版本锚点无从推导")
    return m.group(1)


_VER = _current_version()
_VER_TUPLE = "(" + ", ".join(_VER.split(".")) + ", 0)"
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

#: RN-093：**改坏期间的原文落盘**。内存里的 `finally` 挡不住 SIGTERM ——
#: `timeout 900 python scripts/revert_verify.py` 到点把进程杀掉时，
#: 被改坏的产品文件就**原样留在工作区里**，而且不会有任何提示。
#: 2026-08-18 实际发生：`gui_widget.py` 的 RN-060 断点（把
#: `_snap_nav_scroll_to_item_boundary(...)` 换成 `pass`）被留在树上，
#: 于是 ① 那条判据当场红，我差点把它当成真的回归去查；
#: ② 下一轮回退验证的失效体检把这条断点报成"锚点出现 0 次"（连锁误诊）；
#: ③ **最坏的情况是它被一起提交上去** —— 一次没跑成的自检把产品改坏了。
SNAPSHOT_DIR = ROOT / ".revert_verify_snapshot"
MANIFEST = SNAPSHOT_DIR / "manifest.json"


def save_snapshot(snapshot: dict[Path, bytes]) -> None:
    """把改坏之前的原文写到磁盘上，进程被杀也还能找回来。"""
    shutil.rmtree(SNAPSHOT_DIR, ignore_errors=True)
    SNAPSHOT_DIR.mkdir(parents=True, exist_ok=True)
    manifest = {}
    for i, (path, data) in enumerate(sorted(snapshot.items(), key=lambda kv: str(kv[0]))):
        bak = SNAPSHOT_DIR / f"{i:03d}.bak"
        bak.write_bytes(data)
        manifest[path.relative_to(ROOT).as_posix()] = bak.name
    MANIFEST.write_text(json.dumps(manifest, ensure_ascii=False, indent=2), encoding="utf-8")


def restore_from_disk() -> list[str]:
    """把上一轮没跑完留下的改坏文件还原，返回被还原的相对路径。"""
    if not MANIFEST.exists():
        return []
    try:
        manifest = json.loads(MANIFEST.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return []
    restored = []
    for rel, bak_name in manifest.items():
        path, bak = ROOT / rel, SNAPSHOT_DIR / bak_name
        if not bak.exists() or not path.exists():
            continue
        data = bak.read_bytes()
        if path.read_bytes() != data:
            path.write_bytes(data)
            restored.append(rel)
    return restored


def clear_snapshot() -> None:
    shutil.rmtree(SNAPSHOT_DIR, ignore_errors=True)


def _install_emergency_restore() -> None:
    """被 Ctrl-C / `timeout` 杀掉时，先还原再死。"""

    def _handler(signum, _frame):
        restored = restore_from_disk()
        clear_snapshot()
        print(f"\n!! 收到信号 {signum}，已还原 {len(restored)} 个被改坏的文件后退出。",
              flush=True)
        os._exit(130)

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass            # 非主线程 / 平台不支持，忽略（磁盘快照仍然兜底）


class Revert:
    def __init__(self, group, name, rel_path, old, new, selector, defect):
        self.group = group
        self.name = name
        self.path = ROOT / rel_path
        self.old = old
        self.new = new
        self.selector = selector      # 传给 pytest 的 -k 或 nodeid
        self.defect = defect          # 这个断点模拟的是哪个真实缺陷


REVERTS = [
    # ============================================ R9-A：t_shape 第五样式
    Revert(
        "R9-A", "从 USER_STYLES 里删掉 t_shape",
        "crosshair_overlay.py",
        'USER_STYLES = ("crosshair", "dot", "circle", "t_shape", "custom")',
        'USER_STYLES = ("crosshair", "dot", "circle", "custom")',
        "tests/test_crosshair_style_catalog_r9a.py::test_ui_labels_cover_exactly_the_renderer_styles",
        "渲染器与 UI 名表漂移：点得中但画不出来",
    ),
    Revert(
        "R9-A", "T 型竖杆画成完整十字",
        "crosshair_overlay.py",
        # 锚点跟着中心间隙(gap)那次改动搬过家：原来是 cx,cy 起画，现在从 rot(0, gap) 起。
        "    bx1, by1 = rot(0, gap)",
        "    bx1, by1 = rot(0, -half)",
        "tests/test_crosshair_style_catalog_r9a.py::test_t_shape_has_no_pixels_above_the_center_line",
        "几何错但不报错：像素照样有，只有肉眼看得出不是 T",
    ),
    Revert(
        "R9-A", "破碎时 t_shape 不再算线状族",
        "crosshair_overlay.py",
        '        if state.style in ("crosshair", "t_shape"):',
        '        if state.style in ("crosshair",):',
        "tests/test_crosshair_style_catalog_r9a.py::test_shatter_treats_t_shape_as_a_line_style",
        "击杀破碎效果碎成圆点而不是线段",
    ),
    Revert(
        # 2026-08-16：这条原来叫「预览漏掉 t_shape 分支」，打的是
        # `elif style == "t_shape":`。08-15 把预览改成直接调 paint_crosshair 之后，
        # 那个分支连同整套私绘代码一起没了，判据也换成了反向的那条，
        # 而本文件没跟着改——**锚点和判据名双双失效，谁都没发现**，
        # 直到它把整个回退验证台卡在「基线就不绿」上。
        "R9-A", "预览又自己按样式分叉画一份",
        "pages/crosshair_page.py",
        "            frame = CrosshairAnimator().advance(state, 0.0)",
        "            frame = CrosshairAnimator().advance(state, 0.0)\n"
        "            style = state.style\n"
        "            if style == \"t_shape\":\n"
        "                pass",
        "tests/test_crosshair_style_catalog_r9a.py::test_preview_has_no_private_drawing_branches",
        "预览和渲染层各画各的几何：十字预览大一倍、点准心随粗细漂移",
    ),
    Revert(
        "R9-A", "样式名表被抄第二份",
        "pages/crosshair_page.py",
        'CROSSHAIR_STYLE_LABELS = {',
        '_LEGACY_LABELS = {"crosshair": "十字"}\nCROSSHAIR_STYLE_LABELS = {',
        "tests/test_crosshair_style_catalog_r9a.py::test_style_labels_are_spelled_out_only_once_in_the_page",
        "样式名表回潮成三份，改一处漏两处",
    ),
    # ============================================ R9-A：审计副作用（UP-090/093）
    Revert(
        "R9-A", "审计脚本删掉沙箱调用（保留 import）",
        "scripts/layout_overflow_audit.py",
        "sandbox_external_writes()",
        "pass  # 沙箱调用被删，但 import 还在",
        "tests/test_audit_side_effects_r9a.py::test_every_page_building_script_sandboxes_the_game_dir",
        "第一版判据在这里假绿过：import 行本身含函数名",
    ),
    Revert(
        "R9-A", "真机跑测不再隔离游戏目录",
        "scripts/live_run.py",
        '        data["csgo_dir"] = str(game_dir)',
        '        pass  # 不设 csgo_dir',
        "tests/test_audit_side_effects_r9a.py::test_live_run_sandboxes_the_game_dir_by_default",
        "UP-093：跑一次真机测试就写用户真实 CS2 目录",
    ),
    Revert(
        "R9-A", "沙箱不再掐配置落盘",
        "scripts/_audit_sandbox.py",
        "    block_config_persistence(verbose=verbose)",
        "    pass  # 落盘不掐了，只改内存里的 csgo_dir",
        "tests/test_audit_side_effects_r9a.py::test_audit_never_persists_config",
        "跑一次审计，用户真实配置里的 CS2 目录就被改成 %TEMP% 沙箱路径",
    ),
    Revert(
        # 只掐两个公开入口不够：防抖 timer 和 atexit 兜底都直接调 _do_save_config。
        # 这条断点专门盯"掐漏了那个真正写盘的"。
        "R9-A", "沙箱漏掐真正写盘的那个入口",
        "scripts/_audit_sandbox.py",
        '_SAVE_ENTRY_POINTS = ("save_config", "save_config_now", "_do_save_config")',
        '_SAVE_ENTRY_POINTS = ("save_config", "save_config_now")',
        "tests/test_audit_side_effects_r9a.py::test_audit_never_persists_config",
        "公开入口都掐了，防抖 timer 到点照样把沙箱路径写进用户配置",
    ),
    # ============================================ R9-B：崩溃日志压缩
    Revert(
        "R9-B", "真故障块不再保留",
        "main_widget.py",
        "            kept.append(block)",
        "            pass  # 真故障块被丢掉",
        "tests/test_native_crash_log_r9b.py::test_real_crash_blocks_survive_compaction",
        "压缩把该留的证据删了——这个改动最大的风险方向",
    ),
    Revert(
        "R9-B", "没东西可压时也重写文件",
        "main_widget.py",
        "        if not (empty_count or benign_count or dropped_old):\n            return  # 没有可压的东西，别动文件",
        "        if False:\n            return",
        "tests/test_native_crash_log_r9b.py::test_nothing_to_compact_leaves_the_file_untouched",
        "每次启动都重写一遍纯属自找风险",
    ),
    Revert(
        "R9-B", "旧压缩头不再吸收（逐轮堆积）",
        "main_widget.py",
        "            if line.startswith(_COMPACT_MARK):\n                continue                      # 旧的压缩标题行，丢掉",
        "            if False:\n                continue",
        "tests/test_native_crash_log_r9b.py::test_repeated_compaction_accumulates_instead_of_stacking_headers",
        "第一版真栽在这：启动 N 次就有 N 段「已压缩」说明",
    ),
    Revert(
        "R9-B", "块尾空行不再削（逐轮增殖）",
        "main_widget.py",
        "            while block and not block[-1].strip():\n                block = block[:-1]",
        "            pass",
        "tests/test_native_crash_log_r9b.py::test_repeated_compaction_accumulates_instead_of_stacking_headers",
        "空行像压缩标题一样逐轮增殖",
    ),
    Revert(
        "R9-B", "剥等号时把 pid= 也剥了",
        "main_widget.py",
        '                stamp = block[0][len(_SESSION_MARK):].strip().rstrip("=").strip()',
        '                stamp = block[0].replace("=", "").strip()',
        "tests/test_native_crash_log_r9b.py::test_session_stamp_keeps_the_pid_readable",
        "pid=37392 被写成 pid37392",
    ),
    Revert(
        "R9-B", "子进程闸门被移到压缩之后",
        "main_widget.py",
        '        if not os.environ.get("_CS2C_CRASHLOG_COMPACTED"):\n'
        "            _compact_native_crash_log(crash_path)\n"
        '            os.environ["_CS2C_CRASHLOG_COMPACTED"] = "1"',
        "        _compact_native_crash_log(crash_path)\n"
        '        if not os.environ.get("_CS2C_CRASHLOG_COMPACTED"):\n'
        '            os.environ["_CS2C_CRASHLOG_COMPACTED"] = "1"',
        "tests/test_native_crash_log_r9b.py::test_subprocesses_do_not_compact",
        "三个进程各压一遍，主进程的 append 句柄被打乱",
    ),
    # ============================================ R9-C：页头统一
    Revert(
        "R9-C", "某页改回手搓页头",
        "pages/about_page.py",
        "        header = PageHeader(",
        '        _legacy = QLabel("关于软件")\n'
        '        _legacy.setObjectName("titleLabel")\n'
        "        header = PageHeader(",
        "tests/test_page_header_adoption_r9c.py::test_no_page_hand_rolls_a_title_label",
        "样板悄悄长回来——照着隔壁页复制没人拦",
    ),
    Revert(
        "R9-C", "又写死了标题字号",
        "pages/about_page.py",
        "            title_font_size=None,",
        "            title_font_size=24,",
        "tests/test_page_header_adoption_r9c.py::test_no_page_pins_a_title_font_size",
        "UP-092：写了 4 种字号，一个都没生效，纯误导",
    ),
    # ============================================ R9-D：音效页基类
    Revert(
        "R9-D", "kill_voice 的连杀档位漏写",
        "pages/kill_voice_page.py",
        "    TEST_LEVELS = [1, 2, 3, 4, 5]",
        "    TEST_LEVELS = None",
        "tests/test_sound_page_base_r9d.py::test_only_the_two_kill_pages_offer_kill_streak_levels",
        "我 R9-D 自己犯的：36 个按钮凭空消失，单元测试和 ruff 全绿",
    ),
    Revert(
        "R9-D", "基类钩子给默认值而不是抛异常",
        "pages/sound_page_base.py",
        "        switch_weapon / reload_sound 取本地扫描出来的 per-weapon 字典。\n"
        '        """\n'
        "        raise NotImplementedError",
        "        switch_weapon / reload_sound 取本地扫描出来的 per-weapon 字典。\n"
        '        """\n'
        "        return []",
        "tests/test_sound_page_base_r9d.py::test_base_class_hooks_fail_loudly_when_not_overridden",
        "新页忘了覆盖 ⇒ 静默拿到空风格表，比直接炸难查得多",
    ),
    # ============================================ R10：页签滚动 / 按钮宽度
    Revert(
        "R10", "flash 基础设置页签的滚动区被删掉",
        "pages/flash_page.py",
        "        scroll = QScrollArea()\n"
        "        scroll.setWidgetResizable(True)\n"
        "        scroll.setFrameShape(QFrame.NoFrame)\n"
        "        scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)\n"
        "\n"
        "        content = QWidget()\n"
        "        layout = QVBoxLayout(content)\n"
        "        layout.setContentsMargins(8, 8, 8, 8)\n"
        "        layout.setSpacing(10)\n"
        "\n"
        "        controls_card, controls_layout = SettingsCard.make(",
        "        content = QWidget()\n"
        "        layout = QVBoxLayout(content)\n"
        "        layout.setContentsMargins(8, 8, 8, 8)\n"
        "        layout.setSpacing(10)\n"
        "\n"
        "        controls_card, controls_layout = SettingsCard.make(",
        "tests/test_tab_scroll_and_button_width_r10.py::test_every_tab_is_scrollable",
        "UP-095：页签装不下时 Qt 压扁控件，字形重叠不可读",
    ),
    Revert(
        "R10", "special_sound 的 C4 页签滚动区被删掉",
        "pages/special_sound_page.py",
        "        tab_scroll = QScrollArea()\n"
        "        tab_scroll.setWidgetResizable(True)\n"
        "        tab_scroll.setFrameShape(QFrame.NoFrame)\n"
        "        tab_scroll.setHorizontalScrollBarPolicy(Qt.ScrollBarAlwaysOff)\n"
        "\n"
        "        content = QWidget()\n"
        "        layout = QVBoxLayout(content)\n"
        "        layout.setContentsMargins(8, 8, 8, 8)\n"
        "        layout.setSpacing(10)\n"
        "\n"
        "        card, card_layout = SettingsCard.make(\n"
        '            "C4 音效",',
        "        content = QWidget()\n"
        "        layout = QVBoxLayout(content)\n"
        "        layout.setContentsMargins(8, 8, 8, 8)\n"
        "        layout.setSpacing(10)\n"
        "\n"
        "        card, card_layout = SettingsCard.make(\n"
        '            "C4 音效",',
        "tests/test_tab_scroll_and_button_width_r10.py::test_every_tab_is_scrollable",
        "UP-081：余量薄的页签，文案一变长就翻车",
    ),
    Revert(
        "R10", "「重置位置和大小」又被写死宽度",
        "pages/kill_icon_page.py",
        "        reset_btn.setMinimumWidth(146)",
        "        reset_btn.setFixedWidth(146)",
        "tests/test_tab_scroll_and_button_width_r10.py::"
        "test_known_tight_buttons_are_not_width_pinned[kill_icon_page.py]",
        "UP-094：可用区 108px 需 112px，字号放大时打省略号",
    ),
    Revert(
        # KI-7 把「保存播放设置」搬进了素材工坊。按钮还是那一个，UP-094 的风险
        # 一模一样（有未保存改动时文案变成「保存播放设置 *」，更宽），只是
        # `TIGHT_BUTTONS` 那份名单只扫 pages/，够不着对话框——所以断点改打在
        # 工坊自己那条"底栏文案不许被打省略号"的判据上。
        "R10", "工坊「保存播放设置」又被写死宽度",
        "dialogs/kill_icon_workshop.py",
        "        self.save_fps_btn.setMinimumWidth(120)",
        "        self.save_fps_btn.setFixedWidth(72)",
        "tests/test_kill_icon_workshop_ki7.py::test_no_button_text_gets_elided",
        "UP-094：写死宽度 + 中文文案 + 字号缩放 = 截断，而对话框不在排版审计视野里",
    ),
    Revert(
        "R10", "产品代码里又混进编码损坏",
        "kill_icon_player.py",
        # KI-1 把本文件整个重写成 Qt 版，原锚点（"""加载旧版逐帧动画"""）随
        # pygame worker 一起没了。换成同文件里另一句一行中文 docstring——这条
        # 判据验的是"产品代码里混进私有区乱码能不能被逮住"，与锚在哪句无关。
        '        """老接口，保留空实现：缓存现在跟着风格与缩放走，不需要外部清。"""',
        # 注意：这里写的是**转义序列**，本文件源码里是 6 个 ASCII 字符，
        # 只有写进目标文件时才变成真正的私有区字符——否则本文件自己就"损坏"了。
        '        """老接口，保留空实现：缓存现在跟着风格与缩放走，不需要外部清\ue000。"""',
        "tests/test_tab_scroll_and_button_width_r10.py::"
        "test_no_encoding_corruption_outside_the_tutorial_corpus",
        "UP-098：中文变乱码但 Python 照常运行、测试照常绿，只有用户看见乱码",
    ),

    # ==================================== R11：紧凑模式 + 门禁分母 + GUI 线程
    Revert(
        "R11", "把紧凑档从排版审计里拿掉",
        "scripts/layout_overflow_audit.py",
        'ap.add_argument("--compact", action="store_true",',
        'ap.add_argument("--compact-DISABLED", action="store_true",',
        "tests/test_audit_coverage_r11.py::test_layout_audit_has_a_compact_mode",
        "UP-100：紧凑模式（用户点一下按钮就进）重新变成零判据覆盖的盲区",
    ),
    Revert(
        "R11", "紧凑档尺寸和产品代码对不上",
        "scripts/layout_overflow_audit.py",
        "COMPACT_SIZE = (860, 640)",
        "COMPACT_SIZE = (900, 700)",
        "tests/test_audit_coverage_r11.py::test_compact_size_matches_the_product_code",
        "UP-100：审计跑的尺寸不是产品真实尺寸，全绿是假绿",
    ),
    Revert(
        "R11", "焦点巡检的覆盖面缩回 R8d 的 11 页",
        "scripts/tab_order_audit.py",
        "DEFAULT_PAGES = [pid for pid in PAGE_FACTORY if pid not in SPAWNS_SUBPROCESS]",
        'DEFAULT_PAGES = ["kill_sound", "crosshair", "gun_sound", "music",\n'
        '                 "voice_output", "advanced", "death_sound", "kill_voice",\n'
        '                 "reload_sound", "switch_weapon", "special_sound"]',
        "tests/test_audit_coverage_r11.py::test_focus_audit_default_coverage_never_shrinks",
        "UP-101：报告照旧说「全部为 0」，而没覆盖的 16 页里藏着真缺陷",
    ),
    Revert(
        "R11", "焦点巡检的分母写错",
        "scripts/tab_order_audit.py",
        # ⚠ 开源版是 27 页（闭源版 28，多一个账号页）。这个数字随页面集合变，
        # 改页面时锚点要跟着改，否则这条断点会静默"跳过"。
        "TOTAL_PAGES = 27",
        "TOTAL_PAGES = 11",
        "tests/test_audit_coverage_r11.py::test_focus_audit_total_pages_matches_the_app",
        "UP-101：分母一改，11/11 就成了「全覆盖」——覆盖率造假最省事的办法",
    ),
    Revert(
        "R11", "把 CI 里的紧凑档删掉",
        ".github/workflows/ci.yml",
        # ⚠ RN-092 把这一步改成了「跑完读裁定行」的两行写法，锚点跟着搬家。
        "          python scripts/layout_overflow_audit.py --compact --themes dark,light"
        " --scales 1.0,1.1,1.25 --require-fonts 2>&1 | Tee-Object -FilePath layout_compact.log",
        "          echo skip",
        "tests/test_audit_coverage_r11.py::test_ci_runs_the_new_gates[--compact]",
        "UP-100：判据留着但没人跑，等于没有判据（R8a 的教训）",
    ),
    Revert(
        "R11", "「我的预设」那一行退回死横排",
        "widgets/my_presets_section.py",
        "        row = QBoxLayout(QBoxLayout.LeftToRight)",
        "        row = QHBoxLayout()",
        "tests/test_compact_mode_layout_r11.py::test_my_presets_row_can_switch_direction",
        "UP-100：紧凑模式下 883px 的一行顶穿 854px 视口，整页横向滚动",
    ),
    Revert(
        "R11", "special_sound 的头部卡又钉回滚动区外",
        "pages/special_sound_page.py",
        "        scroll_layout.addWidget(header_card)\n\n        grid = QGridLayout()\n"
        "        grid.setContentsMargins(0, 0, 0, 0)\n"
        "        grid.setHorizontalSpacing(10)\n"
        "        grid.setVerticalSpacing(8)\n"
        "        self.round_grid = grid",
        "        layout.addWidget(header_card)\n\n        grid = QGridLayout()\n"
        "        grid.setContentsMargins(0, 0, 0, 0)\n"
        "        grid.setHorizontalSpacing(10)\n"
        "        grid.setVerticalSpacing(8)\n"
        "        self.round_grid = grid",
        "tests/test_compact_mode_layout_r11.py::test_special_sound_tabs_have_a_single_scroll_root",
        "UP-100：「回合」页签的滚动区被挤成 62px 舷窗，里面装 542px 内容",
    ),
    Revert(
        "R11", "flash 页的 Tab 顺序钉死被删掉",
        "pages/flash_page.py",
        "        self.setTabOrder(self.bg_color_combo, self.fade_in_checkbox)",
        "        pass  # setTabOrder removed",
        "tests/test_compact_mode_layout_r11.py::test_flash_basic_tab_order_is_pinned",
        "UP-102：键盘用户 Tab 从颜色跳到下一行滑块再跳回上一行，排版毫无异常",
    ),
    Revert(
        "R11", "道具瞄点又在 GUI 线程上死等",
        "utility_display.py",
        "            if self._schedule_ready_poll():\n                return",
        "            pass",
        "tests/test_utility_display_nonblocking_r11.py::"
        "test_construction_does_not_block_even_when_the_worker_never_reports_ready",
        "UP-006：开道具页时 GUI 线程冻 0.9s（最坏 10s）",
    ),
    Revert(
        "R11", "就绪定时器不再挂在实例上",
        "utility_display.py",
        "        self._ready_timer = timer\n        timer.start()",
        "        _local_only = timer\n        timer.start()",
        "tests/test_utility_display_nonblocking_r11.py::test_ready_timer_is_kept_on_the_instance",
        "UP-006：QTimer 被回收后定时器静默失效，工作进程永远接不上且一行报错都没有",
    ),
    Revert(
        "R11", "generate_stylesheet 又长回去",
        "theme_manager.py",
        '        """生成完整的QSS样式表"""\n        c = self.colors  # 简化引用',
        '        """生成完整的QSS样式表"""\n' + "        # 假装往这一坨里又堆了新样式\n" * 60
        + "        c = self.colors  # 简化引用",
        "tests/test_closed_items_ratchet_r11.py::test_generate_stylesheet_does_not_grow",
        "UP-058：判为不拆，但不许继续长——新样式该开新方法",
    ),
    Revert(
        "R11", "又多一处手搓 QFrame#card",
        "pages/about_page.py",
        'setObjectName("card")',
        'setObjectName("card")\n        _extra = QFrame(); _extra.setObjectName("card")',
        "tests/test_closed_items_ratchet_r11.py::test_handrolled_cards_do_not_grow",
        "UP-097：45 处手搓卡片判为不迁移，但不许再加新的",
    ),
    Revert(
        "R11", "删掉 UP-008 的回退理由",
        "main_widget.py",
        "    # UP-008（本轮回退，2026-08-07）：曾在此起后台线程预热 GSI 组件 import",
        "    # (comment removed)",
        "tests/test_closed_items_ratchet_r11.py::test_up008_revert_rationale_is_still_recorded",
        "UP-008：理由一删，下一个人会再起一次预热线程，把音频设备初始化搬到后台守护线程",
    ),

    # ============================== QA-001~008：UI 专项之外的八条
    Revert(
        "QA", "把开发机 config.json 加回打包 datas",
        "build_tools/build_release.py",
        '        (stage_dir / "launcher_config.json", "."),',
        '        (stage_dir / "config.json", "."),\n'
        '        (stage_dir / "launcher_config.json", "."),',
        "tests/test_qa_non_ui_r12.py::test_qa001_release_does_not_ship_the_dev_config",
        "QA-001：新机首启被写成开发机配置，CS2 目录指向别人的盘，且首启引导被跳过",
    ),
    Revert(
        "QA", "stage 又开始拷 config.json",
        "build_tools/build_release.py",
        '        "config.json",\n    )',
        "    )",
        "tests/test_qa_non_ui_r12.py::test_qa001_stage_copy_excludes_the_dev_config",
        "QA-001：源头没堵住，任何人往 datas 加一行就又带出去了",
    ),
    Revert(
        "QA", "打包校验不再反向断言产物",
        "build_tools/build_release.py",
        '        ("开发机配置 config.json", internal / "config.json"),',
        '        ("占位（反向断言已被移除）", internal / "__never__"),',
        "tests/test_qa_non_ui_r12.py::test_qa001_build_gate_rejects_a_leaked_config",
        "QA-001：正向清单挡不住「多了才坏」的东西，没有反向断言就发得出去",
    ),
    Revert(
        "QA", "冻结态又去迁移程序目录旁的配置",
        "config.py",
        '        if getattr(sys, "frozen", False):\n            return\n',
        "",
        "tests/test_qa_non_ui_r12.py::test_qa001_frozen_build_never_migrates_the_bundled_config",
        "QA-001：运行时安全带没了，打包包里那份配置又会被复制成用户配置",
    ),
    Revert(
        "QA", "存量纠正被拿掉",
        "config.py",
        "                self._repair_seeded_config(config_data)",
        "                pass",
        "tests/test_qa_non_ui_r12.py::"
        "test_qa001_seeded_config_is_repaired_for_existing_victims",
        "QA-001：已经装过 2.2.x 的用户永远修不好，CS2 目录一直指向打包机",
    ),
    Revert(
        "QA", "闪光子进程退回「管道断裂」检测",
        "flash_process.py",
        "                if _parent is not None and not _parent.is_alive():",
        "                if False:",
        "tests/test_qa_non_ui_r12.py::test_qa002_flash_child_detects_a_dead_parent",
        "QA-002：强杀主进程后全屏白罩永久留屏，重启软件也清不掉",
    ),
    Revert(
        "QA", "GSI 端口自适应又把文件路径当根目录",
        "gsi_server.py",
        "            from cfg_utils import ensure_cfg_exists, find_cs2_install_dir",
        "            from cfg_utils import ensure_cfg_exists, find_cfg_path as find_cs2_install_dir",
        "tests/test_qa_non_ui_r12.py::"
        "test_qa003_port_change_passes_the_install_root_not_a_file_path",
        "QA-003：cfg 重写 100% 失败而日志谎报成功，GSI 数据被推给占端口的第三方",
    ),
    Revert(
        "QA", "ensure_cfg_exists 又恒返回 None",
        "cfg_utils.py",
        "        return True\n    except Exception as e:\n"
        "        logger.error(f\"Error creating/checking GSI configuration file: {e}\")\n"
        "        return False",
        "    except Exception as e:\n"
        "        logger.error(f\"Error creating/checking GSI configuration file: {e}\")",
        "tests/test_qa_non_ui_r12.py::test_qa003_ensure_cfg_exists_reports_success_honestly",
        "QA-003：调用方无从判断成败，只能盲写成功日志",
    ),
    Revert(
        "QA", "HUD 效果线程退回永不成立的空闲判据",
        "gsi_handler_hud_color.py",
        "            if time.time() - self._last_data_ts >= self._DATA_STALE_SECONDS:",
        "            if False:  # idle_count 时代的判据",
        "tests/test_qa_non_ui_r12.py::test_qa004_effect_loop_exits_when_gsi_stops_pushing",
        "QA-004：退出游戏后线程仍以最后一帧无限求值并重写 CFG，直到软件退出",
    ),
    Revert(
        "QA", "资源迁移失败又无条件写完成标记",
        "resource_manager.py",
        "            failures = list(getattr(ResourceManager, \"_migration_failures\", []) or [])",
        "            failures = []",
        # ⚠ 这里原本指的是结构判据 `..._blocks_the_completion_marker`，
        # 回退验证判它假绿：`failures = []` 让结构还在、语义没了。
        # 换成**行为判据** —— 真造一次迁移失败，看标记会不会被写。
        "tests/test_qa_non_ui_r12.py::"
        "test_qa005_marker_is_not_written_when_a_directory_failed",
        "QA-005：某目录复制失败也写完成标记，同版本内永不重试，内置音效永久缺失",
    ),
    Revert(
        "QA", "放大镜签名又在写盘之前记账",
        "pages/magnifier_page.py",
        "            # QA-006: 写成功之后才记签名——失败时保持旧签名，下次还会重试。\n"
        "            self._last_sensitivity_cfg_signature = signature\n            return True",
        "            return True",
        "tests/test_qa_non_ui_r12.py::"
        "test_qa006_signature_is_recorded_only_after_a_successful_write",
        "QA-006：写失败后本次会话永不重试，用户改回来也没用",
    ),
    # QA-007（下载文件名净化）**在本仓库没有断点**：开源版不带在线更新下载器，
    # 那段代码和它的判据一起被裁掉了。断点却随文件同步过来，指着一个不存在的
    # 测试——于是 `--only QA` 这一整组在跑第一条之前就以"基线不绿"中止，
    # 而报错文字让人以为是产品坏了。
    # 现在 `tests/test_revert_verify_registry.py` 会拦下这类过期条目。
    Revert(
        "QA", "混淆失败清单又被丢弃",
        "build_tools/build_release.py",
        "        obfuscation_failures = obfuscate(\n"
        "            stage_dir, project_root, strict=args.strict_obfuscation\n        ) or []",
        "        obfuscate(stage_dir, project_root, strict=args.strict_obfuscation)",
        "tests/test_qa_non_ui_r12.py::test_qa008_obfuscation_failures_are_not_discarded",
        "QA-008：单个文件回退成明文没人知道，构建照样 exit 0，明文随安装包出货",
    ),
    Revert(
        "QA", "快照上限的 int() 又变回裸的",
        "config.py",
        "                try:\n"
        "                    _snap_keep = int(\n"
        "                        config_data.get(\"config_snapshot_max_keep\", "
        "self.config_snapshot_max_keep) or 20\n"
        "                    )\n"
        "                    self.config_snapshot_max_keep = "
        "_snap_keep if 1 <= _snap_keep <= 1000 else 20\n"
        "                except (TypeError, ValueError):\n"
        "                    self.config_snapshot_max_keep = 20",
        "                self.config_snapshot_max_keep = int(\n"
        "                    config_data.get(\"config_snapshot_max_keep\", "
        "self.config_snapshot_max_keep) or 20\n"
        "                )",
        "tests/test_qa_non_ui_r12.py::test_qa010_dirty_snapshot_keep_does_not_brick_startup",
        "QA-010：config.json 里一个非数值让 import config 直接抛异常，软件永久起不来且无任何提示",
    ),
    Revert(
        # 同一处回退，换一条判据来验：上面那条是行为判据（造脏值看起不起得来），
        # 这条是整片扫描（load_config 里还有没有没兜底的 int()/float()）。
        # 两条都必须红，否则"整片扫描"那条就是摆设。
        "QA", "快照上限的 int() 又变回裸的（整片扫描视角）",
        "config.py",
        "                try:\n"
        "                    _snap_keep = int(\n"
        "                        config_data.get(\"config_snapshot_max_keep\", "
        "self.config_snapshot_max_keep) or 20\n"
        "                    )\n"
        "                    self.config_snapshot_max_keep = "
        "_snap_keep if 1 <= _snap_keep <= 1000 else 20\n"
        "                except (TypeError, ValueError):\n"
        "                    self.config_snapshot_max_keep = 20",
        "                self.config_snapshot_max_keep = int(\n"
        "                    config_data.get(\"config_snapshot_max_keep\", "
        "self.config_snapshot_max_keep) or 20\n"
        "                )",
        "tests/test_qa_non_ui_r12.py::test_qa010_no_bare_numeric_cast_left_in_load_config",
        "QA-010：下次谁再往 load_config 加一个裸 int()，整片扫描判据必须逮住",
    ),
    Revert(
        "QA", "快照上限不再钳范围",
        "config.py",
        "                    self.config_snapshot_max_keep = "
        "_snap_keep if 1 <= _snap_keep <= 1000 else 20",
        "                    self.config_snapshot_max_keep = _snap_keep",
        "tests/test_qa_non_ui_r12.py::test_qa010_snapshot_keep_range_is_clamped",
        "QA-010：0 或负数会让 prune_snapshots 把用户的快照全部删光（快照是唯一的后悔药）",
    ),
    Revert(
        'QA', '关于页 GSI 状态又去 import 不存在的名字',
        'pages/about_page.py',
        '            from core.runtime.system_status_service import collect_gsi_status\n'
        '            from gsi_server import get_active_port\n'
        '\n'
        '            status = collect_gsi_status(self.window())',
        '            from gsi_server import get_active_port, get_gsi_server  # type: ignore\n'
        '\n'
        '            status = {"available": True,\n'
        '                      "running": getattr(get_gsi_server(), "is_running", False)}',
        'tests/test_about_diagnostics_gsi.py::test_diagnostics_reports_running_and_the_active_port',
        'QA-011：诊断信息里的 GSI 状态恒为「未知」，用户复制给客服的那份最该看的一行永远是空的',
    ),
    Revert(
        'QA', '快照裁剪回到不分 reason 的一刀切',
        'core/config_snapshot_manager.py',
        '    newest = entries[:1]\n'
        '    rest = entries[1:]\n'
        '    protected = [item for item in rest if not _is_evict_first(item)]\n'
        '    evict_first = [item for item in rest if _is_evict_first(item)]\n'
        '    budget = max(0, keep - len(newest))\n'
        '    chosen = protected[:budget]\n'
        '    chosen += evict_first[: max(0, budget - len(chosen))]\n'
        '    keep_ids = {id(item) for item in newest} | {id(item) for item in chosen}\n'
        '    keep_entries = [item for item in entries if id(item) in keep_ids]\n'
        '    for item in entries:\n'
        '        if id(item) in keep_ids:\n'
        '            continue',
        '    keep_entries = entries[:keep]\n'
        '    for item in entries[keep:]:',
        'tests/test_snapshot_prune_protects_user_snapshots.py::test_auto_preset_flood_never_evicts_user_snapshots',
        'QA-012：按地图自动切预设把用户手建的快照和「恢复前的后悔药」静默删光',
    ),
    Revert(
        'QA', '预设应用前的快照失败又被静默吞掉',
        'core/presets/preset_center.py',
        '        snapshot_ok = False\n'
        '        try:\n'
        '            create_snapshot(f"preset_apply_{\'replace\' if replace else \'merge\'}")\n'
        '            snapshot_ok = True\n'
        '        except Exception as exc:\n'
        '            _logger.warning("应用预设前的自动快照建立失败：%s", exc, exc_info=True)\n'
        '            warnings.append("未能建立应用前快照，此次应用无法回滚到之前的配置")',
        '        snapshot_ok = False\n'
        '        try:\n'
        '            create_snapshot(f"preset_apply_{\'replace\' if replace else \'merge\'}")\n'
        '            snapshot_ok = True\n'
        '        except Exception:\n'
        '            pass',
        'tests/test_preset_center_snapshot_warning.py::test_snapshot_failure_is_reported_not_swallowed',
        'QA-013：快照没建成却照样告诉用户「可在配置快照页回滚」，用户去回滚才发现没有还原点',
    ),
    Revert(
        'QA', '驱动包下载又没有超时',
        'pages/voice_output_page.py',
        '    with urllib.request.urlopen(url, timeout=timeout) as resp, open(dest, "wb") as fh:',
        '    with urllib.request.urlopen(url) as resp, open(dest, "wb") as fh:',
        'tests/test_vb_cable_download_timeout.py::test_download_gives_up_when_peer_stalls_mid_body',
        'QA-014：对端传到一半断流，安装线程永久阻塞，UI 永远停在「正在下载」，临时目录也泄漏',
    ),
    Revert(
        'QA', '音效转发又跑到按需加载前面',
        'core/audio/audio_manager.py',
        '        with self._lock:\n'
        '            exists = key in self._sounds\n'
        '        if not exists:\n'
        '            self._load_sound_by_key(key)\n'
        '\n'
        '        info = self._get_info(key)\n'
        '        if not info:\n'
        '            self._notify_error(f"Audio not loaded: {key}")',
        '        info = self._sounds.get(key)\n'
        '        if not info:\n'
        '            self._notify_error(f"Audio not loaded: {key}")',
        'tests/test_audio_forward_before_load.py::test_cold_key_first_play_is_forwarded',
        'QA-015：没被预载到的音效第一次触发时转发被静默跳过，队友这一次什么都听不到',
    ),
    Revert(
        'QA', '淡出线程不再检查通道归属',
        'core/audio/audio_manager.py',
        # ⚠ 断点必须打在 `_still_mine` 本身，不能只打在 stop 那一处。
        # 第一版就打错了：只把 803 行的 `if _still_mine()` 换回 `if channel.get_busy()`，
        # 而 fade_out 开头那句 `if not _still_mine(): return` 还在，
        # 归属不对时早就 return 了，根本走不到 stop —— **判据照样绿，回退验证会骗人**。
        # 令牌比较这一句才是修复的全部内容，删掉它才叫"删掉修复"。
        '        def _still_mine() -> bool:\n'
        '            return bool(channel.get_busy()) and self.fade_owner.get(channel) == token',
        '        def _still_mine() -> bool:\n'
        '            return bool(channel.get_busy())',
        'tests/test_audio_fade_channel_owner.py::test_previous_round_sound_fadeout_must_not_kill_the_next_one',
        'QA-016：上一回合音效的淡出定时器把下一回合已经在播的音效硬切掉',
    ),
    Revert(
        'QA', '本地监听改回启动时冻结的设备索引',
        'voice_output_manager.py',
        '            primary = self.local_monitor_device_id\n'
        '            if primary is None:\n'
        '                primary = self.default_speaker_id',
        '            primary = self.default_speaker_id',
        'tests/test_voice_local_monitor_device.py::test_local_monitor_follows_current_default_not_startup_snapshot',
        'QA-017：中途换耳机后音板本地监听仍从启动时那台设备出声，或静默失败',
    ),

    # ============================================ R13：设置搜索增强（S1~S5）
    Revert(
        'R13', '项级索引不再被读进来（等价于发布包漏带 JSON）',
        'core/settings_search.py',
        '        with open(path, "r", encoding="utf-8") as fh:\n'
        '            data = json.load(fh)',
        '        raise OSError("revert: 模拟发布包里没带 search_index.json")\n'
        '        with open(path, "r", encoding="utf-8") as fh:\n'
        '            data = json.load(fh)',
        'tests/test_settings_search_r13.py::test_index_is_loaded_by_search_module',
        'R13：JSON 在仓库里、却没被打进发布包/没被读进来 —— 开发机全绿，装完只剩页级搜索',
    ),
    Revert(
        'R13', '下拉退回 QCompleter 自带的纯子串过滤',
        'gui_widget.py',
        '        completer.setCompletionMode(QCompleter.UnfilteredPopupCompletion)',
        '        completer.setFilterMode(Qt.MatchContains)',
        'tests/test_search_jump_r13.py::test_popup_rows_match_engine',
        'R13：下拉与回车是两个搜索引擎 —— 打 zx 下拉 0 条、回车却能跳到准心设置',
    ),
    Revert(
        'R13', '反向子串改回按关键词长度计分（不看覆盖了多少查询）',
        'core/settings_search.py',
        '        rev_score = 44 + min(6, _span_union_len(rev_spans))',
        '        rev_score = 44 + min(4, len(rev_best))',
        'tests/test_settings_search_r13.py::test_reverse_substring_prefers_broader_coverage',
        'R13：搜「准心描边」被基础设置页那个只覆盖 2 个字的「准心」开关抢走第一位',
    ),
    Revert(
        'R13', '单个 ASCII 字母恢复走前缀档',
        'core/settings_search.py',
        '    return len(q) >= 2 or not _is_ascii_query(q)',
        '    return True',
        'tests/test_settings_search_r13.py::test_single_ascii_letter_does_not_flood',
        'R13：加了英文别名后打一个字母 a，about/account/advanced/aim/autostart… 22 页并列涌出',
    ),
    Revert(
        'R13', '每次按键新建 model 并删旧的',
        'widgets/search_popup.py',
        '    model.removeRows(0, model.rowCount())\n'
        '    for row in rows:\n'
        '        model.appendRow(_make_item(row))',
        '    model.removeRows(0, model.rowCount())\n'
        '    for row in rows:\n'
        '        model.appendRow(_make_item(row))\n'
        '    raise RuntimeError("Internal C++ object already deleted")',
        'tests/test_search_jump_r13.py::test_popup_rows_match_engine',
        'R13：setModel 之后旧 model 的 C++ 对象已销毁，再碰一下就抛异常 —— 用户敲第二个字就炸',
    ),
    Revert(
        'R13', '跳转不再先切页签',
        'gui_widget.py',
        '            self._activate_page_tab(page, tab_text)',
        '            pass  # revert: 不切页签',
        'tests/test_search_jump_r13.py::test_jump_switches_to_the_right_tab',
        'R13：落在非当前页签里的项（特殊音效的回合/投掷物/血量警告）搜得到却定位不到',
    ),
    Revert(
        'R13', '结果面板不再跟主题（退回系统默认调色板）',
        'gui_widget.py',
        '            pal.setColor(QPalette.Base, base)',
        '            pass  # revert: 不改底色',
        'tests/test_search_jump_r13.py::test_popup_follows_theme_with_readable_contrast',
        'R13：popup 是独立顶层窗口接不到 MainWindow 的 QSS，深色主题下闪出一块纯白面板',
    ),

    # ======================================= R14：搜索再增强（S7~S10，真机反馈）
    Revert(
        'R14', '项级去掉片段覆盖（中文查询退回"整串子串"匹配）',
        'core/settings_search.py',
        '    cover = _cover_score(q, tl)\n'
        '    if cover:\n'
        '        return cover',
        '    pass  # revert: 不做片段覆盖',
        'tests/test_search_r14.py::test_fragment_cover_recalls_composed_queries',
        'R14：中文不打空格，「准心回正」整串当一个 token —— 页面上叫「启用准心快速回正」，'
        '不是子串就 0 分，第一位变成基础设置页那个孤零零的「准心」',
    ),
    Revert(
        'R14', '片段覆盖门槛从 0.75 调回 0.5',
        'core/settings_search.py',
        '_COVER_MIN_RATIO = 0.75',
        '_COVER_MIN_RATIO = 0.5',
        'tests/test_search_r14.py::test_fragment_cover_demands_most_of_the_query',
        'R14：半个查询对得上就算命中 —— 「锁血提示」被「启用游戏内提示」勾走（只对上「提示」）',
    ),
    Revert(
        'R14', '页级也改用片段覆盖（不再只认整词）',
        'core/settings_search.py',
        '        elif len(wl) >= 2 and wl in q:',
        '        elif len(wl) >= 2 and _cover_len(q, wl) >= 2:',
        'tests/test_search_r14.py::test_page_level_does_not_use_fragment_cover',
        'R14：查「声音太大」时词表里含「声音」的页面全部并列涌出（「打死人声音」也算），'
        '音频体检反超基础设置',
    ),
    Revert(
        'R14', '同义词惩罚从 0.88 调回 0.94',
        'core/settings_search.py',
        'SYNONYM_PENALTY = 0.88',
        'SYNONYM_PENALTY = 0.94',
        'tests/test_search_r14.py::test_synonym_never_beats_the_word_the_user_typed',
        'R14：变体精确命中 94 分压过原词的页面精确命中 90 分 —— 打「crosshair」'
        '到不了准心设置页，被别处一个恰好叫「准心」的开关顶掉',
    ),
    Revert(
        'R14', '同义词层整个失效（只用原词）',
        'core/settings_search.py',
        '    return tuple(out[:MAX_QUERY_VARIANTS])',
        '    return (token,)  # revert: 不展同义词',
        'tests/test_search_r14.py::test_synonym_recall',
        'R14：界面写「准心」用户打「准星」、写「灵敏度」用户打「鼠标速度」 —— 全是空结果',
    ),
    Revert(
        'R14', '生成器不再挡「标签：值」型运行时快照',
        'scripts/build_search_index.py',
        '    if _STATUS_LABELED.search(s):\n        return ""',
        '    pass  # revert: 放行状态快照',
        'tests/test_search_r14.py::test_status_filter_is_measured_on_the_function_not_only_the_artifact',
        'R14：「当前样式：十字」这类收割那一刻的状态进索引 —— 一份永远过期的数据，'
        '用户搜「十字」跳过去那儿写的可能是「圆圈」',
    ),
    Revert(
        'R14', 'AST 认不出 SettingsCard.make 工厂写法',
        'scripts/build_search_index.py',
        '        if fn.attr == "make" and isinstance(fn.value, ast.Name):\n'
        '            return fn.value.id          # SettingsCard.make → SettingsCard',
        '        pass  # revert: 只看 fn.attr',
        'tests/test_search_r14.py::test_ast_recognizes_the_factory_form',
        'R14：全仓 65 处卡片都写成 SettingsCard.make(...)，AST 里是 attr="make"，'
        '按 fn.attr 取名什么都对不上 —— 局内视角的「CFG 同步」「准心快速回正」一条没收到',
    ),
    Revert(
        'R14', '结果面板退回"只有空框聚焦才弹"',
        'gui_widget.py',
        '        if etype not in (QEvent.FocusIn, QEvent.MouseButtonPress, QEvent.KeyPress):',
        '        if etype != QEvent.FocusIn or watched.text().strip():',
        'tests/test_search_sticky_r14.py::test_these_events_reopen_the_panel',
        'R14：输入后点一下别处，下拉消失且回不来，必须把字删光重打一遍',
    ),
    Revert(
        'R14', '重开时复用上次的行而不重新搜',
        'gui_widget.py',
        '        if text:\n            self._on_search_text_edited(text)',
        '        if False:\n            self._on_search_text_edited(text)',
        'tests/test_search_sticky_r14.py::test_reopen_reruns_the_search_instead_of_reusing_stale_rows',
        'R14：中间换过主题/去过别的页，把旧行弹回来就是给用户看一份过期结果（静默、不报错）',
    ),
    Revert(
        'R14', '拆掉"焦点已经跑了就别硬弹"的守卫',
        'gui_widget.py',
        '        if box is None or not box.hasFocus():',
        '        if box is None:',
        'tests/test_search_sticky_r14.py::test_reopen_bails_when_focus_already_left',
        'R14：延迟这 0ms 里焦点可能已经走了，硬弹会留一个没人要的面板浮在界面上',
    ),

    # ==================================== VER：版本号四处同步（2026-08-11 建立）
    # 这组模拟的缺陷都是"抬版本号时漏改其中一处"。此前没有任何判据看着这件事，
    # 漏改任何一处，全部用例照绿、构建照过，通常等装到用户机器上才发现。
    # 2.2.0/2.2.1/2.2.2 三次发布连续暴露了同一版本号对应多份产物的问题，根因之一就在这里。
    Revert(
        'VER', 'version_info.txt 的 filevers 忘了跟着抬',
        'version_info.txt',
        f'filevers={_VER_TUPLE}',
        'filevers=(2, 2, 1, 0)',
        'tests/test_version_consistency.py::test_version_info_tuples_match',
        'exe 文件属性里的版本号停在上一版，排障时对着用户截图会认错版本',
    ),
    Revert(
        'VER', 'version_info.txt 的 ProductName 忘了跟着抬',
        'version_info.txt',
        f"StringStruct(u'ProductName', u'CS2 Customizer {_VER}')",
        "StringStruct(u'ProductName', u'CS2 Customizer 2.2.1')",
        'tests/test_version_consistency.py::test_version_info_strings_match',
        '任务管理器/属性页显示的产品名还是旧版本号',
    ),
    Revert(
        'VER', '只漏了 ProductVersion 一个字段（考验"游离版本号"全文扫）',
        'version_info.txt',
        f"StringStruct(u'ProductVersion', u'{_VER}.0')",
        "StringStruct(u'ProductVersion', u'2.2.1.0')",
        'tests/test_version_consistency.py::test_version_info_has_no_stray_version',
        '逐字段枚举的判据可能漏枚举某个字段；这条不枚举、直接全文扫，是兜底',
    ),
    # 2026-08-15：installer.iss 不再自带版本号（改由 /DAppVersion 从 config.VERSION 传入），
    # 原先"AppVersion 忘了抬 / 头部注释停在旧版本"两个断点所对应的判据已随架构撤销。
    # 换成守新机制的两条——它们要防的是同一个后果：打出一个装的却是上一版的安装包。
    Revert(
        'VER', 'installer.iss 又长回写死的版本兜底常量',
        'build_tools/installer.iss',
        '#error 未指定版本号',
        '#define AppVersion "2.2.1"',
        'tests/test_version_consistency.py::test_installer_iss_declares_no_version_of_its_own',
        '后果最重且**静默**：漏传 /DAppVersion 时照旧版号去打包同名旧目录，零报错',
    ),
    Revert(
        'VER', '打安装包时把版本号写死而不是取 config.VERSION',
        'build_tools/build_release.py',
        'f"/DAppVersion={version}"',
        '"/DAppVersion=2.2.1"',
        'tests/test_build_installer_step.py::test_installer_passes_version_from_caller',
        '版本号与真源脱钩，抬版本后打出来的安装包仍标着上一版',
    ),
    Revert(
        'VER', 'README 首行标题被改成别的项目名',
        'README.md',
        # ⚠ 这个锚点**每次发版都要跟着抬**（它按定义就写着当前版本号）。
        # 2026-08-18 抬到 2.2.4 时 `--stale-only` 当场把它报出来了 —— 这正是
        # 失效体检该干的活：断点腐烂在版本锚点上是必然事件，不是意外。
        '# CS2 Customizer',
        '# Some Other Project',
        'tests/test_version_consistency.py::test_readme_title_matches',
        '落地页标题与项目名不符——访客第一眼看到的东西错了',
    ),
    Revert(
        'VER', 'CHANGELOG 缺当前版本的小节',
        'CHANGELOG.md',
        # old 必须是**当前版本**的小节：把它改掉，判据才会发现"当前版本没有对应小节"。
        # 反过来写（改历史小节）在当前版本小节仍然存在时判据照样通过，断点会静默失效。
        f'## [{_VER}]',
        '## [0.0.0]',
        'tests/test_version_consistency.py::test_changelog_has_section_for_current_version',
        '当前版本在更新日志里找不到对应小节，发布时没有可抄的内容',
    ),
    # ==================================== KI-4/5/6：击杀图标兼容性与清单板
    #
    # 这一组断点全都是**导入照常成功、报错一句没有**的类型——这也是 KI-4
    # 要修的四条路的共同点。假绿的判据在这里代价特别大：功能测试全绿，
    # 而用户拿到的是一个 0.03 秒的图标、一条马赛克、或者一个写到资源目录
    # 外面的文件。
    Revert(
        "KI", "定格时长被从播放时间轴上摘掉",
        "kill_icon_overlay.py",
        "    animation_duration = frame_count / float(fps) + clamp_hold(hold)",
        "    animation_duration = frame_count / float(fps)",
        "tests/test_kill_icon_overlay_ki1.py::test_single_frame_icon_is_visible_at_all",
        "静态图标只显示 0.033 秒，弹窗说导入成功、游戏里什么都没有",
    ),
    Revert(
        "KI", "裁边改成逐帧各裁各的",
        "core/kill_icon_import.py",
        "        box = _frames_union_bbox(frames)\n"
        "        if box is not None and box != (0, 0, frames[0].width, frames[0].height):\n"
        "            frames = [frame.crop(box) for frame in frames]",
        "        box = _frames_union_bbox(frames)\n"
        "        if box is not None and box != (0, 0, frames[0].width, frames[0].height):\n"
        "            frames = [frame.crop(frame.getbbox() or box) for frame in frames]",
        "tests/test_kill_icon_compat_ki4.py::"
        "test_trim_uses_the_union_box_so_the_animation_does_not_jitter",
        "每一帧的内容都被推到画格正中，播放时整个动画在原地抖",
    ),
    Revert(
        "KI", "zip 条目路径不再校验",
        "core/kill_icon_pack.py",
        '        if part == "..":\n            return None',
        '        if part == "..":\n            continue',
        "tests/test_kill_icon_pack_ki4.py::"
        "test_zip_slip_is_refused_before_anything_is_written",
        "zip-slip：从网上下的图标包能往资源目录外面写文件",
    ),
    Revert(
        "KI", "选中图集的 png 不再去找同名 json",
        "core/kill_icon_import.py",
        '    sibling = _sibling_metadata_path(path) if lower.endswith(".png") else None',
        "    sibling = None",
        "tests/test_kill_icon_compat_ki4.py::test_selecting_the_sheet_png_finds_its_json",
        "整张图集被当成一帧，屏幕上是一条巨大的马赛克，全程零警告",
    ),
    Revert(
        "KI", "单文件与目录的格式表又分家",
        "core/kill_icon_import.py",
        "SEQUENCE_EXTENSIONS = tuple(sorted(set(ANIMATED_EXTENSIONS + STATIC_EXTENSIONS)))",
        'SEQUENCE_EXTENSIONS = (".png", ".webp", ".jpg", ".jpeg", ".bmp")',
        "tests/test_kill_icon_compat_ki4.py::"
        "test_the_two_extension_tables_are_literally_the_same_set",
        "jpg 单独拖进来被拒、放进文件夹却能进——用户只觉得这软件挑食",
    ),
    Revert(
        # KI-7 之后这段逻辑在素材工坊里（设置页不再逐等级编辑）。
        "KI", "单帧素材的时长又被当成播放速度",
        "dialogs/kill_icon_workshop.py",
        '            if frames == 1 and hasattr(self.player, "update_hold_for_style"):',
        "            if False:",
        "tests/test_kill_icon_grid_ki6.py::"
        "test_static_levels_save_a_hold_and_animated_levels_save_a_frame_rate",
        "调静态图标的时长毫无反应：帧率对一张图来说没有意义",
    ),
    Revert(
        "KI", "拖拽过滤器又不认文件夹",
        "widgets/drop_import_mixin.py",
        "            if self._accept_directories and os.path.isdir(p):",
        "            if False and os.path.isdir(p):",
        "tests/test_kill_icon_page_ki3.py::test_folders_can_be_dropped_at_all",
        "帧序列文件夹拖进去毫无反应，连报错都没有，而页面上写着「拖进来就能导入」",
    ),
    Revert(
        "KI", "切风格后拿上一个风格的帧数糊弄",
        "kill_icon_player.py",
        '        info = self._catalog.get((kills, "")) if style_name == self._catalog_style else None\n'
        '        if info is not None:\n'
        '            return info.frame_count',
        '        info = self._catalog.get((kills, "")) if style_name == self.current_style else None\n'
        '        if info is not None:\n'
        '            return info.frame_count',
        "tests/test_kill_icon_grid_ki6.py::"
        "test_switching_styles_does_not_report_the_previous_styles_frames",
        "刚导入一个图标包，清单板五个格子显示的是老风格的帧数和时长，而且不会自己好",
    ),
    Revert(
        "KI", "装载完成不通知页面",
        "kill_icon_player.py",
        "        self.assets_ready.emit(style_name)",
        "        pass  # 不通知",
        "tests/test_kill_icon_grid_ki6.py::"
        "test_the_page_refreshes_itself_when_the_assets_land",
        "导入成功了、格子却还是空的，要再刷一次才好",
    ),
    Revert(
        "KI", "空格子上的删除/导出没有灰掉",
        "widgets/kill_icon_level_grid.py",
        "        export.setEnabled(has_assets)",
        "        export.setEnabled(True)",
        "tests/test_kill_icon_grid_ki6.py::test_the_menu_greys_out_what_cannot_be_done",
        "点了没反应比灰着更让人困惑",
    ),

    # ==================================== KI-7：拆成「简单层 + 素材工坊」两层
    #
    # 这一组防的不是功能坏掉，而是**复杂度长回去**和**搬家途中掉东西**。
    # 两者都没有当场的症状：页面胖回去了没人会报 bug，工坊里少接一根线也
    # 要等到有人真去用那个功能才发现。
    Revert(
        "KI", "缩略图又走整套解码那条路",
        "widgets/kill_icon_style_strip.py",
        "        from kill_icon_overlay import load_level_thumbnail",
        "        from kill_icon_overlay import load_level_animation as load_level_thumbnail",
        "tests/test_kill_icon_simple_page_ki7.py::test_thumbnails_do_not_decode_whole_animations",
        "风格库里有几套就整套解码几次，用户 519 帧的默认风格一进页面就顿住",
    ),
    Revert(
        "KI", "导入小窗开始问第二个问题",
        "dialogs/kill_icon_import_wizard.py",
        "        self.warning_label.setWordWrap(True)",
        "        self.warning_label.setWordWrap(True)\n"
        "        from PySide6.QtWidgets import QSlider as _S\n"
        "        self._extra = _S(self)",
        "tests/test_kill_icon_wizard_ki7.py::test_the_wizard_asks_exactly_one_question",
        "「最多问一个问题」被稀释成又一个高级面板",
    ),
    Revert(
        "KI", "预选的等级和下拉里显示的对不上",
        "dialogs/kill_icon_import_wizard.py",
        '        index = self.level_combo.findData(f"{self._kills}{self._variant}")',
        "        index = self.level_combo.findData((self._kills, self._variant))",
        "tests/test_kill_icon_wizard_ki7.py::test_the_dropdown_actually_shows_the_guessed_level",
        "下拉显示「1 杀」而实际会导入到 3 杀——元组过 QVariant 后 findData 恒 -1",
    ),
    Revert(
        "KI", "设置页又把编辑器搬回首屏",
        "pages/kill_icon_page.py",
        "        scroll_layout.addWidget(self._create_workshop_card())",
        "        from widgets.kill_icon_level_grid import KillIconLevelGrid\n"
        "        self.level_grid = KillIconLevelGrid()\n"
        "        scroll_layout.addWidget(self.level_grid)\n"
        "        scroll_layout.addWidget(self._create_workshop_card())",
        "tests/test_kill_icon_simple_page_ki7.py::test_the_editor_did_not_follow_the_page",
        "只想换套图标的人一进来又要面对 30 多个可操作控件",
    ),
    Revert(
        "KI", "拖到某一格上还多问一句",
        "dialogs/kill_icon_workshop.py",
        "    def _on_level_files_dropped(self, kills, paths):\n"
        '        """拖到某一格上：就进那一格。用户已经用位置表达了意图，不再问一遍。"""\n'
        "        self.import_paths(paths, int(kills))",
        "    def _on_level_files_dropped(self, kills, paths):\n"
        "        self._on_files_dropped(paths)",
        "tests/test_kill_icon_workshop_ki7.py::test_dropping_onto_a_level_cell_targets_that_level",
        "用户已经用「拖到哪一格」表达了意图，还弹个框问一遍",
    ),
    Revert(
        "KI", "工坊里改完节奏试播用的是存盘值",
        "dialogs/kill_icon_workshop.py",
        "        seconds = cell.seconds if cell else 0.0\n"
        "        fps = fps_for_duration(frames, seconds) if frames > 1 else None",
        "        fps = self.player.get_style_fps(self.style_name, kills) if frames > 1 else None",
        "tests/test_kill_icon_workshop_ki7.py::"
        "test_testing_a_level_uses_the_slider_value_not_the_stored_one",
        "拖完滑条试播毫无变化，用户以为「拖了没用」",
    ),
    Revert(
        # 这条防的是"页面上那块预览凭空消失"——布局不溢出、不报错、判据全绿，
        # 只有渲染成图肉眼看才发现。撑住宽度的**只有** sizeHint（最小宽是 0，
        # 那是为窄窗口留的），所以断点打在 sizeHint 上。
        "KI", "预览控件又不报自己的期望尺寸",
        "widgets/kill_icon_preview.py",
        "        return QSize(self._box[0], self._box[1])",
        "        return QSize(0, 0)",
        "tests/test_kill_icon_simple_page_ki7.py::test_the_hero_preview_is_actually_visible",
        "QWidget 默认 sizeHint 无效，摆进水平布局就被收扁",
    ),
    Revert(
        "KI", "卡片条高度在装进真卡片之前就写死",
        "pages/kill_icon_page.py",
        # 锚点在 2026-08-16 修 V-004 时被改写过一次（原文是
        # `setFixedHeight(self.style_strip.sizeHint().height() + 6)`）。
        # 失效体检把它逮了出来——**断点一旦锚不上就是在空转**。
        "        self.style_scroll.setFixedHeight(need + 6)",
        "        self.style_scroll.setFixedHeight(72)",
        "tests/test_kill_icon_simple_page_ki7.py::"
        "test_the_card_strip_is_tall_enough_to_show_the_whole_card",
        "风格卡最后一行「素材齐全 / 2-5 个等级」被裁掉，切换前看不出缺不缺素材",
    ),
    Revert(
        # 断点必须是 `setFixedWidth`，不能只是把 `setMinimumWidth` 调小：
        # 网格列宽由该列最宽的按钮决定，最小宽调小了实际宽度照样够——
        # 那个断点模拟不出任何缺陷，判据当然不会红（第一版就是这么假绿的）。
        # 真正会出事的形状是 UP-094 那一种：写死宽度 + 中文文案 + 字号缩放。
        "KI", "工坊「高级导入 / 批量…」又被写死宽度",
        "dialogs/kill_icon_workshop.py",
        "        self.advanced_btn.setMinimumWidth(156)",
        "        self.advanced_btn.setFixedWidth(96)",
        "tests/test_kill_icon_workshop_ki7.py::test_no_button_text_gets_elided",
        "对话框不在排版审计的视野里，按钮文案被打省略号没人会发现",
    ),
    Revert(
        "KI", "工坊的底栏按钮不再折行",
        "dialogs/kill_icon_workshop.py",
        "        columns = len(self._buttons) if self.width() >= self.BUTTONS_ONE_ROW_WIDTH else 2",
        "        columns = len(self._buttons)",
        "tests/test_kill_icon_workshop_ki7.py::test_the_dialog_fits_its_own_minimum_size",
        "五个按钮并排要 660px 而窗口最小 560——拖窄就把按钮挤出去（排版审计不量对话框）",
    ),

    # ---- KI-7b：异构模型复审之后修的五条 ------------------------------
    Revert(
        # 这一条是**只看截图**被指出来的：KI-7 自带 73 条判据全绿，
        # 因为"改完要点保存"这件事我自己知道，所以从没写过"不点会怎样"。
        "KI", "工坊关窗又把没保存的节奏扔掉",
        "dialogs/kill_icon_workshop.py",
        "        if self._dirty:\n            self._apply_timing()\n        self.level_grid.stop_previews()",
        "        self.level_grid.stop_previews()",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_closing_the_workshop_saves_pending_timing",
        "拖完滑条预览立刻变快（看着已生效），点「完成」改动全丢，只有按钮上一个 *",
    ),
    Revert(
        # 断点只挪掉 reject 那一半：拦 accept 是最自然的写法，而用户关窗
        # 最常用的恰恰是右上角那个叉（走 reject）。
        "KI", "关窗落盘只拦「完成」不拦叉窗口",
        "dialogs/kill_icon_workshop.py",
        "    def done(self, result):\n        # 关窗**一定**先落盘",
        "    def accept(self):\n        result = 1\n        # 关窗**一定**先落盘",
        "tests/test_kill_icon_ki7b_review_fixes.py::test_closing_by_escape_also_saves",
        "叉掉窗口/按 Esc 依旧静默丢改动，而这是最常用的关窗方式",
    ),
    Revert(
        "KI", "切风格之前不先落盘",
        "dialogs/kill_icon_workshop.py",
        "        if self._dirty:\n            self._apply_timing()\n        self.style_name = name",
        "        self.style_name = name",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_switching_style_flushes_pending_timing_to_the_old_style",
        "在 A 上调完节奏切到 B，改动无声消失；先改 style_name 再落还会写错风格",
    ),
    Revert(
        "KI", "爆头角标又把「已就绪」顶掉",
        "widgets/kill_icon_level_grid.py",
        '        self.badge_label.setText("已就绪")',
        '        self.badge_label.setText("爆头专属" if self._has_headshot else "已就绪")',
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_headshot_does_not_replace_the_ready_badge",
        "那一格看上去像「爆头专用」，而设置页的爆头是个独立勾选框，两处概念对不上",
    ),
    Revert(
        "KI", "时长滑条又变回没有名字",
        "widgets/kill_icon_level_grid.py",
        '        self.slider_caption = QLabel("在屏幕上停留")',
        '        self.slider_caption = QLabel("")',
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_the_duration_slider_says_what_it_does",
        "光秃秃一根滑条配「0.60 秒 · 20 FPS」，拖的是时长/帧率/进度三种都说得通",
    ),
    Revert(
        # 断点让下拉在当前风格不在库里时静默停在第一项——这正是 QComboBox
        # 的默认行为，也是最容易写出来的那一版。
        "KI", "工坊下拉丢掉磁盘上已消失的当前风格",
        "dialogs/kill_icon_workshop.py",
        "        if self.style_name and self.style_name not in styles:\n"
        "            styles.insert(0, self.style_name)",
        "        styles = list(styles)",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_current_style_survives_even_if_it_vanished_from_disk",
        "下拉显示 A、style_name 还是 B，用户以为在编辑 A 其实在编辑 B",
    ),
    Revert(
        # 断点把反解改成"自己按比例估"——就是没有 `icon_geometry` 那一版
        # 最容易写出来的近似：拿示意图中心当基准，忽略落点公式里的 3/4 和 +50。
        "KI", "示意图拖拽自己估落点不走叠加层公式",
        "widgets/kill_icon_preview.py",
        "        base_x, base_y, w, h = self.icon_geometry((0, 0))\n"
        "        offset_x = int(round((point.x() - map_x) / ratio - (base_x + w / 2)))\n"
        "        offset_y = int(round((point.y() - map_y) / ratio - (base_y + h / 2)))",
        "        screen_w, screen_h = REFERENCE_SCREEN\n"
        "        offset_x = int(round((point.x() - map_x) / ratio - screen_w / 2))\n"
        "        offset_y = int(round((point.y() - map_y) / ratio - screen_h / 2))",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_dragging_lands_where_the_blue_box_is_drawn",
        "点的地方和框画的地方分家，界面看着没毛病、进游戏才发现位置不对",
    ),
    Revert(
        "KI", "拖拽不再夹在滑条量程里",
        "widgets/kill_icon_preview.py",
        "        limit = self.OFFSET_LIMIT\n"
        "        return (max(-limit, min(limit, offset_x)),\n"
        "                max(-limit, min(limit, offset_y)))",
        "        return (offset_x, offset_y)",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_dragging_is_clamped_to_the_slider_range",
        "拖出量程的值滑条表示不了，回填就被夹回去——表现是松手往回弹一下",
    ),
    Revert(
        "KI", "示意图拖动的值不回滑条",
        "pages/kill_icon_page.py",
        "        self.position_map.position_changed.connect(self._on_map_dragged)",
        "        pass",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_the_page_routes_the_drag_through_its_sliders",
        "蓝框拖得动但什么都不改，等于做了个骗人的交互",
    ),
    Revert(
        "KI", "拖到原地也发一枪信号",
        "widgets/kill_icon_preview.py",
        "        if offset == self._offset:\n            return\n        self._offset = offset",
        "        self._offset = offset",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_dragging_to_the_same_place_stays_quiet",
        "每次 mouseMove 都发，一次拖动能把配置写盘打满（save_config 有防抖但不是免费的）",
    ),
    Revert(
        # 这条是"改完布局要出一张图看一眼"那条规矩当场兑现的：加了"可拖动"
        # 三个字之后，示意图底下那行的两头都被裁了——而它是 drawText 画的，
        # 排版审计量的是控件几何，一个字都量不到。
        "KI", "示意图底下那行字又硬画不省略",
        "widgets/kill_icon_preview.py",
        "        return QFontMetrics(self.font()).elidedText(\n"
        "            self.CAPTION, Qt.ElideRight, max(0, int(width)))",
        "        return self.CAPTION",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_the_caption_never_gets_painted_past_the_edge",
        "说明文字被裁掉两头，看上去像渲染坏了；排版审计量不到 drawText",
    ),
    Revert(
        # 把写死高度加回去 = 复现"setFixedHeight 打不过 QSS min-height"。
        # Qt 在 min > max 时取 min，于是按钮 54 高、布局按 28 算，
        # 下边框被卡片边缘切掉一道。判据必须带主题样式表跑，否则这条恒绿。
        "KI", "每格按钮又被写死高度（打不过 QSS 的 min-height）",
        "widgets/kill_icon_level_grid.py",
        '        self.test_btn.setObjectName("secondaryButton")\n',
        '        self.test_btn.setObjectName("secondaryButton")\n'
        '        self.test_btn.setFixedHeight(28)\n',
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_cell_buttons_stay_inside_the_card",
        "按钮下边框被卡片边缘齐齐切掉；布局按 28 算所以几何上「没溢出」，判据全绿",
    ),
    Revert(
        # 这条的来路特殊：**异构模型在一张干净截图上 3/3 报出来的**，
        # 我自己 73 条 KI-7 判据一条都没覆盖。断点退回"有多长画多长"。
        "KI", "预览框里的占位文字又有多长画多长",
        "widgets/kill_icon_preview.py",
        "        box = self.placeholder_box(rect)\n"
        "        return (box, Qt.AlignCenter | Qt.TextWordWrap,\n"
        "                self.placeholder_for_box(box.width(), box.height()))",
        "        return rect, Qt.AlignCenter, self._placeholder",
        "tests/test_kill_icon_ki7b_review_fixes.py::"
        "test_the_placeholder_never_spills_out_of_the_preview_box",
        "「这套风格还没有素材…」两头各切掉一个字，且画在圆角边框外面，像渲染坏了",
    ),

    # ---- V 组：UI 视觉巡检 R1（2026-08-16）------------------------------
    # 这六条的共同点是**几何全部合法**，所以排版审计一路绿灯——
    # 它们只有在像素上才看得见。详见 docs/quality/UI视觉巡检_R1_20260816.md。
    Revert(
        "V", "QSS 图片又退回 data URI",
        "theme_manager.py",
        '        check_rule = f"image: url({check_icon});" if check_icon else ""',
        '        check_rule = "image: url(data:image/svg+xml;base64,PHN2Zy8+);"',
        "tests/test_ui_visual_r1_fixes.py::test_qss_never_uses_data_uri_images",
        "Qt 不认 data URI，写了不报错也不显示：所有已勾选的复选框只剩一个纯色方块",
    ),
    Revert(
        "V", "下拉箭头退回 Web CSS 的三角形技巧",
        "theme_manager.py",
        "            QComboBox::down-arrow {{\n"
        "                {arrow_rule}",
        "            QComboBox::down-arrow {{\n"
        "                border-left: 5px solid transparent;\n"
        "                border-top: 6px solid red;",
        # ⚠ 这条断点删掉的是 `image:` 那一行本身，所以"图片路径存不存在"那条判据
        # 会**空转成绿**（一条 image: 都没有，循环体一次都不进）。回退验证第一次
        # 就是这么抓到的——必须配一条"下拉箭头得有 image:"的判据才拦得住。
        "tests/test_ui_visual_r1_fixes.py::test_combobox_arrow_is_drawn_with_an_image",
        "Qt 把四条边照实心画：全应用 233 个下拉框的箭头都变成实心小方块",
    ),
    Revert(
        "V", "箭头图标画成方块",
        "theme_manager.py",
        "    painter.fillPath(path, color)",
        "    painter.fillRect(0, 0, int(w), int(h), color)",
        "tests/test_ui_visual_r1_fixes.py::test_down_arrow_icon_is_a_triangle_not_a_block",
        "下拉箭头不是三角形而是方块——正是修复前用户看到的样子",
    ),
    Revert(
        "V", "帮助按钮的 padding 归零被撤掉",
        "theme_manager.py",
        "                min-width: 24px; max-width: 24px;\n"
        "                min-height: 24px; max-height: 24px;",
        "                min-height: 42px;",
        "tests/test_ui_visual_r1_fixes.py::test_help_button_box_model_is_consistent",
        "min > max 时 Qt 取 min：24×24 的圆变成 24×42 灰胶囊，「?」被 padding 挤没",
    ),
    Revert(
        "V", "帮助按钮又开始自己写内联样式",
        "ui_help_panel.py",
        '        self.setToolTip("查看帮助")',
        '        self.setToolTip("查看帮助")\n'
        '        self.setStyleSheet("QPushButton { color: red; }")',
        "tests/test_ui_visual_r1_fixes.py::test_help_button_box_model_is_consistent",
        "内联样式会被 ui_style_applier 的清扫器抹掉（本类没声明 fp_keep_style），"
        "于是 23 个页面的帮助按钮全变成无字灰胶囊",
    ),
    Revert(
        "V", "卡片条视口比内容矮",
        "pages/kill_icon_page.py",
        # ⚠ 第一版断点写的是 `need = sizeHint - 10`，**没逮住**：这个方法会被调
        # 好几次（建页 / load_settings / 事件循环空转后再校一次），每次都拿当时的
        # sizeHint 重算，最后一次算出来的值反而不比最终内容矮。
        # 断点要**直接砍最终高度**才稳定复现"视口装不下内容"。
        "        self.style_scroll.setFixedHeight(need + 6)",
        "        self.style_scroll.setFixedHeight(need - 20)",
        "tests/test_ui_visual_r1_fixes.py::"
        "test_kill_icon_style_strip_viewport_fits_its_content",
        "视口比内容矮，而这个滚动区纵向是 AlwaysOff：「zip / 动图 / 图片」被永久切掉",
    ),
    Revert(
        "V", "reset 之后的在途 flush 又能把旧数据倒灌回磁盘",
        "core/page_usage_tracker.py",
        "        if generation != _generation:\n            return\n",
        "",
        "tests/test_page_usage_tracker.py::"
        "test_reset_invalidates_an_already_running_flush",
        "Timer.cancel() 拦不住已经开始跑的回调：「重置所有设置」之后，"
        "上一批统计会被倒灌回来。CI 上表现为 top_pages 返回空、IndexError（本机复现不出）",
    ),
    Revert(
        "V", "页面说明又写回版面决策",
        "pages/kill_sound_page.py",
        '    PAGE_LEAD = "击杀敌人时播放你自己的音效，逐把枪选风格；一个风格里自带 1~5 连杀的不同音效。'
        '点「测试」可以按连杀档位试听；总开关在「基础设置」里。"',
        '    PAGE_LEAD = "击杀音效页保持列表式效率，把分类切换和快速试听留在一屏里。"',
        "tests/test_page_copy_is_user_facing.py::test_page_copy_has_no_layout_jargon",
        "副标题讲的是界面怎么排而不是功能是什么，玩家读完不知道该干嘛"
        "——外审在 8 个页面上独立指出同一件事",
    ),
    Revert(
        "V", "文案又指向不存在的「首页」",
        "pages/kill_sound_page.py",
        "再去「基础设置」打开总开关。",
        "再回首页启用。",
        "tests/test_page_copy_is_user_facing.py::"
        "test_page_copy_does_not_point_at_a_nonexistent_page",
        "「回首页启用」曾出现在 5 个页面，而侧栏里从来没有叫「首页」的东西",
    ),
    Revert(
        "V", "侧栏又有页面漏配图标",
        "widgets/icon_provider.py",
        '    "fun_afterlife":        "mdi.cellphone-play",',
        "",
        "tests/test_ui_visual_r1_fixes.py::test_every_nav_page_has_an_icon",
        "get_page_icon 查不到就静默返回空 QIcon：那一项在侧栏里没图标、"
        "文字比同组其它项左移一截",
    ),
    Revert(
        "V", "方形约束又落回共用的 modeToggleButton 上",
        "theme_manager.py",
        "            QPushButton#modeToggleIconButton {{\n"
        "                padding: 0px;",
        "            QPushButton#modeToggleButton {{\n"
        "                padding: 0px;",
        "tests/test_ui_visual_r1_fixes.py::"
        "test_sidebar_mode_button_is_not_squeezed_into_a_square",
        "侧栏底部「紧凑模式 «」被压成 38px 方块，文字裁成「奏模式」"
        "——我自己修 V-005 时踩的回归，重跑截图才发现",
    ),
    Revert(
        "V", "切页后不再把当前导航项滚进可视区",
        "gui_widget.py",
        "            self._refresh_nav_icons(page_id)\n            self._ensure_nav_button_visible(page_id)\n",
        "            self._refresh_nav_icons(page_id)\n",
        "tests/test_ui_visual_r1_fixes.py::"
        "test_sidebar_scrolls_the_active_nav_item_into_view",
        "默认 1280×800 下 28 页里 15 页在折叠线外，切过去侧栏还停在顶部，"
        "当前项既看不见也没高亮 —— 用户失去「我在哪一页」的指示",
    ),
    # ==================================== RN：翻新工程（RN-002 名单单源化）
    Revert(
        "RN", "审计脚本又自己抄了一份设备页名单",
        "scripts/_audit_neutralize.py",
        "    from core.page_traits import DEVICE_OWNING_PAGES",
        '    DEVICE_OWNING_PAGES = {"viewmodel", "magnifier", "flash", '
        '"voice_output", "kill_icon", "music"}',
        "tests/test_no_hardcoded_page_lists.py::"
        "test_device_owning_page_list_has_exactly_one_copy",
        "抄的那一刻逐字相同、判据全绿，等产品那份变了才发作 —— 2026-08-17 判据"
        "首跑就抓出 9 份副本，其中 3 份**已经漂了**（各少一页）",
    ),
    Revert(
        "RN", "产品自己把名单写回字面量",
        "gui_widget.py",
        "        self._preload_skip_pages = set(DEVICE_OWNING_PAGES)",
        '        self._preload_skip_pages = {"viewmodel", "magnifier", "flash", '
        '"voice_output", "kill_icon", "music"}',
        "tests/test_no_hardcoded_page_lists.py::test_product_reads_the_single_source",
        "只扫脚本是不够的：产品改回硬编码而脚本仍读真相源时，**两份都在还各说各话**，"
        "那是最坏的一种",
    ),
    # 「已关档页面的控件文案被悄悄改掉」这条断点**在本仓库没有对应判据**：
    # 结构基线数据（tests/baselines/renovation/）是上游的内部工程状态，没有同步过来，
    # 于是那个参数化用例 id 在这里根本不存在 —— 断点会**一直空转**，
    # 而空转的断点比没有断点更糟：它让人以为这块有人看着。
    # 判据本身照常同步（没有基线目录时它自己 skip），排除的是数据不是判据。
    Revert(
        "RN", "统计文件的缓存又只认 mtime、不认字节数",
        "core/page_usage_tracker.py",
        "        return (st.st_mtime_ns, st.st_size)",
        "        return st.st_mtime_ns",
        "tests/test_page_usage_tracker.py::"
        "test_two_writes_in_one_timestamp_tick_are_not_masked_by_the_cache",
        "两次写盘落在同一个文件时间戳刻度内时，_load() 认为文件没变、返回缓存里"
        "那份旧的：用户重置后立刻做配置恢复，恢复进来的统计被挡在外面 —— "
        "本机复现不出，只在快机器上发作（2026-08-17 由 CI 逮到）",
    ),
    Revert(
        "RN", "ensureWidgetVisible 少滚一截之后没人补",
        "gui_widget.py",
        "        if overflow > 0:\n"
        "            bar.setValue(min(bar.maximum(), bar.value() + overflow))\n",
        "        if False:\n"
        "            bar.setValue(min(bar.maximum(), bar.value() + overflow))\n",
        "tests/test_ui_visual_r1_fixes.py::test_nav_button_nudge_fixes_a_short_scroll",
        "ensureWidgetVisible 按调用那一刻的布局算，布局没落定就少滚一截，"
        "而且少滚了不会报错 —— 那一项静静留在视口外，用户失去「我在哪一页」的指示。"
        "余量本来就只有 24px，字体度量一变就压线（2026-08-17 CI 上 hud_color）",
    ),
    Revert(
        "RN", "帮助文案又被拆成两块叠加",
        "ui_help_panel.py",
        "PAGE_HELP_TEXTS = {",
        "PAGE_HELP_TEXTS = {}\nPAGE_HELP_TEXTS.update({",
        "tests/test_ui_help_panel_texts.py::test_help_texts_are_defined_exactly_once",
        "两块并存时后一块把前一块逐条盖掉，前面那些文案成了没人读得到的死文字 —— "
        "而查最终字典的判据照样绿。原先真有 237 行文案这么躺着，"
        "改文案的人还会挑到上面那块去改，改完当然「没生效」",
    ),
    Revert(
        "RN", "又加了一个建出来就 hide 的 summary_label",
        "tests/test_no_invisible_summary_label.py",
        # ⚠ 锚点跟着棘轮走：M3-b 清掉 viewmodel + flash 之后是 18。
        # 上一版锚的是 `= 20`，清完就成了空转断点（失效体检逮到）。
        "MAX_REMAINING = 17",
        "MAX_REMAINING = 17",
        "tests/test_no_invisible_summary_label.py::"
        "test_invisible_summary_label_count_only_shrinks",
        "21 个页面各有一个建出来就 hide()、全仓没人再显示的 summary_label，"
        "每次状态同步还照给它算 40~98 字的文本。它不报错不崩溃只是白算，"
        "读代码时看着完全正常 —— 这类东西只能靠扫描发现",
    ),
    Revert(
        "RN", "侧栏内容变高后不再重新校正当前项",
        "gui_widget.py",
        "        if (event.type() == QEvent.Resize\n"
        "                and (watched is getattr(self, \"_sidebar_nav_container\", None)",
        "        if (False\n"
        "                and (watched is getattr(self, \"_sidebar_nav_container\", None)",
        "tests/test_ui_visual_r1_fixes.py::"
        "test_sidebar_recovers_when_content_grows_after_the_page_switch",
        "切页那一刻算好的滚动位置，会被「之后」才发生的内容变高作废，"
        "当前项被挤出视口而没人再管 —— 本机怎么调窗口尺寸都复现不出",
    ),
    Revert(
        "RN", "只盯滚动内容、不盯视口变矮",
        "gui_widget.py",
        "        scroll_area.viewport().installEventFilter(self)",
        "        pass  # 断点：不再盯视口",
        "tests/test_ui_visual_r1_fixes.py::"
        "test_sidebar_keeps_active_nav_item_visible_when_viewport_shrinks",
        "RN-008 的真正根因：底部音乐条 musicControlBar（42px）是**滚完之后**才出现的，"
        "主窗从侧栏身上扣走 42px、视口跟着矮 42px，刚滚好的那一项被挤出可视区；"
        "而滚动内容的高度一点没变，只盯 nav_container 的话这个 Resize 根本不发生。"
        "CI 上连红五轮的指纹 y = 视口 − 24 就是它：y = V滚动 − 24 − 42 = V断言 − 24",
    ),
    Revert(
        "RN", "校正又只信 height() 不看 sizeHint",
        "gui_widget.py",
        "        height = max(btn.height(), btn.sizeHint().height())",
        "        height = btn.height()",
        "tests/test_ui_visual_r1_fixes.py::"
        "test_nav_button_nudge_does_not_trust_a_not_yet_laid_out_height",
        "布局还没给按钮定高时 height() 很小甚至是 0，算出来的「没超出」是假的。"
        "⚠ 这条是**防御性**的，不是 RN-008 的根因 —— 我一度用它解释 y=599，"
        "「高度被当成 0」和「视口后来缩了 42」在数值上完全同解，靠一个数字分不出来",
    ),
    Revert(
        "RN", "风格管理完之后又把 36 把武器重刷一遍",
        "pages/kill_voice_page.py",
        "        self._refresh_style_catalog()\n\n    def _on_weapon_style_changed",
        "        self._refresh_style_catalog()\n        self.load_settings()\n\n"
        "    def _on_weapon_style_changed",
        "tests/test_kill_voice_no_duplicate_work.py::"
        "test_managing_styles_touches_each_weapon_row_exactly_once",
        "重复工作的**终态和做一遍完全一样**：结构、指纹、两档像素逐字节等同，"
        "建页耗时的差别淹在噪声里 —— 所有基线都会照样绿。"
        "A 堆的清理靠基线证「没改坏」，只能靠这类计次判据证「没长回来」",
    ),
    Revert(
        "RN", "状态区又把已配置名单算两遍",
        "pages/kill_voice_page.py",
        "        self.category_overview_title_label.setText(f\"当前分类 · {current_category}\")",
        "        configured_names = self._configured_weapon_names()\n"
        "        self.category_overview_title_label.setText(f\"当前分类 · {current_category}\")",
        "tests/test_kill_voice_no_duplicate_work.py::"
        "test_status_badge_computes_the_configured_names_once",
        "两次调用之间没有任何东西改变它的输入，结果必然逐字相同 —— "
        "纯重复计算，肉眼读代码时两行离了 10 行远，看不出来",
    ),
    Revert(
        "RN", "刀的皮肤名又归一不到配置键",
        "gsi_handler_kills.py",
        "        if weapon_name.startswith(\"weapon_knife\"):\n"
        "            return \"weapon_knife\"",
        "        if weapon_name == \"weapon_knife\":\n"
        "            return \"weapon_knife\"",
        "tests/test_melee_kill_config_actually_applies.py::"
        "test_melee_skin_names_normalize_to_the_configured_key",
        "GSI 报的是 `weapon_knife_karambit` 这类皮肤名，配置表的键只有 `weapon_knife`。"
        "不归一就永远查不到 —— 「设了没反应」，不报错不崩溃日志还正常",
    ),
    Revert(
        "RN", "取键函数又不应用近战回退了",
        "gsi_handler_kills.py",
        "        weapon_name = self._apply_melee_fallback(weapon_name, config.weapon_kill_voices)",
        "        pass  # 断点：不再应用近战回退",
        "tests/test_melee_kill_config_actually_applies.py::"
        "test_both_key_getters_actually_apply_the_melee_fallback",
        "⚠ 别的判据测的是归一函数本身，**把调用点删掉它们照样全绿** —— "
        "所以必须有一条 AST 判据钉住调用点存在",
    ),
    Revert(
        "RN", "击杀语音页又没有近战分类",
        "pages/kill_voice_page.py",
        "        \"近战\": [\"weapon_knife\", \"weapon_taser\"],",
        "",
        "tests/test_melee_kill_config_actually_applies.py::"
        "test_kill_voice_page_offers_the_melee_category",
        "「击杀音效」有近战、「击杀语音」没有 ⇒ 刀杀和电人能配音效不能配语音，"
        "而这恰恰是最想要播报的两种击杀。这类「一组同类项里少一项」人眼极难发现",
    ),
    Revert(
        "RN", "预览按钮在组件没起来时又静默了",
        "pages/screen_effects_page.py",
        "        if self.overlay_manager is None:",
        "        if False:",
        "tests/test_preview_and_test_buttons_never_go_silent.py::"
        "test_preview_without_overlay_manager_says_something_specific",
        "`overlay_manager` 只在特效管理器**构造失败**时才是 None —— "
        "恰恰是软件真出问题的时候，用户点预览连个提示都没有",
    ),
    Revert(
        "RN", "第 1 连杀试听又变回静默",
        "pages/kill_voice_page.py",
        "        if not voice_file:\n            if level > 1:",
        "        if not voice_file and level > 1:\n            if level > 1:",
        "tests/test_preview_and_test_buttons_never_go_silent.py::"
        "test_test_button_reports_missing_audio_at_every_level",
        "同一个「测试」按钮，2~5 连杀有提示、第 1 连杀装死 —— "
        "用户点最常用的那一档反而什么都看不到",
    ),
    Revert(
        "RN", "「基础设置」又被塞回音效组里",
        "gui_widget.py",
        "            (\"开始\", [\n                (\"basic\", \"基础设置\"),\n            ]),\n"
        "            (\"音效设置\", [\n",
        "            (\"音效设置\", [\n                (\"basic\", \"基础设置\"),\n",
        "tests/test_sidebar_nav_structure.py::"
        "test_basic_settings_is_not_buried_in_the_sound_group",
        "准心、屏幕特效、切枪音效的总开关全写在「基础设置」里，"
        "把它挂在音效组下面 ⇒ 找准心的开关得先去音效菜单里翻（RN-108）。"
        "⚠ 这条**不能**用「它是不是第一项」那条判据来防：塞回音效组之后它仍然是"
        "第一组第一项，那条判据照样绿 —— 回退验证当场逮到的",
    ),
    Revert(
        "RN", "有新页面插到「基础设置」前面去了",
        "gui_widget.py",
        "            (\"开始\", [\n                (\"basic\", \"基础设置\"),\n            ]),",
        "            (\"开始\", [\n                (\"about\", \"关于软件\"),\n"
        "                (\"basic\", \"基础设置\"),\n            ]),",
        "tests/test_sidebar_nav_structure.py::"
        "test_basic_settings_is_the_very_first_nav_item",
        "置顶这件事只有「第一项」算数：往它上面塞一项，"
        "「不在音效组里」那条判据依然全绿",
    ),
    Revert(
        "RN", "Alt+N 的上限又写死成 4",
        "gui_widget.py",
        "        for idx in range(min(9, len(self.nav_groups))):",
        "        for idx in range(min(4, len(self.nav_groups))):",
        "tests/test_sidebar_nav_structure.py::"
        "test_every_nav_group_gets_an_alt_shortcut",
        "写死的 4 恰好等于当时的分组数 ⇒ 加一组之后最后一组悄悄没了快捷键，"
        "而断言个数的旧判据照样绿",
    ),
    Revert(
        "RN", "关于页那句提示又变回没有落点的死提示",
        "pages/about_page.py",
        "        self.goto_onboarding_button.clicked.connect(self._open_onboarding_guide)",
        "        pass",
        "tests/test_onboarding_reentry.py::"
        "test_about_page_hint_now_has_somewhere_to_go",
        "「请确保已正确选择 CS 文件夹」说了要做什么、却没说去哪儿做 —— "
        "而 CS2 目录是其余所有功能的前提（RN-110）",
    ),
    Revert(
        "RN", "引导打不开时又一声不吭",
        "pages/about_page.py",
        "        if not callable(opener):\n"
        "            toast_warning(\"上手引导打不开，请到「工具与系统 - 高级设置」里选 CS2 目录。\", 4200)\n"
        "            return",
        "        if not callable(opener):\n            return",
        "tests/test_onboarding_reentry.py::"
        "test_about_page_button_says_where_to_go_when_it_cannot_open_the_guide",
        "这个按钮是给「不知道去哪儿设目录」的新用户准备的，它自己再没反应"
        "就等于把人扔在原地。⚠ 判据断言的是「高级设置」四个字，不是「有没有提示」",
    ),
    Revert(
        "RN", "基础设置页的引导条只剩一句话、点不开",
        "gui_widget.py",
        "            self._reopen_onboarding_guide,",
        "            lambda: None,",
        "tests/test_onboarding_reentry.py::"
        "test_basic_page_carries_the_three_step_guide_bar",
        "引导条的价值全在那个按钮上：只留文字的话，用户读完还是不知道去哪儿点",
    ),
    Revert(
        "RN", "徽章又回去数配置里的原始值",
        "pages/kill_sound_page.py",
        "        selected_count = self._configured_weapon_count(resolved=resolved)",
        "        from pages.audio_status_badge import count_enabled_styles\n"
        "        selected_count = count_enabled_styles((config.weapon_kill_sounds or {}).values())",
        "tests/test_kill_sound_status_tells_the_truth.py::"
        "test_badge_count_matches_what_the_rows_actually_show",
        "RN-026：徽章数配置原始值、列表按能否解析显示 ⇒ 风格一丢就长期写着"
        "「已配置 37 / 手枪 10/10」而下面 39 把枪全是「不启用」，且没有任何东西报错",
    ),
    Revert(
        "RN", "失效项又被静默算进「已配置」",
        # ⚠ 锚点原本在 kill_sound_page.py。RN-033 把这份实现**上提到了基类**
        # （四页共用），锚点随之搬家。失效体检当场报"锚点出现 0 次" —— 这已经是
        # 第二次由体检逮到断点腐烂，印证总纲那句：**审计/棘轮/断点自己也会腐烂**。
        "pages/sound_page_base.py",
        "        return \"0\" if display == self.DISABLED_STYLE_TEXT else display",
        "        return str(self._configured_style(weapon))",
        "tests/test_kill_sound_status_tells_the_truth.py::"
        "test_stale_styles_are_named_not_silently_counted_as_configured",
        "⚠ 只把数字改对不够：用户看到数字变小只会觉得「我的配置怎么少了」。"
        "必须**说出来**有几项失效、以及怎么办",
    ),
    Revert(
        "RN", "分类名又拿页签文字当字典键",
        "pages/kill_sound_page.py",
        "        names = list(self.CATEGORIES.keys())\n"
        "        if not hasattr(self, \"tab_widget\")",
        "        names = []\n        if not hasattr(self, \"tab_widget\")",
        "tests/test_kill_sound_status_tells_the_truth.py::"
        "test_category_lookup_survives_a_renamed_tab",
        "RN-028：页签文案加个计数后缀，查表就静默返回 []，分类徽章变 0/0 而不报错。"
        "与 kill_voice 的 RN-020 同形，那页已修、这页一直还在",
    ),
    Revert(
        "RN", "风格没了又被报成「音频设备不可用」",
        "pages/kill_sound_page.py",
        "            report_preview_failure(self, PreviewFailure.STALE_STYLE, style_text)\n"
        "            return",
        "            sound_key = f\"kill-{level}\"\n            sound_dir = None",
        "tests/test_kill_sound_status_tells_the_truth.py::"
        "test_a_vanished_style_is_not_reported_as_a_broken_sound_card",
        "RN-029：把用户支去查声卡和驱动，而真实原因是那个风格被删了",
    ),
    Revert(
        "RN", "击杀音效页的已配置名单又算两遍",
        "pages/kill_sound_page.py",
        "        self.category_overview_title_label.setText(f\"当前分类 · {current_category}\")",
        "        configured_names = self._configured_weapon_names()\n"
        "        self.category_overview_title_label.setText(f\"当前分类 · {current_category}\")",
        "tests/test_kill_sound_status_tells_the_truth.py::"
        "test_status_badge_computes_the_configured_names_once",
        "RN-019：与 kill_voice 的 RN-014 一模一样的重复计算，终态逐字相同、所有基线照样绿",
    ),
    Revert(
        "RN", "风格管理完之后又把 39 把武器重刷一遍",
        "pages/kill_sound_page.py",
        "        self._refresh_style_catalog()\n\n    def _on_weapon_style_changed",
        "        self._refresh_style_catalog()\n        self.load_settings()\n\n"
        "    def _on_weapon_style_changed",
        "tests/test_kill_sound_status_tells_the_truth.py::"
        "test_managing_styles_touches_each_weapon_row_exactly_once",
        "RN-027：与 kill_voice 的 RN-015 逐字同形。终态一样，所有基线照样绿",
    ),
    Revert(
        "RN", "引导窗又能开出第二个",
        "gui_widget.py",
        "        existing = getattr(self, \"_onboarding_dialog\", None)\n"
        "        if existing is not None and existing.isVisible():",
        "        existing = None\n        if False:",
        "tests/test_onboarding_reentry.py::"
        "test_opening_the_guide_twice_reuses_the_same_window",
        "`self._onboarding_dialog = dialog` 是唯一的防 GC 引用，造第二个就把第一个的"
        "引用覆盖掉，而第一个还显示在屏幕上。入口已经有三处（首启/基础设置/关于）",
    ),
    Revert(
        "RN", "自动弹引导又自己构造了一次对话框",
        "gui_widget.py",
        "            self._show_onboarding_dialog()\n"
        "            self.logger.info(\"首次使用引导已弹出\")",
        "            from dialogs.onboarding_dialog import OnboardingDialog\n\n"
        "            dialog = OnboardingDialog(self)\n"
        "            self._onboarding_dialog = dialog\n"
        "            dialog.show()\n"
        "            self.logger.info(\"首次使用引导已弹出\")",
        "tests/test_onboarding_reentry.py::"
        "test_auto_popup_and_manual_reopen_share_one_entry_point",
        "自动弹和手动重开就此分家：改一边忘一边**不会报错**，只会悄悄不一样。"
        "同 RN-002 那份被抄了 9 遍、3 份已经漂了的设备页名单",
    ),
    # ---------------------------------------------- RN-032 工装配置目录（这一轮）
    Revert(
        "RN", "工装又自己造临时配置目录、不落占位配置",
        "scripts/_pristine_config.py",
        '    (tmp / "config" / "config.json").write_text(PLACEHOLDER, encoding="utf-8")',
        '    pass  # 占位配置没了，migrate_old_config 会把个人配置复制进来',
        "tests/test_pristine_config_for_tooling.py::"
        "test_placeholder_config_is_written_before_anything_can_migrate",
        "RN-031 只修了六处里的一处 ⇒ 像素基线/排版审计/耗时基线/搜索索引"
        "全都还在开发机的个人配置上产出。⚠ 断点瞄的是**占位文件在不在**，"
        "不是「函数有没有被调用」",
    ),
    Revert(
        "RN", "又有第二份工装自己写 CS2C_CONFIG_DIR",
        "scripts/layout_overflow_audit.py",
        '_tmp = use_pristine_config_dir("cs2customizer_layout_audit")',
        'import tempfile as _tf\n'
        '_tmp = Path(_tf.gettempdir()) / "cs2customizer_layout_audit"\n'
        '(_tmp / "config").mkdir(parents=True, exist_ok=True)\n'
        'os.environ.setdefault("CS2C_CONFIG_DIR", str(_tmp / "config"))',
        "tests/test_pristine_config_for_tooling.py::"
        "test_only_one_place_in_scripts_touches_the_config_dir_env",
        "只要还有第二份副本，修好一份就等于没修（RN-002 那份名单被抄了 9 遍、"
        "其中 3 份已经漂了）",
    ),
    Revert(
        "RN", "force 语义被降级成 setdefault",
        "scripts/_pristine_config.py",
        '    if os.environ.get("CS2C_CONFIG_DIR") and not force:',
        '    if os.environ.get("CS2C_CONFIG_DIR"):',
        "tests/test_pristine_config_for_tooling.py::"
        "test_force_overrides_an_inherited_config_dir",
        "`renovation_baseline.structure_of` 是被 pytest 起的子进程，会继承 conftest "
        "那个跨轮次累积的配置目录 —— 不 force 就把 RN-031 的修法整个作废，"
        "**而且失效时毫无声响**",
    ),
    # ------------------------------------------------ RN-033 家族计数口径
    Revert(
        "RN", "switch_weapon 的徽章又回去数配置原始值",
        "pages/switch_weapon_page.py",
        "        selected_count = self._configured_weapon_count(resolved=resolved)",
        "        from pages.audio_status_badge import count_enabled_styles\n"
        "        selected_count = count_enabled_styles((config.weapon_switch_sounds or {}).values())",
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_badge_number_matches_the_rows_the_user_can_see",
        "⚠ 断点改的是**徽章实际用的那个变量**。上一轮判据落在 "
        "`_configured_weapon_count()` 这个辅助函数上，两者不相干 —— "
        "缺陷注进去判据照样绿，回退验证当场逮住",
    ),
    Revert(
        "RN", "失效项又不说了，只是从计数里消失",
        "pages/sound_page_base.py",
        '            return "warn", f"已配置 · {selected_count} · {stale_count} 项失效"',
        '            return "info", f"已配置 · {selected_count}"',
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_the_badge_says_out_loud_that_some_entries_went_stale",
        "只把数字改对不够：用户看到数字变小只会觉得「我的配置怎么少了」。"
        "「有 N 项失效」才是唯一可行动的信息",
    ),
    Revert(
        "RN", "「怎么修」又写回那个死控件",
        "pages/switch_weapon_page.py",
        "            self.category_overview_hint_label.setText(self._stale_style_hint(stale_count))",
        "            self.summary_label.setText(self._stale_style_hint(stale_count))",
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_the_visible_hint_line_says_how_to_fix_it",
        "RN-009：`summary_label` 建出来就 hide()，全仓无人再显示它。"
        "kill_sound 那轮我就写错过一次，外审复跑一句「醒目报错却无修复引导」点破",
    ),
    Revert(
        "RN", "试听又把「风格没了」报成「文件不存在」",
        "pages/switch_weapon_page.py",
        "            report_preview_failure(self, PreviewFailure.STALE_STYLE,",
        "            report_preview_failure(self, PreviewFailure.NO_FILE,",
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_previewing_a_stale_style_says_the_style_is_gone",
        "那一行明明显示「不启用」，点测试却报「文件不存在」⇒ 用户会去查音频设备"
        "和素材，而真正的原因是他配的风格被改名/删掉了",
    ),
    Revert(
        "RN", "death_sound 又宣称那个已经没了的风格正生效",
        "pages/death_sound_page.py",
        "        current_style = self._effective_style_value()",
        '        current_style = str(getattr(config, "death_sound_style", "0") or "0")',
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_death_page_never_claims_a_vanished_style_is_selected",
        "这一页原状是个**闭环矛盾**：选择卡说「当前已选择 X，切换后可以直接点击"
        "测试」，点了测试它说「还没选风格」—— 页面把用户送进一个必然失败的动作",
    ),
    Revert(
        "RN", "death_sound 的试听又说「还没选风格」",
        "pages/death_sound_page.py",
        "                report_preview_failure(self, PreviewFailure.STALE_STYLE, stale_style)",
        "                report_preview_failure(self, PreviewFailure.NO_STYLE)",
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_death_page_preview_reports_stale_not_no_style",
        "用户明明选过 —— 只是他选的那个风格已经被改名/删掉，下拉框退回了「不启用」",
    ),
    # ------------------------------------------------ RN-034/035/037/040
    Revert(
        "RN", "全新安装的素材目录又被画成红色报错",
        "pages/audio_status_badge.py",
        '    if missing:\n        return "info", "素材 · 待添加"',
        '    if missing:\n        return "danger", f"资源 · 异常 {len(missing)}"',
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_a_missing_material_dir_is_not_painted_as_a_red_error",
        "RN-035：「还没放素材」不是异常，是起点。把起点画成红色，"
        "新用户第一反应是软件坏了 —— 外审 S4 六发里五发独立点出这一条",
    ),
    Revert(
        "RN", "副标题又无条件命令用户去开一个可能已经开着的开关",
        "pages/switch_weapon_page.py",
        '    PAGE_LEAD = "切换武器时播放你自己的音效。逐把枪选风格，点「测试」试听；总开关在「基础设置」里。"',
        '    PAGE_LEAD = "切换武器时播放你自己的音效。先去「基础设置」打开总开关，再逐把枪选风格，点「测试」试听。"',
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_no_page_orders_the_user_to_flip_a_switch_that_may_already_be_on",
        "同一屏上徽章写着「开关 · 已启用」，副标题却叫人去打开它。"
        "外审六发截图里四发独立点出，措辞几乎一样",
    ),
    Revert(
        "RN", "reload_sound 的档位死分支又回来了",
        "pages/reload_sound_page.py",
        "        del level\n        self._test_reload_sound(weapon)",
        "        self._test_reload_sound(weapon) if level is None else self._test_reload_sound(weapon, level)",
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_the_level_argument_branch_is_gone",
        "`_test_reload_sound()` 只接一个参数 ⇒ 那个分支一走必 TypeError。"
        "它没爆过只因为本页 TEST_LEVELS is None，档位菜单压根没建",
    ),
    Revert(
        "RN", "kill_voice 的试听又变成只写日志",
        "pages/kill_voice_page.py",
        "            configured = self._configured_style(weapon)",
        "            self.logger.info(f\"武器 {weapon} 未启用语音\")\n"
        "            return\n"
        "            configured = self._configured_style(weapon)",
        "tests/test_sound_family_status_tells_the_truth.py::"
        "test_kill_voice_preview_is_never_silent",
        "RN-040：用户看到的是「点了没反应」。同 UP-037 那一类，"
        "其余各页早就改成给提示了，这页漏下了",
    ),
    # ------------------------------------------------ RN-046~055（M2-b 两页）
    Revert(
        "RN", "gun_sound 又把失效的风格算进「已配置」",
        "pages/gun_sound_page.py",
        "        selected_count = sum(1 for value in effective.values() if value != \"0\")",
        "        selected_count = sum(1 for value in self.weapon_configs.values()\n"
        "                             if self._get_profile_style(value) != \"0\")",
        "tests/test_gun_special_sound_truth.py::"
        "test_gun_sound_does_not_count_styles_that_are_gone",
        "RN-046：徽章「已配置 · 2/18」而那两行的下拉框都显示「不启用」——"
        "计数数配置原始值、界面显示解析后的值，两边永久对不上且无人报错",
    ),
    Revert(
        "RN", "gun_sound 的试听又把「风格没了」报成「文件不存在」",
        "pages/gun_sound_page.py",
        "            report_preview_failure(self, PreviewFailure.STALE_STYLE,",
        "            report_preview_failure(self, PreviewFailure.NO_FILE,",
        "tests/test_gun_special_sound_truth.py::"
        "test_gun_sound_preview_tells_stale_from_unset",
        "配过、但风格已被改名/删除时，原来会去播一个不存在的音效键、"
        "落到 NO_FILE ⇒ 用户被指去翻一个已经不存在的目录（同 RN-029）",
    ),
    Revert(
        "RN", "空状态提示又被塞回 18 张武器卡",
        "pages/gun_sound_page.py",
        "        profile = self.weapon_configs[weapon_type]\n"
        "        duck_ratio = self._get_profile_duck_ratio(profile)",
        "        if not styles:\n"
        "            empty_hint = QLabel(\"当前还没有检测到这个武器的可用风格资源。\")\n"
        "            empty_hint.setObjectName(\"hintLabel\")\n"
        "            card_layout.addWidget(empty_hint)\n"
        "        profile = self.weapon_configs[weapon_type]\n"
        "        duck_ratio = self._get_profile_duck_ratio(profile)",
        "tests/test_gun_special_sound_truth.py::"
        "test_gun_sound_empty_state_is_said_once_not_eighteen_times",
        "RN-049：全新安装下同一句话出现 18 次，而顶部状态卡同屏已写着"
        "「素材 · 待添加」。与上一轮那句 50 字辩解同病，这次是 18 份",
    ),
    Revert(
        "RN", "special_sound 的回合计数又被手写成 5 个字段",
        "pages/special_sound_page.py",
        "        round_selected = self._selected(round_effective)",
        "        round_selected = len([v for v in (\n"
        "            getattr(config, \"round_start_style\", \"0\"),\n"
        "            getattr(config, \"round_action_style\", \"0\"),\n"
        "            getattr(config, \"round_win_style\", \"0\"),\n"
        "            getattr(config, \"round_lose_style\", \"0\"),\n"
        "            getattr(config, \"round_mvp_style\", \"0\"),\n"
        "        ) if str(v) != \"0\"])",
        "tests/test_gun_special_sound_truth.py::"
        "test_special_sound_round_count_is_not_capped_at_five",
        "⭐ 分子手写 5 个字段、分母从事件表派生成 8 ⇒ **计数上限 5、分母 8**，"
        "配满也永远显示不满。事件表的 docstring 开篇讲的就是别再有第二份手写清单",
    ),
    Revert(
        "RN", "special_sound 的四个试听又变成只写日志",
        "pages/special_sound_page.py",
        "        if self._report_preview(configured, style, label):\n            return",
        "        if str(configured or \"0\").strip() == \"0\":\n"
        "            self.logger.info(f\"{grenade_type} 当前未启用音效\")\n"
        "            return",
        "tests/test_gun_special_sound_truth.py::"
        "test_special_sound_preview_never_silently_does_nothing",
        "RN-047：四个「测试」原来全是只写日志就 return ⇒ 用户看到「点了没反应」。"
        "外审 8 发截图里 7 发独立报「点击无反应易被误认为软件故障」",
    ),
    Revert(
        "RN", "选了风格但模块没开这件事又没人说",
        "pages/special_sound_page.py",
        "            return \" · 模块已关闭（配了也不会响）\"",
        "            return \" · 模块已关闭\"",
        "tests/test_gun_special_sound_truth.py::"
        "test_special_sound_warns_when_style_chosen_but_module_off",
        "RN-051：本页有两层开关（模块复选框 + 每项的「不启用」）。"
        "外审 4 发独立报玩家会只选下拉项而遗漏模块开关，局内不响却查不出原因",
    ),
    Revert(
        "RN", "状态徽章又不跟当前页签走",
        "pages/special_sound_page.py",
        "            (\"success\" if tab_badge[0] else \"info\", tab_badge[1]),",
        "            (\"success\" if round_on else \"info\", f\"回合音量 · {round_volume}%\"),",
        "tests/test_gun_special_sound_truth.py::"
        "test_special_sound_status_chip_follows_current_tab",
        "RN-053：在「血量警告」页签上那颗徽章写的是「回合音量 · 100%」，"
        "与屏幕上的内容毫无关系。外审两发独立点出",
    ),
    Revert(
        "RN", "风格解析又被抄成第二份",
        "pages/audio_status_badge.py",
        "def resolve_style(configured, available: Iterable) -> str:",
        "def _resolve_style_unused(configured, available: Iterable) -> str:",
        "tests/test_gun_special_sound_truth.py::"
        "test_style_resolver_is_single_sourced",
        "RN-046：这条知识曾同时以四份副本存在（基类 / death / gun / special），"
        "每份都只做了一半。RN-002/031/032 已证三次：还有第二份就等于没修",
    ),
    Revert(
        "RN", "死方法又被留在页面里",
        "pages/gun_sound_page.py",
        "    def _create_compact_weapon_card(self, weapon_type: str, display_name: str, styles: list[str]):",
        "    def _create_weapon_card_unused(self, weapon_type: str) -> None:\n"
        "        pass\n\n"
        "    def _create_compact_weapon_card(self, weapon_type: str, display_name: str, styles: list[str]):",
        "tests/test_gun_special_sound_truth.py::"
        "test_no_private_method_is_dead",
        "原状是一个 113 行、全仓零调用的卡片构造器，里面还带着两处错"
        "（标签写成「镜声风格」、武器名那一行从未 addLayout）⇒ 接回去当场就错",
    ),
    Revert(
        "RN", "卡片说明又改回讲版面",
        "pages/special_sound_page.py",
        "\"回合开始、结束、MVP 等时刻各播一段音效。逐项选风格，音量统一由上面这一条控制。\",",
        "\"把启用开关和总音量固定在上方，下面集中管理各阶段风格。\",",
        # ⚠ RN-077：判据从音效家族两页搬到了全站（分母 2 → 28），选择器跟着搬。
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_no_layout_self_talk_in_any_card_subtitle",
        "RN-050：「固定在上方」这句已经是**事实错误** —— UP-100 为修「62px 舷窗」"
        "把头部卡挪进了滚动区。描述版面的文案会随版面腐烂，描述功能的不会",
    ),
    Revert(
        "RN", "提示又去指一个本页不存在的按钮",
        "pages/special_sound_page.py",
        'hint = resource_hint(health, open_label="打开当前资源")',
        'hint = resource_hint(health)',
        "tests/test_gun_special_sound_truth.py::"
        "test_hint_only_names_buttons_that_exist",
        "RN-056：本页那颗主按钮叫「打开当前资源」，而共享提示写的是"
        "「打开音频资源」。单一真相源不等于"
        "文案可以照搬——"
        "这条是改完复跑外审、"
        "8 发里 4 发独立报出来的",
    ),
    Revert(
        "RN", "血量警告三行又被摊成通栏，紧凑档顶出可视区",
        "pages/special_sound_page.py",
        "        card_layout.addLayout(slider_row)\n        card_layout.addWidget(style_row)",
        "        card_layout.addWidget(threshold_row)\n        card_layout.addWidget(cooldown_row)\n        card_layout.addWidget(style_row)",
        "tests/test_gun_special_sound_truth.py::"
        "test_health_tab_keeps_the_two_sliders_on_one_row",
        "RN-055：三行通栏把卡片抬高一行，紧凑档 860x640 下最后一行被截 —— "
        "外审复跑当场报「高」，而改之前紧凑档这一页是 NONE",
    ),
    # ------------------------------------------------ RN-005/059/060/061（M3-a）
    Revert(
        "RN", "中和表又被抄回脚本里",
        "scripts/ui_shot_capture.py",
        "        neutralized = neutralize_apply(config, page_ids)",
        "        NEUTRALIZABLE = {\"magnifier\": {\"magnifier_enabled\": False}}\n"
        "        for pid, ov in NEUTRALIZABLE.items():\n"
        "            for a, v in ov.items():\n"
        "                setattr(config, a, v)\n"
        "        neutralized = sorted(NEUTRALIZABLE)",
        "tests/test_audit_can_see_every_page.py::"
        "test_the_neutralize_table_exists_in_exactly_one_place",
        "RN-005：这张表曾在 5 支脚本各一份、内容 1~3 项不等，后果是 "
        "flash/viewmodel/voice_output 三页（4265 行）被全部 5 支跳过 —— 零覆盖",
    ),
    Revert(
        "RN", "热键闸门失效（审计又会真挂钩）",
        "core/hotkeys/registry.py",
        '    return os.environ.get("CS2C_NO_GLOBAL_HOTKEYS") == "1"',
        "    return False",
        "tests/test_audit_can_see_every_page.py::"
        "test_the_gate_registers_nothing_with_the_real_libraries",
        "RN-059：闸门是「这个进程绝不注册真实全局热键」这条**保证**本身。"
        "它一失效，离屏审计就会按用户配置真去挂钩、劫持键盘鼠标",
    ),
    Revert(
        "RN", "设备页又被整类拒绝",
        "scripts/_audit_neutralize.py",
        "    return frozenset(DEVICE_OWNING_PAGES) - set(NEUTRALIZE)",
        "    return frozenset(DEVICE_OWNING_PAGES)",
        "tests/test_audit_can_see_every_page.py::"
        "test_no_page_is_skipped_by_the_audits_any_more",
        "整类拒绝就是老状态：排版审计 24/28、指纹 21/28、截图缺 4 页、"
        "建页耗时缺 6 页，而**没有任何地方报错**",
    ),
    Revert(
        "RN", "侧栏导航项又被切成两半",
        "gui_widget.py",
        "        MainWindow._snap_nav_scroll_to_item_boundary(scroll, btn)",
        "        pass",
        "tests/test_audit_can_see_every_page.py::"
        "test_sidebar_never_shows_a_half_cut_nav_item_at_the_top",
        "RN-060：28 页里 **16 页**的侧栏顶部/底部各切掉 13~21px（项高 43px），"
        "用户看到残缺的导航文字。排版审计一直绿（滚动区露半行不算溢出），"
        "外审 8 发独立报出来 —— 而它只在导航列表靠后的页出现，"
        "那些页正是 RN-005 盲区里的四页",
    ),
    Revert(
        "RN", "建页耗时清单又漏掉设备页",
        "scripts/bench_page_build.py",
        '    ("flash", "pages.flash_page", "FlashPage"),',
        "",
        "tests/test_audit_can_see_every_page.py::"
        "test_bench_covers_every_registered_page",
        "RN-061：这份清单长期只有 18/28 页，缺的 9 页里 6 个是设备页 —— "
        "棘轮看不见它们，而漏了不报错",
    ),
    Revert(
        "RN", "焦点巡检又把 flash / viewmodel 排除在外",
        "scripts/tab_order_audit.py",
        "SPAWNS_SUBPROCESS: set[str] = set()",
        'SPAWNS_SUBPROCESS: set[str] = {"flash", "viewmodel"}',
        "tests/test_audit_can_see_every_page.py::"
        "test_focus_audit_covers_every_page_with_a_class",
        "RN-059：这是**第 8 处**私有跳过名单。探针在 subprocess.Popen 边界实测"
        "两页构造时子进程调用 0 次。纳入后覆盖面 25/28 → 27/28，"
        "**当场就在 viewmodel 上报出一处 Tab 顺序错位**（RN-069）",
    ),
    Revert(
        "RN", "viewmodel 的 Tab 顺序又跳回左下角",
        "pages/viewmodel_page.py",
        # ⚠ 锚点与判据都换过。原来锚的是 RN-069 那行 `setTabOrder` 补丁，
        # 而 RN-083 改版面之后**那行补丁本身成了错的**（去掉它焦点巡检才是 0 挪动），
        # 锚点随之消失。原判据挂的是 `test_focus_audit_covers_every_page_with_a_class`
        # —— 那是条**覆盖面**判据（管「有没有看这一页」），不是顺序判据。
        # 现在改成注入一条真会打乱顺序的 setTabOrder，判据直接量顺序。
        "        presets_layout.addWidget(presets_scroll)",
        "        presets_layout.addWidget(presets_scroll)\n"
        "        self.setTabOrder(self.auto_switch_interval_input, save_btn)",
        "tests/test_flash_viewmodel_truth.py::test_viewmodel_tab_order_follows_the_screen",
        "RN-069：走到第 5 个焦点时跳到左下角的「保存到CFG」（y=487），"
        "再折回右上角的「循环按键」输入框（y=229）。"
        "⇒ 显式 setTabOrder 是对**某个具体版面**的断言，改版面就得重新验它",
    ),
    Revert(
        "RN", "lint 又把整个 scripts/ 蒙住",
        "ruff.toml",
        '    "scripts/bootstrap_tutorial_content.py",',
        '    "scripts",',
        "tests/test_audit_no_modal_no_game_writes.py::"
        "test_lint_does_not_blindfold_the_whole_scripts_directory",
        "RN-070：`exclude = [..., \"scripts\"]` 让 64 支 / 19226 行工装代码零 lint，"
        "而 CI 把 `ruff check .` 当 lint 门禁。里面躺着一条 F821"
        "（`ui_perf_probe` 用 sys 没 import），一秒就能查出来的东西躺了很久",
    ),
    Revert(
        "RN", "ui_perf_probe 的 UTF-8 兜底又变成哑弹",
        "scripts/ui_perf_probe.py",
        "import sys                      # RN-071：下面 stdout.reconfigure 要它，缺了会静默失效",
        "",
        "tests/test_audit_no_modal_no_game_writes.py::"
        "test_every_script_that_uses_sys_imports_it",
        "RN-071：`sys.stdout.reconfigure` 抛的 NameError 被同一段的 "
        "`except Exception: pass` 吞掉 ⇒ 整块 UTF-8 兜底恒失效。"
        "该脚本打 ✅×5 / ❌×3 / ⚠×1，GBK 控制台上本该必崩 —— "
        "**兜底把自己的失败也兜掉了**",
    ),
    Revert(
        "RN", "建页基准又不沙箱化游戏目录",
        "scripts/bench_page_build.py",
        "    sandbox_external_writes(verbose=False)",
        "    pass",
        "tests/test_audit_side_effects_r9a.py::"
        "test_every_page_building_script_sandboxes_the_game_dir",
        "RN-072：实测它在动用户真实的 `Steam/.../csgo/cfg/`（GSI cfg / cs2customizer.cfg / "
        "autoexec.cfg 三个文件）。UP-090 的机制早就在，只是没接到这支脚本上",
    ),
    Revert(
        "RN", "沙箱判据又只认构造 MainWindow 的脚本",
        "tests/test_audit_side_effects_r9a.py",
        '        if _constructs(src, "MainWindow") or _builds_pages_directly(src):',
        '        if _constructs(src, "MainWindow"):',
        "tests/test_audit_side_effects_r9a.py::"
        "test_the_detector_also_sees_scripts_that_build_pages_without_mainwindow",
        "RN-072：`bench_page_build` 用 importlib 动态构造单个页类、一次都没构造 "
        "MainWindow，于是整支落在判据视野之外 —— **判据的分母不含出事的那个**。"
        "放开分母后当场又多抓出一支 `probe_r8d_focus`",
    ),
    Revert(
        "RN", "建页基准又只 import 中和表不调用",
        "scripts/bench_page_build.py",
        "    neutralize_apply(_config_mod.config, {pid for pid, _, _ in specs})",
        "    pass",
        "tests/test_audit_can_see_every_page.py::"
        "test_the_shared_table_is_actually_used_by_the_gate_scripts",
        "RN-073：第二层中和在这支脚本里等于没接上。"
        "而**上一版判据是假绿的** —— 它只查文件里有没有 `_audit_neutralize` "
        "这个子串，`import 了但不调用`完全过关。改成 AST 找 Call 才咬得住",
    ),
    Revert(
        "RN", "模态框闸门又变成消音器",
        "scripts/_audit_neutralize.py",
        "        _BLOCKED.append(what)",
        "        pass",
        "tests/test_audit_no_modal_no_game_writes.py::"
        "test_the_modal_gate_records_instead_of_swallowing",
        "RN-072：闸门必须同时是**发现通道**。只挡不记账的话，"
        "「某页构造期弹框」会从挂死变成静默通过 —— 缺陷被判据自己藏起来",
    ),
    Revert(
        "RN", "单选钮的 border-radius 又按内容框算",
        "theme_manager.py",
        # ⚠ 必须锚 `:checked` 那一行。第一版锚的是基础规则那行，回退之后
        # `:checked` 自己的 radius 还在 ⇒ 选中态仍是圆 ⇒ **判据假绿**（回退验证逮到）。
        # 缺陷长在选中态上，断点就得长在选中态上。
        "                border-radius: {(toggle.radio_size + 2 * max(4, toggle.radio_border_width + 3)) // 2}px;",
        "                border-radius: {toggle.radio_size // 2}px;",
        "tests/test_radio_indicator_is_round.py::"
        "test_radio_indicator_is_round_in_every_state",
        "RN-066/076：Qt QSS 的 `width/height` 是**内容框**，边框加在外面。"
        "按内容框算 radius ⇒ 内缘 radius = 9−5 = 4 铺在 18px 白底上 ⇒ "
        "**选中项渲染成白色实心方块**，和同排未选中的圆圈不是一个形状。"
        "⚠ 判据必须读像素：我上一轮拿 QSS 驳这条外审断言，判了假报（同 V-003 的错法）",
    ),
    Revert(
        "RN", "卡片副标题又写成版面自白",
        "pages/viewmodel_page.py",
        '            "5 组持枪视角参数，每组都能单独改并保存下来。"',
        '            "5 组常用持枪参数继续保留完整编辑能力，滚动区域更紧凑一些。"',
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_no_layout_self_talk_in_any_card_subtitle",
        "RN-077：这句是**对着上一版说话**，而用户没见过上一版。"
        "判据上一版分母只有音效家族两页，全站放开后一次量出 20 条 / 8 页 —— "
        "而那两页一条都没有。**判据写完要问的不是它绿不绿，是它的分母是多少**",
    ),
    Revert(
        "RN", "自白抽取器又只认 SettingsCard",
        "tests/test_no_layout_self_talk_sitewide.py",
        '        elif any(k in low for k in ("card", "panel", "section", "group")):',
        "        elif False:",
        # ⚠ 这个选择器改过两次，两次都是因为守卫本身假绿：
        #   ① `..._sees_the_subtitles` 只数总数 → 拆掉分支后总数还有 60+，过关；
        #   ② 点名 magnifier / voice_output 两页 → 这两页两种工厂都用，照样出货。
        # 现在盯的是**会被拆掉的那条分支自己出了几条**。
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_the_extractor_actually_sees_the_variant_factories",
        "RN-077：抽取器第一版只认 `SettingsCard` / `_create_section_card`，"
        "于是 `magnifier_page` 的 `_create_inner_panel_card()` 整支落在视野外，"
        "里面躺着两条自白。**判据没错，它只是什么都没看**",
    ),
    Revert(
        "RN", "引导文案又指向一个同名的页签",
        "pages/flash_page.py",
        # ⚠ 锚点跟着文案走：这一行在**同一轮里改过三次**（修同名歧义 → 修我自己
        # 引入的「左侧」→ 按钮能自己开之后改口径），前两版锚点都当场空转。
        # ⭐ 教训：**别把断点锚在这一轮还在改的那一行**，或者收尾时统一重锚一次。
        "被闪的时候，用你自己的颜色、图片和音效替换游戏默认的闪白。还没启用的话，点一下「启用自定闪光」就能开。",
        "先去「基础设置」打开总开关。",
        "tests/test_flash_viewmodel_truth.py::"
        "test_the_master_switch_hint_says_which_basic_settings",
        "RN-075：`flash` **自己的第一个页签就叫「基础设置」**，里面没有任何总开关；"
        "真开关在侧栏同名的 `basic` 页、卡片叫「功能开关」、开关叫「自定闪光」。"
        "外审 3/3 全票 × 5 张图全部报同一件事，措辞都是「就在基础设置页却完全找不到」",
    ),
    Revert(
        "RN", "flash 底栏主按钮又变回纯导航",
        "pages/flash_page.py",
        '                self.action_bar.configure_primary("启用自定闪光", self._enable_and_start, visible=True)',
        '                self.action_bar.configure_primary("前往效果预览", self._open_preview_tab, visible=True)',
        "tests/test_flash_viewmodel_truth.py::"
        "test_flash_bottom_bar_primary_actually_changes_something",
        "RN-079：主按钮只切页签、不改任何状态，而胶囊常年「效果·未启用 / 运行·待启动」，"
        "全页没有启动入口。外审**改前改后都 3/3 全票判「高」**，"
        "措辞集中在「配完不知道怎么让它在 CS2 里生效」",
    ),
    Revert(
        "RN", "首页开关卡又变回「写了没人读」",
        "gui_widget.py",
        "        switch_id = self._switch_id_by_config_key.get(config_key)",
        '        switch_id = getattr(self, "_switch_id_by_config_key", {}).get(config_key)',
        "tests/test_flash_viewmodel_truth.py::"
        "test_the_home_switch_card_is_actually_readable_from_elsewhere",
        "RN-089：`self.switches` 原本 **1 处 Store、1 处下标赋值、0 个真读者**（AST 实测）。"
        "⭐ 这个断点模拟的不是删掉读，而是把读写成 `getattr(self, ..., {})` —— "
        "**防御性 getattr 会把读操作变成字符串，AST 判据看不见它**，"
        "「有没有真读者」这条判据就退化成查子串（RN-073 那条假绿的写法）",
    ),
    Revert(
        "RN", "视角预设又被推到折叠线以下",
        "pages/viewmodel_page.py",
        "        self._viewmodel_right_column_layout.addWidget(presets_frame)",
        "        scroll_layout.addWidget(presets_frame)",
        "tests/test_flash_viewmodel_truth.py::"
        "test_viewmodel_presets_are_on_the_first_screen",
        "RN-083：右列只有一张卡、自 y≈450 起整列空白，而这一页**最核心的东西**"
        "（5 组预设 + 每组 FOV/XYZ 编辑入口）掉到首屏之外。"
        "外审 3/3 判「高」：「作为『局内视角设置』页却完全找不到 FOV/XYZ 与预设编辑入口」",
    ),
    Revert(
        "RN", "同一个保存动作又有两个名字",
        "pages/viewmodel_page.py",
        '        save_btn = QPushButton("保存到CFG")',
        '        save_btn = QPushButton("保存设置到CFG")',
        "tests/test_flash_viewmodel_truth.py::test_the_two_save_buttons_have_the_same_name",
        "RN-078：卡内和底栏是**同一个动作**，两个名字会让人以为是两件事",
    ),
    Revert(
        "RN", "又用「左侧」给导航指路",
        "pages/flash_page.py",
        "被闪的时候，用你自己的颜色、图片和音效替换游戏默认的闪白。还没启用的话，点一下「启用自定闪光」就能开。",
        "要生效得先在左侧「基础设置」页的「功能开关」里打开「自定闪光」。",
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_no_screen_direction_words_in_user_facing_copy",
        "RN-081：**这就是我修 RN-075 时自己造出来的那条「高」**。"
        "紧凑档 860×640 没有侧栏（导航收成左上角一个 ⋮ 菜单），"
        "「左侧「基础设置」页」在那一档是事实错误。"
        "外审 **3/3 × 多张紧凑图**判「高」，一发直接写「方位误写为『左侧』」。"
        "⇒ 这条是「改完复跑」逮住的第四轮，判据一条都覆盖不到",
    ),
    Revert(
        "RN", "卡片副标题又用「压成一张概况卡」这种说法",
        "pages/flash_page.py",
        "当前这一套配置的摘要：颜色、媒体和预览状态。",
        "把首屏基础观感、媒体搭配和预览状态压成一张概况卡，调完背景后不用再往下找重点信息。",
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_no_layout_self_talk_in_any_card_subtitle",
        "RN-077：这一条**词表和模板一条都没匹上**（动词是「压成」，不在表里），"
        "是外审复跑 3/3 × 多张图报出来的。"
        "⇒ 禁用词表不可能穷尽这一类：判据是拦回归的棘轮，发现通道是外审看图",
    ),
    Revert(
        "RN", "帮助面板又点名一个不存在的页签",
        "ui_help_panel.py",
        "2. 回到本页「基础设置」页签调整闪光颜色、透明度和过渡方式",
        "2. 在「基础」选项卡调整闪光颜色、透明度和过渡方式",
        "tests/test_flash_viewmodel_truth.py::test_copy_only_names_tabs_that_exist",
        "RN-075/RN-056：`flash` 页**没有**叫「基础」的页签（它叫「基础设置」）。"
        "这一条是 RN-075 那条判据的**第一版规则跑错时顺带逮到的** —— "
        "规则错了，但它看的地方对",
    ),
    Revert(
        "RN", "viewmodel 又建一个建出来就 hide 的 summary_label",
        "tests/test_no_invisible_summary_label.py",
        "MAX_REMAINING = 17",
        "MAX_REMAINING = 20",
        "tests/test_no_invisible_summary_label.py::"
        "test_ratchet_is_tightened_when_pages_are_cleaned",
        "RN-009：棘轮清了两页（viewmodel + flash）就必须收紧到 18。"
        "**棘轮不收紧等于没有棘轮** —— 松着的两格会把下一次回归静默吃掉",
    ),
    # ==================================== 2026-08-18 关档自查补的两条旧账
    # 66 条已结项逐条对回退验证，查出两条「改了产品代码却没有任何东西钉住」。
    # 两条都是 M1/M2 期间关的档 —— **关档不等于有人看着**。
    Revert(
        "RN", "改一次设置又把状态区渲染两遍",
        "pages/screen_effects_page.py",
        "        self._sync_enabled_state()\n\n    def _preview_normal(self):",
        "        self._sync_enabled_state()\n        self._sync_status_strip()\n\n"
        "    def _preview_normal(self):",
        "tests/test_settings_change_renders_once.py::"
        "test_toggling_a_setting_renders_the_status_strip_exactly_once",
        "RN-010：`_sync_enabled_state()` 末尾自己就会调 `_sync_status_strip()`。"
        "⭐ 这个断点模拟的是**回潮**：在 `_on_setting_changed` 里补一句"
        "「改完刷新一下状态」是再自然不过的念头，而重复调用从调用点上完全看不出来。"
        "⇒ **A 堆的清理不留判据，等于没清**",
    ),
    Revert(
        "RN", "副标题又承诺按连杀数分开配",
        "pages/kill_sound_page.py",
        "一个风格里自带 1~5 连杀的不同音效。",
        "可以按武器类别和连杀数分开配。",
        "tests/test_copy_promises_only_real_config_dimensions.py::"
        "test_no_page_promises_a_per_streak_configuration",
        "RN-042：配置里只有 weapon → {enabled, style}，**没有连杀这个维度**；"
        "连杀档位是风格目录内部按 1..5 命名的文件，用户选不了。"
        "外审两发独立点出「提示可按连杀数分配，但界面上完全找不到入口」",
    ),
    # ================================== 2026-08-18 发版前置：RN-003 与冒烟挑错对象
    Revert(
        "RN", "击杀图标链路又不在打包关键模块清单里",
        "build_tools/build_release.py",
        '    "kill_icon_overlay",\n    "kill_icon_player",',
        '    # (removed)',
        "tests/test_release_critical_modules.py::test_the_kill_icon_chain_is_registered",
        "RN-003：这份清单从 2.1.3 起没动过，而 2.2.4 最大的新功能整条链路一个模块都不在册。"
        "真漏了的话打包照样成功、安装包照样出得来，**用户装上之后那个功能是死的**，"
        "发布链路全程不报一声",
    ),
    Revert(
        "RN", "侧栏对齐又只往上退（项高不齐时会切掉一整项）",
        "gui_widget.py",
        "        targets.sort(key=lambda t: abs(t - current))   # 就近优先",
        "        targets = targets[:1]   # 只往上退",
        "tests/test_nav_snap_picks_the_nearest_boundary.py::"
        "test_it_picks_the_nearer_boundary_not_always_the_one_above",
        "RN-100：**这条缺陷是在本仓库发现的，上游一直是绿的** —— 那边项高恰好统一 "
        "43px，滚动值天然落在边界上，「只往上退」这条路根本没走过。本仓库项高是 "
        "42/43/47 混着的，滚动值偏离边界 4px，只往上退的唯一候选要跳 38px、"
        "当前项被挤出去 ⇒ 撤销 ⇒ 顶上那一项 40px 里被切掉 38，14 个页面中招。"
        "⭐ 一个只在「恰好整齐」时正确的算法，在它正确的那个环境里是看不出来的",
    ),
    Revert(
        "RN", "两个产品又会永久互相抢 autoexec 最后一位",
        "core/crosshair_reset.py",
        '    if MOVED_MARK in (autoexec_text or ""):\n'
        '        return autoexec_text        # 已经挪过一次，不参与抢位（RN-099）',
        '    pass',
        "tests/test_autoexec_keeps_us_last.py::"
        "test_we_only_reorder_once_so_two_products_do_not_fight",
        "RN-099：本项目和上游产品跑的是同一份代码，两边都会把自己挪到最后，"
        "用户机器上的 autoexec 每启动一次被翻一次 —— 2026-08-19 实测撞到，"
        "把前一天刚修好的准星跟随又覆盖回去了。"
        "⭐ RN-095 只修了一半：alias 名字空间共用认了，"
        "**「抢最后一位」这个策略也被共用了**没认",
    ),
    Revert(
        "RN", "写 CFG 失败后页面又显示「已保存」",
        "pages/hud_color_page.py",
        "            config.save_config()\n\n"
        "            if not config.csgo_dir:",
        "            config.save_config()\n"
        "            self._set_dirty(False)\n\n"
        "            if not config.csgo_dir:",
        "tests/test_page_hud_color_baseline.py::"
        "test_a_failed_save_leaves_the_page_dirty",
        "RN-130：把脏标志的清除挪回写 CFG **之前**（原状）。写 CFG 失败时标志照样被清 —— "
        "用户看到报错框、关掉，页面却显示「没有未保存修改」，切页不再拦他。"
        "**软件配置存住了、游戏里的 CFG 没写成，而界面上没有任何痕迹说明这件事。**"
        "⭐ 「我干完了」这个标志必须置在动作**成功之后**，不是动作开始时",
    ),
    Revert(
        "RN", "风格库空着时又不显示引导",
        "widgets/kill_icon_style_strip.py",
        "        self._order = None",
        "        self._order = []",
        "tests/test_kill_icon_empty_state_ki8.py::"
        "test_a_brand_new_strip_that_gets_no_styles_shows_the_hint",
        "RN-124：`set_styles` 开头有一句「列表没变就早退」，而 `_order` 的初始值写成 "
        "`[]` 时，**第一次拿到空列表也算「没变」** —— 于是「还没有任何风格，点右边的"
        "「＋ 导入」装一套。」这句写好的引导永远走不到。全新用户看到的是一片纯黑。"
        "⭐ 这条引导唯一存在的理由，正好是它唯一到不了的那个分支",
    ),
    Revert(
        "RN", "准心页又把参数排到样式前面",
        "pages/crosshair_page.py",
        "        controls_column_layout.addWidget(style_color_grid)\n"
        "        controls_column_layout.addWidget(size_thickness_card)",
        "        controls_column_layout.addWidget(size_thickness_card)\n"
        "        controls_column_layout.addWidget(style_color_grid)",
        "tests/test_crosshair_page_layout_and_preview.py::"
        "test_style_and_color_come_before_the_numeric_parameters",
        "RN-115：这一页最核心的选择「准心样式」原本在首屏之外（完整档视口 546px、"
        "样式卡从 y=630 起），玩家进来只看得到滑块。外审两档 10 发都指着这块，"
        "但措辞全是「被截断/被遮挡」—— ⭐ 拿它的位置当线索，别拿它的机制当结论",
    ),
    Revert(
        "RN", "预览示意又变成常驻定时器",
        "pages/crosshair_page.py",
        "        if self._burst_elapsed_ms >= self.PREVIEW_BURST_MS:",
        "        if False:",
        "tests/test_crosshair_page_layout_and_preview.py::"
        "test_the_burst_stops_by_itself_when_time_is_up",
        "RN-116：用户裁定明确否决了常驻定时器（只要 1.5 秒示意）。少了这个出口它就一直跑，"
        "而「一直跑」在界面上和「播得很流畅」长得一模一样，只有判据看得出来",
    ),
    Revert(
        "RN", "死方法扫描的语料又缩回「只看本文件」",
        "tests/test_no_dead_private_methods_in_pages.py",
        "            related = descendants(cls.name) | ancestors(cls.name)",
        "            related = descendants(cls.name)",
        "tests/test_no_dead_private_methods_in_pages.py::"
        "test_a_hook_overridden_in_a_subclass_is_not_dead",
        "RN-103：调用面缩到本文件时，`SoundPageBase` 那 5 个被 4 个子类页调着的方法"
        "会被整批判成死码 —— 其中 `_build_sound_page_ui` **91 行**。"
        "⭐ 断点故意瞄准「语料/调用面」而不是「计数对不对」：**"
        "「没人用」这个结论的可信度，等于那个「所有人」的定义有多准**",
    ),
    Revert(
        "RN", "冒烟自动挑产物又会挑到安装包",
        "scripts/smoke_packaged.py",
        '                 and c.parent.name.lower() != "installer"',
        '                 and True',
        "tests/test_smoke_picks_the_app_not_the_installer.py::"
        "test_the_installer_directory_is_excluded",
        "RN-097：安装包在应用产物**之后**生成，按 mtime 永远最新 ⇒ 冒烟启动的是安装程序，"
        "等 UAC 超时、日志 0 字符、7 条判据一起红。"
        "⭐ **一道门禁测错对象比它不存在更坏**：它给出一个看着很严重、"
        "却和被测对象毫无关系的结论。而且它真的在用户机器上拉起了安装器",
    ),
    # ================================== 2026-08-18 用户实战报回来的三条
    Revert(
        "RN", "击杀又被记在「此刻举着的枪」头上",
        "gsi_handler_kills.py",
        "                and current_time - self.last_confirmed_fire_weapon_time\n"
        "                <= self.kill_weapon_switch_grace",
        "                and False",
        "tests/test_kill_weapon_survives_a_quick_switch.py::"
        "test_a_kill_after_quick_switching_still_belongs_to_the_gun_that_fired",
        "RN-096：AWP 打死人之后顺手切副武器（狙击手标准操作），"
        "而 round_kills 那一包晚一拍才到 —— 弹药变化落在上一包，本帧推断不出开火武器，"
        "就地取材记成了「举着的五七」。⭐ 用户 8 次 AWP 击杀全被记错，"
        "而我第一轮拿日志里那个 `weapon=` 字段当证据做统计 —— "
        "**那是软件自己解析出的结论，不是观测事实**，等于循环论证",
    ),
    Revert(
        "RN", "刀杀又被记成上一把枪",
        "gsi_handler_kills.py",
        "                not self._melee_config_key(self.frame_active_weapon)\n"
        "                and self.last_confirmed_fire_weapon",
        "                self.last_confirmed_fire_weapon",
        "tests/test_kill_weapon_survives_a_quick_switch.py::"
        "test_a_knife_kill_is_still_a_knife_kill",
        "RN-096 的副作用防线：近战没有弹夹、永远推断不出开火，"
        "一刀切会把刀杀全部记成上一把枪 ⇒ **RN-016「近战配了没反应」立刻复活**。"
        "修一条缺陷时先量会不会造出另一条",
    ),
    Revert(
        "RN", "击杀图标又被关回「音效播成功了才出」",
        "gsi_handler_kills.py",
        "        iconed = False\n"
        "        if self.image_player and config.kill_icon_enabled:",
        "        iconed = False\n"
        "        if played and self.image_player and config.kill_icon_enabled:",
        "tests/test_kill_feedback_channels_are_independent.py::"
        "test_icon_still_fires_when_the_weapon_has_no_kill_sound",
        "RN-094：用户死斗实录 112 次击杀 8 次无反馈，**8 次全是 weapon_fiveseven**"
        "（那把枪配置里是「不启用」）。图标有自己的开关和素材，"
        "却被「这把枪的击杀音效有没有播出」暗中门控 ⇒ 三个功能同时「坏」，"
        "看起来像总线故障。用户的处理是把图标总开关关掉",
    ),
    Revert(
        "RN", "exec cs2customizer.cfg 又不排在最后",
        "core/crosshair_reset.py",
        "    if our_cfg not in order or order[-1] == our_cfg:\n        return autoexec_text",
        "    if our_cfg not in order:\n        return autoexec_text",
        "tests/test_autoexec_keeps_us_last.py::test_rewriting_is_idempotent",
        "RN-095：这个断点模拟的不是「没挪」，是**挪得太勤** —— "
        "去掉「已经在最后就别动」这个判断，每次启动都会重写用户自己的 autoexec.cfg。"
        "⚠ 真缺陷（排在别人前面被覆盖）由同文件另外两条判据钉住",
    ),
    Revert(
        "RN", "冲突检测只认主 alias、漏掉老 HUD 那个",
        "core/crosshair_reset.py",
        "OWNED_ALIASES = (PRIMARY_ALIAS, SECONDARY_ALIAS, *LEGACY_ALIASES)",
        "OWNED_ALIASES = (PRIMARY_ALIAS,)",
        "tests/test_autoexec_keeps_us_last.py::test_we_own_exactly_the_aliases_we_emit",
        "RN-095：开源版**同样**定义了 `fp_hud_mouse1`。只查主 alias 的话，"
        "「主的没被抢、老的被抢了」这种局面会被判成没冲突 —— 又一次分母",
    ),
    Revert(
        "RN", "焦点巡检那道门又拿退出码当裁定",
        ".github/workflows/ci.yml",
        "          python scripts/tab_order_audit.py --verbose 2>&1 | Tee-Object -FilePath focus.log\n"
        "          ./.github/verdict.ps1 -Name focus -LogPath focus.log",
        "          python scripts/tab_order_audit.py --verbose",
        "tests/test_ci_gates_read_the_verdict_line.py::"
        "test_every_blocking_audit_step_reads_the_verdict_line",
        "RN-092：这正是 2026-08-17 `41217bf` 那次**假红**的原文。"
        "焦点巡检 28 页全 0、打印「通过 / RESULT rc=0」，0.66 秒后进程退出码 1、无 traceback。"
        "⭐ RN-068 早就把可信通道建好了，**却没人去读** —— 半截修复的另一种形态：通道有了、消费者没换",
    ),
    Revert(
        "RN", "CI 要的裁定名和脚本打的对不上",
        ".github/workflows/ci.yml",
        "./.github/verdict.ps1 -Name contrast -LogPath contrast.log",
        "./.github/verdict.ps1 -Name contrastt -LogPath contrast.log",
        "tests/test_ci_gates_read_the_verdict_line.py::"
        "test_the_verdict_name_matches_what_the_script_delivers",
        "RN-092：名字对不上**只会表现为「这道门一直红」**，"
        "很容易被当成产品缺陷去查一整轮 —— 和 RN-068 当初的症状一模一样",
    ),
    Revert(
        "RN", "两道排版审计共用一个日志名",
        ".github/workflows/ci.yml",
        "-FilePath layout_compact.log\n"
        "          ./.github/verdict.ps1 -Name layout -LogPath layout_compact.log",
        "-FilePath layout_full.log\n"
        "          ./.github/verdict.ps1 -Name layout -LogPath layout_full.log",
        "tests/test_ci_gates_read_the_verdict_line.py::"
        "test_each_audit_step_writes_its_own_log_file",
        "RN-092：共用日志名的话，紧凑档那道门会读到完整档留下的裁定 —— "
        "**紧凑档从此永远绿**。这是我加这道门时差一点犯的错",
    ),
    Revert(
        "RN", "副标题抽取器又漏掉 PAGE_LEAD 这条通路",
        "tests/test_no_layout_self_talk_sitewide.py",
        '                        and isinstance(node.value.value, str) and node.value.value):\n'
        '                    out.append((node.value.lineno, node.value.value, "PAGE_LEAD"))',
        '                        and isinstance(node.value.value, str) and node.value.value):\n'
        '                    pass',
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_the_extractor_actually_sees_the_page_lead_constants",
        "RN-091：全站副标题抽取器原来只认「调用的实参」，"
        "音效家族 4 页的页头文案是类常量 `PAGE_LEAD`（经基类转递），"
        "**`kill_sound_page.py` 实测抽到 0 条**，而总量守卫（≥60）一直是绿的。"
        "⇒ 每加一条通路就要配一条只盯它自己的守卫，否则总量会把它盖住",
    ),
    # ======================================== 开源版专属：品牌 / 素材 / 文档
    # ⚠ 这三组上游没有，只存在于开源版：BRAND 验「旧品牌名回流时判据变不变红」，
    # ASSET 验「素材混进仓库」，DOC 验开源治理文档。
    # **同步时最容易被整组丢掉** —— 2026-08-19 那次重锚补丁就丢了全部 22 条，
    # 是 `test_no_legacy_brand`「白名单条目里已经没有旧名了」那条反过来逮到的。
    Revert(
        'BRAND', '数据目录名漏改（config.APP_NAME 退回旧品牌）',
        'config.py',
        'APP_NAME = "CS2Customizer"',
        'APP_NAME = "FanTool"',
        'tests/test_no_legacy_brand.py::test_runtime_app_name_is_not_legacy',
        '开源版与闭源版共用 %LOCALAPPDATA%；两边配置键集合不同，'
        'save_config 写的是显式白名单 dict，后写的一方会静默删掉对方独有的键',
    ),
    Revert(
        'BRAND', '两处 APP_NAME 只改了一处（配置目录与日志目录被拆到两个文件夹）',
        'core/utils/logger.py',
        'APP_NAME = "CS2Customizer"',
        'APP_NAME = "FanTool"',
        'tests/test_no_legacy_brand.py::test_runtime_app_name_is_not_legacy',
        '日志写进 A 目录、配置写进 B 目录；用户按提示去删配置目录清不掉日志，排障时也找不到日志',
    ),
    Revert(
        'BRAND', '单实例锁文件名漏改',
        'core/single_instance.py',
        'LOCK_FILENAME = "CS2Customizer_single_instance.lock"',
        'LOCK_FILENAME = "FanTool_single_instance.lock"',
        'tests/test_no_legacy_brand.py::test_single_instance_and_autostart_keys_are_not_legacy',
        '闭源版在跑时开源版会以为"自己已经在运行"而直接退出——两个产品变成互斥的',
    ),
    Revert(
        'BRAND', '开机自启注册表值名漏改',
        'core/utils/autostart.py',
        '_VALUE_NAME = "CS2Customizer"',
        '_VALUE_NAME = "FanTool帆派助手"',
        'tests/test_no_legacy_brand.py::test_single_instance_and_autostart_keys_are_not_legacy',
        '两者的开机自启项互相覆盖，用户只能自启其中一个，且不知道是谁把谁顶掉了',
    ),
    Revert(
        'BRAND', '写进用户游戏目录的 cfg 文件名漏改',
        'core/cfg_compiler.py',
        '"cs2customizer.cfg")',
        '"fanpai.cfg")',
        'tests/test_no_legacy_brand.py::test_generated_game_cfg_names_are_not_legacy',
        '旧品牌名长期躺在用户的 CS2 目录里；两个产品还会抢同一个 cfg 文件互相覆盖',
    ),
    Revert(
        'BRAND', '白名单腐烂：豁免条目里已经没有旧名了却还挂着',
        'core/presets/share_file.py',
        # 注意要连注释一起换掉：只删常量的话文件里还留着注释中的旧扩展名，
        # 判据照绿——那样这个断点自己就是假的。
        '#: 前身（闭源版）导出的分享文件用 `.fanpai`。**只在打开对话框的过滤器里认它**——\n'
        '#: 容器格式与安检逻辑完全一致，没有理由让用户手工改扩展名才能导入；\n'
        '#: 但导出一律写新扩展名，不再产生旧后缀的文件。\n'
        'LEGACY_SHARE_EXTS = (".fanpai",)',
        'LEGACY_SHARE_EXTS = ()',
        'tests/test_no_legacy_brand.py::test_allowlist_entries_still_exist',
        '白名单变成只增不减的免检清单——文件早就不含旧名，条目还在，'
        '下次有人往这个文件里加东西就免检了',
    ),
    Revert(
        'BRAND', '旧品牌回流到白名单之外的文件（文本判据本体）',
        'CONTRIBUTING.md',
        '本仓库是闭源商业版的**功能子集**',
        '本仓库是帆派助手的**功能子集**',
        'tests/test_no_legacy_brand.py::test_no_legacy_brand_outside_allowlist',
        '前面几条行为判据只看那几个常量；旧名从文档、注释、界面文案回流时得靠这条兜底',
    ),
    Revert(
        'DOC', 'README 引用了不存在的图片（首页渲染成破图标）',
        'README.md',
        '![CS2 Customizer 主界面](docs/images/home.png)',
        '![CS2 Customizer 主界面](docs/images/does-not-exist.png)',
        'tests/test_version_consistency.py::test_readme_images_all_exist',
        '真实发生过：开源化时「界面预览」引用了 docs/images/ 下三个 gif，'
        '而那个目录压根不存在，GitHub 首页就是三个破图标',
    ),
    Revert(
        'DOC', '英文 README 丢了回中文版的链接（语言切换变单向）',
        'README.en.md',
        '[简体中文](README.md) · **English**',
        '**English**',
        'tests/test_version_consistency.py::test_readme_language_switch_is_bidirectional',
        '单向链接是双语化最常见的半成品：读者跳到英文版就出不来了',
    ),
    Revert(
        'DOC', '官网地址漏进了会发网络请求的模块',
        'service_urls.py',
        'TELEMETRY_BASE_URL = ""',
        'TELEMETRY_BASE_URL = "https://fantool.online"',
        'tests/test_no_legacy_brand.py::test_official_site_url_only_in_readme',
        '这正是「默认不连任何服务器」被破坏的样子：每个 fork 出去的客户端都开始'
        '打原作者的服务器，带宽是他的、崩溃堆栈里的用户数据责任也是他的，'
        '而那些用户已经不是他的用户了',
    ),
    Revert(
        'DOC', '中文 README 的一级标题被改掉',
        'README.md',
        '# CS2 Customizer\n',
        '# Some Other Project\n',
        'tests/test_version_consistency.py::test_readme_title_matches',
        '落地页第一眼看到的名字错了。这条判据的落点随排版改过两次'
        '（首行 → 开头 10 行内找一级标题），断点跟着落在标题行本身',
    ),
    Revert(
        'ASSET', '生成器与已入库的闪屏图脱钩（图上还是旧产品名）',
        'build_tools/make_installer_assets.py',
        'SPLASH_TITLE = "CS2 Customizer"',
        'SPLASH_TITLE = "帆派助手"',
        'tests/test_brand_assets.py::test_committed_brand_images_are_not_stale',
        '真实发生过：入库的 splash.png 与闭源版 md5 完全相同，图上印着旧产品名，'
        '而代码/文档/注册表键全已改名——用户第一眼看到的就是那张图',
    ),
    Revert(
        'ASSET', '社交预览图与生成器脱钩（那一腿是不是真的在比）',
        'scripts/make_social_preview.py',
        '"给 CS2 玩家的本地个性化工具"',
        '"给 CS2 玩家的本地个性化助手"',
        'tests/test_brand_assets.py::test_committed_brand_images_are_not_stale',
        '上一条断点只动了 make_installer_assets。这条专门证明社交预览图那一腿'
        '也在真比——一张图加进清单却没真比对，比不加更糟',
    ),
    Revert(
        'ASSET', '向导大图标题字号写死（改名后左右各裁掉一个字母）',
        'build_tools/make_installer_assets.py',
        '_fit_font(WIZARD_TITLE, WIZARD_TITLE_BOX, WIZARD_TITLE_SIZE, bold=True)',
        '_font(WIZARD_TITLE_SIZE, bold=True)',
        'tests/test_brand_assets.py::test_wizard_large_text_fits_inside_safe_boxes',
        '真实发生过：字号是照 4 个汉字的旧名调的，换成 14 个拉丁字符后同字号'
        '宽了一倍多，标题两端被裁，生成脚本照样退出码 0',
    ),
    Revert(
        'ASSET', '安全框自己越出画布（量具没校准）',
        'build_tools/make_installer_assets.py',
        'WIZARD_URL_BOX = (36, 554, WIZARD_SIZE[0] - 36, 582)',
        'WIZARD_URL_BOX = (36, 554, WIZARD_SIZE[0] + 200, 582)',
        'tests/test_brand_assets.py::test_wizard_large_safe_boxes_are_inside_the_canvas',
        '"文字在框内"这条判据的量具是框本身。框越出画布时，文字明明被裁掉了'
        '那条判据还会照样通过——假绿',
    ),
    Revert(
        'ASSET', '标题安全框挪到没有字的位置（空文案也能骗过包围盒判据）',
        'build_tools/make_installer_assets.py',
        'WIZARD_TITLE_BOX = (18, 380, WIZARD_SIZE[0] - 18, 436)',
        'WIZARD_TITLE_BOX = (18, 120, WIZARD_SIZE[0] - 18, 176)',
        'tests/test_brand_assets.py::test_wizard_large_actually_has_ink_where_the_text_should_be',
        '只验"包围盒落在框内"的话，空字符串的包围盒必然在框内——这条要求图上'
        '真的有亮色像素，堵的是"判据绿了但图是空的"',
    ),
    Revert(
        'ASSET', '截图前那道"沙箱路径不含用户名"的门被拿掉',
        'scripts/capture_readme_shots.py',
        'hits = [t for t in personal_tokens() if t.lower() in text.lower()]',
        'hits = []',
        'tests/test_brand_assets.py::test_screenshot_guard_rejects_username_in_sandbox_path',
        '真实发生过：沙箱默认落在 %TEMP%（=C:\\Users\\<用户名>\\...），高级设置页把'
        'CS2 目录原样显示出来，advanced.png 里印着真实用户名并推上了公开仓库——'
        '而本项目的日志脱敏器专门干掉的就是这个串',
    ),
    Revert(
        'ASSET', '图标与生成器脱钩',
        'build_tools/make_app_icon.py',
        'ring_r = big * 0.31',
        'ring_r = big * 0.26',
        'tests/test_brand_assets.py::test_committed_icons_are_not_stale',
        '位图一旦入库就会和生成器脱钩，而脱钩是静默的——这正是启动闪屏印着'
        '旧产品名一路全绿到公开前的原因',
    ),
    Revert(
        'ASSET', '图标退回单一尺寸帧',
        'build_tools/make_app_icon.py',
        'SIZES = (16, 24, 32, 48, 64, 128, 256)',
        'SIZES = (64,)',
        'tests/test_brand_assets.py::test_icon_has_every_size_windows_asks_for',
        '原来那张图标就是**单帧 64×64**：16px 的资源管理器列表和任务栏全靠系统'
        '缩放，发虚。少一档不报错，只在那个场景里难看',
    ),
    Revert(
        'ASSET', '图标帧写成 PNG（Inno Setup 吃不下）',
        'build_tools/make_app_icon.py',
        '        bitmap_format="bmp",\n',
        '',
        'tests/test_brand_assets.py::test_icon_frames_are_bmp_not_png',
        '真实发生过：项目根 icon.ico 是 PNG 帧，Inno 不接受，于是有人手工重铸了'
        '一份 setup_icon.ico——一个没人记得的手工步骤，下一个改图标的人会踩回去',
    ),
    Revert(
        'ASSET', '小尺寸不再单独画（16px 糊成一团）',
        'build_tools/make_app_icon.py',
        'SIMPLIFY_BELOW = 40',
        'SIMPLIFY_BELOW = 0',
        'tests/test_brand_assets.py::test_smallest_icon_frame_is_actually_legible',
        '实测过：把大图几何原样缩到 16px，准星刻线正好顶到外环，三者糊成一个'
        '实心疙瘩——文件正常、尺寸齐全、肉眼认不出是什么',
    ),
    Revert(
        'ASSET', '旧品牌 AI 美术底图被提交进仓库',
        'build_tools/make_installer_assets.py',
        'SPLASH_ART_SOURCE = OUT / "splash_art_ai.png"',
        'SPLASH_ART_SOURCE = OUT / "setup_icon.ico"',
        'tests/test_brand_assets.py::test_legacy_splash_art_is_not_tracked',
        '把常量指向一个确实已入库的文件，等价于"那张美术底图被 git add 了"。'
        '它既是旧品牌残留，又是来源不清的 AI 素材，公开仓库两头都不该有',
    ),
]


def run_pytest(selector: str) -> bool:
    """跑一条判据，返回 True=绿。"""
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", selector, "-q", "--no-header",
         "-p", "no:cacheprovider"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    return proc.returncode == 0


def selector_is_collectable(selector: str) -> bool:
    """判据名还存在吗？只收集不执行，快且没有副作用。

    判据被改名/删掉之后，本文件里的 nodeid 就成了空指针。pytest 对
    "collect 不到" 的退出码是 5（`-q` 下打印 `no tests collected`），
    和"跑了但红了"的 1 是两码事——可基线检查只看 `returncode == 0`，
    于是一次改名会被报成「基线就不绿」，**整台回退验证直接停摆**，
    而真正的原因（这条断点已经空转很久了）一个字都没提。
    2026-08-16 就是这么被卡住的：`test_preview_handles_every_user_style`
    早在 08-15 改成了 `test_preview_has_no_private_drawing_branches`。
    """
    env = dict(os.environ)
    env["PYTHONIOENCODING"] = "utf-8"
    proc = subprocess.run(
        [sys.executable, "-m", "pytest", selector, "--collect-only", "-q",
         "--no-header", "-p", "no:cacheprovider"],
        cwd=str(ROOT), env=env, capture_output=True, text=True,
        encoding="utf-8", errors="replace", timeout=300,
    )
    return proc.returncode == 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑某一组（R9-A / R9-B / R9-C / R9-D）")
    ap.add_argument("--stale-only", action="store_true",
                    help="只做失效体检（锚点是否还在、判据名是否还在），不改任何文件、不跑用例")
    args = ap.parse_args()

    items = [r for r in REVERTS
             if not args.only or r.group == args.only or args.only in r.name]

    # ---- RN-093：先收拾上一轮没跑完留下的烂摊子 ----
    # ⚠ 必须在失效体检**之前**做：留在树上的改坏文件会让锚点变成"出现 0 次"，
    # 于是一条好端端的断点被报成"已失效"，误诊套误诊。
    leftovers = restore_from_disk()
    if leftovers:
        print("⚠ 上一轮回退验证没跑完（多半是被 timeout / Ctrl-C 杀掉的），"
              f"以下 {len(leftovers)} 个文件还留着改坏的内容，已自动还原：")
        for rel in leftovers:
            print(f"   - {rel}")
        print()
    clear_snapshot()

    # ---- 失效体检：断点会随产品代码一起腐烂，先把腐烂的挑出来单独报 ----
    # 放在基线之前：一条改了名的判据不该让另外 90 多条断点跟着停摆。
    print("=" * 78)
    print("失效体检：锚点还在不在、判据名还在不在")
    print("=" * 78)
    stale = []
    for r in items:
        if not r.path.exists():
            stale.append((r, "产品文件已不存在"))
            continue
        n = r.path.read_text(encoding="utf-8").count(r.old)
        if n != 1:
            stale.append((r, f"锚点在源码里出现 {n} 次（要求恰好 1 次）"))
    checked = {}
    for r in items:
        if any(r is s for s, _ in stale):
            continue
        if r.selector not in checked:
            checked[r.selector] = selector_is_collectable(r.selector)
        if not checked[r.selector]:
            stale.append((r, f"判据名已不存在：{r.selector}"))
    if stale:
        print(f"⚠ {len(stale)}/{len(items)} 条断点已失效——它们**一直在空转**，"
              f"以为有人看着的地方其实没人看着：")
        for r, why in stale:
            print(f"   - {r.group} {r.name}：{why}")
        print("   本轮跳过这些，其余照跑。修法：把锚点/判据名改到现在的代码上。\n")
    else:
        print(f"✅ {len(items)} 条断点的锚点与判据名都还对得上\n")
    stale_ids = {id(r) for r, _ in stale}
    items = [r for r in items if id(r) not in stale_ids]
    if args.stale_only:
        return 3 if stale else 0
    if not items:
        print("没有可跑的断点。")
        return 3

    # 开跑前给所有涉及的文件拍快照，收尾无论如何都还原。
    # RN-093：快照**同时落盘**，并装上信号处理器 —— `finally` 挡不住 SIGTERM。
    touched = {r.path for r in items}
    snapshot = {p: p.read_bytes() for p in touched}
    save_snapshot(snapshot)
    _install_emergency_restore()

    results = []
    try:
        # 先确认全绿基线——基线本来就红的话，后面的"变红"说明不了任何事
        print("=" * 78)
        print("基线：改坏之前，所有相关判据必须是绿的")
        print("=" * 78)
        selectors = sorted({r.selector for r in items})
        baseline_bad = [s for s in selectors if not run_pytest(s)]
        if baseline_bad:
            print("❌ 基线就不绿，回退验证无意义：")
            for s in baseline_bad:
                print(f"   {s}")
            return 2
        print(f"✅ {len(selectors)} 条判据基线全绿\n")

        for i, r in enumerate(items, 1):
            src = r.path.read_text(encoding="utf-8")
            count = src.count(r.old)
            if count != 1:
                results.append((r, None, f"锚点出现 {count} 次，跳过"))
                print(f"[{i}/{len(items)}] {r.group} {r.name} —— ⚠ 锚点出现 {count} 次，跳过")
                continue

            r.path.write_text(src.replace(r.old, r.new, 1), encoding="utf-8")
            try:
                green = run_pytest(r.selector)
            finally:
                r.path.write_bytes(snapshot[r.path])

            ok = not green          # 期望：改坏后判据变红
            results.append((r, ok, "变红 ✅" if ok else "**仍然绿** ❌"))
            mark = "✅" if ok else "❌"
            print(f"[{i}/{len(items)}] {mark} {r.group} {r.name}")
            print(f"        模拟缺陷：{r.defect}")
            if not ok:
                print(f"        ⚠ 判据没逮住！{r.selector}")
    finally:
        for p, data in snapshot.items():
            if p.read_bytes() != data:
                p.write_bytes(data)
        clear_snapshot()
        print("\n所有文件已还原至改动前状态。")

    print("\n" + "=" * 78)
    caught = sum(1 for _, ok, _ in results if ok is True)
    missed = [(r, note) for r, ok, note in results if ok is False]
    skipped = [(r, note) for r, ok, note in results if ok is None]
    print(f"回退验证：{caught}/{len(results)} 条判据成功逮住它要防的缺陷")
    if skipped:
        print(f"跳过 {len(skipped)} 条（锚点对不上，说明产品代码变了，得更新本文件）：")
        for r, note in skipped:
            print(f"  - {r.group} {r.name}：{note}")
    if stale:
        print(f"⚠ 另有 {len(stale)} 条断点已失效，本轮没跑（见开头的失效体检）")
    if missed:
        print(f"❌ {len(missed)} 条判据是**假绿**的：")
        for r, note in missed:
            print(f"  - {r.group} {r.name} → {r.selector}")
        return 1
    return 0 if not (skipped or stale) else 3


if __name__ == "__main__":
    raise SystemExit(main())

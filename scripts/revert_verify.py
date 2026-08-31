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
        "test_no_encoding_corruption_anywhere_in_the_repo",
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
        '点「测试」可以按连杀档位试听；总开关管它开不开。"',   # ⚠ 2026-08-21 随 RN-163 改过文案
        '    PAGE_LEAD = "击杀音效页保持列表式效率，把分类切换和快速试听留在一屏里。"',
        "tests/test_page_copy_is_user_facing.py::test_page_copy_has_no_layout_jargon",
        "副标题讲的是界面怎么排而不是功能是什么，玩家读完不知道该干嘛"
        "——外审在 8 个页面上独立指出同一件事",
    ),
    Revert(
        "V", "文案又指向不存在的「首页」",
        "pages/kill_sound_page.py",
        # ⚠ 2026-08-21（RN-163）：总开关搬进本页，这句指路已删。锚点改到现在这句上。
        "再拨开总开关。",
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
        # ⚠ 锚点跟着棘轮走：M3-b 之后是 18，批 32 放宽分母（全等 → 后缀）
        # 并清掉 music 之后，完整产品是 19、**本仓库（子集，没有 account 页）是 18**。
        # ⚠⚠ 这个字面量上**钉了两条断点**（另一条在下面 viewmodel 那一组），
        # 而失效体检一次只报**还在失效**的那一条 —— 批 32 修了一条就以为修完了，
        # 下一轮全组跑才把另一条顶出来。
        # ⭐ **锚在同一个会变的数上的断点，要么一次全找出来，要么就会分两轮暴露。**
        "MAX_REMAINING = 18",
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
        '    PAGE_LEAD = "切换武器时播放你自己的音效。逐把枪选风格，点「测试」试听；总开关管它开不开。"',
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
        "RN", "共用提示又去点名某些页上没有的按钮",
        "pages/audio_status_badge.py",
        '        return "还没有素材：放入音频后点「刷新风格列表」就能用。"',
        '        return "还没有素材：放入音频后点「打开音频资源」就能用。"',
        "tests/test_gun_special_sound_truth.py::"
        "test_the_shared_hint_names_no_button_that_is_missing_on_some_page",
        "RN-056：七页共用这一句，而 `special_sound` 那颗按钮叫「打开当前资源」"
        "—— 写「打开音频资源」就是在指挥用户点一颗本页没有的按钮。"
        "⭐ **单一真相源不等于文案可以照搬。**\n"
        "⚠⚠ 这条断点 2026-08-22（RN-168）**重新指过**：原来它锚在 "
        "`resource_hint(health, open_label=...)` 上，而 RN-153 把那句提示改成"
        "不再点名按钮之后，那个参数就没有读者了 —— 断点变成假绿，"
        "顺带暴露出一个**活成纪念碑的死参数**（传进去、没人读、无人报错）。"
        "更要命的是它当时指的那条判据 `test_hint_only_names_buttons_that_exist` "
        "**本身就是半空转的**：它只扫「当前可见的 QLabel」，而这句提示在健康状态下"
        "是空串，压根不在页面上 —— 我把文案改成明确错误的名字，它照样绿。"
        "⭐⭐ **只看「碰巧可见的东西」的判据，看不见「只在特定状态下才出现的文案」**，"
        "而缺陷恰恰只在那个状态下现身。新判据自己把三种状态造出来",
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
        "test_sidebar_never_shows_a_half_cut_nav_item_at_either_edge",
        "RN-060：28 页里 **16 页**的侧栏顶部/底部各切掉 13~21px（项高 43px），"
        "用户看到残缺的导航文字。排版审计一直绿（滚动区露半行不算溢出），"
        "外审 8 发独立报出来 —— 而它只在导航列表靠后的页出现，"
        "那些页正是 RN-005 盲区里的四页",
    ),
    Revert(
        "RN", "字段标签又被无条件开成可折行",
        "ui_style_applier.py",
        "                widget.setWordWrap(not self._is_field_label(widget.text()))",
        "                widget.setWordWrap(True)",
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_field_labels_never_wrap_into_two_lines",
        "RN-191：紧凑档「主武器热键:」宽 69px、需 73px —— **差 4px 就断成两行**"
        "（「主武器热」/「键:」），magnifier 一页 4 个。"
        "⭐ 折行既不溢出也不截断，躲得过一切既有判据（RN-121 记过）。"
        "⭐⭐ 而 RN-121 当年**已经留了 opt-out**，可它是 opt-in 的 —— "
        "表单标签的调用方一个都没设。**一个「默认开、需要显式关」的行为，"
        "等于「绝大多数地方都开着」；opt-out 的存在不代表它被用上了**",
    ),
    Revert(
        "RN", "就地总开关的覆盖面又只按已合规的页算",
        "tests/test_master_switch_row.py",
        '    "music": "music_enabled",',
        "",
        "tests/test_master_switch_row.py::"
        "test_every_home_switch_has_a_page_that_hosts_it",
        "RN-189：首页 17 颗总开关里曾有 **8 颗**在它自己那一页上拨不到，"
        "而管这件事的两条判据都遍历 `EXPECTED_KEYS` —— 那是**已经装了开关的页**。"
        "⭐⭐ **一条只遍历「已合规对象」的判据，它的分母是由结论决定的**："
        "读起来是「这条规则在生效」，实际是「凡是符合的都符合」。"
        "分母现在取首页那张 `switch_configs`（首页真的画了几颗，就是几颗）",
    ),
    Revert(
        "RN", "magnifier 又把用户支去基础设置开总开关",
        "pages/magnifier_page.py",
        '            self, "magnifier_enabled", "开镜放大")',
        '            self, "magnifier_enabled_NOPE", "开镜放大")',
        "tests/test_master_switch_row.py::"
        "test_the_config_key_each_page_declares_really_exists_at_home",
        "RN-189：这一页的副标题**无条件**写「先去「基础设置」打开总开关」，"
        "而同屏徽章可能正写着「开关 · 已启用」—— RN-034 拖了很久的最后一笔。"
        "开关搬到本页之后那句话连「去哪儿」都不必提",
    ),
    Revert(
        "RN", "空库时又出现两颗紫按钮",
        "widgets/community_library.py",
        "        style_as_secondary_button(bar.primary_btn)",
        "        pass",
        "tests/test_empty_library_covers_every_page.py::"
        "test_the_empty_state_has_exactly_one_purple_button",
        "RN-186：引导卡那颗和底栏那颗同时是 `primaryButton`，外审 3/3 报"
        "「首步动作焦点冲突」「不知先点哪个」。⭐⭐ 本仓 RN-139 早就判过"
        "「**两颗紫的等于零颗**」并留了棘轮 —— 可那条只盯 `basic` 一页。"
        "**判据的页面范围就是它的分母**：一条只保 1/28 页的规则，"
        "读起来跟「这条规则在生效」一模一样",
    ),
    Revert(
        "RN", "空库底栏文案又开始描述版面",
        "widgets/community_library.py",
        # ⚠ RN-193 又改了一次这句话（去掉编号）。锚点跟着走。
        '            f"下载好的包放进资源目录（点「{keep_text}」），再点「{refresh_label}」。")',
        '            f"第 1 步在上面那张卡里。点「{keep_text}」放进资源目录。")',
        "tests/test_empty_library_points_at_the_community.py::"
        "test_the_empty_state_keeps_a_way_to_put_the_files_in",
        "RN-187：原文案写「第 1 步在上面那张卡里」，外审 3/3 判"
        "「用生硬文字打补丁」「视线上下割裂」。⭐ 编号本身就够了 —— "
        "写着「第 2 步」的人自然知道第 1 步在别处，不必再告诉他往哪儿看。"
        "⚠ 本仓有一条专门的 `test_no_layout_self_talk_sitewide`，**它没逮住这一句**",
    ),
    Revert(
        "RN", "紧凑档状态徽章又被压到画不出字",
        "pages/audio_status_badge.py",
        "        self._lock_in_chip_height()",
        "        pass",
        "tests/test_compact_mode_layout_r11.py::"
        "test_status_chips_are_never_squashed_flat_in_compact_mode",
        "RN-185：RN-180 的引导卡让紧凑档竖向更紧，布局挑了这条**没有下限**的"
        "徽章条来压 —— 条高 13px 而芯片要 40px，四颗芯片只剩顶上一道圆弧。"
        "⭐ 而排版审计第 4 条问的是「同排芯片高度是否一致」，"
        "**四颗一起被压扁恰好就是一致的** —— 一条只看「齐不齐」的判据，"
        "看不见「全都不对」",
    ),
    Revert(
        "RN", "空库时控件又变回可点却没反应",
        "widgets/community_library.py",
        "        widget.setEnabled(False)",
        "        pass",
        "tests/test_empty_library_covers_every_page.py::"
        "test_empty_library_leaves_no_control_that_does_nothing",
        "RN-179：七页合计 **188 个**下拉框和试听按钮在空库时照样可点，"
        "点下去什么都不会发生（switch_weapon 39+39、gun_sound 18+18…）。"
        "⭐ 一个可点却什么都不做的控件比一个置灰的更糟 —— "
        "置灰说的是「你还没准备好」，可点却无反应说的是「这软件坏了」",
    ),
    Revert(
        "RN", "空库时的第一步又被塞回页尾",
        "widgets/community_library.py",
        "    use_callout = callout is not None",
        "    use_callout = False",
        "tests/test_empty_library_covers_every_page.py::"
        "test_the_first_step_is_in_the_card_not_the_bottom_bar",
        "RN-180：外审 20 发 / 跨 9 页判「核心流程倒置」。而 CLAUDE.md 里早写着"
        "「解释放在困惑发生的位置之前，不是页尾；放页尾 = 没放」—— "
        "⭐ 我自己写下的教训自己没照做，因为它归档在「网站」小节里而我在做桌面版。"
        "**教训是按场景归档的，而缺陷不认场景**",
    ),
    Revert(
        "RN", "预设摘要又只列前三组",
        "pages/viewmodel_page.py",
        '        for preset in getattr(self, "preset_vars", []):',
        '        for preset in getattr(self, "preset_vars", [])[:3]:',
        "tests/test_flash_viewmodel_truth.py::"
        "test_the_preset_summary_names_every_preset_not_just_the_first_few",
        "RN-177：摘要自称「共 5 组」却只列 3 组，而当时屏幕上又只看得见 1 组 —— "
        "**三个地方三个数，没有一处能互相印证**。摘要列全之后它本身就成了"
        "「5 组确实都在」的凭证，不必先滚到底才能确认",
    ),
    Revert(
        "RN", "侧栏下边缘的余数又开始画半截项",
        "gui_widget.py",
        "                scroll.setViewportMargins(0, 0, 0, max(0, limit - y))",
        "                pass",
        "tests/test_audit_can_see_every_page.py::"
        "test_sidebar_never_shows_a_half_cut_nav_item_at_either_edge",
        "RN-178：只对齐上边缘时**27/28 页**的下边缘各露出 2~10px 的半截项"
        "（项高 40~42），而上边缘是 0/28 —— 一半的账被判据名字里的 "
        "`at_the_top` 挡了整整一轮。视口 657px 装不下整数个项，"
        "滚动只能决定余数在哪一端，消不掉它；只有把余数吃进视口底边距才两端都干净",
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
        # ⚠ RN-177 又把锚点搬走了一次：那一行内层滚动区已经删掉。
        # ⭐ 这条断点的锚点**三度失效**（RN-069 → RN-083 → RN-177），
        #   每次都是版面被改。⇒ 把锚点挪到本页最稳的一行：右列装配那一句。
        "        right_column_layout.addWidget(presets_frame)",
        "        right_column_layout.addWidget(presets_frame)\n"
        "        self.setTabOrder(self.auto_switch_interval_input, save_btn)",
        "tests/test_flash_viewmodel_truth.py::test_viewmodel_tab_order_follows_the_screen",
        "RN-069：走到第 5 个焦点时跳到左下角的「保存到CFG」（y=487），"
        "再折回右上角的「循环按键」输入框（y=229）。"
        "⇒ 显式 setTabOrder 是对**某个具体版面**的断言，改版面就得重新验它",
    ),
    Revert(
        "RN", "lint 又把整个 scripts/ 蒙住",
        "ruff.toml",
        # ⚠ 锚在 `exclude = [` 上，不锚在某个被排除的文件名上 ——
        # 开源版的排除清单是**空的**（那些损坏脚本不属于开源子集），
        # 锚在文件名上会让这条断点在开源仓找不到锚点（2026-08-23 实测，同步验收门当场红）。
        "exclude = [",
        'exclude = [\n    "scripts",',
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
        # ⚠ RN-192：那颗「启用自定闪光」按钮没了（启用归总开关），
        # 副标题里点名它的半句也删了。⭐ 同一行在两条断点里各锚了一次 ——
        #   一行文案被 N 条断点锚着，改它就是 N 处同时空转。
        "被闪的时候，用你自己的颜色、图片和音效替换游戏默认的闪白。",
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
        # ⚠ RN-192：「启用」归总开关、按钮只管「启动」，那颗按钮已经改名。
        '                self.action_bar.configure_primary("启动", self._enable_and_start, visible=True)',
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
        # ⚠ 2026-08-21：这段查表抽成了 `_find_feature_switch()`（RN-144 要用同一段），
        # 锚点跟着搬过去。原来那一行在源码里出现了 2 次，`--stale-only` 当场报失效。
        "        switch_id = self._switch_id_by_config_key.get(config_key)\n"
        "        return self.switches.get(switch_id) if switch_id else None",
        '        switch_id = getattr(self, "_switch_id_by_config_key", {}).get(config_key)\n'
        '        return getattr(self, "switches", {}).get(switch_id) if switch_id else None',
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
        # ⚠⚠ RN-177 之后**注入点也得换**，不只是锚点：预设卡的构造被挪到了
        # 两列装配**之前**，于是原来那句 `scroll_layout.addWidget(presets_frame)`
        # 反而把它放到了两列**上面** —— 破坏动作不再复现缺陷，判据当场假绿。
        # ⭐ **锚点还在不代表破坏还成立**：失效体检只查锚点在不在，
        #   查不出「这一刀现在砍的是别的地方」。那一层只有真跑一遍才看得见。
        # 改成在页面收尾处把它抢过来 —— Qt 会重新认父，卡片落到两列下面，
        # 正是 RN-083 的原状。
        "        scroll_layout.addStretch()",
        "        scroll_layout.addWidget(presets_frame)\n"
        "        scroll_layout.addStretch()",
        "tests/test_flash_viewmodel_truth.py::"
        "test_viewmodel_presets_are_on_the_first_screen",
        "RN-083：右列只有一张卡、自 y≈450 起整列空白，而这一页**最核心的东西**"
        "（5 组预设 + 每组 FOV/XYZ 编辑入口）掉到首屏之外。"
        "外审 3/3 判「高」：「作为『局内视角设置』页却完全找不到 FOV/XYZ 与预设编辑入口」",
    ),
    Revert(
        "RN", "「保存到CFG」又长出第二个入口",
        "pages/viewmodel_page.py",
        '        self._cfg_status_label = QLabel("")\n'
        '        self._cfg_status_label.setObjectName("cfgStatusLabel")',
        '        from PySide6.QtWidgets import QPushButton as _QPB2\n'
        '        _dup2 = _QPB2("保存到CFG")\n'
        '        cfg_layout.addWidget(_dup2)\n'
        '        self._cfg_status_label = QLabel("")\n'
        '        self._cfg_status_label.setObjectName("cfgStatusLabel")',
        "tests/test_flash_viewmodel_truth.py::test_there_is_exactly_one_save_to_cfg_button",
        "RN-078 → RN-404。⚠⚠ 这个断点在批 31 **换了模拟的缺陷**，因为原来那条"
        "（把卡内那颗改名成「保存设置到CFG」）的锚点随卡内那颗按钮一起没了。"
        "⭐⭐ 而更该记的是：它守着的那条判据当时**已经变成一条恒真的断言** —— "
        "集合里只剩一个元素，`len(saves) == 1` 永远成立。"
        "**一条判据的对象被修没了，它不会报错，它会变成一条永远通过的断言**",
    ),
    Revert(
        "RN", "又用「左侧」给导航指路",
        "pages/flash_page.py",
        # ⚠ RN-192：那颗「启用自定闪光」按钮没了（启用归总开关），
        # 副标题里点名它的半句也删了。⭐ 同一行在两条断点里各锚了一次 ——
        #   一行文案被 N 条断点锚着，改它就是 N 处同时空转。
        "被闪的时候，用你自己的颜色、图片和音效替换游戏默认的闪白。",
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
        "MAX_REMAINING = 18",
        "MAX_REMAINING = 20",
        "tests/test_no_invisible_summary_label.py::"
        "test_ratchet_is_tightened_when_pages_are_cleaned",
        "RN-009：棘轮清一页就得跟着收紧一格（本仓库现在 18）。"
        "⚠ 这条锚点在批 32 更新过：那一批放宽了分母"
        "（`summary_label` 全等 → `*_summary_label` 后缀）并清掉 music。"
        "⭐ **锚在一个会变的数上的断点，那个数一动它就空转。**"
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
        "RN", "高级设置又把「备份设置」高亮成主按钮",
        "pages/advanced_page.py",
        '            self.action_bar.configure_primary("", None, visible=False)',
        '            self.action_bar.configure_primary("备份设置", self._backup_settings, visible=True)',
        "tests/test_advanced_page_action_bar_and_debug.py::"
        "test_no_primary_button_once_the_directory_is_set",
        "RN-132：这一页的设置**改完立即生效**，没有「保存」这个动作 —— "
        "而全页最抢眼的紫色按钮却指向低频的「备份设置」。外审两档 4 发都在说"
        "新手会把它当成保存/生效去点。⭐ 没有主路径动作时，就不要造一个出来",
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
        "RN", "样式应用器又把「我是一行」的提示改成折行",
        "ui_style_applier.py",
        # ⚠ RN-191：这一行现在按「是不是字段标签」决定折不折行。
        "            if not widget.property(self.KEEP_WRAP_PROPERTY):\n"
        "                widget.setWordWrap(not self._is_field_label(widget.text()))",
        "            widget.setWordWrap(True)",
        "tests/test_single_line_hints_stay_single_line.py::"
        "test_the_hint_is_still_one_line_after_the_page_is_fully_built",
        "RN-121：`fix_text_display()` 在页面构造**之后**无条件给每个 QLabel 开换行，"
        "把调用方的意图整个冲掉，而且**悄无声息**。代价：折行的 QLabel 在横排里会把"
        "自己的宽度报小，crosshair 标题行那句提示只拿到 120px（需要 156px），"
        "而同一行空着 928px ⇒ 断在「统 / 一」中间。"
        "⭐ **折行往往不是「空间不够」的结果，是「我说我能折行」的结果** —— "
        "所以它躲得过一切「有没有溢出/截断」的判据。"
        "⚠ 同样的教训正上方 UP-018 已经写过一遍（那条修的是尺寸），隔壁分支没跟上",
    ),
    Revert(
        "RN", "滚动区又只提示「上面还有」",
        "ui_effects.py",
        "    scroll_area._scroll_shadow_bottom = ScrollShadow(\n"
        "        scroll_area, ScrollShadow.EDGE_BOTTOM)",
        "    pass",
        "tests/test_scroll_edge_indicator.py::"
        "test_the_bottom_one_lights_up_before_the_user_scrolls",
        "RN-120：原来只装顶部那一条，而且只在 `value > 0`（**用户已经滚过了**）之后才亮 —— "
        "可玩家要知道的是「下面还有没有」，在他滚动**之前**。"
        "外审 crosshair 6 发、advanced 3/3 票都在报「缺乏滚动提示」，而指示器一直装在那儿。"
        "⭐ **一个装了却没人受益的提示，跟没装的区别只在于：它会让人以为已经装过了**",
    ),
    Revert(
        "RN", "滚动渐隐带又不用背景色",
        "ui_effects.py",
        "        c = QColor(theme.colors.bg_primary) if theme is not None else QColor(0, 0, 0)",
        "        c = QColor(0, 0, 0)",
        "tests/test_scroll_edge_indicator.py::"
        "test_the_mask_fades_into_the_background_in_every_theme",
        "RN-120：渐变原先写死 `QColor(0,0,0,30)` —— 深色背景上叠黑色。"
        "实算九套主题：深色五套合成后对比 **1.000~1.030**，"
        "其中纯黑主题（`bg_primary=#000000`）是 **1.000 —— 一个像素都没变**。"
        "现在渐隐带取 `bg_primary` 本身，让贴边的字**淡出**而不是被切断；"
        "颜色要是不跟着主题走，深色主题上会出现一条浅色横带，**比不画更糟**。"
        "⭐ 这条断点自己也腐烂过一次：我把做法从「画线」改成「渐隐」，"
        "锚点那行代码就没了 —— **改了修法要顺手把断点也改到新的失效方式上**",
    ),
    Revert(
        "RN", "滚动指示又错过「还没滚动」那一刻",
        "ui_effects.py",
        "            vbar.rangeChanged.connect(self._on_range_changed)",
        "            pass",
        "tests/test_scroll_edge_indicator.py::test_the_range_signal_is_connected",
        "RN-120：只连 `valueChanged` 的话，页面刚建好时 value 恒为 0、"
        "而 `maximum` 是布局排完才定的 ⇒ **「还没滚动、下面有内容」这个最要紧的时刻"
        "根本不会触发任何一次更新**。而它失效时毫无声响：指示条只是一直灭着",
    ),
    Revert(
        "RN", "界面模式又能在测试文件之间漏过去",
        "tests/conftest.py",
        '    _want = {"csgo_dir": _cs2customizer_game_sandbox, "ui_expert_mode": False}',
        '    _want = {"csgo_dir": _cs2customizer_game_sandbox}',
        "tests/test_test_config_does_not_leak_between_files.py::"
        "test_a_polluted_seed_does_not_change_what_the_next_process_sees",
        "RN-142：测试的配置目录是**固定路径、跨文件跨轮次累积**的，而 run_tests 逐文件"
        "起独立进程 —— 前一个文件把 `ui_expert_mode=True` 存了盘，后一个文件就接着用。"
        "实测代价：`test_advanced_page_ui_polish`（字母序靠前）看到初始值，CI 当场红；"
        "`test_ui_visual_r1_fixes`（字母序靠后）的空转守卫要求 ≥20 项导航，"
        "**一直靠前面那些文件的污染才绿**。"
        "⭐ **一条不钉前置状态的判据，绿不绿取决于同一次运行里前面跑过谁** —— "
        "这比「本机绿 CI 红」更难查：同一台机器上单跑绿、全量红，或者反过来",
    ),
    Revert(
        "RN", "锚点条又给藏起来的卡片留一颗点不动的 chip",
        "pages/advanced_page.py",
        "                and c.isVisibleTo(self)",
        "                and True",
        "tests/test_advanced_page_action_bar_and_debug.py::"
        "test_a_hidden_card_gets_no_anchor_chip",
        "RN-138：RN-133 把「内部调试」卡片收进专家模式，锚点条却照样按标题扫出"
        "一颗「调试」—— 点下去 `ensureWidgetVisible` 作用在隐藏控件上，**画面纹丝不动**。"
        "普通用户看到的是一颗坏掉的按钮。"
        "⭐ **把一块内容藏起来，指向它的东西不会跟着藏**",
    ),
    Revert(
        "RN", "又跟看不见调试卡片的人报调试状态",
        "pages/advanced_page.py",
        "        if self._debug_surface_visible():\n"
        "            badges.append(",
        "        if True:\n"
        "            badges.append(",
        "tests/test_advanced_page_action_bar_and_debug.py::"
        "test_normal_users_are_not_told_about_a_feature_they_cannot_see",
        "RN-138：挂一颗「调试 · 未启用」给看不到调试卡片的人，"
        "等于告诉他有个东西关着，却既不说那是什么、也没有任何地方能打开它。"
        "⭐ 一个「要不要露出来」的条件，凡是有第二处要问它，**就得有名字** —— "
        "RN-133 那次它只是一句就地写死的 `getattr(config, ...)`，"
        "于是另外三处指向同一块内容的东西一处都没跟上",
    ),
    Revert(
        "RN", "截图脚本又自己把专家模式打开",
        "scripts/ui_shot_capture.py",
        "    _ui_mode.apply(config, args.expert)",
        "    config.ui_expert_mode = True",
        "tests/test_ui_mode_sampling.py::"
        "test_visual_harnesses_sample_the_product_default",
        "RN-134：产品默认是普通模式，工装写死成专家视图 ⇒ **整批视觉结论审的是另一个软件**。"
        "十七轮外审、十六页像素基线全建立在这上面，"
        "而 RN-133「把调试卡片收进专家模式」改完复跑外审照报不误。"
        "⭐ 这条断点瞄的是「取样对象」而不是「结论对不对」——"
        "**取样错了的时候，每一条结论都长得很正常**",
    ),
    Revert(
        "RN", "工装换页又不带 force，专家页会静默拍成上一页",
        "scripts/ui_shot_capture.py",
        "            _ui_mode.goto(win, pid)",
        "            win.show_page(pid, animated=False)",
        "tests/test_ui_mode_sampling.py::"
        "test_visual_harnesses_reach_pages_without_relying_on_the_mode",
        "RN-134 的另一半：普通模式下 6 个专家页没有导航入口，`show_page` 直接 return —— "
        "工装于是拿着**上一页**的窗口接着拍，**不报错**，只是图张冠李戴。"
        "⭐ 可达性和视图本来是两件事，全仓 16 处 show_page 都靠「开专家模式」一起兜着，"
        "**所以那行 `= True` 谁也质疑不了**：拿掉它当场少拍 6 页",
    ),
    Revert(
        "RN", "结构投影又看不见「这块被藏起来了」",
        "scripts/_page_structure.py",
        '        out["visible"] = bool(widget.isVisibleTo(root))',
        "        pass",
        "tests/test_structure_baseline_has_no_machine_facts.py::"
        "test_hiding_a_widget_shows_up_in_the_projection",
        "RN-134：投影原先一条可见性都不收，理由是「`isVisible()` 会因窗口没 show 而假红」。"
        "代价是 RN-133 把调试卡片藏起来之后，**改动前后两份投影一模一样** —— "
        "hide/show 这类改动结构判据完全看不见。"
        "⭐ **「这个具体做法会假红」不等于「这件事不该管」**：`isVisibleTo(page)` 不问顶层窗口，"
        "既逮得住 hide/show 又不会离屏假红。先换做法，再谈放弃",
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
        "RN", "回写这条链在抽函数之后断了",
        "gui_widget.py",
        "        toggle = self._find_feature_switch(config_key)\n"
        "        if toggle is None:\n"
        "            return False\n"
        "        value = bool(getattr(self.config, config_key, False))",
        "        toggle = None\n"
        "        if toggle is None:\n"
        "            return False\n"
        "        value = bool(getattr(self.config, config_key, False))",
        "tests/test_flash_viewmodel_truth.py::"
        "test_the_home_switch_card_is_actually_readable_from_elsewhere",
        "RN-144：把查表抽成 `_find_feature_switch()` 之后，"
        "**两个函数各自看着都很正常**，只是 `sync_feature_switch` 不再走到它 —— "
        "首页那颗开关又停在旧值上（RN-089 的原状）。"
        "⭐ 抽函数会把一条链拆成两段，而判据如果只盯其中一段，另一段断了没人知道",
    ),
    Revert(
        "RN", "社区地址又变成一个必需的顶层 import",
        # ⚠ 2026-08-21（RN-153）：这道守卫**搬家了** —— 从 kill_icon 页搬进
        # `widgets/community_library`，因为音效家族四页也要用同一张地址表。
        # ⭐ 同一道守卫散成 N 份，就是 N 个各自会漏的地方（RN-157 漏过一次）。
        "widgets/community_library.py",
        "except ImportError:                      # pragma: no cover - 只有开源版会走到\n"
        "    COMMUNITY_CATEGORY_URLS = {}",
        "except ValueError:                       # 抓错异常类型，等于没抓\n"
        "    COMMUNITY_CATEGORY_URLS = {}",
        "tests/test_kill_icon_empty_library_guidance.py::"
        "test_no_module_imports_the_community_urls_without_a_guard",
        "RN-145：开源版的 `service_urls.py` **归它自己所有**，里面没有社区站。"
        "一个必需的顶层 import 会让**整页 import 不进去** —— "
        "而同步管道的机械步骤完全看不出来（它只比文件差异），"
        "闭源版这边全绿。⭐ 跨仓差异要让代码自己容得下，别指望补丁替你兜",
    ),
    # ==================================== RN-145：空图标库的引导（不内置素材）
    Revert(
        "RN", "引导按钮又被播放器就绪状态灰掉",
        "pages/kill_icon_page.py",
        "                self.test_btn.setEnabled(True)",
        "                self.test_btn.setEnabled(player_ready)",
        "tests/test_kill_icon_empty_library_guidance.py::"
        "test_the_guidance_button_is_not_greyed_out_by_the_player",
        "RN-145：那颗按钮空库时是「去拿一套图标包」，不是「试播」。"
        "拿 `player_ready` 灰它 = 用一个**跟它无关的条件**把全新用户唯一的出路封死。"
        "⭐ 一颗按钮换了含义，门禁条件要跟着换 —— 页面照常渲染、文案照常正确，"
        "只是那颗大按钮点不动，且没有任何报错",
    ),
    Revert(
        "RN", "空库时主按钮又回去试播一套不存在的风格",
        "pages/kill_icon_page.py",
        "            self._open_icon_library()",
        "            self._test_current()",
        "tests/test_kill_icon_empty_library_guidance.py::"
        "test_clicking_it_actually_opens_the_icon_library",
        "RN-145：按钮照常写着「去拿一套图标包」、照常能点、照常有反应，"
        "只是**什么也不会发生**（没有素材可播）。"
        "⭐ 文案对了不等于接线对了 —— 这类退化在截图里完全看不出来",
    ),
    Revert(
        "RN", "副标题抽取器又漏掉模块常量这条通路",
        "tests/test_no_layout_self_talk_sitewide.py",
        '                elif t.id.endswith("_LEAD_TEXT"):\n'
        '                    out.append((node.value.lineno, node.value.value, "LEAD_TEXT"))',
        '                elif False:\n'
        '                    pass',
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_the_extractor_actually_sees_the_module_lead_constants",
        "RN-145：页头文案一旦有两种说法，`description=` 收的就是名字不是字面量，"
        "**这一页当场从全站文案扫描里掉出去**，而总量守卫只少一条、照样绿。"
        "⭐ 这是改动自己造出来的盲区 —— 把字面量收成常量的那一刻就发生了，没有任何东西会响",
    ),
    # ==================================== RN-167 / RN-162 / RN-168 / RN-171（批 4）
    Revert(
        "RN", "空库时底栏又去劝人「自己做一套」",
        "pages/kill_icon_page.py",
        '            "打开素材工坊", self._open_workshop, visible=not empty)',
        '            "打开素材工坊", self._open_workshop, visible=True)',
        "tests/test_empty_library_covers_every_page.py::"
        "test_kill_icon_empty_state_offers_exactly_one_call_to_action",
        "RN-171（外审 6/6 票，两档各 3）：RN-145 已经把底栏**主**按钮在空库时收掉了，"
        "于是唯一还亮着的成了**次**按钮「打开素材工坊」—— 卡里主推「去社区拿现成的」，"
        "页尾却在推「自己做」（门槛最高的那条路）。"
        "⭐⭐ RN-154 那条的又一次现身：**修一个问题时留下的旧形态，会变成下一个问题**。"
        "⚠ 工艺记一笔：这条**只有整页无折线的截图才看得见**（RN-170）—— "
        "两颗互相冲突的按钮以前从没同时出现在一张图里，而**外审看不见的东西不会报**",
    ),
    Revert(
        "RN", "共用文案件又长出一个没人读的参数",
        "pages/audio_status_badge.py",
        "def resource_hint(health: dict) -> str:",
        'def resource_hint(health: dict, open_label: str = "打开音频资源") -> str:',
        "tests/test_gun_special_sound_truth.py::"
        "test_no_dead_parameters_in_the_shared_copy_helpers",
        "⭐⭐ RN-168：`open_label` 在 RN-153 之后就没有读者了，可是调用方照传、"
        "docstring 照讲、连回退断点都还在守它 —— **传进去、没人读、无人报错，整整三批**。"
        "⭐ 它是被回退验证判假绿才暴露的 ⇒ "
        "**假绿的断点不只是少了一道防线，它还是一根指向死代码的指针**",
    ),
    Revert(
        "RN", "帮助面板又去教用户勾一颗已经删掉的 checkbox",
        "ui_help_panel.py",
        '        "1. 打开这一页的「总开关」<br>"',
        '        "1. 勾上「开启击杀图标」<br>"',
        "tests/test_help_copy_names_real_controls.py::"
        "test_every_named_control_actually_exists",
        "⭐⭐ RN-167：这一条**是批 1 自己弄坏的** —— RN-161 把那颗 QCheckBox 换成了 "
        "MasterSwitchRow，而描述它的那句帮助文案住在 `ui_help_panel.py`，"
        "改按钮的人根本不会打开那个文件。批 1/2/3 三轮全绿。"
        "⭐ **一处改动不会去通知描述它的文案**（RN-138 / RN-163 同一个形状的第三次现身）",
    ),
    Revert(
        "RN", "帮助文案又点名一个不存在的按钮名",
        "ui_help_panel.py",
        '        "1. 点「立即体检」，软件会扫描各功能的资源目录<br>"',
        '        "1. 点「开始体检」，软件会扫描各功能的资源目录<br>"',
        "tests/test_help_copy_names_real_controls.py::"
        "test_every_named_control_actually_exists",
        "RN-167：按钮叫「立即体检」，文案写「开始体检」—— 差两个字，"
        "而用户会在页面上**找不到文案说的那颗按钮**。"
        "⭐ 这条判据比「不许写方位」有用得多：RN-167 引用的那次真实失效"
        "（`audio_status_badge` 指着被换掉的按钮）**删方位词根本防不住**",
    ),
    Revert(
        "RN", "hud_color 的就地总开关又被拆掉",
        "pages/hud_color_page.py",
        "        status_card_layout.addWidget(self.master_switch_row)",
        "        pass  # 不装就地总开关",
        "tests/test_master_switch_row.py::"
        "test_every_page_that_shows_master_state_offers_the_switch[hud_color]",
        "RN-162：批 1 当时**故意不扩**到这一页（它已关档已锁基线，顺手改会毁掉可比基线）。"
        "⭐ 范围按理由走不按顺手走 —— 但「以后补」只有真的补了才算数",
    ),
    Revert(
        "RN", "hud_color 的徽章又去复述同一张卡上的那颗开关",
        "pages/hud_color_page.py",
        '             "生效 · 规则已启用" if master_enabled else "生效 · 规则未启用"),',
        '             "总开关 · 开启" if master_enabled else "总开关 · 关闭"),',
        "tests/test_tool_pages_ui_polish.py::"
        "test_hud_color_page_status_strip_tracks_dirty_state",
        "RN-163 那条的第二种形态：开关搬进同一张卡之后，"
        "「总开关 · 开启」就是**一行里把一件事说两遍**",
    ),
    Revert(
        "RN", "hud_color 又把用户支去基础设置",
        "pages/hud_color_page.py",
        '                "总开关没开：规则会继续保留，但不会在游戏里生效。")',
        '                "总开关在「基础设置」里，关闭时规则会继续保留。")',
        "tests/test_master_switch_row.py::"
        "test_no_page_with_its_own_switch_still_sends_the_user_away",
        "⭐⭐ 这句是 RN-163 那 13 处指路文案的**第 14 处**，"
        "在批 1 之后又活了整整三批 —— 因为那条判据是「**有自己开关的页**才查」，"
        "而这一页当时没有开关，条件不成立就直接绕过去了。"
        "⭐ **条件式判据会在条件不成立的地方留下盲区，而盲区不报错。**",
    ),
    # ==================================== RN-165（批 3：剩余四页）
    Revert(
        "RN", "某一页又自己拼一份空状态底栏",
        "widgets/community_library.py",
        "    bar.configure_primary(cta_text, lambda: open_category(category_key), visible=True)",
        "    return False  # 共用件被掏空，各页只能自己拼",
        "tests/test_empty_library_covers_every_page.py::"
        "test_the_shared_helper_is_the_only_place_that_opens_the_category",
        "⭐ RN-165：八页「库空不空」各问各的（数据结构完全不同），"
        "但**空了该长什么样只能有一份** —— 否则八页会各自演化成八个略有差别的空状态，"
        "而没有任何东西会发现它们不一样了",
    ),
    Revert(
        "RN", "共用件又把第二步删掉",
        "widgets/community_library.py",
        '        bar.configure_extra("", None, visible=False)',
        '        bar.configure_primary("", None, visible=False)',
        "tests/test_empty_library_covers_every_page.py::"
        "test_the_empty_state_always_keeps_a_way_to_put_the_files_in",
        "⭐⭐ RN-153 的血教训：第一版把「打开资源目录」整个换掉了，"
        "而底栏文案还在说「放进资源目录」—— **指着一个不存在的按钮**。"
        "我修好了第一步（去哪儿拿），却顺手删掉了第二步（放哪儿去）。"
        "⚠ RN-180 之后这条断点和它的判据**一起搬了家**：CTA 进了引导卡，"
        "第二步成了底栏那颗没被碰过的主按钮，共用件不再需要动 extra —— "
        "而 `configure_extra` 这个名字仍在源码里（用来收「新建风格」），"
        "于是那条 AST 判据变成假绿、一声不吭。"
        "⭐ **「源码里出现过这个调用」和「用户真的还有那条路」是两回事**",
    ),
    Revert(
        "RN", "flash 的启动入口被空库引导顶掉",
        "pages/flash_page.py",
        # ⚠ RN-192：同上，按钮改名成「启动」。
        '                self.action_bar.configure_primary("启动", self._enable_and_start, visible=True)',
        '                self._guide_empty_library(True, "去社区拿一套自定闪光", "打开图片文件夹", self._open_flash_images_folder, "刷新样式列表")',
        "tests/test_empty_library_covers_every_page.py::"
        "test_flash_only_guides_on_the_two_asset_tabs",
        "⭐ flash 的主按钮本来就是个状态机。引导插到「启用/启动」那一支，"
        "就等于**把全页唯一能让功能真正跑起来的按钮换成了逛社区**（RN-079 刚修好的那颗）",
    ),
    Revert(
        "RN", "special_sound 又漏掉空库引导的调用点",
        "pages/special_sound_page.py",
        "        self._sync_community_guidance()",
        "        pass  # self._sync_community_guidance()",
        "tests/test_empty_library_covers_every_page.py::"
        "test_every_page_actually_calls_the_guidance[special_sound_page.py]",
        "RN-165：逻辑共用，但**调用点每页一行** —— 抄漏一处那一页的空库引导就是死的，"
        "而不会有任何一处报错（同 RN-138 / RN-163 那个形状）",
    ),
    # ==================================== RN-153 / RN-148（批 2）
    Revert(
        "RN", "结构投影又直接 json.loads 标记后的全部内容",
        "scripts/renovation_baseline.py",
        "        value, _end = json.JSONDecoder().raw_decode(tail)",
        "        value = json.loads(tail)",
        "tests/test_renovation_baselines.py::"
        "test_the_structure_probe_survives_a_log_line_after_the_json",
        "⭐⭐ RN-166：子进程的日志是异步落到同一个流上的，一条 "
        "`[WARNING] [AudioHealth] ...` 完全可能排在 JSON **之后**。"
        "那时 `json.loads` 抛 JSONDecodeError —— 而它报出来的样子是「结构对不上」。"
        "⭐ **一个解析错误伪装成了一次内容差异**，于是人会去改基线"
        "（我照着重锁了三轮），而真正的毛病在工装里",
    ),

    Revert(
        "RN", "空库时主按钮又把用户送去空文件夹",
        # ⚠ 2026-08-21（RN-165）：这段逻辑**搬进共用件了**
        # （`widgets/community_library.guide_empty_library`）——
        # 八页共用同一份空状态。锚点跟着搬。
        "widgets/community_library.py",
        "    if not empty or not has_category(category_key):",
        "    if True:",
        # ⚠ RN-180 之后这条判据改了名，也改了量的位置：CTA 从底栏搬进引导卡，
        # 判据于是从「底栏主按钮是什么」改问「最显眼的那一步是什么」。
        "tests/test_empty_library_points_at_the_community.py::"
        "test_an_empty_library_leads_with_the_community_not_an_empty_folder",
        "RN-153：全新安装时底栏最抢眼的那颗按钮是「打开音频资源」，"
        "点开是个**空文件夹** —— 用户手上没有文件，那儿什么也解决不了。"
        "⭐ 打开一个空文件夹不是一条路",
    ),
    Revert(
        "RN", "有素材了还一直显示社区引导",
        # ⚠ 2026-08-21（RN-165）：这段逻辑**搬进共用件了**
        # （`widgets/community_library.guide_empty_library`）——
        # 八页共用同一份空状态。锚点跟着搬。
        "pages/sound_page_base.py",
        "            empty=self._library_is_empty(),",
        "            empty=True,",
        "tests/test_empty_library_points_at_the_community.py::"
        "test_a_stocked_library_keeps_the_original_primary",
        "RN-153 的反面守卫：**永远显示引导**也能让正面那几条全绿，"
        "而那会把一个正常用户每次都送去社区站。"
        "⭐ 一条只验「新形态出现了」的判据，挡不住「新形态永远出现」",
    ),
    Revert(
        "RN", "音效页抄漏了空库引导的调用点",
        "pages/kill_voice_page.py",
        "        self._sync_community_guidance()",
        "        pass  # self._sync_community_guidance()",
        "tests/test_empty_library_points_at_the_community.py::"
        "test_every_sound_page_calls_the_shared_guidance[kill_voice]",
        "RN-153：逻辑在基类只有一份，但**调用点每页一行** —— "
        "抄漏一处，那一页的空库引导是死的，而**不会有任何一处报错**。"
        "⭐ 与 RN-138 / RN-163 同一个形状：一处改动不会去通知它的所有调用点",
    ),
    Revert(
        "RN", "没有社区站的发行版留下一颗指向空地址的按钮",
        # ⚠ 2026-08-21（RN-165）：这段逻辑**搬进共用件了**
        # （`widgets/community_library.guide_empty_library`）——
        # 八页共用同一份空状态。锚点跟着搬。
        "widgets/community_library.py",
        "    if not empty or not has_category(category_key):",
        "    if not empty:",
        "tests/test_empty_library_points_at_the_community.py::"
        "test_a_build_without_the_community_falls_back_to_a_real_path",
        "RN-157 的教训：开源版的 `service_urls` 归它自己所有，没有社区站。"
        "⭐ **一颗指向空地址的按钮比没有按钮更糟** —— 它看起来是出路，"
        "点下去什么也没有",
    ),
    # ⚠ 开源版**摘掉了**「社区地址表和老常量又各写一份」那条断点：
    # 它的锚点在 `service_urls.py` 里，而开源版的那一份**归它自己所有**、
    # 根本没有社区站地址。断点锚在一个"另一个发行版里不存在的东西"上，
    # 在闭源仓是看不出来的（同 RN-158）。
    Revert(
        "RN", "帮助面板又不自己装边缘提示",
        "ui_help_panel.py",
        "        install_scroll_shadow(scroll)",
        "        pass  # install_scroll_shadow(scroll)",
        "tests/test_help_panel_edge_indicator.py::"
        "test_the_help_panel_has_edge_indicators_at_all",
        "RN-148：这块内容有 243px 在视口外，而它一直没有边缘提示器 —— "
        "全站遍历**压根没走到它**。⭐ 那句静默的 `except Exception: pass` "
        "正是它能躺住的原因：**失败和没走到长得一模一样**",
    ),
    # ============== RN-144 升级版：功能页上那颗**就地**总开关（含 RN-147 / RN-155）
    Revert(
        "RN", "就地开关又退回只改样子、不发信号",
        "gui_widget.py",
        "            toggle.toggle()        # 与鼠标点它是同一条路",
        "            toggle.setChecked(bool(enabled))",
        "tests/test_master_switch_row.py::"
        "test_flipping_the_page_switch_runs_the_real_side_effects",
        "⭐⭐ RN-144 升级版最贵的一条：`ToggleSwitch` 的文件头写着「与 QCheckBox "
        "API 兼容」，但它的 `setChecked()` **不发 `toggled`**（只有 `toggle()` 发）。"
        "写成 setChecked 之后，页内开关**看着拨过去了，副作用一条都没跑** —— "
        "叠加层不同步、素材不预热、config 不落盘，而且没有任何一处会报错。"
        "⭐ 「API 兼容」是关于方法名的说法，不是关于**信号语义**的保证",
    ),
    Revert(
        "RN", "就地开关自己写 config，绕开那条唯一链路",
        "widgets/master_switch_link.py",
        "        if not window.set_feature_enabled(self.config_key, bool(checked)):",
        "        if not setattr(__import__('config').config, self.config_key, bool(checked)):",
        "tests/test_master_switch_row.py::"
        "test_flipping_the_page_switch_runs_the_real_side_effects",
        "RN-144 升级版：自己 setattr 拿到的是「界面显示已开、功能根本没起」。"
        "⭐ 同一件事只能有一条链路；第二条链路一定会缺东西，而缺的那部分不报错",
    ),
    Revert(
        "RN", "开不起来的功能，页内开关不弹回去",
        "widgets/master_switch_link.py",
        "        # ⭐ 回读实际值，**不信任刚写进去的那个**：",
        "        return\n        # ⭐ 回读实际值，**不信任刚写进去的那个**：",
        "tests/test_master_switch_row.py::"
        "test_the_row_snaps_back_when_nothing_actually_happened",
        "RN-144 升级版：拨了但根本没生效时，开关必须自己弹回去 —— "
        "⭐ 写进去的值不等于实际的值。"
        "⚠ 这条断点原来指向 `..._snaps_the_page_switch_back`（准心缺 pywin32 那个场景），"
        "**回退验证当场 0/1**：我给那条回滚分支也加了一次广播，"
        "于是「自己回读」被广播兜住了，砍掉它判据照样绿。"
        "⭐ **两条路互为兜底时，单独砍掉任何一条，判据都逮不住** —— "
        "冗余是好设计，但它会让判据失去分辨力。⇒ 已改指一条「只有自己回读能救」的场景",
    ),
    Revert(
        "RN", "首页拨了开关，功能页那颗不跟上",
        "gui_widget.py",
        "        self._sync_master_switch_rows(config_key)\n\n        # 卡片边框闪烁反馈",
        "        # 卡片边框闪烁反馈",
        "tests/test_master_switch_row.py::"
        "test_flipping_the_home_switch_moves_the_page_switch",
        "RN-144 升级版：双向同步少了广播这一半。用户在首页关掉、切回功能页，"
        "会看到一颗停在「开」的开关。⭐ 同屏两处说法不一致（RN-107 族）",
    ),
    Revert(
        "RN", "总开关动了，页面那条状态文案不重算",
        "widgets/master_switch_link.py",
        "        self._notify_page()\n\n    def _notify_page(self)",
        "        pass\n\n    def _notify_page(self)",
        "tests/test_master_switch_row.py::"
        "test_the_badge_follows_the_switch_it_describes",
        "RN-144 升级版：开关拨过去了，「总开关 · 未开启」那条徽章还停在旧文案。"
        "⭐ 一个「值没变就早退」的优化，会把「别人还没同步过」这件事一起早退掉",
    ),
    Revert(
        "RN", "基类又不去读那个总开关钩子",
        "pages/sound_page_base.py",
        "        if self.MASTER_SWITCH_KEY:",
        "        if False:",
        "tests/test_master_switch_row.py::"
        "test_every_page_that_shows_master_state_offers_the_switch[reload_sound]",
        "RN-144：换弹音效页的类属性照样填着 `MASTER_SWITCH_KEY`，"
        "**开关行却一行都没建出来**。只判类属性的判据在这一刻是绿的 —— "
        "⭐ 配置对不等于配置被读了",
    ),
    Revert(
        "RN", "RN-147 那三个音效页又掉出去",
        "pages/kill_sound_page.py",
        '    MASTER_SWITCH_KEY = "kill_sound_enabled"',
        '    MASTER_SWITCH_KEY = ""',
        "tests/test_master_switch_row.py::"
        "test_every_page_that_shows_master_state_offers_the_switch[kill_sound]",
        "RN-147：音效家族四页是同一个机制，本轮一起收的。"
        "⚠ 断点方向与第一版**相反** —— 那时守的是「别顺手扩大范围」，"
        "现在守的是「别把已经进来的三页丢回去」。"
        "⭐ 范围变了，守卫的方向也要跟着翻，不能留着上一版的守卫装样子",
    ),
    Revert(
        "RN", "击杀图标的总开关又混回子选项堆里",
        "pages/kill_icon_page.py",
        '            self, "kill_icon_enabled", "击杀图标")',
        '            self, "kill_icon_headshot_enabled", "击杀图标")',
        "tests/test_master_switch_row.py::"
        "test_the_config_key_each_page_declares_really_exists_at_home[kill_icon-kill_icon_enabled]",
        "RN-155：填错一个键的后果是**静默空转** —— 开关照样画得出来、点得动，"
        "只是拨的是另一个功能。⭐ 这条判据把「填错」从运行时变成红灯",
    ),
    Revert(
        "RN", "击杀图标的素材预热又只挂在页面那一侧",
        "gui_widget.py",
        '        if config_key == "kill_icon_enabled":\n'
        '            player = getattr(self, "kill_icon_player", None)',
        '        if False:\n'
        '            player = getattr(self, "kill_icon_player", None)',
        "tests/test_master_switch_row.py::"
        "test_the_kill_icon_player_is_driven_from_the_one_chain",
        "⭐ 这一段补的是一个**既有的不对称**：页内那颗复选框一直会调 "
        "`enable_kill_icons()`，而首页同名的总开关只写 config。"
        "同一个开关从两个地方拨，效果不一样，谁都不报错 —— "
        "**同一件事有两条链路时，短的那条一定缺东西**",
    ),
    # ==================================== RN-139：基础设置页的首屏主按钮
    Revert(
        "RN", "首屏主按钮又指回「载入音频」",
        "gui_widget.py",
        '            "载入音频",\n'
        "            self._reload_audio,\n"
        "            # RN-139：从主按钮降为普通按钮。",
        '            "载入音频",\n'
        "            self._reload_audio,\n"
        "            primary=True,\n"
        "            # RN-139：从主按钮降为普通按钮。",
        "tests/test_basic_page_primary_action.py::"
        "test_there_is_exactly_one_primary_button",
        "RN-139：两颗紫的等于零颗 —— 「主」是相对的。"
        "这条退化**不报错、不溢出、不截断**，排版审计一路绿灯，"
        "只是产品替用户排的那个序作废了",
    ),
    Revert(
        "RN", "引导按钮降级回普通按钮",
        "gui_widget.py",
        "            # 用户裁定（2026-08-21）：只换首屏主按钮，不动导航顺序。\n"
        "            primary=True,",
        "            # 用户裁定（2026-08-21）：只换首屏主按钮，不动导航顺序。",
        "tests/test_basic_page_primary_action.py::"
        "test_the_only_purple_button_is_the_onboarding_guide",
        "RN-139：入口还在、还能点、还接在共用的引导上，"
        "只是它不再是这一屏上最抢眼的那颗 —— 而外审 advanced 6/6、basic 5/6 票"
        "说的就是「新手第一步就走错」。⭐ 视觉主次的退化没有任何一条既有判据看得见",
    ),
    Revert(
        "RN", "空库时状态又去报 config 里那个用不了的风格名",
        "pages/kill_icon_page.py",
        '        style_text = "还没有" if empty else self._compact_text(self._current_style(), "未设置")',
        '        style_text = self._compact_text(self._current_style(), "未设置")',
        "tests/test_kill_icon_empty_library_guidance.py::"
        "test_the_status_strip_does_not_name_a_style_that_is_not_installed",
        "RN-145：`_current_style()` 读的是 config 存的名字，跟「这台机器上有没有这套风格」是两回事。"
        "全新用户 config 里留着「默认」⇒ 徽章写「风格 · 默认」，"
        "而同一张卡上另一行写着「共 0 套可选」——**一屏之内自相矛盾**（同 RN-107 族）。"
        "⭐ 这条是改完看图才发现的：我修好了预览占位却漏了另外三处同样读它的地方",
    ),
    Revert(
        "RN", "副标题抽取器又漏掉 PAGE_LEAD 这条通路",
        "tests/test_no_layout_self_talk_sitewide.py",
        # ⚠ 2026-08-21 改锚点：RN-145 把这个分支重排成 `if t.id == "PAGE_LEAD" / elif`，
        # 老锚点（`and isinstance(...)` 那两行）在源码里变成 0 次 —— 断点当场空转，
        # 是 `--stale-only` 逮住的。⭐ **重构不会告诉你哪些判据的锚点被你挪走了。**
        '                if t.id == "PAGE_LEAD":\n'
        '                    out.append((node.value.lineno, node.value.value, "PAGE_LEAD"))',
        '                if False:\n'
        '                    pass',
        "tests/test_no_layout_self_talk_sitewide.py::"
        "test_the_extractor_actually_sees_the_page_lead_constants",
        "RN-091：全站副标题抽取器原来只认「调用的实参」，"
        "音效家族 4 页的页头文案是类常量 `PAGE_LEAD`（经基类转递），"
        "**`kill_sound_page.py` 实测抽到 0 条**，而总量守卫（≥60）一直是绿的。"
        "⇒ 每加一条通路就要配一条只盯它自己的守卫，否则总量会把它盖住",
    ),
    # ==================================== 批 7：RN-030 / RN-194 / RN-196
    Revert(
        "RN", "排版审计又只量页签内容（整页范围被删）",
        "scripts/layout_overflow_audit.py",
        "    yield (None, page, tab_pages)          # 必须在任何 setCurrentIndex 之前",
        "    pass  # 断点：不再交出「页面余下部分」这个范围",
        "tests/test_audit_measures_the_whole_page.py::"
        "test_every_visible_widget_of_every_page_falls_inside_some_scope",
        "RN-030：`_scopes()` 只要发现 QTabWidget 就**只**返回页签内容，"
        "于是页头、状态徽章条、顶层卡片、底部操作栏从来没被任何判据看过。"
        "实测 10 页 / ~490 个可见控件，magnifier 一页就占 125/210（61%）——"
        "而 RN-191 那四个折行的标签（`主武器热键:` 等）逐字就在这片盲区里。"
        "⭐ 「只返回页签内容」是拿**替换**当**排除**用",
    ),
    Revert(
        "RN", "先把页签切一遍再量整页",
        "scripts/layout_overflow_audit.py",
        "        if w is not None\n"
        "    )\n"
        "    yield (None, page, tab_pages)",
        "        if w is not None\n"
        "    )\n"
        "    for _tw in tabs:                      # 断点：量整页之前先戳一遍页签\n"
        "        for _i in range(_tw.count()):\n"
        "            _tw.setCurrentIndex(_i)\n"
        "            app.processEvents()\n"
        "    yield (None, page, tab_pages)",
        "tests/test_audit_measures_the_whole_page.py::"
        "test_the_page_scope_is_measured_before_any_tab_is_touched",
        "⭐⭐ **工装的观测动作本身会改变被观测对象**：切一遍页签，整页的布局最小高"
        "会永久变大（magnifier 596→612、flash 500→516），`setCurrentIndex(original)` "
        "复位也回不来（Qt 的尺寸提示要显示过一次才准）。"
        "第一版就是先切后量，magnifier 的纵向缺口凭空从 6px（容差内）变成 22px",
    ),
    Revert(
        "RN", "skip 写成整个 QTabWidget（页签条掉进两不管）",
        "scripts/layout_overflow_audit.py",
        "        w for tw in tabs for w in (tw.widget(i) for i in range(tw.count()))\n"
        "        if w is not None",
        "        w for w in tabs\n"
        "        if w is not None",
        "tests/test_audit_measures_the_whole_page.py::test_the_tab_bar_itself_is_measured",
        "页签**条**不属于任何一个页签内容，但它一直被正常布局、有文字、会被截断。"
        "跳过整个 QTabWidget 会让它既不在整页范围里、也不在任何页签范围里 ——"
        "⭐ 修一个盲区时最容易顺手造出另一个更小的盲区",
    ),
    Revert(
        "RN", "变坏也不算数（存量债棘轮只认新增）",
        "scripts/layout_overflow_audit.py",
        "        elif px > entry[0] + 2:          # 2px 容差：取整/滚动条钢化",
        "        elif False:          # 断点：变坏不报",
        "tests/test_audit_measures_the_whole_page.py::"
        "test_the_known_debt_ratchet_bites_in_all_three_directions",
        "RN-196：在册存量债的棘轮必须三向咬人（新增 / 变坏 / 已经不该在册）。"
        "只认新增的话，那 6 条债可以一路劣化下去而门一直是绿的",
    ),
    Revert(
        "RN", "本机门禁少接一道审计",
        "scripts/gate.py",
        '    "contrast": "ui_contrast_audit.py",',
        "    # 断点：对比度审计没接进来",
        "tests/test_ci_gates_read_the_verdict_line.py::"
        "test_the_local_gate_covers_every_audit_that_delivers_a_verdict",
        "RN-194：本机入口的分母取「所有会交裁定的审计」，不取它自己那张表 ——"
        "⭐ 一张只列出「已经接进来的东西」的表，永远发现不了漏了谁（同 RN-189）",
    ),
    Revert(
        "RN", "本机门禁自己抄一份裁定正则",
        "scripts/gate.py",
        "    rc = parse_verdict(out, name)",
        "    import re\n"
        "    rc = None\n"
        "    for _line in out.splitlines():\n"
        "        if re.match(r'^RESULT', _line.strip()):\n"
        "            rc = 0",
        "tests/test_ci_gates_read_the_verdict_line.py::"
        "test_the_local_gate_does_not_reimplement_the_verdict_rule",
        "裁定规则在 Python 侧只准有一份。抄出来的那份最容易漂：CI 取**最后一条**"
        "匹配行，本机若取第一条，两道门在「审计中途重跑过」时会给出不同结论",
    ),
    Revert(
        "RN", "枪声页文案又去教用户调连发武器",
        "pages/gun_sound_page.py",
        "太长会盖掉下一枪；点得快的枪往短了调。",
        "太长会盖掉下一枪；连发武器往短了调。",
        "tests/test_gun_sound_profiles.py::"
        "test_the_page_does_not_name_weapon_classes_it_cannot_select",
        "RN-254：这一页把 17 把全自动枪排除在外，而静音覆盖那颗滑块的 tooltip "
        "写着「连发武器往短了调」—— 教用户去调一个他在这一页根本选不到的东西。"
        "⚠ RN-167 那条棘轮只查**按钮名**，看不见「点名一类武器」这种写法",
    ),
    Revert(
        "RN", "ruff.toml 替一个已删的文件留排除行",
        "ruff.toml",
        # 同上：锚 `exclude = [`，在两个仓里都存在。
        "exclude = [",
        'exclude = [\n    "scripts/bootstrap_tutorial_content.py",',
        "tests/test_audit_no_modal_no_game_writes.py::"
        "test_lint_does_not_blindfold_the_whole_scripts_directory",
        "UP-091：`bootstrap_tutorial_content.py` 已于 2026-08-23 删除。"
        "排除行留着不报错、也不再保护任何东西 —— 而**这条回退断点自己就锚在那一行上**，"
        "删文件不动它就会当场变成假绿。⭐ 一张只增不减的排除名单会慢慢变成免检区",
    ),
    Revert(
        "RN", "产品代码点名一条还没结的 RN，登记册那一格没人管",
        "pages/gun_sound_page.py",
        "# 属 RN-167 族（文案点名了这一页不存在的东西）",
        # ⚠⚠ 2026-08-28 批 21 全组跑判它**假绿**：这里原来写的是 `RN-199`，
        #    而 **RN-199 已于批 15 关档**（删整条教程线）⇒ 判据不再报，
        #    因为它报的是「代码点名了一条**还没结**的 RN」。
        #    ⭐ 又一次「一条靠巧合成立的红，会在巧合消失的那一刻变成假绿」
        #      （批 12 已记过一次，那次也是我自己写的断点）。
        #    改指 RN-104（「资源·异常 N」红标无原因，跨页 8 页）——
        #    ⚠ 它同样会有关档的那一天；⭐ **这类断点没有结构性的修法，
        #      只有"全组跑"这一个发现机制** ⇒ 收工只跑新组是不够的。
        "# 属 RN-104 族（文案点名了这一页不存在的东西）",
        "tests/test_renovation_registry_does_not_rot.py::"
        "test_product_code_that_names_an_rn_is_not_still_open",
        "RN-198：登记册是全工程唯一一个**没有棘轮**的真相源。一次对账查出 **14 条**"
        "已经做完却还挂着「新立/待裁定」的条目。这个断点模拟的是其中一种发现路径："
        "产品代码里点着某条 RN 的名，而登记册里它还没结。"
        "⚠ 登记册在另一个仓（一个纯文档仓），所以这条判据的**数据检查**在 CI 与"
        "开源版里 skip（逻辑守卫照跑）；它守的是**本机提交前**那一刻，"
        "而腐烂恰恰就发生在那一刻",
    ),
    # ============================================ RN-195：音乐控制条
    Revert(
        "RN", "首播时没人去把控制条建出来",
        "music_player.py",
        "            notify_playback_started()",
        "            pass  # notify_playback_started()",
        "tests/test_music_bar_only_after_playing.py::"
        "test_play_track_is_the_one_place_that_announces_playback",
        "RN-195：控制条改成「放过音乐才建」之后，**首播那条通知路径不能省**。"
        "`pages/music_page.py` 自己一个播放控件都没有（唯一入口是双击曲目），"
        "暂停/下一首/音量全在这条栏上 —— 通知一断，用户放着音乐却连暂停都点不到。"
        "⭐ 一个把用户扔进没有出口的状态的「收窄」，不是收窄，是新缺陷",
    ),
    Revert(
        "RN", "认不出的播放记录被判成「没放过」",
        "music_player.py",
        '        return int(getattr(config, "music_current_index", -1)) >= 0\n'
        "    except (TypeError, ValueError):\n"
        "        return True",
        '        return int(getattr(config, "music_current_index", -1)) >= 0\n'
        "    except (TypeError, ValueError):\n"
        "        return False",
        "tests/test_music_bar_only_after_playing.py::"
        "test_a_value_it_cannot_classify_falls_toward_building_the_bar",
        "RN-195：这个判断的两个失效方向**不对称** —— 误判成「没放过」是把用户"
        "唯一的播放控制面整个拿掉，误判成「放过」只是多占 42px。"
        "⭐ 分不出类的值，必须朝那个只会难看、不会致残的方向倒"
        "（与批 8 `_is_open()` 同型）",
    ),
    Revert(
        "RN", "延迟入口改回无条件建控制条",
        "gui_widget.py",
        "QTimer.singleShot(8000, self._create_music_control_bar_if_played)",
        "QTimer.singleShot(8000, self._create_music_control_bar)",
        "tests/test_music_bar_only_after_playing.py::"
        "test_every_deferred_entry_point_goes_through_the_conditional_creator",
        "RN-195：两处延迟创建（8 秒兜底 / 后台 stage2）只要有一处改回无条件，"
        "「建不建」就有了两份判断，而结论取决于**哪个定时器先到**",
    ),
    Revert(
        "RN", "量图工装钉了档位却不回验",
        "scripts/page_fingerprint.py",
        "    # RN-195：跑完回验 —— 这一轮全程都在钉住的那一档里。\n"
        "    _mbar.assert_stable(win)",
        "    # RN-195：跑完回验 —— 这一轮全程都在钉住的那一档里。",
        "tests/test_music_bar_only_after_playing.py::"
        "test_every_measuring_harness_pins_the_music_bar",
        "RN-195：实测这一轮 28 页跑 8.11 秒，而控制条由一个 **8 秒**定时器建 —— "
        "最后两页量到的是矮 42px 的可视区，前 26 页不是，同一份基线里混着两种"
        "坐标系（实测差 11~16 条/页），而分界线离边界只有 0.11 秒。"
        "⭐ 钉住只是「我打算量哪一档」，回验才是「这一轮真的全程都在那一档」",
    ),
    # ============================================ RN-174 / RN-401：准心页说实话
    Revert(
        "RN", "页头又去点名一颗按钮",
        "pages/crosshair_page.py",
        'description="调准心的形状、颜色、动效和击杀联动。总开关打开后，改哪一项当场就生效——"',
        'description="调准心的形状、颜色、动效和击杀联动。改完点右下角「绘制准心」写进游戏。"  #',
        "tests/test_crosshair_page_tells_the_truth.py::"
        "test_the_header_does_not_name_a_button_to_press",
        "RN-174：外审 5/6 票报「找不到保存/应用入口」——**现象真、归因全反**："
        "这一页压根没有「应用入口」这个东西（参数各自的槽里当场 save_config，"
        "准心是自绘覆盖层，不写任何游戏文件）。页头点名一颗按钮 = 告诉玩家"
        "「不点就没生效」，那是假的。⭐ 文案不许替代码编一个借口",
    ),
    Revert(
        "RN", "页头讲「当场生效」却不讲它的前提",
        "pages/crosshair_page.py",
        "总开关打开后，改哪一项当场就生效",
        "改哪一项当场就生效",
        "tests/test_crosshair_page_tells_the_truth.py::"
        "test_the_header_states_the_precondition_for_taking_effect",
        "RN-174：第一版把三句假话改成一句真话「改哪一项当场就生效」，"
        "**外审当场指出它还是半真话**（4/6 判高）—— `crosshair_enabled` 默认关着，"
        "而默认状态恰好就是新用户的状态。"
        "⭐⭐ **把假话改成真话时，漏掉了那句真话自己的前提**",
    ),
    Revert(
        "RN", "底栏又长出一颗「应用形状」的主按钮",
        "pages/crosshair_page.py",
        'self.action_bar.configure_primary("", None, visible=False)',
        'self.action_bar.configure_primary("导出准心", self._export_crosshair, visible=True)',
        "tests/test_crosshair_page_tells_the_truth.py::"
        "test_the_bottom_bar_offers_no_apply_shaped_button",
        "RN-174：这**正是第一版修法**，外审当场否掉——「置灰的『导出准心』极易被"
        "误认为是『保存/应用』按钮，导致玩家误以为当前修改未生效」。"
        "⭐⭐ 一颗灰着的、紫色的、蹲在右下角的按钮，形状本身就在说「这里有个保存动作」——"
        "而这一页没有。⇒ 我把 5/6 票那条原始困惑**换了个样子留在了原地**",
    ),
    Revert(
        "RN", "文案棘轮的方位词从句退化成摆设",
        "tests/test_help_copy_names_real_controls.py",
        r'    r"\s*(?:" + POSITION + r"的?\s*)?[「]([^「」]{1,24})[」]"',
        r'    r"\s*[「]([^「」]{1,24})[」]"',
        "tests/test_help_copy_names_real_controls.py::"
        "test_the_position_word_clause_is_not_vacuous",
        "RN-401：第一版正则要求动词**紧挨**引号，于是「点右下角「绘制准心」」"
        "「点本页的「启用自定闪光」」这类**一条都进不了分母**（50 → 59）。"
        "⭐ 而方位词恰恰是「硬指引」的标志 —— 这条棘轮最该盯的那一片，"
        "被它自己的正则整片切掉了",
    ),
    Revert(
        "RN", "帮助面板通路不再剔除注释",
        "tests/test_help_copy_names_real_controls.py",
        '    text = _strip_comments((REPO / "ui_help_panel.py").read_text(encoding="utf-8"))',
        '    text = (REPO / "ui_help_panel.py").read_text(encoding="utf-8")',
        "tests/test_help_copy_names_real_controls.py::"
        "test_comments_in_the_help_panel_are_not_read_as_user_copy",
        "RN-401：这条通路是**裸文本扫描**，不去注释就会把「记录这条缺陷的注释」"
        "读成给用户看的文案 —— 文案已经改对了，判据照旧红。"
        "页面通路早有 `_non_docstring_strings` 这层保护（RN-072/RN-163）。"
        "⭐⭐ **一个教训只修在它被发现的那条通路上，等于只修了一份副本**",
    ),
    Revert(
        "RN", "帮助面板又教用户去点一颗已删的按钮",
        "ui_help_panel.py",
        # ⚠ 锚点 2026-08-26 搬过一次家：RN-087 删掉了后半句「也可以去导航里的
        # 「基础设置」页…」，原锚点结尾那个分号跟着没了 —— **失效体检当场逮到**。
        # ⭐ 我删一句文案，而一条断点正锚在那句上；这就是 `--stale-only` 存在的理由。
        '"1. 在本页打开「自定闪光」总开关，再点「启动」开始后台监听<br>"',
        '"1. 点本页的「启用自定闪光」直接开<br>"',
        "tests/test_help_copy_names_real_controls.py::"
        "test_every_named_control_actually_exists",
        "RN-401 首跑逮到的真缺陷：「启用自定闪光」这颗按钮 **RN-192 早就删了**"
        "（启用归状态卡上的总开关，底栏那颗只管启动）。RN-192 当场改了页头、"
        "还在现场注释里写下「文案点名的控件名必须跟调用方一起走」——"
        "**却没人打开帮助面板那个文件**",
    ),
    Revert(
        "RN", "单行提示表被清空（判据静默什么都不测）",
        "tests/test_single_line_hints_stay_single_line.py",
        '    ("kill_icon", "装好的图标包会排在这一行",',
        '    ("kill_icon_DISABLED", "装好的图标包会排在这一行",',
        "tests/test_single_line_hints_stay_single_line.py::"
        "test_the_hint_is_still_one_line_after_the_page_is_fully_built",
        "RN-174：删掉 crosshair 那一格之后这张表只剩 1 条。"
        "⚠ pytest 对「参数化了零个用例」是**静默通过**的 —— 报告上看不出区别。"
        "⭐ 一条会随产品一起缩小的清单，必须有人盯着它的下界。"
        "⚠ 2026-08-29 批 25 改过一次锚点（那句文案退成了纯说明）—— "
        "⭐⭐ 而这次**不是失效体检先发现的，是回退验证的基线直接判红**："
        "那条判据自己带着分母守卫（找不到标签就报「判据在空转」），"
        "所以文案一改它当场喊疼。对照批 24 那两条改完文案照样绿的锚点 ⇒ "
        "⭐ **一条判据的锚点腐烂时会不会喊疼，取决于它有没有替自己写一条分母守卫**",
    ),
    # ============================================ RN-087：文案指路去一个不必去的地方
    Revert(
        "RN", "帮助文案又把人支去「基础设置」开开关",
        "ui_help_panel.py",
        '        "1. 在本页状态卡最上面打开「总开关」<br>"\n'
        '        "2. 选择准心形状',
        '        "1. 在基础设置中启用「自定义准心」开关<br>"\n'
        '        "2. 选择准心形状',
        "tests/test_help_copy_names_real_controls.py::"
        "test_no_help_text_sends_the_user_somewhere_they_no_longer_need_to_go",
        "RN-087：RN-144/147/155/189 早把总开关搬到了每一页自己的状态卡第一行，"
        "而帮助面板**九条**还在教用户「去基础设置启用某某开关」。"
        "⭐ RN-192 / RN-401 修好了 `flash` 那一条、还在现场注释里写下"
        "「文案点名的控件名必须跟调用方一起走」——**同一个文件里另外九条一动没动**，"
        "因为那条棘轮问的是「点名的控件**存不存在**」，"
        "而这九条点名的东西（基础设置里那颗开关）**确实存在**。"
        "⇒ ⭐⭐ **「文案说的东西存在」和「文案说的事该做」是两条判据**",
    ),
    Revert(
        "RN", "就地开关名单漏掉了走基类那五页",
        "tests/test_help_copy_names_real_controls.py",
        '        if re.search(r"class\\s+\\w+\\s*\\(\\s*SoundPageBase\\b", src):',
        '        if False and re.search(r"class\\s+\\w+\\s*\\(\\s*SoundPageBase\\b", src):',
        "tests/test_help_copy_names_real_controls.py::"
        "test_the_in_place_switch_roster_is_not_empty",
        "RN-087：`kill_sound` 那五页的总开关在 `SoundPageBase` 里（键是变量，"
        "AST 认不出来）⇒ 只扫页面自己的源码会把它们**整片漏掉** —— "
        "而这次九条错文案里正好有**五条**是它们的。"
        "⭐ **一份「哪些页适用」的名单，漏掉的那部分不会喊疼**（同 RN-186："
        "判据的页面范围就是它的分母）",
    ),
    # ============================================ RN-188：全站主按钮唯一性
    Revert(
        "RN", "又一页长出第二颗同名主按钮",
        "pages/hud_color_page.py",
        '        self.action_bar.configure_primary("保存 HUD 规则"',
        '        self.action_bar.configure_primary("保存 HUD 规则", self._save_hud_rules, visible=True)\n'
        '        self.action_bar.configure_extra("保存 HUD 规则", self._save_hud_rules, visible=True)\n'
        '        self.action_bar.extra_btn.setObjectName("primaryButton")\n'
        '        self.action_bar.configure_primary("保存 HUD 规则"',
        "tests/test_one_primary_button_per_screen.py::"
        "test_no_page_grows_a_new_pair_of_identical_primary_buttons",
        "RN-188：全站 28 页实测，**4 页同屏 >1 颗，且无一例外都是同一个动作出现两次**"
        "（viewmodel 保存到CFG ×2 / voice_output 添加槽位 ×2 / account 登录账号 ×2 / "
        "about 查看更新日志 ×2）。⭐ **两颗紫的等于零颗**（RN-139）。"
        "⭐⭐ 而 `viewmodel` 那一对是 **RN-078 的裁定亲手造出来的** ——"
        "它把「两个名字」统一成「一个名字」，解决了「以为是两件事」，"
        "却造出了「两颗一模一样的紫按钮」，隔了 5 天、跨了两个条目才被看见",
    ),
    Revert(
        "RN", "债表变成博物馆（修好了不回来删）",
        "tests/test_one_action_one_entrance.py",
        '    "preset_center": ("_save_changes",),',
        '    "preset_center": ("_save_changes", "_this_one_was_fixed_long_ago"),',
        "tests/test_one_action_one_entrance.py::"
        "test_the_rest_of_the_debt_only_shrinks",
        "RN-188 / RN-452：只判「变没变坏」的棘轮，在缺陷修好之后会**永远停在旧数上** ——"
        "从「守着一条线」退化成「记录一个历史」，而且**没有任何东西会说它退化了**。"
        "⇒ 三向都要红：新增 / 变多 / **已经不该在册**。同 RN-196 的 `KNOWN_COMPACT_DEBT`",
    ),
    Revert(
        "RN", "债表里的页被摘出导航，而实现文件还在",
        "gui_widget.py",
        '                ("viewmodel", "局内视角"),',
        '                # ("viewmodel", "局内视角"),',
        "tests/test_one_primary_button_per_screen.py::"
        "test_every_page_whose_file_exists_was_actually_scanned",
        "RN-188：这张债表记的是**完整产品**的实测值，而派生的功能子集里每一格都可能不同"
        "（实测：子集里 `account` 整页不存在、`about` 的按钮被机械替换改名且少一颗）。"
        "⭐ 「照闭源版文件集写死的断言，在子集仓里不是「更严」，是「错」」——**一周内第三次**。"
        "⇒ 判别式沿用批 11 那条：**缺的页必须连实现文件都不在**；"
        "实现文件还在却没扫到，就是**一整页被摘出了导航**，必须红。"
        "⚠ 这条断点防的正是「为了让子集跑绿而把整条 skip 掉」那种放宽",
    ),
    Revert(
        "RN", "全站扫描只走到一半（专家页静默漏掉）",
        "tests/test_one_primary_button_per_screen.py",
        "            _ui_mode.goto(win, page_id)",
        "            win.show_page(page_id, animated=False)",
        "tests/test_one_primary_button_per_screen.py::"
        "test_the_scan_actually_sees_the_pages",
        "RN-188：普通模式下 6 个专家页没有导航入口，不带 `force=True` 的 `show_page` "
        "会**静默 return** ⇒ 28 页只走到 22 页。⭐ 那条教训逐字写在 `_ui_mode.goto` "
        "的注释里，而我在普查脚本里用对了、换到判据里又自己抄了一遍 ——"
        "**一个教训只修在它被发现的那条通路上，等于只修了一份副本**",
    ),
    # =============== RN-190 / RN-464 / RN-465：fun_afterlife 补齐全站家具
    Revert(
        "RN", "fun 页又手搓一颗总开关",
        "pages/fun_page.py",
        '        self.master_switch_row = make_master_switch_row(',
        '        self.enable_box = QCheckBox("启用死亡刷短视频")\n'
        '        self.master_switch_row = make_master_switch_row(',
        "tests/test_fun_page_has_the_site_wide_furniture.py::"
        "test_this_page_uses_the_in_place_master_switch_row",
        "RN-190：16 个首页功能开关里另外 **15 个**都走共用那一行。"
        "手搓那颗的后果不是「少个组件」，是**方向不对称的同步**："
        "首页拨 → 页面会跟；**页面拨 → 首页那颗一动不动**（RN-107 族）。"
        "⭐ 而共用件不只是开关：双向同步、那句「改了会保存但游戏里不生效」、"
        "参数区降权三件套都在里面 —— **一件一件补，就是一件一件会漏**",
    ),
    Revert(
        "RN", "fun 页的状态又不说它对谁生效",
        "pages/fun_page.py",
        '            "已启用 · 只在「" + " / ".join(picked) + "」里触发；"',
        '            "已启用" + ("" if picked else "") + ";"',
        "tests/test_fun_page_has_the_site_wide_furniture.py::"
        "test_the_status_says_which_modes_it_actually_fires_in",
        "旧账 RN-251：默认触发模式是 `[\"deathmatch\", \"casual\"]`，**不含竞技/搭档**，"
        "而原来只有「一个都没勾」时才说不会触发 ⇒ 打排位的人看到干净的「已启用」。"
        "外审 S4 **4/4** 报「会误以为功能失效」。"
        "⚠⚠ 而**判断题那把尺子看不到这条**：整页图上 6/6 答对、依据逐字指向"
        "「竞技未勾选」。⭐⭐⭐ 两个数不矛盾，**它们量的是不同的时刻** ——"
        "判断题问「你现在看着这一屏看得出来吗」，而缺陷发作在他**离开这一屏、"
        "进游戏死了之后**。**判断题默认「用户正看着这一屏」。**",
    ),
    Revert(
        "RN", "fun 页又手写一份「要无边框窗口化」",
        "pages/fun_page.py",
        '        self.notice_label = make_overlay_requirement_label("短视频窗口")',
        '        self.notice_label = QLabel("需要游戏使用「全屏窗口化」显示模式。")',
        "tests/test_fun_page_has_the_site_wide_furniture.py::"
        "test_the_overlay_requirement_uses_the_shared_sentence",
        "RN-429：那句话的唯一一份在 `widgets/overlay_requirement.py`（批 22 收的）。"
        "⭐⭐ 批 24「共用件省的是重复，不是判断」的背面：**手写一份，"
        "就等于把自己从后续每一次改进里摘出去**",
    ),
    Revert(
        "RN", "fun 页又没有帮助面板",
        "pages/fun_page.py",
        '        install_help_panel(header.title_row, header.body, PAGE_HELP_TEXTS["fun_afterlife"])',
        '        pass  # 不装帮助面板',
        "tests/test_fun_page_has_the_site_wide_furniture.py::"
        "test_this_page_has_a_help_panel",
        "RN-001b：这一页是全站 22/28 里**没有**帮助面板的那几页之一。"
        "⭐ 全站家具普查（真源）：底部操作栏 26/28、状态徽章 26/28、帮助面板 22/28 ——"
        "而 `fun_afterlife` 是**唯一一个真正的页面**（`basic` 内联在主窗里）三样全缺",
    ),
    Revert(
        "RN", "fun 页三颗按钮又回到一个层级都没有",
        "pages/fun_page.py",
        "        style_as_primary_button(self.login_button)",
        "        pass  # 不给层级",
        "tests/test_fun_page_has_the_site_wide_furniture.py::"
        "test_the_buttons_have_a_hierarchy",
        "外审 ③ 有 5/6 把「预览效果」读成「只是打开东西看看」，"
        "而它会在屏幕上真的弹出一块贴屏窗口。"
        "⭐ 第一次使用必须先登录（没登录刷不出内容）⇒ 那一颗才是主按钮",
    ),
    # ================== RN-454 / RN-460 / RN-462 / RN-463：一件事一颗开关
    Revert(
        "RN", "GSI 闸门又长回两道（子开关复活）",
        "gsi_handler_music.py",
        "        if not config.music_enabled:\n            return\n",
        "        if not config.music_enabled:\n            return\n"
        "        if not getattr(config, 'music_game_link_enabled', True):\n            return\n",
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_the_game_link_has_exactly_one_switch",
        "RN-454：那个键在整个产品里只有这一个消费点，而且就在总开关下面**紧挨着的一行** —— "
        "它是纯 AND 项，没有任何独立作用，而两颗开关的默认值**相反**。"
        "⭐⭐⭐ **一件事一颗开关。**"
        "⚠ 这条断点用 AST 判（属性访问），不用字符串 —— "
        "第一版按行做字符串匹配，当场把一行讲这条缺陷来历的 **docstring** 报成了使用。"
        "⭐ **在源码上做字符串匹配，会把「讲这件事」和「做这件事」算成一件事**",
    ),
    Revert(
        "RN", "撤开关撤过头：总开关也没了",
        "pages/music_page.py",
        '            self, "music_enabled", "音乐联动")',
        '            self, "music_enabled_XX", "音乐联动")',
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_the_game_link_has_exactly_one_switch",
        "RN-454 反面守卫：撤的是**副本**，不是这件事本身。"
        "⭐⭐ 同批 31 那条：**一条只判「坏东西没了」的判据，"
        "挡不住「好东西也一起没了」**",
    ),
    Revert(
        "RN", "总开关关着又把整页置灰",
        "pages/music_page.py",
        # ⚠⚠ 这条断点第一版的"破坏"是加一行
        #   `self.link_content_frame_pending_disable = True` —— 那行**什么都不做**，
        #   于是判据当然绿，回退验证判它假绿。
        #   ⭐ **一个模拟不出缺陷的破坏，得到的绿是无意义的。**
        #   现在换成真的按总开关禁用那张卡 —— 也就是 RN-454 最顺手的那个错误修法。
        "        layout.addWidget(self.link_content_frame)",
        "        self.link_content_frame.setEnabled(bool(config.music_enabled))\n"
        "        layout.addWidget(self.link_content_frame)",
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_turning_the_master_off_does_not_grey_out_the_page",
        "RN-454 的第二道守卫：合并两颗开关时最顺手的写法是 "
        "`link_content_frame.setEnabled(config.music_enabled)` —— 一行，看着对，"
        "而它会把新用户的整页禁用控件从 **2 顶到 27**，"
        "正是批 17 实测后改判为不做的 RN-421。"
        "⭐ **一个正确的合并，可以把一条已经被否掉的方案偷偷放回来**",
    ),
    Revert(
        "RN", "曲目列表又变回只能选一首",
        "pages/music_page.py",
        "        self.playlist_widget.setSelectionMode(QListWidget.ExtendedSelection)",
        "        self.playlist_widget.setSelectionMode(QListWidget.SingleSelection)",
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_the_playlist_really_allows_what_the_page_promises",
        "RN-460：按钮写「删除选中」、确认框写「选中的 N 首」、胶囊写「选中 · N 首」——"
        "三处都在承诺多选。改前判断题「能不能一次删两首」**有歌的两档 11/12 答「做得到」**，"
        "依据逐字就是那三处承诺 ⇒ **承诺被 100% 读到了，产品不兑现**。"
        "⚠⚠ 改后同一题票数**一模一样**（B 场景 6/6「做得到」）——"
        "⭐⭐⭐ **同一个票数，在修改前后指向的是两件相反的事实**；"
        "看图看不见 `selectionMode`，所以这条只能由**行为**判据证",
    ),
    Revert(
        "RN", "总开关旁边又不说它管哪一件事",
        "pages/music_page.py",
        "        overview_layout.addWidget(self.master_switch_scope_label)",
        "        pass  # 范围说明不要了",
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_the_master_switch_says_what_it_does_not_block",
        "RN-462：⭐⭐⭐ **我撤掉的那颗冗余开关，同时是唯一一处界定范围的说明** ——"
        "「允许**游戏状态**自动控制音乐」身兼两职，我撤它时只看见了「它是一颗多余的开关」。"
        "改后外审 7 发冒出「以为整个播放器未启用、不敢使用」（改前 0 发）。"
        "⚠ 那句说明其实还在（联动卡里），只是批 32 把列表提到前面之后掉到了折线以下 ⇒ "
        "⭐ **解释性文字要放在困惑发生的位置**",
    ),
    Revert(
        "RN", "抬了 schema 版本号却不给迁移函数",
        "config.py",
        "CONFIG_MIGRATIONS = {1: _migrate_1_to_2}",
        "CONFIG_MIGRATIONS = {}",
        "tests/test_config_schema_migration.py::"
        "test_the_migration_is_actually_registered",
        "RN-463：`_run_schema_migrations` 遇到没注册的版本会 **break** ⇒ "
        "后面的迁移**全部静默跳过**。⭐ **版本号只许和迁移函数一起往上抬。**"
        "⚠ 这个框架从 P4.2 建起一直是空的：写好了、接线了、有 4 条测试，"
        "**但从来没跑过一个真正的迁移** —— "
        "⭐⭐ **一条从没被走过的通路，和一条走不通的通路，平时长得一模一样**",
    ),
    Revert(
        "RN", "迁移把「本来不联动」的老用户改成联动",
        "config.py",
        "            cfg.music_enabled = False",
        "            pass  # 不动总开关",
        "tests/test_config_schema_migration.py::"
        "test_the_migration_keeps_a_user_who_had_turned_linking_off",
        "RN-454 的迁移：老用户里只有「总开关开 + 子开关关」这一种组合会被改变行为——"
        "他今天是**不联动**，撤掉子开关后会突然开始联动。"
        "⭐⭐⭐ **迁移的方向要朝「保住用户已经表达过的意图」那边倒，"
        "不朝「保住某个键的字面值」那边倒。**",
    ),
    # ======================= RN-455 / RN-457 / RN-458 / RN-459：music 说的话得是真的
    Revert(
        "RN", "页头又把新用户指向那条还没建的控制栏",
        "pages/music_page.py",
        '            description="放本地音乐或在线 URL，双击列表里的歌就开始放；"',
        '            description="放本地音乐或在线 URL。底部控制栏是手动播放；"',
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_the_page_header_does_not_point_at_a_bar_that_may_not_be_there",
        "RN-455：`playback_has_ever_started()` 为假时那条栏**根本没建**（RN-195/批 9）。"
        "⭐⭐⭐ **一个正确的收窄，把它自己的入口关在了自己后面。**"
        "外审在「有歌、没播过」那一档 7/8 判高，而空列表那档只有 1/8 ——"
        "⭐ 遮住它的不是产品做对了，是那一档本身让人问不出这个问题",
    ),
    Revert(
        "RN", "帮助面板第 2 步又教人去用那条控制栏",
        "ui_help_panel.py",
        '        "2. <b>双击列表里的歌名开始播放</b>——这一页本身没有播放按钮<br>"',
        '        "2. 使用底部控制栏播放、暂停、切换曲目<br>"',
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_the_help_panel_does_not_point_at_a_bar_that_may_not_be_there",
        "RN-455 的另一半。⚠ 这条断点**故意钉在另一个文件上**：同一条缺陷"
        "同时住在页面和帮助面板里，只钉一处的话，另一处腐烂了没人知道",
    ),
    Revert(
        "RN", "撤销又写回下游（config），屏幕和播放器不动",
        "pages/music_page.py",
        '                self.player.restore_playlist(tracks)\n'
        '                self.refresh_playlist_display()\n'
        '                self.logger.info(f"撤销删除 {len(entries)} 首音乐")',
        '                config.music_playlists[name] = tracks\n'
        '                config.save_config()\n'
        '                self.refresh_playlist_display()\n'
        '                self.logger.info(f"撤销删除 {len(entries)} 首音乐")',
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_undo_actually_puts_the_tracks_back_on_screen",
        "RN-457：⭐⭐⭐ **撤销半成功比撤销没用更坏。**实测原状点完撤销："
        "config 5 首、`player.playlist` 4 首、屏幕 4 首 —— 用户看到什么都没发生。"
        "⭐ **写在下游的撤销，会安静地把内存和磁盘拆成两份。**"
        "⚠ 这条断点钉的是**行为**不是「有没有调 toast_undo」——"
        "后者在这个破坏下照样是绿的（调是调了，写错了地方）",
    ),
    Revert(
        "RN", "三颗红里又有一颗没有撤销",
        "pages/music_page.py",
        '                toast_undo(f"已清空 {len(backup)} 首音乐", _undo)',
        '                pass  # 清空列表不给撤销',
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_every_red_button_on_the_music_page_can_be_undone",
        "RN-457：外审 18/18 说「三颗红没有区分危险程度」，16/18 猜「删除」最难挽回，"
        "只有 2/18 提到这一颗 —— 而它才是唯一真挽不回的。"
        "⭐⭐ **他们按「名字听起来多严重」排序，而那个排序和真实的可挽回性正好错开。**"
        "⇒ 修法不是把颜色改得不一样，是把「三颗一样」这句话变成真的",
    ),
    Revert(
        "RN", "又长出一个建了就 hide 的死控件",
        "pages/music_page.py",
        '        scroll_layout.addWidget(overview_card)',
        '        self.music_summary_label = QLabel("")\n'
        '        self.music_summary_label.hide()\n'
        '        overview_layout.addWidget(self.music_summary_label)\n'
        '        scroll_layout.addWidget(overview_card)',
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_no_judge_pins_text_inside_a_control_nobody_can_see",
        "RN-458 / RN-009 族。⚠ 这条断点**不钉那条棘轮**（`MAX_REMAINING`）——"
        "棘轮只判「总数变没变大」，而这里加回来的是 music 自己那一份，"
        "总数会从 19 变 20，棘轮确实会红。但真正该守的是**这一页**，"
        "所以钉页级那条。⭐⭐⭐ 顺带记住批 32 查出来的那件事："
        "这条棘轮**从来没数过 music** —— 它按属性名全等匹配 `summary_label`，"
        "而这一个叫 `music_summary_label`。"
        "**一个按名字找的判据，被一次改名绕开了，而改名的人并不是想绕开它**",
    ),
    Revert(
        "RN", "同一件事又在一张卡里说了五遍",
        "pages/music_page.py",
        '        self.play_settings_group.setToolTip(detail_text)',
        '        self.play_mode_hint_label = QLabel(\n'
        '            f"当前默认模式为{mode_text}，只影响底部常驻播放器的默认切歌策略。")\n'
        '        self.play_settings_group.setToolTip(detail_text)',
        "tests/test_music_page_tells_the_truth_about_playing.py::"
        "test_the_play_mode_card_does_not_say_the_same_thing_five_times",
        "RN-459：那张卡真正的内容只有 4 个单选钮，而「只影响底部常驻播放器」"
        "在里面出现 5 处。⭐ 外审 18/18 全部答对了这个设置管的是谁 ——"
        "**这件事早就传达成功了，多说的那几遍是纯成本**",
    ),

    # ============================================ RN-404 / RN-416 / RN-452：一个动作一个入口
    Revert(
        "RN", "卡里又放了一颗底栏已经有的按钮",
        "pages/viewmodel_page.py",
        '        self._cfg_status_label = QLabel("")',
        '        from PySide6.QtWidgets import QPushButton as _QPB\n'
        '        _dup = _QPB("保存到CFG")\n'
        '        _dup.clicked.connect(self._save_viewmodel_cfg)\n'
        '        cfg_layout.addWidget(_dup)\n'
        '        self._cfg_status_label = QLabel("")',
        "tests/test_one_action_one_entrance.py::"
        "test_the_four_renovated_pages_have_exactly_one_entrance",
        "RN-404：同一个动作两个入口。外审行为题 16 发 16/16 逐字报出这一对，"
        "理由一律是「无法判断它们是不是同一件事」，而 16/16 同时答「担心点错」。"
        "⭐ RN-078 的裁定亲手造出了它：把两个名字统一成一个，"
        "解决了「以为是两件事」，却造出了「两颗一模一样的紫按钮」",
    ),
    Revert(
        "RN", "撤重复撤过头：两颗一起没了",
        "pages/viewmodel_page.py",
        '        self.action_bar.configure_primary("保存到CFG", self._save_viewmodel_cfg, visible=True)',
        '        self.action_bar.configure_primary("", None, visible=False)',
        "tests/test_one_action_one_entrance.py::"
        "test_removing_the_copy_did_not_remove_the_action",
        "RN-452 反面守卫：撤的是**副本**，不是动作本身。"
        "⭐⭐ **这种错不会让主刀那条判据变红** —— 重复确实没有了，"
        "只是这件事从此没人能做了。"
        "⭐ 一条只判「坏东西没了」的判据，挡不住「好东西也一起没了」",
    ),
    Revert(
        "RN", "同文案但不同方法的第二个入口（AST 看不见的那一半）",
        "pages/about_page.py",
        '        self.copy_diag_button = QPushButton("复制诊断信息")',
        '        _fake = QPushButton("打开官网")\n'
        '        _fake.clicked.connect(lambda: None)\n'
        '        fb_row.addWidget(_fake)\n'
        '        self.copy_diag_button = QPushButton("复制诊断信息")',
        "tests/test_one_action_one_entrance.py::"
        "test_no_visible_button_text_appears_both_in_a_card_and_in_the_bar",
        "RN-452：`about` 那一对「打开官网」**绑的不是同一个方法** —— "
        "底栏接 `_open_website`、卡内接 `_open_official_site`，"
        "而两个方法的函数体逐字相同。⇒ **一条按「绑同一个方法」找重复的判据，"
        "挡不住「先把方法复制一遍」**。所以按文案的这条运行时判据必须同时存在。"
        "（反过来，`voice_output` 的「导出 / 导出配置」文案不同、方法相同，"
        "只有 AST 那条看得见 —— ⭐ **两条判据各自都有对方看不见的那一半**）",
    ),
    Revert(
        "RN", "撤走按钮后，剩下那行字不说动作去哪儿了",
        "pages/viewmodel_page.py",
        '                "⚠ 设置改过了，还没写进 CFG —— 点右下角那颗「保存到CFG」。")',
        '                "⚠ 未同步")',
        "tests/test_one_action_one_entrance.py::"
        "test_the_card_that_lost_its_button_says_where_the_action_went",
        "RN-452：改前 4 发没有一发提过这行字；撤掉卡内那颗按钮之后，"
        "同题同图 **3/3** 说「分不清左边那个是可点击的同步按钮还是状态展示」。"
        "⭐⭐⭐ **一个控件怎么被读，由它的邻居决定** —— "
        "那行字一个字都没改，只是它的邻居没了，于是它接管了按钮的位置和读法",
    ),
    Revert(
        "RN", "脏标记又从屏幕上的文案里读回来",
        "pages/viewmodel_page.py",
        "        return bool(getattr(self, \"_cfg_dirty\", False))",
        "        cfg_text = self._cfg_status_label.text().strip()\n"
        "        return (\"未保存\" in cfg_text) or (\"已修改\" in cfg_text)",
        "tests/test_one_action_one_entrance.py::"
        "test_the_dirty_flag_is_not_read_back_out_of_a_label",
        "RN-452：这一页的脏/净判断原来是对一句**屏幕上的文案**做子串匹配算出来的，"
        "而底栏回执、三张卡摘要、五颗状态芯片全都读它。"
        "⭐⭐⭐ **一句文案同时是状态真源时，任何一次文字润色都是一次行为变更** —— "
        "批 31 只是把那句话改得更像一句话，整页的脏/净判断当场反了",
    ),
    Revert(
        "RN", "扫描器认不出底栏配置调用（判据空转）",
        "tests/test_one_action_one_entrance.py",
        '        if n.func.attr in ("configure_primary", "configure_secondary") and len(n.args) >= 2:',
        '        if n.func.attr in ("configure_primary_RENAMED",) and len(n.args) >= 2:',
        "tests/test_one_action_one_entrance.py::test_the_scan_is_not_blind",
        "RN-169：`configure_primary` 一旦改名，下面每一条断言都会**无条件通过**。"
        "⭐ 先证明它看得见东西，再让它去断言「没问题」",
    ),
    # ============================================ RN-406：选中自定义却什么都不画
    Revert(
        "RN", "样式徽章又只报名字、不报后果",
        "pages/crosshair_page.py",
        '            ("warning" if blank_custom else "info",\n'
        '             f"样式 · {style_text}（未绘制）" if blank_custom else f"样式 · {style_text}"),',
        '            ("info", f"样式 · {style_text}"),',
        "tests/test_crosshair_custom_style_is_honest.py::"
        "test_the_badge_says_the_consequence_not_just_the_name",
        "RN-406：`样式 · 自定义` 这句话是**真的**，但它回答的不是用户此刻的问题"
        "（「我选了它，为什么屏幕上什么都没有」）。而且它是 info 色 ——"
        "和「十字」「圆圈」那些完全正常的状态长得一模一样。"
        "⭐ 让**颜色**携带「现在能不能用」，是这条修法里唯一结构性的部分",
    ),
    Revert(
        "RN", "紧凑摘要在 0 点时又闭嘴了",
        "pages/crosshair_page.py",
        '                f"自定义 {custom_points} 点" if custom_points else "自定义未绘制")',
        '                f"自定义 {custom_points} 点" if custom_points else "")',
        "tests/test_crosshair_custom_style_is_honest.py::"
        "test_the_compact_summary_does_not_go_quiet_exactly_when_it_matters",
        "RN-406：原状是 `if style_value == \"custom\" and custom_points:` ——"
        "有点时才说，**0 点时整句消失**。⭐⭐ **一个在最需要说话的时候恰好闭嘴的提示，"
        "比没有这个提示更糟**：它让「一切正常」和「什么都画不出来」"
        "在紧凑档里长得一模一样",
    ),
    Revert(
        "RN", "「没画过就什么都不画」这条事实没人看着了",
        "crosshair_overlay.py",
        "    points = frame.custom_points or ()\n    if not points:\n        return",
        "    points = frame.custom_points or ()\n    if not points:\n        points = ((15, 15),)",
        "tests/test_crosshair_custom_style_is_honest.py::"
        "test_a_custom_crosshair_with_no_points_really_draws_nothing",
        "RN-406：本页有四句文案在说「未绘制 ⇒ 屏幕上不会出现准心」。"
        "渲染器哪天加了兜底，那四句**同时变成假话**，而没有任何一条文案判据看得见。"
        "⭐ **一句文案所依赖的事实，要有判据看着**（同 RN-174 那条"
        "`..._never_writes_a_game_file`）",
    ),
    Revert(
        "RN", "「有没有画过」这个判断被抄了第二份",
        "pages/crosshair_page.py",
        "        blank_custom = self._custom_style_is_blank()",
        '        blank_custom = (style_value == "custom" and not custom_points)',
        "tests/test_crosshair_custom_style_is_honest.py::"
        "test_the_blank_custom_judgement_has_exactly_one_source",
        "RN-406：这个判断同时决定四个地方的说法（徽章色阶与文案、紧凑摘要、"
        "样式卡副文案、自定义卡副文案）。抄成第二份，改一处就造出"
        "「同屏两处说法不一致」（RN-107 族）。"
        "⭐ 上面那几条文案判据**全都能被「在四个地方各抄一份 if」满足** ——"
        "所以必须另有一条直接查调用点的",
    ),
    Revert(
        "RN", "抓像素那行又变回悬空指针（判据随机把进程打死）",
        "tests/test_master_switch_effect_is_honest.py",
        "    image = widget.grab().toImage()          # ← 引用留住，别让它变成临时对象\n"
        "    return image.constBits().tobytes()",
        "    return widget.grab().toImage().bits().tobytes()",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_pixel_grab_keeps_the_image_alive",
        "RN-433：`bits()` 返回的是指向 QImage 缓冲区的**裸指针**，"
        "链式写法里那张 QImage 没有任何 Python 引用 ⇒ 读已释放内存。"
        "⭐⭐ 要害是它的**失败方式**：不是判据变红，是**进程当场死掉**，"
        "而 `revert_verify` 的基线阶段只看退出码 ⇒ 报成「基线就不绿」，"
        "整台回退验证停摆（RN-194 同族）。"
        "⭐ **一条判据的失败方式不止「红」一种；只有「红」那一种会说人话。**"
        "⚠ 所以这条断点**不能**指向 `..._changes_pixels` 自己 —— 那条被改坏之后"
        "是**随机**崩，回退验证会拿到一个时红时绿的结果。"
        "⭐ **一条判据要能被验证，它的失败必须是确定的。**",
    ),

    # ============================================ RN-175 族：一个动作一个生效点
    #
    # ⭐ 这一页的**行为**一直是对的（`_apply_preset` 一个字节都没写进游戏），
    # 错的是三个词。所以断点分两种：管措辞的，和管行为的 —— 谁也替不了谁。
    Revert(
        "RN", "预设按钮退回听起来像一次提交的词",
        "pages/hud_color_page.py",
        'QPushButton("载入这套")',
        'QPushButton("应用预设")',
        "tests/test_hud_color_has_one_commit_point.py::"
        "test_the_preset_button_does_not_sound_like_a_commit",
        "RN-175：外审 4/6 票说「应用预设」和底栏「保存 HUD 规则」构成**双重确认**。"
        "⭐ 查实这颗按钮的行为一直只是「填进编辑区」—— **错的只是那个词**。"
        "⭐ 一个动作只有一个生效点",
    ),
    Revert(
        "RN", "预设动作变成第二个生效点",
        "pages/hud_color_page.py",
        "        self._apply_rules_to_ui(profile, preset_rules)\n"
        "        self._set_dirty(True)",
        "        self._apply_rules_to_ui(profile, preset_rules)\n"
        "        self._set_dirty(True)\n        config.save_config()",
        "tests/test_hud_color_has_one_commit_point.py::"
        "test_applying_a_preset_still_writes_nothing_to_the_game",
        "RN-175：⭐ **一条管措辞的判据，和一条管行为的判据，谁也替不了谁** ——"
        "词改对了、哪天有人给它加一句 `save_config()`，双重确认就又回来了，"
        "而管措辞那条全绿",
    ),
    Revert(
        "RN", "状态胶囊退回一词两义的「同步」",
        "pages/hud_color_page.py",
        '"保存 · 已存下"',
        '"保存 · 已同步"',
        "tests/test_hud_color_has_one_commit_point.py::"
        "test_the_save_state_chip_does_not_say_synced",
        "RN-426：那句「已同步」**在总开关关着时也是真话**（它由 `_dirty` 决定，"
        "说的是「你的改动已经写出去了」）。⭐⭐ **一句真话被读成另一件事，"
        "和一句假话，要用两种修法** —— 前者不能靠「改成正确的说法」修，"
        "它本来就正确；只能换掉那个一词两义的词",
    ),
    Revert(
        "RN", "「怎么在游戏里生效」退回只活在模态框里",
        "pages/hud_color_page.py",
        '                "已写进游戏的 cfg（并挂进 autoexec）；"\n'
        '                "当局要立刻见效，在游戏控制台敲 exec cs2customizer.cfg。")',
        '                "HUD 规则要点一下保存才会写入")',
        "tests/test_hud_color_has_one_commit_point.py::"
        "test_the_bottom_bar_says_how_it_takes_effect_in_game",
        "RN-131：那条指令原来**只在保存成功的模态框里出现过一次**，关掉就没了，"
        "而外审仍有 3 发在问「是自动生效还是要在控制台输入指令」。"
        "⭐ **一句只在模态框里出现过的说明，等于没有说明。** "
        "⚠ 措辞只描述代码真做过的事 —— ⛔ 不写「下次进游戏会自动生效」，"
        "那是**游戏**会不会执行 autoexec，我没有证据",
    ),
    Revert(
        "RN", "共用回执重新把「自动保存」当成全站事实",
        "pages/hud_color_page.py",
        "    SAVES_AUTOMATICALLY = False",
        "    SAVES_AUTOMATICALLY = True",
        "tests/test_hud_color_has_one_commit_point.py::"
        "test_no_page_says_no_button_needed_while_showing_a_button",
        "RN-436：批 16 把「改动已自动保存，**不用点任何按钮**」当成全站事实铺到 15 页，"
        "而实测**15 页里 2 页不是**（`hud_color` 摆着「保存 HUD 规则」、"
        "`magnifier` 摆着「应用」）—— 同一行底栏里，左边说「不用点任何按钮」，"
        "右边就是那颗必须点的按钮。"
        "⭐⭐ **一句被当成全站事实的话，只要有一页不成立，它在那一页就是假的** —— "
        "而共用件让它假得整整齐齐，15 页一个模子。⭐ **共用件省的是重复，不是判断。** "
        "⚠ 判据的分母**由机器自己找**（带总开关的页 × 页上带提交词的可见按钮），"
        "不是手写名单 —— 将来哪一页加了保存按钮，它会自己报到",
    ),

    # ============================================ RN-150：禁用了但看不出来
    #
    # ⭐ 这一族的度量花了四把尺子才定下来（1 / 41 / 14 / 1 四个不同的数）——
    # 完整过程写在判据的模块 docstring 里。断点打在**最后那把尺子承重的地方**。
    Revert(
        "RN", "禁用的主按钮退回「暗一档的品牌色」",
        "theme_manager.py",
        "QPushButton#primaryButton:disabled {{\n"
        "                background-color: {self._hex_to_rgba(c.bg_tertiary, 90)};",
        "QPushButton#primaryButton:disabled {{\n"
        "                background-color: {c.accent_hover};",
        "tests/test_disabled_buttons_look_disabled.py::"
        "test_a_disabled_button_stops_looking_like_the_brand_colour",
        "RN-150：定点实测同一屏底栏两颗**都禁用**的按钮 —— "
        "次按钮 `(0,0,0)`（透明露底）、主按钮 `(61,36,112)`（`#3d2470` 一块紫色填充）。"
        "⭐ 这条原则本文件里早就写过（`#dangerButton:disabled` R7/D-06："
        "「红色的语义是『点下去会毁数据』，禁用的语义是『你点不了』，两者同时出现是自相矛盾的」），"
        "只是从没铺到主按钮 —— 品牌色的语义是「这是主要动作，点它」，同样自相矛盾。"
        "⚠ 判据的阈值**由本主题的中性底色实算**，不是拍的数字："
        "⭐⭐ **「中性」不是一个绝对值，是一个相对位置**",
    ),
    Revert(
        "RN", "降权规则重新盖掉禁用态（禁用的和可点的长得一样）",
        "theme_manager.py",
        '            QFrame#card[masterOff="true"] QPushButton#primaryButton:disabled {{',
        '            QFrame#card[masterOff="true"] QPushButton#primaryButtonXX:disabled {{',
        "tests/test_disabled_buttons_look_disabled.py::"
        "test_a_disabled_button_still_looks_like_a_button",
        "RN-150 ⚠⚠ **这一条是「防止我自己改过头」的守卫逮到的，而它逮到的是别人埋的**："
        "`QFrame#card[masterOff=\"true\"] QPushButton#primaryButton` 的特异度"
        "（多一个 id + 一个属性）压过 `#primaryButton:disabled`，"
        "于是在降权的卡片里，一颗**禁用**的主按钮和一颗**可点**的长得逐字节相同"
        "（`kill_sound` 空库那颗实测）。⭐⭐ 那是批 16~20 五批降权留下的**背面代价** ——"
        "⭐ **一条修法的代价，长在它自己修好的那件事的背面**（本工程第四次）",
    ),
    Revert(
        "RN", "按钮扫描器只认加载过的页（分母塌成个位数）",
        "tests/test_disabled_buttons_look_disabled.py",
        "    for page_id in list(main_window._page_names.keys()):",
        "    for page_id in list(main_window.pages.keys()):",
        "tests/test_disabled_buttons_look_disabled.py::"
        "test_the_sweep_actually_sees_the_buttons",
        "RN-150：第一版就是这么写的 —— 那时只有 1 页加载过，**量到 7 颗按钮，"
        "而全站有 247 颗**，而且它不报错。"
        "⭐ **一个算错分母的扫描器，长得和「这份界面很干净」一模一样。** "
        "页面名单的真源是 `win._page_names`（`ui_shot_capture:286` 一直这么写）",
    ),
    Revert(
        "RN", "阳性对照被摘掉（判据退化成「我改过的那一类被我改过了」）",
        "tests/test_disabled_buttons_look_disabled.py",
        '    secondary = [r for r in swept if r[1] == "secondaryButton"]',
        '    secondary = [r for r in swept if r[1] == "nope"]',
        "tests/test_disabled_buttons_look_disabled.py::"
        "test_the_secondary_buttons_are_the_positive_control",
        "RN-150：次按钮是全站最多的一类（150 颗），**本来就合格** ⇒ 免费的阳性对照。"
        "⭐ 没有它，上面那条判据可能只是在证明「我改过的那一类被我改过了」"
        "（批 17 那条教训：没有阳性对照的尺子，和一把只会读出一种答案的尺子分不开）",
    ),

    # ============================================ RN-429：覆盖层的运行前提
    #
    # ⭐ 这一族的分母**不是 import 图**：`kill_icon_page` 只负责配置，
    # 播放它的 `kill_icon_player` 在 GSI 事件链上 —— 两者之间没有任何 import 边。
    # 三种自动取法（一跳 / 传递闭包 / 两跳+标 False）全部要么漏要么滥，
    # 所以分母是**页面自己的声明**，由下面这几条断点看着别塌。
    Revert(
        "RN", "覆盖层模块不再表态自己画给谁看",
        "crosshair_overlay.py",
        "DRAWN_OVER_THE_GAME = True",
        "DRAWN_OVER_THE_GAME_TODO = True",
        "tests/test_overlay_pages_state_their_requirement.py::"
        "test_every_always_on_top_module_says_who_it_is_drawn_for",
        "RN-429：`crosshair_overlay` 和 `ui_toast` 在代码上长得一模一样（都置顶），"
        "差别只在**画给谁看** —— 而那个差别机器推不出来。"
        "⭐ 所以它必须被写下来，且不许沉默：新写一个覆盖层的人会被这条逼着回答一次",
    ),
    Revert(
        "RN", "那句运行前提从屏幕上消失",
        "pages/kill_icon_page.py",
        '        status_card_layout.addWidget(make_overlay_requirement_label("击杀图标"))',
        "        pass",
        "tests/test_overlay_pages_state_their_requirement.py::"
        "test_every_page_that_draws_over_the_game_says_so_out_loud",
        "RN-429：`kill_icon` 是这一族里**任何 import 分母都够不着**的那一页 —— "
        "它进得了判据，靠的是本页自己声明 `DRAWS_OVER_THE_GAME`。"
        "⚠ 判据量的是**渲染出来的屏幕文案**，不是页面源码里的字符串："
        "那句话住在共用件里，页面文件里一个字都没有。"
        "⭐⭐ **判据问的必须是「屏幕上有没有」，不是「这个文件里有没有」**",
    ),
    Revert(
        "RN", "那句话只说了一半（不说独占全屏会怎样）",
        "widgets/overlay_requirement.py",
        'f"——独占全屏会把它整个盖住，什么都不会显示。"',
        'f"。"',
        "tests/test_overlay_pages_state_their_requirement.py::"
        "test_every_page_that_draws_over_the_game_says_so_out_loud",
        "RN-429：这句话必须同时说清**该怎么做**和**否则会怎样**。"
        "⭐ 语序按批 18 的账：动作在前、后果在后 —— 同一句话换个语序，"
        "「他知不知道该干什么」从 57% 到 100%。"
        "⚠ 判据认的是**语义**不是措辞（`advanced` 写「全屏独占」、"
        "`fun` 写「全屏窗口化」，都算过）—— 同义词表列成数据，"
        "有人换第三种说法时红的是那张表，不是那一页",
    ),
    Revert(
        "RN", "这条前提跟着总开关一起变淡",
        "widgets/overlay_requirement.py",
        '    label.setObjectName(OVERLAY_HINT_OBJECT_NAME)',
        '    label.setObjectName("hintLabel")',
        "tests/test_overlay_pages_state_their_requirement.py::"
        "test_the_requirement_does_not_fade_with_the_master_switch",
        "RN-429：这条前提**与总开关无关** —— 不管开没开它都成立。"
        "⭐ 而开关关着的时候玩家正在配，**那恰恰是最需要看到它的时刻**；"
        "把它卷进「关着 ⇒ 整页降权」就是「越需要越看不见」。"
        "⚠ 量的是**像素**不是属性：批 19 证过属性设上了、QSS 写对了，"
        "屏幕上照样可以一个像素都不变；反过来也一样",
    ),
    Revert(
        "RN", "阳性对照被摘掉（判据退化成「我改过的页面被我改过了」）",
        "pages/fun_page.py",
        "DRAWS_OVER_THE_GAME = True",
        "DRAWS_OVER_THE_GAME = False",
        "tests/test_overlay_pages_state_their_requirement.py::"
        "test_the_declaration_has_not_quietly_emptied_itself",
        "RN-429：`advanced` 与 `fun_afterlife` **早在本条立案之前就用自己的话**"
        "写了这条前提 ⇒ 它们是免费的阳性对照。"
        "⭐ **没有阳性对照的尺子，和一把只会读出一种答案的尺子分不开**（批 17）"
        "—— 少了它们，判据 ② 就只能证明「我改过的页面被我改过了」",
    ),

    # ============================================ RN-430：并入关系与旧账归宿
    #
    # ⚠ 同 RN-408：被测对象（登记册）在另一个仓，断点只能打在**判据自己的
    # 承重逻辑**上。而这一组比 RN-408 更需要这么打 —— 它新增的
    # 「并入」是一个**结项**状态，一旦判据空转，被并掉的条目就会
    # 从未结清单里静默消失，而那正是本工程最贵的一类腐烂。
    Revert(
        "RN", "并入解析器瞎了（0 条，①②⑤ 全部无条件通过）",
        "tests/test_renovation_registry_merges_are_traceable.py",
        "        m = _MERGE.match(re.sub(r\"\\*+\", \"\", status).lstrip(\"⚠⭐⛔ \"))",
        "        m = None",
        "tests/test_renovation_registry_merges_are_traceable.py::"
        "test_the_real_registry_is_not_read_as_empty",
        "RN-430：「并入」算已结，而它算已结的**安全性不是自带的** ——"
        "来自「目标必须真实存在」「不许自己也是并入」这两条。"
        "⭐ **一个「结项」状态的安全性，来自另一条判据保证它指向的东西真的还在。**"
        "解析器一瞎，`并入 RN-999` 就成了一句让条目凭空消失的咒语，"
        "而且消失得毫无痕迹（它在统计里算结了）",
    ),
    Revert(
        "RN", "旧账逐页表解析器瞎了（归宿格与关档对账全部空转）",
        "tests/test_renovation_registry_merges_are_traceable.py",
        "        if header is None or \"主题\" not in header or page is None:",
        "        if True or header is None or \"主题\" not in header or page is None:",
        "tests/test_renovation_registry_merges_are_traceable.py::"
        "test_the_real_registry_is_not_read_as_empty",
        "RN-430：旧账那 104 行**没有状态列**（RN-198 已声明的盲区），"
        "本组是唯一够得着它们的判据。⭐ 分母塌了的时候，"
        "「这一页的旧账都有归宿」和「这一页根本没被读到」长得一模一样",
    ),
    Revert(
        "RN", "页面清单的已关档页认成 0 个（关档对账无条件通过）",
        "tests/test_renovation_registry_merges_are_traceable.py",
        "        if tuple(cells) == PAGE_TABLE_HEADER:",
        "        if False and tuple(cells) == PAGE_TABLE_HEADER:",
        "tests/test_renovation_registry_merges_are_traceable.py::"
        "test_the_real_registry_is_not_read_as_empty",
        "RN-430：页面清单里**四张表**都有「状态」格、都会出现「已关档」"
        "（批次台账 / 里程碑 / 交叉链路 / 页面表）⇒ 必须按表头挑，不能按关键字扫。"
        "⭐ 同 RN-189：分母要取真源，不是「凡是像的都算」",
    ),
    Revert(
        "RN", "「并入」被判成还开着（真源和并入方重复计一次）",
        "tests/test_renovation_registry_does_not_rot.py",
        "     \"记录不做\", \"实测后不成立\", \"并入\"}",
        "     \"记录不做\", \"实测后不成立\"}",
        "tests/test_renovation_registry_merges_are_traceable.py::"
        "test_the_synthetic_defects_are_actually_caught",
        "RN-430：状态词表是**唯一真相源**，两支判据共用它。"
        "把「并入」从 CLOSED_WORDS 里拿掉，被并的条目就重新出现在未结清单里 ——"
        "⭐ 那时账面上和**没并过**一模一样，而登记册看起来完全正常。"
        "⚠ 这条断点故意打在**另一支**判据的常量上：本组的判据要能发现"
        "它依赖的那个词表被改坏了，而不是只管自己那几条",
    ),
    # ============================================ RN-408：页面清单的棘轮
    #
    # ⚠ 这一组的**被测对象在另一个仓**（页面清单、总纲都是纯文档仓里的文件），
    # 而 revert_verify 只动得了 `ROOT` 底下的东西 ⇒ 断点只能打在**判据自己的
    # 承重逻辑**上。这不是将就：RN-408 那一类腐烂的唯一防线就是这几条判据，
    # 而**判据自己空转**恰恰是本工程反复踩到的形态（RN-169 / RN-198 / 批 10 两条假绿）。
    Revert(
        "RN", "页面清单解析器瞎了（0 行，下面每条断言无条件通过）",
        "tests/test_renovation_progress_board_does_not_rot.py",
        "        if header is not None and len(cells) == len(header):",
        "        if False and header is not None and len(cells) == len(header):",
        "tests/test_renovation_progress_board_does_not_rot.py::"
        "test_the_parser_actually_sees_the_page_table",
        "RN-408：一个把表解析成 0 行的解析器，长得和「这份文档很干净」一模一样。"
        "⭐ 先证明判据看得见东西，再让它去断言「没问题」（RN-169）",
    ),
    Revert(
        "RN", "批号从行文里读，而不是从状态格里读",
        "tests/test_renovation_progress_board_does_not_rot.py",
        "    for status in _statuses(_registry_text()).values():",
        "    for status in [_registry_text()]:",
        "tests/test_renovation_progress_board_does_not_rot.py::"
        "test_only_status_cells_count_as_a_batch_record",
        "RN-408：行文里的批号是**排期**，状态格里的"
        "「已结（…）·批 10」才是**记录**。⭐ 这个区分是拿批 10 换来的 ——"
        "那一轮有一条判据被一句**预告**（「排在批 10，做完即关档」）里的同一个"
        "字面量喂成了绿。**一个字符串出现过，不等于那件事发生过**。"
        "⚠⚠ 批 12 全组回退验证把这条判成**假绿**：批 11 写它的时候，"
        "真登记册的行文里恰好有几个台账里还没有的批号，所以「改成读全文」当场变红；"
        "批 12 把那一批记进台账之后，行文与台账正好一致，同一个破坏就咬不动了。"
        "⭐⭐ **一条靠巧合成立的红，会在巧合消失的那一刻变成假绿。**"
        "⇒ 判据已改成拿合成登记册直接考真函数（证据格写批 5、状态格不写），"
        "那个差别**不依赖任何真实数据，永远存在**",
    ),
    Revert(
        "RN", "悄悄把一个页状态移出分母",
        "tests/test_renovation_progress_board_does_not_rot.py",
        'STATUS_IN_PROGRESS = ("盘点", "锁基线", "找茬", "待裁定", "动刀", "验收")',
        'STATUS_IN_PROGRESS = ("盘点", "锁基线", "找茬", "待裁定", "动刀")',
        "tests/test_renovation_progress_board_does_not_rot.py::"
        "test_the_page_status_vocabulary_does_not_rot",
        "RN-408：从中间态清单里删掉一个词，对账判据**不会变红，只会少查几页** ——"
        "⭐ 分母缩水和「没问题」在结果上长得一模一样（RN-198 的解析器把分母从 66% "
        "缩到 13% 时也不报错）。所以守着它的必须是**状态词表那条双向断言**",
    ),
    Revert(
        "RN", "「存不存在」拿「结没结」那个分母去答",
        "tests/test_renovation_progress_board_does_not_rot.py",
        '    on_file = {cells[0].strip("* ") for _, cells in _rows(text)}',
        "    on_file = set(status)",
        "tests/test_renovation_progress_board_does_not_rot.py::"
        "test_a_batch_row_only_claims_closures_the_registry_agrees_with",
        "RN-408 判据首跑当场咬到我这条：旧账逐页表那 104 条**没有状态列**，"
        "所以「有状态格的那堆 RN」不是「在册的那堆 RN」。第一版当场诬告 RN-254。"
        "⭐ **两个分母长得很像** —— 都是「从登记册里读出来的一堆 RN 号」",
    ),
    Revert(
        "RN", "一整页被摘出导航，页面清单还挂着它",
        "gui_widget.py",
        '                ("about", "关于软件"),',
        '                # ("about", "关于软件"),',
        "tests/test_renovation_progress_board_does_not_rot.py::"
        "test_the_board_lists_exactly_the_pages_the_product_registers",
        "RN-408：页面名单的真源是 `gui_widget.nav_groups`，页面清单不许维护第二份。"
        "⚠ 这条判据横跨两个仓，所以它必须先回答「这两边是同一个产品吗」——"
        "**多出来的页只有在实现文件也一并不在时才算派生子集的正常缺项**；"
        "实现文件还在却不在导航里，那就是一整页被摘掉了。"
        "⭐⭐ 第一版没问这个问题，当场在派生子集里假红（那边整个没有账号页）——"
        "**本机的镜像不是任何一个真实环境的忠实模型**",
    ),
    Revert(
        "RN", "总纲按文件名找不到了，判据静默失去被测对象",
        "tests/test_renovation_progress_board_does_not_rot.py",
        '    charters = sorted(CAMPAIGN.glob("总纲*.md"))',
        '    charters = sorted(CAMPAIGN.glob("总纲*.rst"))',
        "tests/test_renovation_progress_board_does_not_rot.py::"
        "test_the_closing_checklist_is_enumerated_in_exactly_one_place",
        "RN-408：收工清单被复述了五遍（两个文件、两个不同的数）。"
        "⭐⭐ **同一件事说五遍，任何一遍变假都不会有人发现 —— 因为没人知道有五遍。**"
        "这条断点防的是「找不到真源就当没事」——**必须是红，不许是 skip**",
    ),
    # ==================================== RN-407：总开关关着时整页停止假装已生效
    Revert(
        "RN", "底栏那句回执又变回**无条件**的「已保存」",
        "widgets/page_action_bar.py",
        # ⚠⚠ 批 24 改到现在的代码上：那一行已经拆成 if/else 四分支
        #   （自动保存 / 手动保存 各两句），旧锚点在源码里出现 0 次
        #   —— **失效体检当场报出来，而它已经空转了整整这一批**。
        #   ⭐ **一条锚点失效的断点，和一条正常工作的断点，在跑之前长得一模一样。**
        # ⚠ 我第一次改的锚点是 `auto = saves_automatically(…)` → `auto = True`，
        #   **验出来是空转**：这条判据跑的那些页本来就是自动保存的，
        #   把 `auto` 钉成 True 对它们一个字都不改。
        #   ⭐ **一个破坏要能被看见，它必须落在判据真正在看的那条轴上** ——
        #     这条判据看的是「回执跟不跟总开关走」，不是「用哪一套措辞」。
        "        if enabled is not None:",
        "        if enabled is not None and enabled:",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_action_bar_receipt_follows_the_master_switch",
        "RN-407：这正是批 10 我自己写进去的那句话的形态 ——"
        "它在总开关开着时是真话，关着时是假话，而外审对它的判词是"
        "现状 4/4 高、候选 C 6/6 高（这条缺陷里票数最高的一项）。"
        "⭐ **一句只在某个状态下为真的回执，在别的状态里就是一句谎。**",
    ),
    Revert(
        "RN", "回执改回「等人来通知」，于是建完那一瞬间它什么都不说",
        "widgets/page_action_bar.py",
        "            row = getattr(node, \"master_switch_row\", None)",
        "            row = None",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_receipt_needs_no_one_to_come_and_tell_it",
        "RN-407：第一版把状态存成一个布尔、由 `MasterSwitchRow` 在 `singleShot(0)` 里"
        "拨过来，于是「页面刚建好、事件循环还没转」的那一瞬间底栏一个字都不说，"
        "三条既有判据当场逮到。⭐⭐ **回执的真源是那颗开关自己，"
        "不是「有没有人来通知过我」**（同 RN-417：量不稳的东西就去量决定它的规则）",
    ),
    Revert(
        "RN", "降权只降卡片外壳，说话的那些控件一个像素不动",
        "widgets/master_switch_effect.py",
        # ⚠⚠ 2026-08-28 批 21 全组跑判它**假绿**。原来的破坏是把 ②b 那步
        #    「repolish 卡片里的强调色后代」关掉（`if False or (`）——
        #    而**批 19 加的 ②c 是一条独立路径**（属性直接挂在控件自己身上、
        #    自己 repolish），它把同一片像素照样改了 ⇒ 判据不再变红。
        #    ⭐⭐ **一条断点模拟的缺陷，可以被后来加的第二条路径补偿掉；
        #      那时它不再证明那条判据有效，而它看起来毫无变化。**
        #    ⇒ 改成关掉 `_repolish` 本身 —— 那才是这条判据当初要防的那个缺陷
        #      的**忠实形态**：属性设上了、QSS 写对了、**没人叫控件重算样式**。
        "    style = widget.style()\n"
        "    style.unpolish(widget)\n"
        "    style.polish(widget)",
        "    return",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_de_emphasis_actually_changes_pixels",
        "⚠⚠ **这条断点第一次指的是 `..._is_de_emphasised_when_the_switch_is_off`，"
        "回退验证当场判它假绿** —— 那条判据查的是卡片上那个**属性**，"
        "而属性设上了、QSS 也写对了，屏幕上照样可以一个像素都不变"
        "（改祖先的动态属性不会让后代重算样式）。"
        "⭐⭐⭐ **判据绿不代表屏幕上有东西 —— 那就去量屏幕**：现在指的是"
        "直接抓那个控件像素的那一条。"
        "RN-407 ⭐⭐ **这条修复是外审复跑打出来的**：第一版只降了标题字色和左侧竖杠，"
        "**43 发里 39 发照旧报**「所有控件均为高亮紫色激活态且未置灰 ⇒ 以为在运行」。"
        "⭐ 「这一片是活的」这个信号不是外壳发出来的，是滑块/单选/主按钮上的"
        "**品牌强调色**发出来的。⚠ 另一半坑：**改祖先的动态属性不会让后代重算样式**"
        "—— QSS 规则写对了、判据也绿，而屏幕上一个像素没变，因为没人叫它们 repolish",
    ),
    Revert(
        "RN", "降权顺手把控件禁用了（RN-179 那条缺陷换个形态回来）",
        "widgets/master_switch_effect.py",
        "        card.setProperty(CARD_DIM_PROPERTY, value)",
        "        card.setEnabled(enabled)\n        card.setProperty(CARD_DIM_PROPERTY, value)",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_de_emphasis_itself_never_disables_anything[crosshair]",
        "RN-407 / RN-179：要的是「**可调、会保存，但现在不生效**」。"
        "禁用是另一条缺陷（那一轮实测「空库时 188 个控件可点却没反应」），"
        "⭐ **两条都不要** —— 所以这条断点是**反方向**的：它防的不是「没做」，"
        "是「做过了头」",
    ),
    Revert(
        "RN", "那句「照常可调」重新变成一条会长高的横幅",
        "widgets/master_switch_effect.py",
        'NOTICE_OFF_TEXT = "现在可以调、改了会保存；游戏里还不生效"',
        'NOTICE_OFF_TEXT = ("总开关关着：下面的设置照常可以调，改了也会自动保存，'
        '但现在不会出现在游戏里。把总开关打开就立刻生效。")',
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_off_copy_promises_the_controls_still_work",
        "RN-407：这就是第一版的原文。做成开关行下面的横幅之后开关行 24px → **63px**，"
        "紧凑档排版审计当场判红：状态卡在滚动区外面的 9 页，那 39px 是从 548px 的"
        "可视区里硬扣的（`kill_voice` 在册纵向裁切 64→107px，还多出两条全新溢出）。"
        "⭐⭐ **把话说清楚，不等于可以把它塞在任何地方** —— "
        "固定不动的那块屏幕是稀缺资源",
    ),
    Revert(
        "RN", "预览被藏起来（候选 C 那一步）",
        "pages/crosshair_page.py",
        "        self.preview_frame = preview_frame",
        "        self.preview_frame = preview_frame\n        preview_frame.hide()",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_preview_is_still_being_drawn_when_the_switch_is_off[crosshair]",
        "RN-407：批 14 的候选 C 把预览改成不渲染，**6/6 判高**"
        "「失去反馈，与底栏『已自动保存』矛盾」—— 比它想修的那条还重。"
        "⭐ **说后果，别撤反馈。**"
        "⚠ 这条断点第一次打在「把那句话藏起来」上，指向的判据只查文案不查可见性，"
        "**回退验证当场判它假绿** —— ⭐ 断点模拟的缺陷和判据盯的行为**必须是同一件事**",
    ),
    Revert(
        "RN", "状态胶囊组照旧用彩色喊「运行中」",
        "widgets/master_switch_effect.py",
        "    if host is not None and host.property(HOST_DIM_PROPERTY) != value:",
        "    if False and host.property(HOST_DIM_PROPERTY) != value:",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_status_chips_follow_the_switch[crosshair]",
        "RN-407：外审 43 发里 **16 发**把那颗**橙色**的「未启用」读成了"
        "「运行中/已激活」的高亮指示灯 —— 深色底上的橙色对 CS2 玩家就是「点亮了」。"
        "⭐ **按警示色着色而不按状态着色，颜色照样不携带信息。**",
    ),
    Revert(
        "RN", "空库置灰记原状时把「祖先关着」当成「它自己本来就是关的」",
        "widgets/community_library.py",
        "    return bool(widget.isEnabledTo(parent) if parent is not None",
        "    return bool(widget.isEnabled() if parent is not None",
        "tests/test_empty_library_covers_every_page.py::"
        "test_dimming_records_the_control_own_switch_not_its_ancestors",
        "RN-179 ⚠⚠ `isEnabled()` 在**任何一层祖先被禁用时都返回 False**，"
        "于是 `_set_dim` 会把一颗本来好好的控件记成「它原本就是灰的」，"
        "等库补上之后按这份错误的原状还回去 ⇒ **那颗控件永久变灰，且没有任何一处报错**。"
        "⭐⭐ **一个只在自己那条路径上正确的读数，会在别人叠上来的那一刻变成谎话** —— "
        "而它坏的方式是「记错了，然后忠实地还原成错的」，看起来完全像在守规矩。"
        "⚠ 这条是 RN-421 那个**已被撤回**的实验顺带挖出来的：撤回的是产品改动，"
        "不是这条修正 —— ⭐ **一次没走通的尝试，未必没有走通的部分**",
    ),
    Revert(
        "RN", "开关旁那句话又把「可以调」挤到后半截",
        "widgets/master_switch_effect.py",
        'NOTICE_OFF_TEXT = "现在可以调、改了会保存；游戏里还不生效"',
        'NOTICE_OFF_TEXT = "游戏里不生效；照常可调、改了会保存"',
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_notice_leads_with_what_he_can_do_now",
        "RN-424 ⚠ 注入的就是**批 16 的原文**。带地板对照实测："
        "把这两句话整个拿掉 = 知道「现在就能先调」**0/45（0%）**；"
        "批 16 那个语序 = **26/45（57%）**；只把语序反过来（一个字不删）= "
        "**43/44（97%）**。⭐⭐⭐ **批 16 为了让人看见「不生效」把否定提到句首"
        "（那条判断是对的），而同一个动作把「可以调」挤进了没人读的后半截** —— "
        "一条修法的代价，长在它自己修好的那件事的背面。"
        "⭐⭐ 两句话分工：这一句回答「我现在能干什么」，底栏那句回答"
        "「我改的东西生不生效」（那一句的否定仍在句首，见另一条判据）",
    ),
    Revert(
        "RN", "总开关关着，状态胶囊照旧写「已启用」",
        "pages/music_page.py",
        # ⚠ 锚点在批 33 搬过一次家：那一批撤掉了子开关（RN-454），
        # 「已配置」这个第三态（子开关开 + 总开关关）随着那个组合一起消失，
        # 函数从三态收成两态。⭐ **一个状态词是为了描述某个组合而存在的，
        # 组合没了，它就该跟着没** —— 而钉着它的断点得跟着走。
        '    return "已启用" if link_enabled else "已关闭"',
        '    return "已启用"',
        "tests/test_master_switch_effect_is_honest.py::"
        "test_nothing_on_screen_claims_to_be_enabled_while_the_switch_is_off[music]",
        "RN-425 ⭐⭐ **批 16 把状态胶囊退成了中性色，却没有动它说的话** —— "
        "颜色不再喊「运行中」了，字还在喊。`link_enabled` 只读子开关，"
        "不看总开关，于是总开关写着「未开启」而胶囊写着「联动 · 已启用」。"
        "外审在这一页 2/45 判「会以为已经生效」，措辞直指这颗胶囊。"
        "⭐ **「这个设置开着」和「这件事正在发生」是两回事，"
        "而「已启用」三个字同时承担了这两个意思。**"
        "⚠ 这处缺陷批 16 就在屏幕上了、当轮 45 发一次没报 —— "
        "⭐⭐ **一处缺陷被读到的概率，取决于它旁边那句话占用了多少注意力**",
    ),
    Revert(
        "RN", "降权又只认「住在一张卡里」的控件",
        "widgets/master_switch_effect.py",
        "            if not isinstance(w, _VALUE_ACCENT):",
        "            if True:",
        # ⚠⚠ 2026-08-28 批 21 全组跑判它**假绿**。这个破坏让
        #    `parameter_area_controls()` 对每一页都返回**空**，
        #    而原来的 selector 是那条按页判据「没有控件还留着强调色」——
        #    分母一空，它就**无条件通过**。
        #    ⭐⭐ **对一条"断言没有坏东西"的判据，任何缩小分母的破坏
        #      都只会让它更绿。** 能接住这类破坏的只有反空转那一条。
        #    ⇒ selector 改指反空转判据（它断言 15 页里至少 10 页找得到控件）。
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_parameter_area_definition_can_still_find_controls",
        "RN-427 ⚠⚠ 批 16 把「参数区」等同于「objectName 叫 card 的 QFrame」——"
        "那是一个**代理**，而代理会漏：`music` 的「允许游戏状态自动控制音乐」和"
        "`voice_output` 的三颗转发复选框住在 **`QGroupBox`** 里，一张卡都不沾，"
        "降权**一个像素都没够着**（开/关两态逐像素完全相同），"
        "而当时的判据问的是「每张卡有没有被降权」，**15 页全绿**。"
        "⭐⭐⭐ **一个用容器类型当代理的分母，会漏掉所有没用那个容器的地方。**"
        "⚠ 我自己换的头两个代理同样是坏的（「不在状态卡里」扫进了底栏按钮和页头"
        "那颗「?」；「所有强调色控件」扫进了「去社区拿一套」这类号召按钮）——"
        "⭐⭐ **同一种颜色可以承担两个意思，分母要按「它在这儿说什么」划，"
        "不按「它是什么控件」划**",
    ),
    Revert(
        "RN", "hud_color 底栏那句又说「点保存就生效」",
        "pages/hud_color_page.py",
        # ⚠ 判据跑的是 **else 分支**（页面此刻不脏），所以要破坏的是那一支。
        # ⚠⚠ 批 24 改到现在的代码上：那两句文案已经换了（RN-131 补上了
        #   「怎么在游戏里生效」），旧锚点在源码里出现 0 次 —— 失效体检当场报出来，
        #   而它**已经空转了整整这一批**。⭐ 这正是失效体检存在的理由：
        #   **一条锚点失效的断点，和一条正常工作的断点，在跑之前长得一模一样。**
        #   破坏方式不变：绕过 `set_message` 这个入口，直接对入口里面那个控件 setText。
        '            self.action_bar.set_message(\n'
        '                "已写进游戏的 cfg（并挂进 autoexec）；"',
        '            self.save_hint_label.setText(\n'
        '                "已写进游戏的 cfg（并挂进 autoexec）；"',
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_receipt_survives_the_page_refreshing_itself[hud_color]",
        "RN-427 ⭐⭐ **一条守卫的输入如果能被一次常规操作顺手改写，那条守卫就不是"
        "守卫。** 批 16 把这句话写进了 `_render_message` 的注释里，并把守卫建在"
        "**入口**（`set_message`）上；而 `hud_color` 拿到的是**入口里面那个控件**"
        "（`save_hint_label = action_bar.message_label`）然后直接 setText。"
        "实测：拨完开关回执还在，跑一次 `_refresh_dirty_ui()`（用户改任何一个"
        "设置都会触发）之后**回执整句消失**，只剩那句「点保存，设置才会生效」——"
        "外审原话「误以为只要点保存就会在游戏内生效，无需开启总开关」。"
        "⭐⭐ **守卫建在入口上，而那一页拿到了入口里面那个控件的引用** —— "
        "这不是有人绕过规则，是规则的边界没覆盖到它自己暴露出去的那个引用",
    ),
    Revert(
        "RN", "那条胶囊关着时还叫「当前状态」",
        "widgets/master_switch_effect.py",
        "        title.setText(STRIP_TITLE_ON if enabled else STRIP_TITLE_OFF)",
        "        title.setText(STRIP_TITLE_ON)",
        "tests/test_master_switch_effect_is_honest.py::"
        "test_the_status_strip_is_titled_by_what_it_actually_lists[music]",
        "RN-428 ⚠⚠ **本条立案时我写的说法（「『当前』这两个字在说时间」）"
        "被枚举一遍推翻了**：`crosshair` 有 7 条「当前X」摘要，而它在外审枚举轮"
        "**3/3 报 NONE**。触发误读的是**描述「某件事发生时会自动做什么」**的条目"
        "（「阵亡后自动继续播放」「本地监听开启」「事件 · 2 项」「地图 · 未检测到」），"
        "静态属性（「当前样式：点」）不会。"
        "⭐⭐ **一个读起来像实时读数 / 像规则引擎的东西，光是存在就在暗示"
        "有个进程在跑。** ⇒ 不逐句改摘要，只改一处共用的标题，"
        "它一次性给整条胶囊重新定性。"
        "实测（枚举轮，同分母 15 页 ×3 发）：**状态胶囊组那一类的抱怨 15 → 7**，"
        "而**我没碰的「勾选着的子开关」那一类 14 → 14 一动没动** —— "
        "⭐⭐⭐ **那个没动的类别正好证明动了的那一类的下降不是「它今天话少」**",
    ),
    Revert(
        "RN", "空库那颗唯一的出路按钮不再声明「不归总开关管」",
        "pages/kill_icon_page.py",
        "                mark_ungoverned_by_master(self.test_btn)",
        "                pass  # 回退验证：这一处声明被拿掉",
        "tests/test_the_way_out_is_not_dimmed_by_the_master_switch.py::"
        "test_the_only_way_out_does_not_change_with_the_master_switch",
        "RN-439：空库 + 总开关关 = **全新用户的定义**，而这两个默认值同时成立时，"
        "这一页唯一走得通的那颗按钮被降权压成灰蓝 (110,112,129)。"
        "⭐⭐⭐ **两条各自正确的规则，在交集处出错；而必然踩进那个交集的，"
        "正好是这条引导唯一服务的那个人**",
    ),
    Revert(
        "RN", "共用引导件那颗不再声明（一处塌，七页里的六页跟着塌）",
        "widgets/community_library.py",
        "        mark_ungoverned_by_master(self.button)",
        "        pass  # 回退验证：这一处声明被拿掉",
        "tests/test_the_way_out_is_not_dimmed_by_the_master_switch.py::"
        "test_the_only_way_out_does_not_change_with_the_master_switch",
        "RN-439：⭐ 一处声明覆盖七页，是批 3（RN-165）把「空了该长什么样」"
        "收成唯一一份换来的现金价值 —— 而它同时意味着**一处塌就是六页一起塌**",
    ),
    Revert(
        "RN", "QSS 里那条豁免规则没人消费（属性照挂、屏幕照旧）",
        "theme_manager.py",
        'QPushButton#primaryButton[{eff.UNGOVERNED_PROPERTY}="true"] {{',
        'QPushButton#primaryButtonXX[{eff.UNGOVERNED_PROPERTY}="true"] {{',
        "tests/test_the_way_out_is_not_dimmed_by_the_master_switch.py::"
        "test_the_only_way_out_does_not_change_with_the_master_switch",
        "RN-439：⚠ `setProperty` 本身**不改变任何一个像素** —— "
        "QSS 里没有对应选择器的话，那就是个空转属性，"
        "而**空转属性和生效属性在代码里长得一模一样**（同 RN-407 那条老坑）",
    ),
    Revert(
        "RN", "豁免规则盖住了禁用态（禁用的和可点的又长得一样了）",
        "theme_manager.py",
        'QPushButton#primaryButton[{eff.UNGOVERNED_PROPERTY}="true"] {{',
        'QPushButton#primaryButton[{eff.UNGOVERNED_PROPERTY}="true"]:disabled, '
        'QPushButton#primaryButton[{eff.UNGOVERNED_PROPERTY}="true"] {{',
        "tests/test_the_way_out_is_not_dimmed_by_the_master_switch.py::"
        "test_the_exemption_does_not_swallow_the_disabled_look",
        "RN-439 ⚠ 豁免那条和 `#primaryButton:disabled` **特异度完全相同**"
        "（各 2 个 id + 2 个属性/伪类），Qt 按后来者胜 ⇒ 它靠**排在前面**生效。"
        "⭐ **一条靠「排在谁前面」生效的规则，挪一次位置就会静默失效** —— "
        "而失效的样子正是 RN-150 花一整批修掉的那颗「禁用了但看着能点」的按钮",
    ),
    Revert(
        "RN", "风格条那句退回去指路（同一屏上出现第二个「第一步」）",
        "widgets/kill_icon_style_strip.py",
        'self.empty_label = QLabel("装好的图标包会排在这一行 —— 现在还是空的。")',
        'self.empty_label = QLabel("还没有任何风格，点右边的「＋ 导入」装一套。")',
        "tests/test_kill_icon_empty_library_guidance.py::"
        "test_only_one_sentence_tells_the_newcomer_where_to_click",
        "RN-405②：页头说「先去社区拿一套图标包」、风格条说「点右边的「＋ 导入」」——"
        "⭐⭐ **两句引导各自都对，摆在同一屏上就变成了「到底听谁的」**。"
        "⚠ 而立案说的「入口太多、第一步不聚焦」实测**不成立**"
        "（行为题 11/12 一眼选中同一颗）⇒ 真正的毛病是**指令有两处**",
    ),
    Revert(
        "RN", "状态胶囊退回「闭合的圆角空框」",
        "theme_manager.py",
        # ⚠ 锚点用 `\n` 不是 `\r\n`：本文件是 `read_text()` 读的（**通用换行**），
        #   CRLF 到这儿已经归一成 LF。⭐ 第一版写成 `\r\n`，四条断点全部
        #   「锚点出现 0 次」被跳过 —— 而失效体检把它报成「一直在空转」，
        #   ⭐⭐ **一条从没匹配上过的断点，和一条腐烂掉的断点，报出来是同一句话。**
        "                background-color: transparent;\n"
        "                border: none;\n"
        "                border-left: 3px solid {c.text_tertiary};\n"
        "                border-radius: 0px;\n",
        "                background-color: {c.bg_card};\n"
        "                border: 1px solid {c.border_secondary};\n"
        "                border-radius: 13px;\n",
        "tests/test_status_chips_do_not_look_clickable.py::test_a_status_chip_is_not_drawn_as_a_closed_box",
        "RN-103：胶囊是**全站唯一一个「按钮尺寸 + 闭合轮廓」的不可点元素**"
        "（可点的 267 个全带描边；不可点还带描边的只剩 card 和一条横贯整行的告示条，"
        "都大一个数量级）。⭐⭐⭐ 它不可点，却长着这套界面里「可点」的那个形状 —— "
        "实测胶囊轮廓 1.02~1.59:1、填充与卡底 1.00:1，而 `secondaryButton` "
        "是 1.12~1.90:1 / 1.00:1：**两者在像素上是同一种东西**",
    ),
    Revert(
        "RN", "只改基础规则、忘了 warn 那条特化（框只剩警告那几颗留着）",
        "theme_manager.py",
        "                color: {self._chip_text(c.accent_warm)};\n"
        "                background-color: transparent;\n"
        "                border: none;\n"
        "                border-left: 3px solid {self._chip_text(c.accent_warm)};\n",
        "                color: {self._chip_text(c.accent_warm)};\n"
        "                background-color: {self._hex_to_rgba(c.accent_warm, 28)};\n"
        "                border: 1px solid {self._hex_to_rgba(self._chip_text(c.accent_warm), 120)};\n",
        "tests/test_status_chips_do_not_look_clickable.py::test_a_status_chip_is_not_drawn_as_a_closed_box",
        "RN-103 ⭐ **一条规则有几个特化分支，就要判几次**：候选 D 就是只给警告留了框，"
        "而外审残留的 4 发**逐字抄的正是那两颗还有框的** —— 框就是那个信号",
    ),
    Revert(
        "RN", "降权那条把闭合轮廓加回来（总开关关着的页面上又变回框）",
        "theme_manager.py",
        "                border: none;\n"
        "                border-left: 3px solid {c.text_tertiary};\n"
        "            }}\n\n            /* ⚠⚠ **这两处原来是橙色的",
        "                border: 1px solid {c.border_secondary};\n"
        "            }}\n\n            /* ⚠⚠ **这两处原来是橙色的",
        "tests/test_status_chips_do_not_look_clickable.py::test_a_status_chip_is_not_drawn_as_a_closed_box",
        "RN-103 ⚠ `QFrame#card[masterOffHost=\"true\"]` 那条**特异度比 level 那几条都高**，"
        "它会把闭合轮廓整个加回来 —— 而且只在总开关关着的页面上。"
        "⭐ 破坏验证第一轮它是**空转**的：标本没有那个祖先属性，规则就够不着 ⇒ "
        "**一条只在某个祖先属性下才生效的规则，需要一个带那个祖先的标本**",
    ),
    Revert(
        "RN", "左侧色条也删了（胶囊什么都不画）",
        "theme_manager.py",
        "                border-left: 3px solid {c.text_tertiary};\n"
        "                border-radius: 0px;\n",
        "                border-radius: 0px;\n",
        "tests/test_status_chips_do_not_look_clickable.py::test_the_chip_still_has_something_on_its_left",
        "RN-103：色条是它**还在说「这是一组状态项」**的唯一凭据。"
        "⭐ 这条不是靠票数立的（四个候选 12/12 都答「分得开」），"
        "是**给未来的自己留的下界**",
    ),
    Revert(
        "RN", "胶囊又能折行了（同排高度不齐）",
        "pages/audio_status_badge.py",
        "            keep_single_line(chip)",
        "            chip.setWordWrap(True)",
        "tests/test_status_chips_do_not_look_clickable.py::test_no_status_chip_is_allowed_to_wrap",
        "RN-121 在批 26 的又一次现身：`fix_text_display()` 给每个 QLabel 无条件"
        "`setWordWrap(True)`，而会折行的 QLabel **把自己的宽度报小**"
        "（实测 hint 128px、文字要 130px）⇒ 折成两行、比同排高 4px。"
        "⭐⭐ 而它是被我**压矮了其余那些**才暴露的 —— 那两颗一直在折行，"
        "只是以前同排的比它高，看不出来。"
        "⭐ **「同排一致」这类判据，改「其余那些」和改「那一个」是等价的破坏。**",
    ),
    Revert(
        "RN", "gap 滑块在自定义样式下又变回可点",
        "pages/crosshair_page.py",
        'STYLE_DEAD_SLIDERS = {"custom": ("gap_slider",)}',
        'STYLE_DEAD_SLIDERS = {}',
        "tests/test_crosshair_says_what_it_actually_does.py::test_a_slider_that_changes_nothing_is_disabled",
        "RN-415：`_paint_custom` 画的是一张 30×30 的像素画，**没有「中心间隙」这个概念**。"
        "实测（改两个值比像素）：自定义样式下 size/thickness/outline/alpha 四条都改得动，"
        "**只有 gap 一个像素不动**，而五条在页面上全是 enabled。"
        "⭐ 判据不点名 gap —— 它自己量出谁是死的，加第六条一样会红",
    ),
    Revert(
        "RN", "自定义样式下把五条滑块全禁掉（过度修正）",
        "pages/crosshair_page.py",
        'STYLE_DEAD_SLIDERS = {"custom": ("gap_slider",)}',
        'STYLE_DEAD_SLIDERS = {"custom": ("gap_slider", "size_slider",'
        ' "thickness_slider", "outline_slider", "alpha_slider")}',
        "tests/test_crosshair_says_what_it_actually_does.py::test_the_sliders_that_do_work_stay_usable",
        "RN-415 阳性对照：那四条对自定义**是真的有用**。⭐ 缺了这条，"
        "上一条可以靠「全禁掉」全绿 —— 而批 17 实测大面积置灰读作「软件坏了」",
    ),
    Revert(
        "RN", "页面又声称我们导出 .json",
        "pages/crosshair_page.py",
        '"导入 / 导出在页面底部操作栏，收本软件导出的 .xchr"',
        '"导入 / 导出在页面底部操作栏，收本软件导出的 .json"',
        "tests/test_crosshair_says_what_it_actually_does.py::test_no_sentence_claims_we_export_a_format_we_do_not",
        "RN-410：导出默认写 `my_crosshair.xchr`、两个对话框只列 `*.xchr`，"
        "而唯一一句解释这件事的话写着「只认本软件导出的 .json」——"
        "⭐ **用户照那句话去找一个软件根本不产出的文件**。"
        "⚠ 判据只比**紧跟在「导出的」后面**的那个扩展名：第一版收「整句里出现过的」，"
        "把讲拖拽的 .json 也算成了谎话 ⇒ "
        "⭐ 一句话是真是假，要拿它自己声称的那件事去比",
    ),
    Revert(
        "RN", "导入按钮的说明又被拿掉（只剩页尾那一份）",
        "pages/crosshair_page.py",
        "        self.action_bar.extra_btn.setToolTip(",
        "        _ = (lambda *a: None)(",
        "tests/test_crosshair_says_what_it_actually_does.py::test_the_import_button_itself_explains_what_it_takes",
        "RN-410：那句话原来在 y=1000，而导入按钮在 y=681 —— "
        "说明在按钮**下方 319px、且在 750px 折线之外**，按钮自己 tooltip 是空的。"
        "⭐ **解释性文字放在困惑发生的位置之前，不是页尾；放页尾 = 没放**",
    ),
    Revert(
        "RN", "空白预览框不再是入口（回到「看着像画板却点不动」）",
        "pages/crosshair_page.py",
        "        is_entry = bool(self._custom_style_is_blank())",
        "        is_entry = False",
        "tests/test_crosshair_says_what_it_actually_does.py::test_the_preview_becomes_the_entry_when_custom_is_blank",
        "RN-414 ⭐⭐ **天然对照实验**（同页同状态同模型，变量只有看不看得见折线以下）："
        "窗口图 ①3/3「不知道」②3/3「不知道」；整页无折线图 ①3/3「绘制准心」"
        "②3/3「知道，在这一屏上」⇒ 入口不是难找，是**根本不在第一屏上**"
        "（单选 y=456、按钮 y=948，相距 492px，可视区 750px）。"
        "⚠ 不能就地再放一颗「绘制准心」（另一条判据明令只许一颗，RN-404 族）⇒ "
        "让批 12 我自己造出来的那块「看着像画板却点不动」的黑框**真的可点**。"
        "改后窗口图 ①3/3「点这里开始画」②3/3「知道，在这一屏上」，安全轴 3/3 不动",
    ),
    Revert(
        "RN", "画过之后预览框仍然可点（有时候能点、而外观从不变化）",
        "pages/crosshair_page.py",
        "        is_entry = bool(self._custom_style_is_blank())",
        "        is_entry = True",
        "tests/test_crosshair_says_what_it_actually_does.py::test_a_drawn_preview_is_not_clickable",
        "RN-414 反面守卫：⭐ 一个「有时候能点、有时候不能点、而外观从不变化」的东西，"
        "比一个从来不能点的还糟 —— 那是批 26「不可点的东西不许长按钮的形状」的镜像",
    ),
    # ---------------------------------------------------------- 批 28（magnifier）
    Revert(
        "RN", "底栏主按钮位又摆回「全不选武器」",
        "pages/magnifier_page.py",
        '        self.action_bar.configure_primary("", None, visible=False)',
        '        self.action_bar.configure_primary("全不选武器",'
        ' self._deselect_all_weapons, visible=True)',
        "tests/test_the_loudest_button_is_not_the_undo_button.py"
        "::test_no_page_puts_a_destructive_action_in_the_loudest_slot",
        "RN-277：54 把武器 `setChecked(True)` 默认全勾 ⇒ **每一个第一次打开这一页的人**"
        "看到的都是那颗写着「全不选武器」的紫按钮 —— 全页唯一的高亮控件。"
        "点一下 54 个复选框全清空、当场落盘、没有确认也没有撤销。"
        "⭐⭐ 而它作用的那 54 个复选框在第二~三屏，按钮却钉在第一屏 ——"
        "**它唯一能改的东西，一个都不在用户眼前**（批 27「入口不在第一屏上」的背面）。"
        "外审行为题 12 发：④「靠近目标还是反方向」⇒ **12/12「反方向」**；"
        "而 ② 12/12 答「先点总开关」—— 用户知道该点哪儿，这不是入口问题",
    ),
    Revert(
        "RN", "底栏主按钮又显示出来（哪怕文案换成中性的）",
        "pages/magnifier_page.py",
        '        self.action_bar.configure_primary("", None, visible=False)',
        '        self.action_bar.configure_primary("应用", None, visible=True)',
        "tests/test_the_loudest_button_is_not_the_undo_button.py"
        "::test_magnifier_leaves_the_loudest_slot_empty",
        "RN-277：这一页没有该由底栏承担的动作。⭐ 换个中性文案挡不住这条 ——"
        "批 10 的判词是「一颗灰着的、紫色的、蹲在右下角的按钮，"
        "**形状本身就在说『这里有个保存动作』**」，而这一页同样没有保存动作",
    ),
    Revert(
        "RN", "武器卡里的「全不选」被一起删掉（把撤走做成了删功能）",
        "pages/magnifier_page.py",
        '        deselect_all_btn = QPushButton("全不选")',
        '        deselect_all_btn = QPushButton("")',
        "tests/test_the_loudest_button_is_not_the_undo_button.py"
        "::test_the_action_itself_survives_in_the_card",
        "RN-277 反向守卫：⭐ 把按钮从底栏撤走**不等于**把这个动作删掉。"
        "它本来就在武器卡表头，紧贴那 54 个复选框 —— 在那儿点，用户看得见自己改了什么",
    ),
    Revert(
        "RN", "底栏那句话不再说「要不要点什么」",
        "pages/magnifier_page.py",
        '            "改完就存下了；只有「偏移校准」里的 X / Y 要点那张卡上的「应用」才算数。"',
        '            ""',
        "tests/test_the_loudest_button_is_not_the_undo_button.py"
        "::test_the_bar_message_tells_the_truth_about_what_needs_clicking",
        "RN-277：本页 `SAVES_AUTOMATICALLY = False`，共用回执**不替它说存不存**（批 24）。"
        "两颗按钮撤走之后，这句话是唯一还在回答「我到底要不要点什么」的东西。"
        "⭐ 判据不比「有没有『保存』两个字」，比的是**它自己声称的那件事**："
        "说了「应用」就必须真有那颗按钮，说了「存下」就必须真有 "
        "`stateChanged.connect(self.save_settings)`（AST 验）",
    ),
    Revert(
        "RN", "方向键那一行又变回不能换行的 QHBoxLayout",
        "pages/magnifier_page.py",
        # ⚠ 锚点在批 28 的**二版修法**里改过一次（h_spacing 6 → 15，因为组间距
        #   不再靠 `addSpacing` 而靠 FlowLayout 自己的水平间距）——第一版断点当场
        #   被失效体检报成「锚点出现 0 次」。
        #   ⭐ **改了修法要顺手把断点也改到新的代码上**（RN-085 那条教训又中一次）。
        "        adjust_wrap, adjust_layout = make_flow_container(h_spacing=15, v_spacing=6)",
        "        adjust_wrap = QWidget(); adjust_layout = QHBoxLayout(adjust_wrap)",
        "tests/test_the_loudest_button_is_not_the_undo_button.py::test_the_nudge_row_can_wrap",
        "RN-196 横向那 29px 的根因：8 颗方向键代码里写 `setFixedSize(QSize(30, 26))`，"
        "实际渲染 **80×50** —— `_style_button` 只抬 min 不动 max ⇒ min > max ⇒ Qt 取 min，"
        "**调用点写的固定尺寸一个像素都不生效**，一行 ~800px 顶穿整页最小宽。"
        "⭐ **一句无效的声明不是无害的，它被放大了两倍半。** "
        "改成 FlowLayout 之后紧凑档横向溢出 29px → 0",
    ),
    Revert(
        "RN", "两句被挤到折行的提示又长回去",
        "pages/magnifier_page.py",
        '            "主武器和手枪各自指定放大热键，并选长按还是单击切换。",',
        '            "主武器和手枪各自指定放大热键，并选长按触发还是单击切换。",',
        "tests/test_the_loudest_button_is_not_the_undo_button.py::test_these_hints_do_not_grow_back",
        "RN-143 在本页最极端的一个样本：原文 27 字要 336px，而这一格分到 335px ——"
        "**差 1 个像素**就折成两行。⭐ 它证明「被挤到折行」和「放不下」完全不是一回事："
        "1px 的缺口，任何「有没有溢出 / 有没有截断」的判据眼里都一切正常",
    ),
    # ------------------------------------------------------- 批 29（voice_output）
    Revert(
        "RN", "主音量旁边那句量程说明被删（滑块又只剩一个孤零零的 100%）",
        "pages/voice_output_page.py",
        'volume_scale_hint = QLabel("滑块中点就是 100%（原音量）；往右可以放大，最高 200%。")',
        'volume_scale_hint = QLabel("")',
        "tests/test_the_slider_says_one_thing_and_shows_another.py"
        "::test_a_slider_whose_full_scale_is_not_100_percent_says_so",
        "RN-064：量程 `[0,200]` + 值 100 ⇒ **手柄正好停在正中间**，而右边写着 100%。"
        "外审 **24 发 24/24** 全部答出「滑块位置约 50~75%，右侧数字写 100%，互相矛盾」。"
        "⭐ 机制不是有人写错了数，是**量程已经走到了显示函数的参数表里再被丢掉**："
        "`format_percent(value, hi=2.0)` 拿 hi 只做夹紧，它从不出现在结果字符串里 ⇒ "
        "**不是没人知道上限是 200%，是知道的那一层没有把它说出来**",
    ),
    Revert(
        "RN", "槽位列表那行图例被删（五条槽位滑块又没人解释量程）",
        "pages/voice_output_page.py",
        '            "每一行：编号 · 快捷键 · 音频文件 · 试听 · 音量（中点 100%，最高 200%） · 删除")',
        '            "")',
        "tests/test_the_slider_says_one_thing_and_shows_another.py"
        "::test_a_slider_whose_full_scale_is_not_100_percent_says_so",
        "⚠⚠ 这条断点**逼着判据改了一次**：第一版判据只要求「页面上任意一处出现 200%」，"
        "于是删掉这行图例它照样绿 —— 而主音量那句话在页面另一头，"
        "离这五条滑块隔着一整屏。⭐ **「这一屏某处写过」不等于「解释放在困惑发生的地方」**"
        "（批 27 那条）⇒ 判据改成沿**祖先链**找、且不许一路走到页面根",
    ),
    Revert(
        "RN", "「就绪」这个初始占位符又回来了（驱动明明还没装）",
        "pages/voice_output_page.py",
        '        self.status_label = QLabel("还没有操作")',
        '        self.status_label = QLabel("就绪")',
        "tests/test_the_slider_says_one_thing_and_shows_another.py"
        "::test_nothing_claims_ready_while_the_driver_is_not",
        "同屏矛盾：徽章「驱动 · 待安装」+ 卡片「⚡ VB-Cable 未安装」，而底栏与状态条"
        "写着「最近状态：就绪」。外审多发判**高**。"
        "⭐ **「就绪」是一个初始占位符，而它长得像一个判断结果。**"
        "⭐⭐ 「最近状态」这个词同时能读成「最近一次操作的结果」和「现在是否就绪」，"
        "而它只实现了前者、初值又恰好是一个听起来像后者的词（同 RN-428 那族）。"
        "⚠ 判据第一版的词表**太宽**，把「先确认 VB-Cable 是否就绪」这句**提问**"
        "也报成了假话 ⇒ 只认断言式说法（整句就是「就绪」，或出现「状态：就绪」）",
    ),
    Revert(
        "RN", "空槽位的「删除」又变回危险红",
        "pages/voice_output_page.py",
        # ⚠ 锚点在同一批里改过一次：第一版修法是换 objectName，
        #   被「换名会多占 2px」的数堵回来之后改成了属性。
        #   ⭐ **改了修法要顺手把断点也改到新的代码上**（批 28 刚踩过）。
        '        want = None if has_audio else "true"',
        '        want = None',
        "tests/test_the_slider_says_one_thing_and_shows_another.py"
        "::test_an_empty_slot_does_not_get_the_scarce_red",
        "`style_as_danger_button` 的文档第 3 行逐字写着「红色语义要稀缺才有效；"
        "**到处都是红的等于没有红的**」——而全新用户打开这一页看到的是 **5 颗高饱和红**"
        "（`rgb(239,68,68)`，全页唯一的饱和色），每一颗管的都是「删掉一个什么都没有的行」。"
        "外审整页图 **6/6** 在「最扎眼的是什么」和「哪个按钮会弄没东西」两问上**都**答「删除」。"
        "⭐ 而同一行里的「试听」早就知道自己该禁用 —— 那道门一直在，只是没给「删除」接上。"
        "⭐⭐ **一条判别标准写在注释里，只会被应用到写它的人当时正在看的那一处。**",
    ),
    Revert(
        "RN", "有音频的槽位也不给红了（把「稀缺」做成了「没有」）",
        "pages/voice_output_page.py",
        '        want = None if has_audio else "true"',
        '        want = "true"',
        "tests/test_the_slider_says_one_thing_and_shows_another.py"
        "::test_a_slot_with_audio_does_get_the_red",
        "阳性对照：装了音频的槽位，删除是一次**真正不可逆的丢失**"
        "（文件路径 + 全局热键绑定 + 音量 + 名称，且当场落盘、无 undo 无快照）。"
        "⭐ 缺了这条，上一条可以靠「把红色整个删掉」全绿 —— 那比现在更糟",
    ),
    Revert(
        "RN", "「试听」和「删除」又各读各的条件",
        "pages/voice_output_page.py",
        "        has_audio = bool(slot.get(\"audio\"))",
        "        has_audio = True",
        "tests/test_the_slider_says_one_thing_and_shows_another.py"
        "::test_preview_and_delete_read_the_same_gate",
        "⭐ 这条缺陷的形状不是「删除按钮颜色不对」，是**同一行里，「试听」知道自己"
        "没东西可播，而「删除」不知道自己没东西可删**。判据钉的是「两颗按钮读同一个条件」，"
        "不是「删除按钮此刻是什么颜色」",
    ),
    # ------------------------------------------------- 批 30（voice_output 第二刀）
    Revert(
        "RN", "页头又承诺「把文字转成语音」（一个不存在的功能）",
        "pages/voice_output_page.py",
        'description="两件事：用快捷键把音频放进游戏语音、把击杀音效转给队友听。都要先装好虚拟声卡。"',
        'description="三件事：把文字转成语音说进游戏、用快捷键放音板、把击杀音效转给队友听。都要先装好虚拟声卡。"',
        "tests/test_the_page_promises_a_feature_it_does_not_have.py"
        "::test_no_page_asks_for_typing_it_cannot_accept",
        "RN-451：这一页 **0 个文本输入控件**，全仓 **0 个 TTS 引擎**（AST 扫 "
        "pyttsx/gtts/edge_tts/sapi/… 命中的只有两处做音量闪避和贴屏浏览器的 comtypes）。"
        "⇒ 用户照着这句话去找一个不存在的输入框。"
        "⭐⭐⭐ 它是 `e7f5a31`（2026-08-16，标题写着「修…2 类**文案缺陷**」）加上去的："
        "旧文案「语音播放」含糊但**是真的**，新文案「把文字转成语音」具体而且**是假的** ⇒ "
        "**一次「把文案写具体」的改动，把真话改成了假话**",
    ),
    Revert(
        "RN", "帮助面板又说「输入文字后按快捷键」",
        "ui_help_panel.py",
        '"• <b>虚拟声卡设置</b> — 装好 VB-Cable，再选麦克风、调主音量和播放模式<br>"',
        '"• <b>语音输出</b> — 输入文字后按快捷键即可将语音送进游戏语音<br>"',
        "tests/test_the_page_promises_a_feature_it_does_not_have.py"
        "::test_the_help_panel_does_not_promise_it_either",
        "⭐⭐ **那句假话就是从这儿抄进页头的。** 它从 **2026-04-19 的 2.0 重构前基线**就在，"
        "中间还活过了 RN-001 那一轮（删掉 237 行**从没被读到过的**帮助文案）—— "
        "没被读，所以也没被证伪，然后在四个月后被当成真源抄走。"
        "⭐⭐⭐ **一份没人读的文档不会被证伪，但它会被当成真源抄走。**",
    ),
    Revert(
        "RN", "加完槽位又不滚到新行（点了等于没反应）",
        "pages/voice_output_page.py",
        "        if not auto_init:\n            self._scroll_slot_into_view(slot_frame)",
        "        if False:\n            self._scroll_slot_into_view(slot_frame)",
        "tests/test_the_page_promises_a_feature_it_does_not_have.py"
        "::test_a_newly_added_slot_is_actually_on_screen",
        "RN-184：实测（改前）加到第 6 个时新行在内容坐标 y=434，而槽位列表可视范围只到 314 "
        "⇒ **露出 0%**，滚动条纹丝不动停在 0。"
        "⭐⭐ 而「添加槽位」正是底栏那颗紫色主按钮（批 29：「这一屏最扎眼的是什么」18/24 答它）"
        "⇒ **全页最响的那颗按钮，点下去在屏幕上不产生任何可见变化。**"
        "⭐ 这是批 28 那条的另一面：那次是「按钮在第一屏，它作用的对象在第三屏」，"
        "这次是「按钮在第一屏，**它造出来的东西落在视口外**」。"
        "⚠⚠ 只 `QTimer.singleShot(0,…)` 不够 —— 回调跑时**滚动条量程还停在旧内容高上**，"
        "`ensureWidgetVisible` 于是「已经滚到底了」（视口滚到 136~428，而新行在 434~510）。"
        "⭐ **「布局还没算完」不只是控件几何没算完，滚动条的量程也没算完**，而后者一声不吭",
    ),
    Revert(
        "RN", "建页铺初始槽位也跟着滚（一开页就停在列表底部）",
        "pages/voice_output_page.py",
        "        if not auto_init:\n            self._scroll_slot_into_view(slot_frame)",
        "        if True:\n            self._scroll_slot_into_view(slot_frame)",
        "tests/test_the_page_promises_a_feature_it_does_not_have.py"
        "::test_opening_the_page_does_not_land_at_the_bottom_of_the_list",
        "RN-184 反向守卫：⭐ 缺了它，上一条可以靠「每加一个都滚到底」全绿 —— "
        "包括建页时那 5 个初始槽位，于是用户一打开这一页就停在列表末尾，第一个槽位反而看不见",
    ),
    # ⛔⛔ 新断点一律加在**这一行之上**。
    #
    # 下面这个标记是开源同步那个语义补丁的**锚点**：开源版在这个位置追加它自己的
    # BRAND / ASSET / DOC 三组断点（上游没有）。补丁原来锚在「最后一条断点的
    # 证据文字」上 —— 于是**每次往 REVERTS 末尾追加条目，那个补丁就断一次**
    # （RN-156：语义补丁的上下文窗口是看不见的；批 7 又踩了一次）。
    #
    # 改成锚在这行不会变的标记上之后，往上面加多少条都不会顶开它。
    # ⇒ 别删这一行、别改它的文字，也别把新条目加到它下面。
    # OSS_SYNC_APPEND_POINT
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

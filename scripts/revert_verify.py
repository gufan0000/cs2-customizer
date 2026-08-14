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
import os
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass


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
        "    sx, sy = rot(0, half)\n    _draw_line(painter, cx, cy, sx, sy)",
        "    sx, sy = rot(0, half)\n    ux, uy = rot(0, -half)\n    _draw_line(painter, ux, uy, sx, sy)",
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
        "R9-A", "预览漏掉 t_shape 分支",
        "pages/crosshair_page.py",
        '            elif style == "t_shape":',
        '            elif style == "__never_matches__":',
        "tests/test_crosshair_style_catalog_r9a.py::test_preview_handles_every_user_style",
        "预览空白但屏幕上有准心",
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
        "R10", "「保存FPS设置」又被写死宽度",
        "pages/kill_icon_page.py",
        "        self.save_fps_btn.setMinimumWidth(120)",
        "        self.save_fps_btn.setFixedWidth(120)",
        "tests/test_tab_scroll_and_button_width_r10.py::"
        "test_known_tight_buttons_are_not_width_pinned[kill_icon_page.py]",
        "UP-094：改动后文案变「保存FPS设置 *」更宽，写死的 120px 更不够",
    ),
    Revert(
        "R10", "产品代码里又混进编码损坏",
        "kill_icon_player.py",
        '        """加载旧版逐帧动画"""',
        # 注意：这里写的是**转义序列**，本文件源码里是 6 个 ASCII 字符，
        # 只有写进目标文件时才变成真正的私有区字符——否则本文件自己就"损坏"了。
        '        """加载旧版逐帧动画\ue000"""',
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
        # ⚠ 开源版是 26 页（闭源版 27，多一个账号页）。这个数字随页面集合变，
        # 改页面时锚点要跟着改，否则这条断点会静默"跳过"。
        "TOTAL_PAGES = 27",
        "TOTAL_PAGES = 11",
        "tests/test_audit_coverage_r11.py::test_focus_audit_total_pages_matches_the_app",
        "UP-101：分母一改，11/11 就成了「全覆盖」——覆盖率造假最省事的办法",
    ),
    Revert(
        "R11", "把 CI 里的紧凑档删掉",
        ".github/workflows/ci.yml",
        "        run: python scripts/layout_overflow_audit.py --compact --themes dark,light"
        " --scales 1.0,1.1,1.25 --require-fonts",
        "        run: echo skip",
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
        'filevers=(2, 2, 3, 0)',
        'filevers=(2, 2, 1, 0)',
        'tests/test_version_consistency.py::test_version_info_tuples_match',
        'exe 文件属性里的版本号停在上一版，排障时对着用户截图会认错版本',
    ),
    Revert(
        'VER', 'version_info.txt 的 ProductName 忘了跟着抬',
        'version_info.txt',
        "StringStruct(u'ProductName', u'CS2 Customizer 2.2.3')",
        "StringStruct(u'ProductName', u'CS2 Customizer 2.2.1')",
        'tests/test_version_consistency.py::test_version_info_strings_match',
        '任务管理器/属性页显示的产品名还是旧版本号',
    ),
    Revert(
        'VER', '只漏了 ProductVersion 一个字段（考验"游离版本号"全文扫）',
        'version_info.txt',
        "StringStruct(u'ProductVersion', u'2.2.3.0')",
        "StringStruct(u'ProductVersion', u'2.2.1.0')",
        'tests/test_version_consistency.py::test_version_info_has_no_stray_version',
        '逐字段枚举的判据可能漏枚举某个字段；这条不枚举、直接全文扫，是兜底',
    ),
    Revert(
        'VER', 'installer.iss 的 AppVersion 忘了跟着抬',
        'build_tools/installer.iss',
        '#define AppVersion "2.2.3"',
        '#define AppVersion "2.2.1"',
        'tests/test_version_consistency.py::test_installer_iss_appversion_matches',
        '后果最重：装进 CS2 Customizer<旧版本> 目录，升级变成两份并存',
    ),
    Revert(
        'VER', 'installer.iss 头部注释停在旧版本',
        'build_tools/installer.iss',
        '安装脚本(2.2.3,onedir 形态)',
        '安装脚本(2.1.4,onedir 形态)',
        'tests/test_version_consistency.py::test_installer_iss_header_comments_match',
        '注释腐烂：下次照着这行去理解脚本适用版本会被误导',
    ),
    Revert(
        'VER', 'README 首行标题被改成别的项目名',
        'README.md',
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
        '## [2.2.3] - ',
        '## [2.1.4] - ',
        'tests/test_version_consistency.py::test_changelog_has_section_for_current_version',
        '抬了版本号却忘了写 changelog，发布时没有可抄的内容（闭源版发 2.2.0/2.2.1 时踩过）',
    ),

    # ==================================== BRAND：旧品牌不得回流（2026-08-12 建立）
    # 开源改名那一轮动了 107 个文件 507 处。这类机械改名的失败方式不是"改错"而是"改漏"，
    # 而漏掉运行时标识**不会让任何用例变红**：程序照跑，只是把数据写进了另一个产品的目录。
    # 前四条是行为判据（读运行时真正用的常量），最后两条是文本判据与白名单防腐。
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

    # ==================================== DOC：落地页完整性（2026-08-12 建立）
    # README 是绝大多数人对这个项目的**唯一一次接触**，而它恰好是判据盲区最大的地方：
    # ruff 不看 Markdown、测试不看图片引用、CI 也不渲染页面。
    # 开源化时就实际发生过"首页三个破图标"，三道门一道都没拦住。
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

    # ==================================== QA-024：Windows 瞬时占用（2026-08-12 建立）
    Revert(
        'QA', '写快照索引不走重试（撞上 Defender 就丢那份"后悔药"）',
        'core/config_snapshot_manager.py',
        '    _replace_with_retry(tmp_path, path)',
        '    os.replace(tmp_path, path)',
        'tests/test_config_snapshot_manager.py::test_index_write_and_restore_both_go_through_the_retry',
        '实测：快照判据在同一台机器上连跑 25 遍红 2 遍（8%），失败点全在这一句。'
        '用户点「恢复设置」时产品先建的那份后悔药，会因为扫描器占住文件而静默丢失',
    ),
    Revert(
        'QA', '重试只认错了异常类型（PermissionError 照旧穿出去）',
        'core/config_snapshot_manager.py',
        '        except PermissionError:\n            time.sleep(delay)',
        '        except FileNotFoundError:\n            time.sleep(delay)',
        'tests/test_config_snapshot_manager.py::test_replace_with_retry_survives_transient_permission_error',
        '重试逻辑在，但捕的不是实际抛出来的那个异常——这是"看着有防护其实没有"的典型',
    ),

    # ==================================== ASSET：品牌图不得与生成器脱钩（2026-08-12 建立）
    # 这一组补的是 BRAND 组的结构性盲区：文本判据明确跳过二进制文件（不跳不行，
    # 你没法对 PNG 做字符串替换），代价是**印在图里的字判据一个字也看不见**。
    # 真实发生过：改名那轮改了 107 个文本文件 507 处、二进制一处没动，公开前的
    # 仓库里只剩启动闪屏和安装向导大图还印着旧产品名（向导图上连旧官网域名都在），
    # 而全部判据 + ruff + CI 一路全绿。
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
    # ---- 图标：2026-08-12 从"一张来源不清的 AI 位图"改成代码生成 ----
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


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--only", default="", help="只跑某一组（R9-A / R9-B / R9-C / R9-D）")
    args = ap.parse_args()

    items = [r for r in REVERTS if not args.only or r.group == args.only]

    # 开跑前给所有涉及的文件拍快照，收尾无论如何都还原
    touched = {r.path for r in items}
    snapshot = {p: p.read_bytes() for p in touched}

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
    if missed:
        print(f"❌ {len(missed)} 条判据是**假绿**的：")
        for r, note in missed:
            print(f"  - {r.group} {r.name} → {r.selector}")
        return 1
    return 0 if not skipped else 3


if __name__ == "__main__":
    raise SystemExit(main())

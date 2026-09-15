# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R4 · 主题对比度审计（UP-021 / UP-022 / UP-023 / UP-050）。

**纯 token 数学**：只读 `ThemeColors` 的色值算 WCAG 比值，不建任何控件、
不起 QApplication、不碰前台。所以它能进 CI，也能在任何机器上秒回。

为什么需要它：R0 勘察发现的对比度缺陷有 4 条，全是"某个主题下某段文字看不见"。
这类缺陷靠人眼在 9 个主题里来回切是查不干净的——`primaryButton` 的白字在
深紫主题下好好的，到墨绿主题就只剩 1.4:1。数学能一次性覆盖 9×N 个组合。

判据（WCAG 2.1 §1.4.3）：
  - 正文 / 按钮文字 ≥ 4.5:1
  - 大字（≥18px 加粗）、图形边界 ≥ 3:1
  - 禁用态**不参与** WCAG（规范明确豁免），但必须和可用态**看得出区别**，
    否则就是 UP-022 那个缺陷本身 —— 这里单独用"可用/禁用文字色差异"来卡。

用法:
    python scripts/ui_contrast_audit.py            # 只报不达标项
    python scripts/ui_contrast_audit.py --verbose  # 打全部比值
退出码: 0=全绿, 1=有不达标项。
"""
from __future__ import annotations

import argparse
import os
import re
import sys

# UP-083: 本脚本虽然只做 token 数学,但 import theme_manager 会连带把 config /
# logger 拉起来,于是每跑一次就往用户真实的 %LOCALAPPDATA%\CS2Customizer\logs 追加
# 一段启动横幅。诊断工具污染真实日志 = 污染真实崩溃的取证材料(UP-065 的教训)。
# 隔离必须在 import 产品代码之前设好。
# RN-032：配置目录一律走共享工装 —— 自己 mkdir + setdefault 挡不住
# migrate_old_config() 把仓库根那份未跟踪的个人 config.json 复制进来。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_contrast_audit")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
try:
    sys.stdout.reconfigure(encoding="utf-8")
except Exception:
    pass

from core.utils.contrast import AA_LARGE, AA_NORMAL, contrast_ratio, worst_contrast  # noqa: E402

# minimal 主题的 generate_stylesheet() 返回空串（走系统原生样式），
# 它那份 ThemeColors 是占位符、从不渲染 —— 审计它只会产生假警报。
SKIP_THEMES = {"minimal"}


_QSS_COMMENT = re.compile(r"/\*.*?\*/", re.S)


def _qss_rule_color(qss: str, selector: str, prop: str = "color") -> str | None:
    """从**生成出来的 QSS 产物**里取某条选择器的属性值。

    为什么必须读产物：R8a 第一版给 ghostButton:pressed 写的判据是
    `("ghost pressed", theme._accent_text_on(c.bg_elevated), (c.bg_elevated,), 4.5)` ——
    它自己调用产品代码里同一个函数现算前景色再判 AA，是**同义反复**：
    把 QSS 改回裸 `accent_primary`（深色主题 2.50:1）判据依然全绿。
    对抗复核当场用这个反例把它打穿了。

    判据必须落在「用户实际看到的那个值」上，不能落在「我认为它应该是什么」上。
    """
    match = _qss_rule_body(qss, selector)
    if match is None:
        return None
    prop_match = re.search(
        r"(?<![-\w])" + re.escape(prop) + r"\s*:\s*([^;\n]+)", match
    )
    return prop_match.group(1).strip() if prop_match else None


def _qss_rule_body(qss: str, selector: str) -> str | None:
    """取某条选择器的规则体。

    选择器**必须锚在行首**：`QPushButton#actionButton:hover` 同时是
    `QWidget#musicControlBar QPushButton#actionButton:hover` 的子串，
    不锚的话两条规则谁在文件里靠前就查谁——查的还是不是想查的那条，全凭运气。
    """
    body = _QSS_COMMENT.sub("", qss)  # 模板注释会原样进入产物，先剥掉
    pattern = re.compile(
        r"^[ \t]*" + re.escape(selector) + r"\s*\{([^}]*)\}", re.S | re.M
    )
    match = pattern.search(body)
    return match.group(1) if match else None


def _qss_bg_stops(qss: str, selector: str) -> tuple[str, ...]:
    """取某条规则背景里出现的所有色值（渐变则返回各端点）。

    不能复用 `_qss_rule_color`：它的属性值正则是 `[^;\\n]+`，遇到换行就停，
    而 QSS 里的 `qlineargradient(...)` 是**跨两行**写的——
    只取第一行会拿到 `qlineargradient(x1:0, y1:0, x2:1, y2:1,`，一个色值都没有，
    判据于是退回兜底色，看着在查渐变，其实没查。
    """
    rule = _qss_rule_body(qss, selector)
    if rule is None:
        return ()
    decl = re.search(r"(?<![-\w])background(?:-color)?\s*:\s*([^;]+)", rule, re.S)
    if not decl:
        return ()
    return tuple("#" + h for h in re.findall(r"#([0-9a-fA-F]{6})", decl.group(1)))


def _checks(theme):
    """返回 [(名称, 前景, 背景s, 阈值), ...]。背景可以是元组=取最差。"""
    c = theme.colors
    qss = theme.generate_stylesheet()
    # 从产物里取真实值；取不到就退回 token（并在名称上标出来，别装作查过了）
    ghost_pressed_fg = _qss_rule_color(qss, "QPushButton#ghostButton:pressed") or c.accent_primary
    ghost_pressed_bg = (
        _qss_rule_color(qss, "QPushButton#ghostButton:pressed", "background-color")
        or c.bg_elevated
    )
    ghost_hover_fg = _qss_rule_color(qss, "QPushButton#ghostButton:hover") or c.text_primary
    ghost_hover_bg = (
        _qss_rule_color(qss, "QPushButton#ghostButton:hover", "background-color") or c.bg_tertiary
    )
    # UP-076：actionButton 是全站最常见的按钮，hover 字色原先直接用 accent_primary，
    # 实测按渐变最差端算 5/9 主题不过 AA（dark 2.50 / warm 2.28 / rose 2.99 /
    # light 2.94 / purple 3.64）。底是 bg_tertiary→bg_elevated 的渐变，两端都要算。
    action_hover_fg = _qss_rule_color(qss, "QPushButton#actionButton:hover") or c.accent_primary
    action_hover_bgs = (
        _qss_bg_stops(qss, "QPushButton#actionButton:hover")
        or (c.bg_tertiary, c.bg_elevated)
    )
    text_bgs = (c.bg_primary, c.bg_secondary, c.bg_card)
    # primaryButton 底是 lighten(accent) → accent 的渐变，两端都要算
    accent_stops = (theme._accent_gradient_top(), c.accent_primary)
    return [
        ("正文 text_primary", c.text_primary, text_bgs, AA_NORMAL),
        ("次要 text_secondary", c.text_secondary, text_bgs, AA_NORMAL),
        ("提示 text_muted(hintLabel)", c.text_muted, text_bgs, AA_NORMAL),
        ("主按钮文字 text_on_primary", c.text_on_primary, accent_stops, AA_NORMAL),
        ("危险按钮文字", theme._on_color(theme._danger_bg()), (theme._danger_bg(),), AA_NORMAL),
        ("chip 警告文字", theme._chip_text(c.accent_warm), (c.bg_card,), AA_NORMAL),
        ("chip 错误文字", theme._chip_text(c.error), (c.bg_card,), AA_NORMAL),
        # R7 补 R4 的漏：R4 只查了「禁用色和常态色能否分辨」，没查「禁用文字在
        # **禁用底**上能否看清」。实测 8/8 主题只有 1.64~2.33:1 —— 文字消失了。
        # 禁用底是 bg_tertiary 以 90/255 叠在卡片上，必须按合成后的色算。
        # 阈值取 3.0 而非 4.5：禁用控件本就该弱化，但不该隐身。
        ("禁用态文字 text_on_disabled", c.text_on_disabled,
         (theme._blend_hex(c.bg_tertiary, 90, c.bg_card),), AA_LARGE),
        # R8a 新补的 ghostButton（UP-073）两个交互态。常态是 text_secondary
        # 落在 text_bgs 上，已被上面第 2 条覆盖，这里只补 hover / pressed。
        # 前景/背景都从 **QSS 产物** 里取（见 _qss_rule_color 的说明）——
        # 第一版拿产品代码现算，是同义反复，改坏了也照样绿。
        ("ghost 按钮 hover 文字(读QSS)", ghost_hover_fg, (ghost_hover_bg,), AA_NORMAL),
        ("ghost 按钮 pressed 文字(读QSS)", ghost_pressed_fg, (ghost_pressed_bg,), AA_NORMAL),
        # UP-076（R8-W5 修）：同样从 QSS 产物里取，回退到裸 accent 就会红。
        ("action 按钮 hover 文字(读QSS)", action_hover_fg, action_hover_bgs, AA_NORMAL),
        # ⭐⭐⭐ 2026-09-06 批 61：这里原来写着「非文字对比度…已另立 UP-063
        #   留到 R7 …… 本轮不在此判失败」。R4 推给 R7、R7 又推一次，
        #   UP-063 现在记作**已放弃** —— 而同一件事在翻新工程账上是
        #   **RN-045（S2）**，一直挂着。⭐ **一条写在注释里的缓期，
        #   没有任何东西看着它到期**（同 RN-538）。
        #   ⇒ 非文字那一档现在有自己的分母，见 `_nontext_checks()`。
    ]


# ⭐ WCAG 2.1 §1.4.11「非文字对比度」：图形对象与**用户界面组件的边界**
#   要 ≥ 3:1。它管的不是「好不好看」，是「看不看得出这里有个东西」。
#   滚动条把手是最典型的一例 —— 看不出能滚，对用户就等于「下面没有内容」。
NONTEXT_THRESHOLD = AA_LARGE  # 3.0


def _nontext_checks(theme):
    """返回 [(名称, 前景, 背景s, 阈值), ...]；背景取最差的那一档。"""
    c = theme.colors
    bgs = (c.bg_primary, c.bg_secondary, c.bg_card)
    out = [
        ("滚动条把手 scrollbar_handle", c.scrollbar_handle, bgs),
        ("滚动条 hover scrollbar_hover", c.scrollbar_hover, bgs),
        ("主边框 border_primary", c.border_primary, bgs),
    ]
    for token in ("border_secondary", "border_focus"):
        val = getattr(c, token, None)
        if val:
            out.append((f"边框 {token}", val, bgs))
    # RN-640：静态控件边框这一档**照量、照进 rows，但不算违规**（理由见 EXEMPT_CONTROL_REASON）。
    out.append((f"边框 {EXEMPT_CONTROL_TOKEN}", resting_control_border(theme), bgs))
    return [(label, fg, bg, NONTEXT_THRESHOLD) for label, fg, bg in out]


def resting_control_border(theme) -> str:
    """静态控件边框的**合成色** —— 和 `generate_stylesheet` 用同一条推导，别各算各的。"""
    from theme_manager import Theme

    return Theme.resting_border(theme.colors)


# ---- 存量债 ----
# ⭐ 批 61 建这张表时有 18 项；批 62 逐项裁定后**清零**：
#   · `border_primary` 8 项 + `border_focus` 2 项 ⇒ **修好了**（推过 3:1）；
#   · `border_secondary` 8 项 ⇒ **裁定豁免**，理由见下面 `EXEMPT_*`。
# ⛔ 这张表只许变短。新欠的账不许往这儿记 —— 要么修，要么单独立案。
NONTEXT_DEBT: set[tuple[str, str]] = set()

# ---- 豁免：`border_secondary` 这一档 ----
# WCAG 2.1 §1.4.11 管的是「**用户界面组件**的边界」和「理解内容所必需的图形」。
# `border_secondary` 实测只用在三类地方，三类都不在射程内：
#   ① 装饰性容器与分隔线（QFrame#card / #section / #group / 侧栏容器 /
#      QMenu::separator / 表格网格线与表头）——它们是版面，不是可操作的组件；
#   ② `:disabled` 与 `[masterOff="true"]` 失效态 —— 规范**明确豁免**禁用控件；
#   ③ 没有第三类。
# ⭐⭐ **这条豁免的死期就写在下面那条断言里**：只要有人把 `border_secondary`
#   用到一个真的控件边界上，理由当场不成立、判据当场红。
#   ⚠ 它在写下来的当天就抓到两个（批 62）：`QPushButton#modeToggleButton,
#     QPushButton#modeToggleIconButton` 和 `QTextEdit, QPlainTextEdit` ——
#     两个都是控件边界，已改走 `border_primary`。
#   ⭐ **一条豁免只要求你写下理由，就会自己筛掉不该被豁免的那几个。**
# ---- 豁免：`border_control` 这一档（RN-640，用户裁定 2026-09-15）----
# 这是**用户界面组件的静止边**，WCAG 1.4.11 字面上管得着 —— 所以这不是「不在射程内」，
# 是**明知在射程内而放弃**：批 61 把它抬到 3:1 之后，用户在真机上的原话是
# 「主要让我难受的就是这些密密麻麻的边框」。深色主题上 3:1 的静态边 = 每个控件一根亮线。
# 放弃的范围只有静止态：hover 仍走 border_primary、focus 仍走 border_focus，两者照旧 ≥3:1 判红。
# ⚠ 数字照量、照进 rows，不许因为豁免就不量 —— 想把它调回来的人得先看到现在的数。
EXEMPT_CONTROL_TOKEN = "border_control"
EXEMPT_CONTROL_REASON = "用户裁定放弃静止态控件边框的 3:1（RN-640）；hover/focus 态不豁免"

EXEMPT_TOKEN = "border_secondary"
EXEMPT_REASON = "装饰容器 / 分隔线 / 表格网格 / 禁用与失效态 —— 均不属 WCAG 1.4.11 的「用户界面组件边界」"
# 允许出现 `c.border_secondary` 的选择器长什么样（命中任一即算装饰或失效态）
EXEMPT_SELECTOR_MARKS = (
    ":disabled", 'masterOff="true"',
    "QFrame#", "QWidget#", "QGroupBox", "QMenu::separator",
    "QHeaderView::section", "QTableCornerButton::section",
    "QListWidget", "QTableWidget", "QTreeWidget", "QTableView", "QTreeView",
)


def exempt_selectors_are_still_decorative():
    """把「豁免的理由」本身跑一遍：返回**说不通**的那几个选择器。"""
    import re as _re
    from pathlib import Path as _Path

    src = (_Path(__file__).resolve().parent.parent / "theme_manager.py").read_text(
        encoding="utf-8")
    lines = src.splitlines()
    bad, seen = [], 0
    for i, ln in enumerate(lines):
        if f"c.{EXEMPT_TOKEN}" not in ln:
            continue
        seen += 1
        sel = "(没找到选择器)"
        for j in range(i, max(0, i - 60), -1):
            m = _re.match(r"^\s*([^\n{]+?)\s*\{\{\s*$", lines[j])
            if m and not lines[j].lstrip().startswith("#"):
                sel = m.group(1).strip()
                break
        if not any(mark in sel for mark in EXEMPT_SELECTOR_MARKS):
            bad.append((i + 1, sel))
    return seen, bad


def audit_nontext():
    """现量一遍非文字对比度，返回 (全部结果, 新增违规, 已修好却还在册的)。

    ⭐ **现量，别读自己冻的那份**（RN-544 那条）：这里每次都从 `ThemeColors`
      重算，判据也调这个函数，所以判据和门禁看到的是同一份数。
    """
    from theme_manager import get_theme_manager

    rows, fresh, healed = [], [], []
    tm = get_theme_manager()
    for name, theme in tm.themes.items():
        if name in SKIP_THEMES:
            continue
        for label, fg, bgs, threshold in _nontext_checks(theme):
            ratio = worst_contrast(fg, bgs)
            rows.append((name, label, fg, ratio, threshold))
            # ⭐ 豁免那一档照量、照进 rows（数字要看得见），但不算违规。
            #   真正会判红的是 `exempt_selectors_are_still_decorative()` ——
            #   **豁免的理由本身**。
            if EXEMPT_TOKEN in label or EXEMPT_CONTROL_TOKEN in label:
                continue
            in_debt = (name, label) in NONTEXT_DEBT
            if ratio < threshold and not in_debt:
                fresh.append((name, label, fg, ratio, threshold))
            elif ratio >= threshold and in_debt:
                healed.append((name, label, fg, ratio, threshold))
    return rows, fresh, healed


def _disabled_distinguishable(theme) -> tuple[bool, float]:
    """禁用态文字必须和常态文字**看得出差别**（UP-022 的本体）。

    WCAG 豁免禁用控件，所以这里不套 4.5；但如果 text_disabled 和 text_primary
    几乎一样亮，用户就完全无法判断按钮为什么点不动。要求两者比值 ≥ 1.6
    （约等于人眼能稳定分辨的最低差异档）。
    """
    ratio = contrast_ratio(theme.colors.text_disabled, theme.colors.text_primary)
    return ratio >= 1.6, ratio


def main() -> int:
    ap = argparse.ArgumentParser(description="CS2 Customizer 主题对比度审计")
    ap.add_argument("--verbose", action="store_true", help="打印全部比值，不只是失败项")
    ap.add_argument("--target", type=float, default=None,
                    help="覆盖正文阈值（默认 WCAG AA 4.5）")
    args = ap.parse_args()

    from theme_manager import get_theme_manager

    tm = get_theme_manager()
    failures = []
    checked = 0

    for name, theme in tm.themes.items():
        if name in SKIP_THEMES:
            print(f"-- 跳过 {name}（系统原生样式，token 不参与渲染）")
            continue
        print(f"== {name} ({theme.name}) ==")
        for label, fg, bgs, threshold in _checks(theme):
            if args.target is not None and threshold == AA_NORMAL:
                threshold = args.target
            ratio = worst_contrast(fg, bgs)
            checked += 1
            ok = ratio >= threshold
            if not ok:
                failures.append((name, label, fg, ratio, threshold))
            if args.verbose or not ok:
                mark = "  " if ok else "!!"
                print(f"  {mark} {label:<28} {fg}  {ratio:.2f}:1 (需 {threshold})")

        ok, ratio = _disabled_distinguishable(theme)
        checked += 1
        if not ok:
            failures.append((name, "禁用态与常态文字可分辨", theme.colors.text_disabled, ratio, 1.6))
            print(f"  !! 禁用态与常态文字可分辨   {theme.colors.text_disabled}  "
                  f"{ratio:.2f}:1 (需 1.6)")
        elif args.verbose:
            print(f"     禁用态与常态文字可分辨   {theme.colors.text_disabled}  {ratio:.2f}:1")

    # ---- 非文字那一档（WCAG 1.4.11）----
    rows, fresh, healed = audit_nontext()
    checked += len(rows)
    exempt_rows = [r for r in rows if EXEMPT_TOKEN in r[1]]
    debt_now = [r for r in rows if r[3] < r[4] and EXEMPT_TOKEN not in r[1]]
    seen, not_decorative = exempt_selectors_are_still_decorative()
    print(f"   豁免 {len(exempt_rows)} 项（{EXEMPT_TOKEN}，{EXEMPT_REASON}）；"
          f"实测比值 {min(r[3] for r in exempt_rows):.2f}~{max(r[3] for r in exempt_rows):.2f}:1，"
          f"用在 {seen} 处")
    for line, sel in not_decorative:
        print(f"  ❌ 第 {line} 行 `{sel}` 在用 {EXEMPT_TOKEN} —— 这看着是控件边界，"
              f"而豁免的理由是「只用在装饰与失效态」")
        failures.append((sel, f"{EXEMPT_TOKEN} 的豁免理由不成立", "-", 0.0, 3.0))
    print(f"\n== 非文字对比度（WCAG 1.4.11，门槛 {NONTEXT_THRESHOLD}）：{len(rows)} 项，欠着 {len(debt_now)} 项 ==")
    for name, label, fg, ratio, threshold in debt_now:
        if EXEMPT_TOKEN in label or EXEMPT_CONTROL_TOKEN in label:
            tag = "豁免"          # 照量照印，但按上面写下的理由不算违规
        else:
            tag = "存量" if (name, label) in NONTEXT_DEBT else "**新增**"
        print(f"  {tag} [{name}] {label}: {fg} → {ratio:.2f}:1，需 ≥{threshold}")
    for row in fresh:
        failures.append(row)
    for name, label, fg, ratio, threshold in healed:
        print(f"  ✅ [{name}] {label} 已达标（{ratio:.2f}:1）—— **请把它从 NONTEXT_DEBT 里删掉**")
        failures.append((name, f"{label}（已修好却还挂在存量册上）",
                         fg, ratio, threshold))

    print(f"\n== 共检查 {checked} 项，{len(failures)} 项不达标 ==")
    for theme_name, label, fg, ratio, threshold in failures:
        print(f"  [{theme_name}] {label}: {fg} → {ratio:.2f}:1，需 ≥{threshold}")
    return 1 if failures else 0


if __name__ == "__main__":
    # ⚠ RN-092：裁定走 `_audit_verdict`，不走退出码 —— 见那个文件的说明。
    from _audit_verdict import deliver, make_teardown_noise_visible

    make_teardown_noise_visible()
    deliver("contrast", main())

# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""非文字对比度（WCAG 2.1 §1.4.11）有没有人看着（RN-045 / X2）。

## 这条判据在防什么

⭐⭐⭐ `scripts/ui_contrast_audit.py` 一直在跑、一直是绿的、一直报「0 项不达标」——
   而它自己最后一条注释逐字写着：「输入框/聚焦边框的非文字对比度 9 个主题
   **全部只有 1.2~1.9:1** …… 已另立 UP-063 留到 R7 …… **本轮不在此判失败**」。
   R4 推给 R7、R7 又推一次，UP-063 最后记作**已放弃**；
   而同一件事在翻新工程账上是 **RN-045（S2）**，一挂就是几十批。
   ⭐ **一条写在注释里的缓期，没有任何东西看着它到期。**（同 RN-538：
     豁免的理由过期了，而豁免本身没有任何东西看着。）

## 三件事

① **滚动条把手按硬阈值判**（批 61 已把九个主题全部推过 3:1，实测 3.41~3.80）。
   ⚠ 它原来是 `_hex_to_rgba(scrollbar_handle, 60)` —— 而**兑水兑得少一点还是水**：
     有人早就诊断对了并把侧栏那一处抬到 alpha 130，实测只从 1.06 爬到 1.16，
     因为病根是**把手色本身就和底色几乎同亮度**。⇒ 判据要同时钉住
     「颜色够亮」和「不许再兑 alpha」两件事。
② **边框那 18 项走存量棘轮**：只许变少。⛔ 不直接判红 ——
   「一道长期红着的门禁等于没有这道门禁」（批 51 RN-505）。
③ **反向断言**：修好了却还挂在存量册上，也红（同 RN-519）。

⭐ 判据**现量**，不读任何冻下来的数（RN-544：一条只读自己冻结值的棘轮，
  结构上看不见增长）。
"""
from __future__ import annotations

import os
import re
import sys
from pathlib import Path

import pytest

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")

REPO = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(REPO))
sys.path.insert(0, str(REPO / "scripts"))


@pytest.fixture(scope="module")
def audit():
    import ui_contrast_audit as mod
    return mod


def test_the_denominator_actually_covers_the_themes(audit):
    """分母守卫：不许因为主题表没读到而空转（批 42 那条公共守卫的形态）。"""
    rows, _fresh, _healed = audit.audit_nontext()
    themes = {r[0] for r in rows}
    assert len(themes) >= 8, f"只量到 {len(themes)} 个主题：{sorted(themes)}"
    assert len(rows) >= 40, f"只量到 {len(rows)} 项非文字对比度 —— 分母塌了"


def test_no_new_nontext_violation(audit):
    """存量之外再冒出一项不达标，当场红。"""
    _rows, fresh, _healed = audit.audit_nontext()
    assert not fresh, (
        "非文字对比度冒出了存量册之外的新违规：\n  "
        + "\n  ".join(f"[{n}] {label} {fg} → {ratio:.2f}:1（需 ≥{th}）"
                      for n, label, fg, ratio, th in fresh)
        + "\n⭐ WCAG 2.1 §1.4.11：用户界面组件的边界要 ≥3:1，"
          "它管的不是好不好看，是**看不看得出这里有个东西**。")


def test_the_debt_list_does_not_keep_healed_items(audit):
    """反向断言：修好了就得从存量册上划掉，否则这张册子会慢慢变成免检区。"""
    _rows, _fresh, healed = audit.audit_nontext()
    assert not healed, (
        "这几项已经达标了，却还挂在 `NONTEXT_DEBT` 里：\n  "
        + "\n  ".join(f"[{n}] {label} → {ratio:.2f}:1" for n, label, _fg, ratio, _th in healed)
        + "\n⭐ 一张只增不减的名单会慢慢变成免检区（同 RN-519 / UP-091）。")


def test_the_debt_only_shrinks(audit):
    """棘轮：批 61 实测 18 项，只许减不许增。"""
    assert len(audit.NONTEXT_DEBT) <= 18, (
        f"存量册涨到 {len(audit.NONTEXT_DEBT)} 项（批 61 实测 18）——"
        "新欠的账不许往这张表上记，要么修，要么单独立案。")


def test_the_scrollbar_handle_is_visible_in_every_theme(audit):
    """RN-045（S2）：九个主题的滚动条把手都要过 3:1，且**不在存量册里**。"""
    rows, _fresh, _healed = audit.audit_nontext()
    bad = [(n, label, fg, ratio) for n, label, fg, ratio, th in rows
           if "scrollbar" in label and ratio < th]
    assert not bad, (
        "这几个主题的滚动条把手还是看不见：\n  "
        + "\n  ".join(f"[{n}] {label} {fg} → {ratio:.2f}:1" for n, label, fg, ratio in bad)
        + "\n⭐ 看不出能滚，对用户就等于「下面没有内容」。")
    parked = {k for k in audit.NONTEXT_DEBT if "scrollbar" in k[1]}
    assert not parked, f"滚动条那几项不许躺进存量册：{sorted(parked)}"


def test_the_handle_is_not_watered_down_with_alpha():
    """⭐⭐ 结构断言：把手不许再兑 alpha。

    颜色够亮和「不兑水」是**两件事**：把颜色改对之后，只要有人把
    `_hex_to_rgba(c.scrollbar_handle, 60)` 加回来，实际看到的颜色又会
    变成一个取决于底色的东西 —— 而同一根滚动条会压在 bg_primary /
    bg_secondary / bg_card 三种底色上，一个 alpha 不可能在三处都对。
    ⚠ 这一条量的是**源码**：批 60 那次教训 ——
      判据量的东西和承重的东西不是同一个，就是一条哑判据。
    """
    src = (REPO / "theme_manager.py").read_text(encoding="utf-8")
    # ⭐ 分母守卫（批 61 全量当场点名，`test_judges_are_not_idling` 逮的）：
    #   这条判据是「扫一遍源码、只做否定断言」的形态 —— 文件读空了、
    #   token 改了名，它照样全绿。⇒ 先证明扫到的东西不是空的。
    assert src.count("scrollbar_handle") >= 10, (
        f"只在 theme_manager.py 里扫到 {src.count('scrollbar_handle')} 处 "
        "`scrollbar_handle` —— 分母塌了，这条判据在空转")
    watered = re.findall(r"_hex_to_rgba\(\s*c\.scrollbar_handle\s*,\s*\d+\s*\)", src)
    assert not watered, (
        f"滚动条把手又被兑了 alpha：{watered}\n"
        "⭐ 兑水兑得少一点还是水 —— 侧栏那一处曾从 60 抬到 130，"
        "实测只把深色主题从 1.06 抬到 1.16。")


def test_the_scrollbar_track_is_drawn_not_transparent():
    """⭐⭐⭐ RN-045 后一半：**对比度过线不等于看得见 —— 还得有一条槽。**

    同题面行为题，依据提到滚动条：修之前（把手 1.06:1）**0/12**；
    只修把手对比度（3.41~3.80，仍 6px 宽、轨道透明）**3/21（14%）**。
    ⚠ 中间试过把宽度 6 → 10px，行为题涨到 **10/20（50%）** —— 而那 4px 在紧凑档
    换来 **13 处**「最小高超出可视区」（7px 就开始红，**余量不到 1px**）。
    ⭐⭐⭐ **一个已经零余量的容器，会把任何一次改进都变成一次「变坏」**
    （那是 RN-529 的题目，排在批 64）。
    ⇒ 改用不占版面的那一半：轨道原来是 `transparent`，屏幕上只有一小节把手浮着，
      没有「这里是一条可滚的槽」这件事。把它画出来。
    """
    src = (REPO / 'theme_manager.py').read_text(encoding='utf-8')
    bad = []
    for axis in ('vertical', 'horizontal'):
        head = f'QScrollBar:{axis} {{{{'
        i = src.find(head)
        assert i > 0, f'样式表里找不到 QScrollBar:{axis} —— 判据在空转'
        body = src[i:src.find('}}', i)]
        if 'background: transparent' in body:
            bad.append(axis)
    assert not bad, (
        f'这几条滚动条的轨道又画成透明了：{bad}\n'
        '⭐ 只剩一小节把手浮在页面上，读不出「这里是一条可滚的槽」。')


def test_the_exemption_reason_still_holds(audit):
    """⭐⭐⭐ **写下一条豁免的同时就要写下它的死期**（RN-538）。

    `border_secondary` 整档被判成「装饰容器 / 分隔线 / 表格网格 / 禁用与失效态」，
    所以不进 WCAG 1.4.11 的分母。那句话本身就是这条判据 ——
    只要有人把它用到一个真控件边界上，理由当场不成立。
    ⚠ 它在写下来的当天就抓到两个（批 62）：顶栏模式切换按钮、多行输入框。
    ⚠⚠ 而它原来只跑在审计脚本的 `main()` 里 —— **破坏验证当场判它假绿**，
      因为门禁那条路（pytest）根本没人调它。
      ⭐ 一条只在某一条路上生效的守卫，在另一条路上就是不存在。
    ⚠⚠⚠ 它还被我**自己删过一次**：一次「截断到某个函数再拼新的」改写把它连带删了，
      而**全量照样全绿** —— 是回退断点点着它的名，失效体检才报出来。
    """
    seen, bad = audit.exempt_selectors_are_still_decorative()
    assert seen >= 20, f"只扫到 {seen} 处 c.{audit.EXEMPT_TOKEN} —— 分母塌了"
    assert not bad, (
        f"这几处在用 {audit.EXEMPT_TOKEN}，而它们看着是**控件边界**，不是装饰：\n  "
        + "\n  ".join(f"第 {line} 行  {sel}" for line, sel in bad)
        + f"\n⭐ 豁免的理由是「{audit.EXEMPT_REASON}」—— 理由不成立，豁免就不成立。")

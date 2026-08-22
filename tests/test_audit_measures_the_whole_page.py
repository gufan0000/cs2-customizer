# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-030：排版审计必须量**整页**，不是只量页签里那一截。

## 这条判据要防的事（实测出来的数，不是推断）

`layout_overflow_audit._scopes()` 原来的写法是：页面里只要有一个
`QTabWidget`，就**只**返回各个页签的内容控件。那句话当年是为了躲开
「非当前页签保留着构造时的陈旧几何」这个假阳性（见 `_scopes` 自己的说明），
理由成立 —— 但它连带把**页签之外的所有东西**一起排除了：页头、状态徽章条、
顶层卡片、底部操作栏，全都不再有任何判据看得见。

2026-08-22 只读探针实测（完整档 / dark / 1.0）：

    magnifier      129 / 210 个可见控件在所有测量范围之外  （61%）
    voice_output    77 / 164                                （47%）
    kill_sound / kill_voice / switch_weapon / reload_sound   各 38
    gun_sound 36 · flash 35 · utility 33 · special_sound 31
    ——————————————————————————————————————————————
    10 / 28 页受影响，全站合计 493 个可见控件从未被量过

⭐ 最硬的一条证据：`magnifier` 那 129 个里逐字包含 `主武器热键:`、
`防抖延迟(ms):`、`微调:`、`大幅:` —— **正是 RN-191 那四个折行的标签**。
那条缺陷一直住在审计的盲区里，只有外审看得见；修的时候也没人发现盲区存在。

## 为什么判据要写成「断言分母」而不是「断言某一页没问题」

本工程到这里已经踩了**五种**分母失效：
整类被豁免（RN-177）· 页面范围太小（RN-186 只盯 basic 一页）·
只写了必要的那一半（RN-185 四颗一起被压扁就"齐平"）·
分母由结论决定（RN-189 遍历「已经合规的页」）· 以及这一条。

五次的共同点是：**判据本身是绿的，而它没在看**。所以这里不再去断言
「某某页没有溢出」——那种判据的绿说明不了任何事——改成直接断言
**每一个可见控件都至少落在一个测量范围里**。以后谁再把 `_scopes()`
收窄，或者把 skip 写过头，这一条当场变红。

⚠ 这条判据必须能被破坏证伪：把 `_scopes()` 改回「只返回页签内容」，
它必须在 10 页上变红。回退验证台里有对应的断点（`layout.whole_page_scope`）。
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest
from PySide6.QtCore import Qt
from PySide6.QtWidgets import QMessageBox, QWidget

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))


@pytest.fixture
def main_window(qapp, monkeypatch):
    """离屏主窗口。**铁律：不许弹真窗口、不许弹模态框。**"""
    monkeypatch.setenv("CS2C_SAFE_MODE_ACTIVE", "1")
    import _audit_neutralize as neutral
    from config import config

    neutral.apply(config)
    config.compact_mode = False
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    # RN-157：模态框在测试进程里是**卡死**不是失败。
    monkeypatch.setattr(QMessageBox, "warning", staticmethod(lambda *a, **k: None))

    import gui_widget

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)
    win.show()
    qapp.processEvents()
    win.setMinimumSize(1280, 800)
    win.resize(1280, 800)
    qapp.processEvents()
    yield win
    win.close()
    win.deleteLater()
    qapp.processEvents()


def _covered_ids(page, qapp):
    """`_scopes()` 交出来的范围，实际能枚举到哪些控件。

    ⭐ 量的是**判据真正看得到的东西**，不是 `_scopes()` 的返回值本身。
    如果只断言「返回值里有 page」，那么把 skip 写成"跳过一切"也照样绿 ——
    判据必须跟着判据的实际口径走。
    """
    import layout_overflow_audit as audit

    covered: set[int] = set()
    for scope_name, scope, skip in audit.scopes_with_skip(page, qapp):
        assert isinstance(scope_name, (str, type(None)))
        covered.add(id(scope))
        for child in scope.findChildren(QWidget):
            if audit.is_inside_any(child, skip):
                continue
            covered.add(id(child))
    return covered


def _missed(page, qapp):
    covered = _covered_ids(page, qapp)
    out = []
    for w in page.findChildren(QWidget):
        if w.isHidden():
            continue          # 离屏下 isVisible() 恒假，只能用 isHidden()
        if id(w) not in covered:
            out.append(w)
    return out


def _describe(widgets, limit=12):
    bits = []
    for w in widgets[:limit]:
        text = ""
        getter = getattr(w, "text", None)
        if callable(getter):
            try:
                value = getter()
            except TypeError:          # QTextEdit.text 之类签名不同的
                value = ""
            if isinstance(value, str):
                text = value.strip()[:24]
        bits.append(f"{type(w).__name__}#{w.objectName()}{'「' + text + '」' if text else ''}")
    if len(widgets) > limit:
        bits.append(f"…另外 {len(widgets) - limit} 个")
    return "、".join(bits)


def _auditable_pages(win):
    import _audit_neutralize as neutral

    page_ids = list(win._page_names.keys())
    neutral.apply(__import__("config").config, page_ids)
    unsafe = neutral.unsafe_pages()
    return [p for p in page_ids if p not in unsafe]


# ============================================ 一、命门：整页都得被量到


def test_every_visible_widget_of_every_page_falls_inside_some_scope(main_window, qapp):
    """全站每一页的每一个可见控件，都必须落在某个测量范围里。

    这是 RN-030 的正面判据。它红的时候给出的是**页面 + 漏掉的控件**，
    不是一句"覆盖率不够" —— 后者没法直接拿去修。
    """
    import _ui_mode as _um

    failures = []
    for page_id in _auditable_pages(main_window):
        _um.goto(main_window, page_id)
        qapp.processEvents()
        page = main_window.pages.get(page_id)
        if page is None:
            continue
        missed = _missed(page, qapp)
        if missed:
            failures.append(f"  [{page_id}] 漏掉 {len(missed)} 个：{_describe(missed)}")

    assert not failures, (
        "下面这些可见控件不在任何测量范围里 —— 排版审计的五条判据一条都看不见它们，"
        "这一页报「全绿」说明不了任何事（RN-030）：\n" + "\n".join(failures)
    )


# ============================================ 二、别把 skip 写过头


def test_the_page_scope_still_skips_the_tab_pages(main_window, qapp):
    """页面范围必须跳过**页签内容**，否则陈旧几何的假阳性会回来。

    ⚠ 这一条和上面那条是**互相拉住**的：只有上面那条，把 skip 删掉就能绿
    （代价是 R5 修掉的那批假阳性全部复活）；只有这一条，把 `_scopes()`
    收回原样也能绿。两条一起才钉得住"既量全、又不误报"。
    """
    import layout_overflow_audit as audit
    import _ui_mode as _um
    from PySide6.QtWidgets import QTabWidget

    checked = 0
    for page_id in _auditable_pages(main_window):
        _um.goto(main_window, page_id)
        qapp.processEvents()
        page = main_window.pages.get(page_id)
        if page is None:
            continue
        tabs = [t for t in page.findChildren(QTabWidget) if t.count() > 0]
        if not tabs:
            continue
        checked += 1
        page_scopes = [s for s in audit.scopes_with_skip(page, qapp) if s[0] is None]
        assert page_scopes, f"{page_id} 有页签，却没有「页面余下部分」这个范围"
        _name, scope, skip = page_scopes[0]
        assert skip, (
            f"{page_id} 的页面范围没有 skip —— 非当前页签的陈旧几何会被当成缺陷"
        )
        for tw in tabs:
            for i in range(tw.count()):
                content = tw.widget(i)
                if content is not None:
                    assert audit.is_inside_any(content, skip), (
                        f"{page_id} 的页签「{tw.tabText(i)}」内容没有被页面范围跳过"
                    )
    assert checked >= 8, f"带页签的页面只找到 {checked} 个，分母本身可能缩了"


# ==================================== 三、整页必须在页签被切之前量


def test_the_page_scope_is_measured_before_any_tab_is_touched(main_window, qapp):
    """⭐⭐ 工装的观测动作本身会改变被观测对象。

    实测（2026-08-22 紧凑档）：把页签切一遍，整页的布局最小高会**永久变大**，
    `setCurrentIndex(original)` 复位也回不来 —— magnifier 596→612、flash 500→516。
    成因是 Qt 的尺寸提示：页签内容没被显示过之前报的 hint 偏小。

    ⇒ 先切页签再量整页，量到的是**审计自己戳过之后**的页面。
    magnifier 的纵向缺口新鲜时 6px（容差内），戳过之后 22px —— 一条本来不该
    报的缺陷就这么被造出来了。

    这条判据断言的是**时序**：整页那一发出来的时候，页面还没被动过。
    """
    import layout_overflow_audit as audit
    import _ui_mode as _um
    from PySide6.QtWidgets import QTabWidget

    def min_h(page):
        lay = page.layout()
        return (lay.minimumSize().height() if lay is not None
                else page.minimumSizeHint().height())

    checked = []
    for page_id in _auditable_pages(main_window):
        _um.goto(main_window, page_id)
        qapp.processEvents()
        qapp.processEvents()
        page = main_window.pages.get(page_id)
        if page is None or not [t for t in page.findChildren(QTabWidget) if t.count() > 0]:
            continue

        fresh = min_h(page)
        seen_page_scope = False
        for name, scope, _skip in audit.scopes_with_skip(page, qapp):
            if name is None:
                assert not seen_page_scope, f"{page_id} 交出了两个整页范围"
                seen_page_scope = True
                assert scope is page, f"{page_id} 的整页范围不是 page 本身"
                assert min_h(page) == fresh, (
                    f"{page_id}：拿到整页范围时，页面的布局最小高已经从 {fresh} "
                    f"变成 {min_h(page)} —— 页签在这之前被切过了。\n"
                    "⇒ `scopes_with_skip` 必须是生成器，且整页那一发要在任何 "
                    "`setCurrentIndex` 之前 yield 出来。"
                )
        assert seen_page_scope, f"{page_id} 没有交出整页范围"
        checked.append(page_id)

    assert len(checked) >= 8, f"只检查到 {len(checked)} 个带页签的页面，分母本身可能缩了"


def test_scopes_with_skip_is_lazy(main_window, qapp):
    """空转守卫：它必须是**生成器**。

    改回一次性返回列表的话，上面那条时序判据会因为「列表构造完才开始遍历」
    而永远看不到新鲜状态 —— 它会静静地变成一条永远绿的判据。
    """
    import inspect
    import layout_overflow_audit as audit

    assert inspect.isgeneratorfunction(audit.scopes_with_skip), (
        "`scopes_with_skip` 不再是生成器 —— 整页那一发就不可能在页签被切之前量到了"
    )


# ==================================== 四、存量债棘轮的正反两面


def test_the_known_debt_ratchet_bites_in_all_three_directions():
    """RN-196 的棘轮必须**认得出**三种情况：新增、变坏、已经不该在册。

    ⚠ 「认得出」和「让门变红」是两件事：前两种红，第三种**只打印提醒**。

    第一版三种都红，理由也对（只判「变没变坏」的棘轮会退化成「记着一个古董」）——
    **但 CI 当场把整道门判红了**：那四条纵向债在 CI 的字体度量下根本不复现。
    ⭐⭐ **像素级棘轮是一台机器的事实**；「不再命中」既可能是修好了、也可能只是
    这台机器渲染得不一样，判据分不出这两者，分不出就不该拿它去红。
    所以这条判据仍然验第三向**被识别出来**，红不红由 `main()` 决定。
    """
    import layout_overflow_audit as audit

    known = dict(audit.KNOWN_COMPACT_DEBT)
    assert ("kill_sound", "clip") in known, "在册表被清空了？下面几条就成了空转"

    # ① 完全照在册的数命中 → 三样都空
    hits = [(pid, px) for (pid, kind), (px, _w) in known.items() if kind == "clip"]
    fresh, worse, loose = audit._split_known(hits, "clip")
    assert (fresh, worse, loose) == ([], [], []), (fresh, worse, loose)

    # ② 一页不在册 → 算新增
    fresh, worse, loose = audit._split_known(hits + [("advanced", 30)], "clip")
    assert fresh == [("advanced", 30)] and not worse and not loose

    # ③ 在册的那页变坏（超过 2px 容差）→ 算变坏
    worse_hits = [(pid, px + 3) if pid == "kill_sound" else (pid, px)
                  for pid, px in hits]
    fresh, worse, loose = audit._split_known(worse_hits, "clip")
    assert not fresh and worse and worse[0][0] == "kill_sound"

    # ③b 2px 以内不算（取整/滚动条钢化的抖动）
    jitter = [(pid, px + 2) if pid == "kill_sound" else (pid, px) for pid, px in hits]
    assert audit._split_known(jitter, "clip") == ([], [], [])

    # ④ 在册的那页不再命中 → 提醒收紧
    fewer = [(pid, px) for pid, px in hits if pid != "kill_sound"]
    fresh, worse, loose = audit._split_known(fewer, "clip")
    assert not fresh and not worse and [p for p, _ in loose] == ["kill_sound"]

    # ⑤ 类别要分开：clip 的在册数不许免掉 overflow
    fresh, _worse, _loose = audit._split_known([("kill_sound", 64)], "overflow")
    assert fresh == [("kill_sound", 64)], "clip 的在册记录漏到了 overflow 上"


def test_every_known_debt_has_a_written_reason():
    """在册表里每一条都必须写理由 —— 没理由的豁免就是偷偷放行。"""
    import layout_overflow_audit as audit

    bad = [k for k, (_px, why) in audit.KNOWN_COMPACT_DEBT.items()
           if not (why or "").strip()]
    assert not bad, f"这些在册存量债没写理由：{bad}"
    bad_px = [k for k, (px, _w) in audit.KNOWN_COMPACT_DEBT.items()
              if not isinstance(px, int) or px <= 0]
    assert not bad_px, f"这些在册存量债的像素数不是正整数：{bad_px}"


# ============================================ 五、页签条自己也得被量到


def test_the_tab_bar_itself_is_measured(main_window, qapp):
    """页签**条**（QTabBar）不属于任何一个页签内容，但它一直被正常布局。

    ⚠ 这里是我第一版差点写错的地方：如果 skip 写成"跳过整个 QTabWidget"，
    页签条就掉进两不管地带 —— 它有文字、会被截断，而且是每页最显眼的控件之一。
    只跳过 `tw.widget(i)`（页签**内容**）才对。
    """
    import _ui_mode as _um
    from PySide6.QtWidgets import QTabBar

    checked = 0
    for page_id in _auditable_pages(main_window):
        _um.goto(main_window, page_id)
        qapp.processEvents()
        page = main_window.pages.get(page_id)
        if page is None:
            continue
        bars = [b for b in page.findChildren(QTabBar) if not b.isHidden()]
        if not bars:
            continue
        covered = _covered_ids(page, qapp)
        for bar in bars:
            checked += 1
            assert id(bar) in covered, f"{page_id} 的页签条不在任何测量范围里"
    assert checked >= 8, f"只检查到 {checked} 条页签条，分母本身可能缩了"

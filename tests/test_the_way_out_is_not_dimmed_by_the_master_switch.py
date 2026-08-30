# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-439：库是空的、总开关关着 —— 这一页**唯一走得通的那条路**被压成了灰色。

## 缺陷长什么样

全新用户第一次打开「击杀图标」页。他的状态是**两个默认值同时成立**：

* 风格库是空的（软件不带素材，2026-08-21 用户裁定「不内置，改成引导」）；
* 总开关是关的（产品默认）。

于是批 2/3（RN-153/165）铺的那条「空库时唯一走得通的路」——
一颗紫色的「去社区拿一套 X」——撞上了批 16~20（RN-407 族）铺的
「总开关关着 ⇒ 卡片里带品牌强调色的控件一律退成中性灰」。

定点实测（`dark`，全新用户配置）：

    「去拿一套图标包」  总开关关 = (110, 112, 129)   ← 灰蓝，和旁边降权后的控件同色
                       总开关开 = (133, 68, 247)    ← 品牌紫
    同款 primaryButton（不在降权卡里）= (134, 69, 248)

⭐⭐⭐ **两条各自正确的规则，在交集处出错；而必然踩进那个交集的，
正好是这条引导唯一服务的那个人。** 空库 + 开关关，就是全新用户的定义。

## 全站分母（先数再修，批 21 的规矩）

拨 15 页的总开关、量 101 颗可见可用按钮，**两态颜色不同的 9 颗**：

| 页 | 按钮 | 该不该被压 |
|---|---|---|
| kill_icon / kill_sound / kill_voice / death_sound / gun_sound / reload_sound / switch_weapon | 「去（社区）拿一套 X」 | ❌ **不该** —— 它开的是浏览器，跟总开关毫无关系 |
| crosshair | 「绘制准心」 | ✅ 该 —— 它改的是这个功能的配置 |
| voice_output | 「添加槽位」 | ✅ 该 —— 同上 |

⇒ **7 错 2 对。** 判别标准不是控件类型，是
**这颗按钮的动作受不受总开关影响**。

## ⭐ 这条判别标准，`theme_manager.py` 里早就写着

RN-427 那组挂在控件自身属性上的选择器，注释逐字写着：

> 只管**编码「当前值」**的那几类（打勾 / 单选 / 滑块）——
> 紫色主按钮编码的是「这是主要动作」，不是「这件事正在发生」。

而 30 行之前那条 `QFrame#card[masterOff="true"] QPushButton#primaryButton`
照样把主按钮一起压了。
⭐ **同一个文件里，判别标准写在一处、只被应用到两组选择器里的一组。**
（同批 21：关系早就写在散文里，只是没有一个格子逼人去用它。）

## 这份判据断言什么

**不断言那颗按钮该是什么颜色** —— 断言的是
「总开关的开关**不许改变它的样子**」，因为总开关不管它。
这样修法用紫色填充还是别的形状语言，都由外审去判，判据不越权。

⚠ 第 3 条是**阳性对照**，缺了它这份判据就退化成「把降权拆掉即可全绿」：
同一批页面上，真正受总开关支配的控件**必须仍然会变**。
（批 22 的教训：一把没有阳性对照的尺子，量不出改进也量不出破坏。）
"""
from __future__ import annotations

from collections import Counter

import pytest
from PySide6.QtWidgets import QPushButton

# ⚠ 主窗夹具**用共享那一份**，不抄第二份（RN-002 那 9 份名单的形态）。
from tests.test_master_switch_effect_is_honest import (  # noqa: E402
    main_window as _shared_main_window,
)

# ⚠ 八页的名单、以及那张**判据自己钉的**社区地址表，都用共享那一份。
from tests.test_empty_library_covers_every_page import (  # noqa: E402
    EMPTY_SYNC,
    TEST_URLS,
)

main_window = _shared_main_window

#: `kill_icon` 不走共用引导件（它的出路按钮是首屏那颗 `test_btn`，RN-145），
#: 所以名单里没有它 —— 这一条是**它自己那处代码站点**，显式补上。
KILL_ICON = "kill_icon"

#: 「我空不空」的钩子，各页数据结构不同、名字也不同。
EMPTY_HOOKS = ("_library_is_empty", "_image_library_is_empty",
               "_audio_library_is_empty")

#: 分母下限。⭐ 少于这个数就说明扫描器塌了，而**一个算错分母的扫描器，
#: 长得和「这份界面很干净」一模一样**（批 23 那四把尺子的第一把）。
MIN_PAGES = 6


def _page_id(filename: str) -> str:
    return filename[:-len("_page.py")]


def _fill(widget):
    """填充色 = 整块像素的众数。

    ⚠ 不取中心：中心往往是**文字**（白），量到的就不是填充（批 23 第三把尺子）。
    ⚠ QImage 先落到变量再取像素 —— 链式写法是悬空指针（RN-433，4 次崩 1 次）。
    """
    image = widget.grab().toImage()
    if image.width() < 6 or image.height() < 6:
        return None
    counter: Counter = Counter()
    for x in range(0, image.width(), 2):
        for y in range(0, image.height(), 2):
            counter[image.pixelColor(x, y).rgb()] += 1
    v = max(counter, key=counter.get)
    return ((v >> 16) & 255, (v >> 8) & 255, v & 255)


def _pixels(widget) -> bytes:
    """整块像素。**对照控件必须用这个，不能用众数。**

    ⚠ 这是批 23 那第三把尺子的第五次现身：一颗复选框的众数是它的**背景**
    （透明 ⇒ (0,0,0)），而携带信号的是那个 16×16 的勾选框；滑块同理
    （众数是槽，变色的是 `sub-page` 那一小截）。
    ⭐ **量众数量到的是这块控件里最大的那一片，不一定是会说话的那一片。**
    ⚠ QImage 先落到变量再取 `constBits()` —— 链式写法是悬空指针（RN-433）。
    """
    image = widget.grab().toImage()
    return image.constBits().tobytes()


def _way_out(page):
    """这一页空库时那颗**唯一走得通**的按钮。找不到就返回 None。"""
    callout = getattr(page, "empty_callout", None)
    if callout is not None and callout.frame.isVisibleTo(page):
        return callout.button
    btn = getattr(page, "test_btn", None)          # kill_icon 自己那处
    if btn is not None and btn.isVisibleTo(page):
        return btn
    return None


def _governed_control(page, way_out):
    """同一页上**真正受总开关支配**的一个控件（阳性对照用）。

    取降权卡里的复选框 / 滑块 —— 它们编码的是「当前值」，
    正是 RN-427 那组选择器管的东西。
    """
    from PySide6.QtWidgets import QCheckBox, QSlider

    for kind in (QCheckBox, QSlider):
        for widget in page.findChildren(kind):
            if widget is way_out or not widget.isVisibleTo(page):
                continue
            if widget.width() >= 6 and widget.height() >= 6:
                return widget
    return None


def _force_empty(page, monkeypatch, filename: str | None) -> bool:
    patched = 0
    for name in EMPTY_HOOKS:
        if hasattr(page, name):
            monkeypatch.setattr(page, name, lambda: True)
            patched += 1
    if not patched:
        return False
    hook = EMPTY_SYNC.get(filename) if filename else "_sync_status_strip"
    fn = getattr(page, hook, None) or getattr(page, "_sync_status_strip", None)
    if callable(fn):
        fn()
    return True


@pytest.fixture(scope="module")
def swept(main_window, qapp):
    """每一页：造空库态 ⇒ 总开关 关/开 各量一次那颗出路按钮。

    ⚠ 拨完必须放回去：配置目录是全仓共用、跨轮次累积的（RN-141）。
    """
    monkeypatch = pytest.MonkeyPatch()
    targets = [(_page_id(f), f) for f in sorted(EMPTY_SYNC)]
    targets.append((KILL_ICON, None))
    out = []
    try:
        # ⚠⚠ **必须钉住社区地址表，不许读产品那份的实际值。**
        # 开源版没有社区站（`service_urls.COMMUNITY_CATEGORY_URLS` 是空的），
        # 于是那张引导卡**一张都不显示**、kill_icon 那颗按钮也从
        # 「去拿一套图标包」变成「导入图标包…」—— 分母从 8 塌到 1。
        # ⭐⭐ 第一版没钉，**本仓全绿、同步到开源仓当场两条红**
        # （同 RN-141/142：**不钉前置状态的判据，绿不绿取决于它跑在哪儿**）。
        # ⚠ 而隔壁 `test_kill_icon_empty_library_guidance.py` 开头就用大段注释
        #   写着这条坑（它那次的代价是挂死 300 秒）—— ⭐ **一条写在别人文件里的
        #   坑，不会因为我读过就自动避开；只有把它抄成一行代码才算避开。**
        from widgets import community_library

        # ⚠ `kill_icon` 不在共享那张表里（那张表是**八页共用引导件**的名单，
        #   而 kill_icon 走自己那颗按钮）—— 补一格，别改共享表。
        pinned = dict(TEST_URLS)
        pinned["kill_icon"] = "https://example.invalid/category.php?id=7"
        monkeypatch.setattr(community_library, "COMMUNITY_CATEGORY_URLS",
                            pinned, raising=False)
        for page_id, filename in targets:
            try:
                main_window.ensure_page_loaded(page_id)
                main_window.show_page(page_id, animated=False, force=True)
                qapp.processEvents()
            except Exception:                       # noqa: BLE001
                continue
            page = main_window.pages.get(page_id)
            row = getattr(page, "master_switch_row", None)
            if page is None or row is None:
                continue
            if not _force_empty(page, monkeypatch, filename):
                continue
            qapp.processEvents()
            way_out = _way_out(page)
            if way_out is None:
                continue
            reference = _governed_control(page, way_out)
            was = row.is_checked()
            try:
                row.set_checked_by_user(False)
                qapp.processEvents()
                off = _fill(way_out)
                off_ref = _pixels(reference) if reference is not None else None
                row.set_checked_by_user(True)
                qapp.processEvents()
                on = _fill(way_out)
                on_ref = _pixels(reference) if reference is not None else None
            finally:
                row.set_checked_by_user(was)
                qapp.processEvents()
            if off is None or on is None:
                continue
            out.append({
                "page": page_id,
                "text": way_out.text().strip(),
                "off": off, "on": on,
                "ref": (reference.objectName() or type(reference).__name__)
                       if reference is not None else None,
                "ref_off": off_ref, "ref_on": on_ref,
            })
    finally:
        monkeypatch.undo()
    return out


def test_the_sweep_actually_finds_the_way_out(swept):
    """⭐ 分母守卫：先证明它看得见东西，再让下面几条断言「没问题」。"""
    assert len(swept) >= MIN_PAGES, (
        f"只量到 {len(swept)} 页的出路按钮（下限 {MIN_PAGES}）—— 扫描器塌了。"
        f"量到的是：{[r['page'] for r in swept]}"
    )


def test_the_only_way_out_does_not_change_with_the_master_switch(swept):
    """⭐⭐ 空库时那颗出路按钮，**开关拨不拨都该长一个样**。

    它开的是浏览器 / 选文件框 —— 总开关关着，这个动作照样成立。
    拿一个不管它的条件去改它的样子，就是 RN-145 那条
    「一颗按钮换了含义，门禁条件要跟着换」的第二次现身，
    只是施加者从 `player_ready` 换成了降权 QSS。
    """
    bad = [
        f"{r['page']} · {r['text']!r}：总开关关 {r['off']} / 开 {r['on']}"
        for r in swept if r["off"] != r["on"]
    ]
    assert not bad, (
        "下面这些页，空库时**唯一走得通**的那颗按钮被总开关改了样子 —— "
        "而总开关不管它开不开浏览器：\n  " + "\n  ".join(bad)
    )


def test_the_things_the_switch_really_governs_still_dim(swept):
    """⭐ 阳性对照：真正受总开关支配的控件**必须仍然会变**。

    缺了这一条，上一条判据可以靠「把降权整个拆掉」全绿 ——
    而那正是批 16~20 五批要解决的问题（43 发里 39 发报
    「所有控件均为高亮紫色激活态 ⇒ 以为功能正在运行」）。

    ⚠ 这一条的分母**只有 2**，而且是量出来的不是拍出来的：
    空库时大多数页把参数控件一起收掉了（RN-179：可点却没反应是另一条缺陷），
    于是「同屏还剩一个受支配的勾选/滑块」的页只有 `gun_sound` 与 `kill_icon`。
    ⭐ 我第一版按上面那条判据的分母 6 抄了过来，**而两条判据数的根本不是同一批东西**
    —— 抄分母和抄结论一样危险。主按钮那一档的对照在下一条里，分母另算。
    """
    measured = [r for r in swept if r["ref"] is not None]
    assert len(measured) >= 2, (
        f"只有 {len(measured)} 页找到了受支配的参照控件 —— 对照组塌了")
    dead = [
        f"{r['page']} · 参照 {r['ref']}：两态整块像素逐字节相同"
        for r in measured if r["ref_off"] == r["ref_on"]
    ]
    assert len(dead) < len(measured), (
        "**一页都没有**受总开关支配的控件在变 —— 降权整层没在工作，"
        "上一条判据这时是空转的：\n  " + "\n  ".join(dead)
    )


def test_the_buttons_the_switch_really_governs_still_dim(main_window, qapp):
    """⭐⭐ 阳性对照（**主按钮这一档**）：改本功能配置的主按钮，必须仍然被压。

    ⚠ 第一版这一条拿的是 `kill_icon` 库不空时那颗「▶ 在屏幕上试播」，
    **前提是错的**：那时它已经被 `_set_primary_look(btn, False)` 换成了
    `actionButton`（描边档），而降权那组选择器只管 `#primaryButton` ——
    两态本来就都是 (38,42,58)，判据在指控一件不存在的事。
    ⭐ 顺带量清楚了这条规则的真实形状：**降权是按控件的 objectName 施加的，
    不是按它干什么施加的** —— 于是同一页上，该压的没压、不该压的压了。

    ⇒ 换成实测里真正该保留降权的那两颗（全站 9 颗里的 2 颗）。
    缺了这一条，上一条判据可以靠「把降权整层拆掉」全绿，
    而那正是批 16~20 五批要解决的问题。
    """
    # ⚠⚠ **2026-08-30 批 31（RN-452）：这份样本被产品改动掏空了一半。**
    #
    # 原来是 `[("crosshair", "绘制准心"), ("voice_output", "添加槽位")]`。
    # 批 31 撤掉了 `voice_output` 卡内那颗「添加槽位」（它和底栏那颗是同一个动作），
    # 于是下面这段 `findChildren` 抓到的变成了**底栏**那颗 —— 而底栏根本不在
    # 降权规则的分母里（那条选择器是 `QFrame#card[masterOff="true"] ...`）。
    # ⇒ 这条阳性对照当场变红，报的却是一件**不存在**的缺陷。
    #
    # ⭐⭐⭐ **一条判据的样本被删掉，有两种失败方式**：
    #   ① 它变成一条**恒真**的断言，安安静静地绿着（同批 31 的
    #      `test_the_two_save_buttons_have_the_same_name`）；
    #   ② 它**红**，而且指着一个没发生的问题。
    # ⭐ 后者更吵，但**前者更危险** —— 只有后者会来找你。
    #
    # ⇒ 样本收窄到「卡内那一档」（本来就是这条规则的分母），并显式说明。
    cases = [("crosshair", "绘制准心")]
    monkeypatch = pytest.MonkeyPatch()
    seen, dead = 0, []
    try:
        for page_id, label in cases:
            try:
                main_window.ensure_page_loaded(page_id)
                main_window.show_page(page_id, animated=False, force=True)
                qapp.processEvents()
            except Exception:                       # noqa: BLE001
                continue
            page = main_window.pages.get(page_id)
            row = getattr(page, "master_switch_row", None)
            if page is None or row is None:
                continue
            bar = getattr(page, "action_bar", None)

            def _in_bar(w, _page=page, _bar=bar):
                node = w
                while node is not None and node is not _page:
                    if _bar is not None and node is _bar:
                        return True
                    node = node.parentWidget()
                return False

            # ⭐ 只认**卡内**那一档：降权那条选择器写的就是
            #   `QFrame#card[masterOff="true"] QPushButton#primaryButton`，
            #   底栏不在它的分母里。拿底栏那颗当对照，是在量另一件事。
            hits = [b for b in page.findChildren(QPushButton)
                    if b.isVisibleTo(page) and b.text().strip() == label
                    and b.objectName() == "primaryButton" and not _in_bar(b)]
            if not hits:
                continue
            btn = hits[0]
            was = row.is_checked()
            try:
                row.set_checked_by_user(False)
                qapp.processEvents()
                off = _fill(btn)
                row.set_checked_by_user(True)
                qapp.processEvents()
                on = _fill(btn)
            finally:
                row.set_checked_by_user(was)
                qapp.processEvents()
            if off is None or on is None:
                continue
            seen += 1
            if off == on:
                dead.append(f"{page_id} · {label!r}：两态填充色都是 {off}")
    finally:
        monkeypatch.undo()

    assert seen == len(cases), (
        f"只量到 {seen}/{len(cases)} 颗对照按钮 —— 对照组塌了，"
        "上面那条判据这时是空转的")
    assert not dead, (
        "这几颗主按钮改的就是本功能的配置，总开关关着时必须看得出来：\n  "
        + "\n  ".join(dead)
        + "\n⚠ 别为了让上一条判据变绿，把降权整层拆掉。"
    )


def test_the_exemption_does_not_swallow_the_disabled_look(main_window, qapp):
    """⭐⭐ 豁免只豁免「降权」这一件事，**不许连禁用态一起豁免掉**。

    这条盯的是一个**靠位置生效**的东西：豁免那条 QSS 规则和
    `#primaryButton:disabled` 那条特异度完全相同（各 2 个 id + 2 个属性/伪类），
    Qt 按**后来者胜** —— 所以豁免必须排在禁用那条**前面**。
    ⭐ **一条靠"排在谁前面"生效的规则，挪一次位置就会静默失效**：
    屏幕上会得到一颗"禁用了但看着能点"的按钮，而那正是 RN-150 花了一整批修掉的东西。
    ⇒ 这条判据是那次改动的**回归守卫**，不是新断言。

    量法：把被豁免的那颗按钮强制禁用，它的填充必须**变**（离开品牌色那一带）。
    """
    import colorsys

    main_window.ensure_page_loaded(KILL_ICON)
    main_window.show_page(KILL_ICON, animated=False, force=True)
    qapp.processEvents()
    page = main_window.pages.get(KILL_ICON)
    assert page is not None

    monkeypatch = pytest.MonkeyPatch()
    row = page.master_switch_row
    was = row.is_checked()
    was_enabled = page.test_btn.isEnabled()
    try:
        monkeypatch.setattr(page, "_library_is_empty", lambda: True)
        page._sync_status_strip()
        row.set_checked_by_user(False)
        qapp.processEvents()
        btn = page.test_btn
        assert btn.property("notGovernedByMaster") == "true", (
            "空库时那颗按钮没有被标成「不归总开关管」—— 这条判据在空转")
        on = _fill(btn)
        btn.setEnabled(False)
        qapp.processEvents()
        off = _fill(btn)
    finally:
        page.test_btn.setEnabled(was_enabled)
        row.set_checked_by_user(was)
        monkeypatch.undo()
        page._sync_status_strip()
        qapp.processEvents()

    saturation = colorsys.rgb_to_hsv(*(v / 255 for v in off))[1]
    assert off != on, (
        f"这颗按钮被禁用之后长得和可点时**一模一样**（都是 {on}）—— "
        "豁免那条 QSS 规则大概被挪到 `:disabled` 那条后面去了。"
    )
    assert saturation <= 0.45, (
        f"禁用态填充 {off} 饱和度 {saturation:.2f} —— 还停在品牌色那一带，"
        "「你点不了」和「这是主要动作」同时出现是自相矛盾的（RN-150）。"
    )

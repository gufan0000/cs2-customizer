# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-075/077：`flash` / `viewmodel` 说的话必须和用户找得到的东西一致。

⭐ RN-075 是**外审 3/3 全票 × 5 张图**逮到的，而我读代码时完全没觉得不对 ——
因为我知道那句话指的是哪一个「基础设置」。用户不知道：
`flash` 页**自己的第一个页签就叫「基础设置」**，而那个页签里没有任何总开关。
真开关在侧栏同名的 `basic` 页、卡片叫「功能开关」、开关叫「自定闪光」。

⇒ 缺陷类：**引导文案点名的目标，和本页某个页签同名，却不是同一个东西。**
这一类靠读代码发现不了（写的人知道自己指的是哪个），只能靠外部视角或判据扫。
"""
from __future__ import annotations

import ast
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parent.parent

#: 能把「同名歧义」消掉的方位限定词。
DISAMBIGUATORS = ["左侧", "侧栏", "左边", "导航", "菜单里", "本页", "当前页", "这一页"]


def _quoted_targets(text: str) -> list[str]:
    """摘出文案里用「」点名的目标。"""
    out, depth, buf = [], 0, ""
    for ch in text:
        if ch == "「":
            depth += 1
            if depth == 1:
                buf = ""
                continue
        if ch == "」":
            depth -= 1
            if depth == 0 and buf:
                out.append(buf)
            continue
        if depth:
            buf += ch
    return out


def _page(page_id: str):
    """离屏构造一个页面。游戏目录出口走 UP-090 的沙箱，不弹框（RN-072）。"""
    import importlib
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    from _audit_neutralize import block_modal_dialogs
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes(verbose=False)
    block_modal_dialogs()
    module = importlib.import_module(f"pages.{page_id}_page")
    cls_name = "".join(part.capitalize() for part in page_id.split("_")) + "Page"
    return getattr(module, cls_name)()


#: 「点这里去开总开关」这句话的所有说法。
MASTER_SWITCH_CUES = ["总开关", "自定闪光", "启用开关"]


def _rendered_copy(page) -> list[str]:
    """页面上真正渲染出来的文字（含帮助面板的富文本）。"""
    from PySide6.QtWidgets import QLabel

    return [label.text() for label in page.findChildren(QLabel) if label.text()]


def _own_tabs(page) -> set[str]:
    from PySide6.QtWidgets import QTabWidget

    names: set[str] = set()
    for tabs in page.findChildren(QTabWidget):
        names |= {tabs.tabText(i) for i in range(tabs.count())}
    return names


@pytest.mark.parametrize("page_id", ["flash", "viewmodel"])
def test_the_master_switch_hint_says_which_basic_settings(qapp, page_id):
    """告诉用户「去打开总开关」的话，必须说清是**哪一个**「基础设置」。

    ⚠ 这条判据的第一版规则是错的：它拦「文案点名了和本页页签同名的目标」，
    于是把「在「图片设置」中选择图片风格」也判红了 —— 而那句是**对的**，
    它指的就是本页那个页签。**指自己的页签没问题，指别处却用了自己页签的名字才有问题。**
    规则改成只管「去开总开关」这一句，因为歧义的代价全在那一句上：
    照着做的人会停在本页的「基础设置」页签里找一个根本不在那儿的开关。

    ⭐ 第一版规则虽然错，却顺带逮出两条真缺陷（帮助面板第 1、2 步），
    所以它不是白跑的 —— 记在 RN-075 里。
    """
    page = _page(page_id)
    own_tabs = _own_tabs(page)
    if not own_tabs:
        pytest.skip(f"{page_id} 没有页签，这条歧义不可能发生")
    collisions = own_tabs & {"基础设置", "基础"}
    if not collisions:
        pytest.skip(f"{page_id} 的页签里没有和侧栏「基础设置」页撞名的：{sorted(own_tabs)}")

    offenders = []
    for text in _rendered_copy(page):
        if not any(cue in text for cue in MASTER_SWITCH_CUES):
            continue
        # 这句话在讲总开关。它一提「基础设置」就必须带方位限定。
        for name in collisions:
            if name in text and not any(d in text for d in DISAMBIGUATORS):
                offenders.append(f"提到「{name}」却没说是哪一个：{text[:80]!r}")
    assert not offenders, (
        f"{page_id} 的总开关引导有同名歧义（RN-075）：\n  " + "\n  ".join(offenders)
        + f"\n本页页签里撞名的：{sorted(collisions)}；"
        "加个方位限定（「左侧「基础设置」页」）或给一个跳过去的入口。")


@pytest.mark.parametrize("page_id", ["flash", "viewmodel"])
def test_copy_only_names_tabs_that_exist(qapp, page_id):
    """文案点名的「X」选项卡/页签，必须真的存在（RN-056 家族）。

    帮助面板第 2 步原来写「在「基础」选项卡」，而本页没有叫「基础」的页签
    （它叫「基础设置」）—— 照着找找不到。
    """
    import re

    page = _page(page_id)
    own_tabs = _own_tabs(page)
    if not own_tabs:
        pytest.skip(f"{page_id} 没有页签")

    ghosts = []
    for text in _rendered_copy(page):
        for named in re.findall(r"「([^」]{1,12})」\s*(?:选项卡|标签页|页签|标签)", text):
            if named not in own_tabs:
                ghosts.append(named)
    assert not ghosts, (
        f"{page_id} 的文案点名了不存在的页签：{sorted(set(ghosts))}\n"
        f"本页页签只有：{sorted(own_tabs)}（RN-056：文案点名的东西必须真的叫这个名字）")


def test_the_flash_hint_names_the_switch_by_its_real_label(qapp):
    """文案里点名的开关名，必须跟**调用方**（首页那张「功能开关」卡）走。

    单一真相源不等于文案可以照搬：`config` 里那个字段叫 `flash_enabled`，
    而用户在屏幕上看到的是「自定闪光」。文案里写错名字等于没写。
    """
    switch_table = (REPO / "gui_widget.py").read_text(encoding="utf-8")
    tree = ast.parse(switch_table)
    labels = set()
    for node in ast.walk(tree):
        if (isinstance(node, ast.Tuple) and len(node.elts) == 3
                and all(isinstance(e, ast.Constant) for e in node.elts)
                and str(node.elts[2].value).endswith("_enabled")):
            labels.add((node.elts[0].value, node.elts[1].value))
    flash_label = next((text for sid, text in labels if sid == "flash"), None)
    assert flash_label, (
        "首页「功能开关」表里找不到 flash 那一行 —— 表结构变了，这条判据要跟着改，"
        "别让它悄悄空转。")

    # ⚠ 判据要读**渲染出来的文字**，不读源码字面量。
    # 上一版查的是源码里有没有子串 `「自定闪光」`，于是按钮改名成「启用自定闪光」之后
    # 它当场判红 —— 而那次改名恰恰是**更符合这条规则**的（按钮就叫这个开关的名字）。
    # 查子串会把"名字对不对"退化成"标点摆得对不对"。
    from PySide6.QtWidgets import QLabel, QPushButton

    page = _page("flash")
    page._sync_action_bar()
    surfaces = [w.text() for w in page.findChildren(QPushButton) if w.text()]
    surfaces += [w.text() for w in page.findChildren(QLabel) if w.text()]
    assert any(flash_label in text for text in surfaces), (
        f"`flash` 页上没有任何一处按真名点这个开关（应含「{flash_label}」）。"
        "RN-056 家族：文案点名的控件必须真的叫这个名字，否则用户照着找不到。")


def test_flash_bottom_bar_primary_actually_changes_something(qapp, monkeypatch):
    """RN-079：底栏最醒目的主按钮必须是**能改变状态**的动作，不是纯导航。

    原状：主按钮无条件写「前往效果预览」——它只切页签，不改任何状态；
    而顶部胶囊常年「效果·未启用 / 运行·待启动」，全页没有任何启动入口。
    外审**改前改后都是 3/3 全票判「高」**，措辞集中在
    「配完不知道怎么让它在 CS2 里生效」。裁定：主按钮改「打开并启动」。
    """
    from config import config

    monkeypatch.setattr(config, "flash_enabled", False, raising=False)
    page = _page("flash")
    page._sync_action_bar()
    label = page.action_bar.primary_btn.text()
    # ⚠⚠ RN-192 改了这条判据量的**位置**，没改它量的**东西**。
    # RN-079 的要害是「底栏主按钮不许是个只切页签的导航动作」，而当时「把状态改过来」
    # 只有底栏一条路。RN-189 把总开关搬进本页状态卡之后，底栏那颗
    # 「启用自定闪光」成了**第二个开启入口** —— 外审 6/6 判「不知道点哪个才生效」。
    # ⭐ 现在两件事分开：**开关负责启用，按钮负责启动**（它们本来就是两个状态：
    #   `flash_enabled` 与 `process_manager.is_running`）。
    assert getattr(page, "master_switch_row", None) is not None, (
        "flash 页没有就地总开关 —— 那「启用」这件事就又只能挂回底栏了（RN-189）")
    assert label != "前往效果预览", (
        f"总开关关着时底栏主按钮是「{label}」—— 那只是切页签的导航动作，"
        "不能拿它当「下一步该做什么」（RN-079）。")
    assert not page.action_bar.primary_btn.isEnabled(), (
        f"总开关还关着，底栏「{label}」却是亮的 —— 一屏两个开启入口，"
        "外审 6/6 判「不知道点哪个才算真正生效」（RN-192）。")

    # 反面：总开关一开，那颗「启动」必须变得可点 —— 否则就是把入口删没了。
    monkeypatch.setattr(page, "_init_flash_process", lambda: None)
    monkeypatch.setattr(config, "flash_enabled", True, raising=False)
    page._sync_action_bar()
    assert page.action_bar.primary_btn.isEnabled(), (
        "总开关开了，底栏「启动」还是灰的 —— 用户没有任何办法启动后台监听。")


def test_the_home_switch_card_is_actually_readable_from_elsewhere():
    """RN-089：`self.switches` 必须有**真读者**，否则页面改了配置首页不跟着动。

    AST 实测（RN-079 之前）：1 处 Store、1 处下标赋值、**0 个真读者**。
    也就是说这 17 颗开关只有它们自己能改；`flash` 页新增的「打开并启动」
    一旦写了 `flash_enabled`，首页会停在「关」上 —— config / UI / 磁盘三态不一致，
    而下一次 `save_config` 落盘哪个值取决于谁最后碰过它。

    ⚠ 判据走 AST 找**真调用**，不查子串 —— RN-073 那条假绿就是查子串查出来的。
    """
    tree = ast.parse((REPO / "gui_widget.py").read_text(encoding="utf-8"))
    sync = next((n for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef) and n.name == "sync_feature_switch"), None)
    assert sync is not None, (
        "`gui_widget` 少了 `sync_feature_switch()` —— 没有它，页面改配置就没法回写首页开关。")

    # ⚠ 2026-08-21（RN-144）：这段查表被抽成了 `_find_feature_switch()`，
    # 因为「跳过去指给他看」那条路要问同一个问题。判据跟着改成**两段**：
    #   ① 那个查表函数里必须有真的属性读；
    #   ② `sync_feature_switch()` 必须真的走到它（不然抽出来等于断链）。
    # ⭐ 判据盯的是**性质**（`switches` 有真读者、回写这条链是通的），
    #    不是"这些字必须出现在这个函数体里" —— 后者会把一次正当的重构判成缺陷。
    finder = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef) and n.name == "_find_feature_switch"), None)
    assert finder is not None, (
        "`gui_widget` 少了 `_find_feature_switch()` —— 首页开关的查表没有落点了。")

    reads_switches = any(
        isinstance(n, ast.Attribute) and n.attr == "switches"
        for n in ast.walk(finder))
    reads_map = any(
        isinstance(n, ast.Attribute) and n.attr == "_switch_id_by_config_key"
        for n in ast.walk(finder))
    assert reads_switches and reads_map, (
        "`_find_feature_switch()` 没有真的去读 `self.switches` / "
        "`self._switch_id_by_config_key` —— 那它就是个空壳，"
        "`switches` 还是「写了没人读」的状态。")

    assert any(isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
               and n.func.attr == "_find_feature_switch"
               for n in ast.walk(sync)), (
        "`sync_feature_switch()` 没有走到 `_find_feature_switch()` —— "
        "回写这条链断了，而两个函数各自看着都很正常。")

    callers = [n for n in ast.walk(ast.parse(
        (REPO / "pages" / "flash_page.py").read_text(encoding="utf-8")))
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "sync_feature_switch"]
    assert callers, (
        "`flash_page` 写了 `flash_enabled` 却没调 `sync_feature_switch()` —— "
        "首页那颗开关会停在旧值上（RN-089）。")


def test_viewmodel_presets_are_on_the_first_screen(qapp):
    """RN-083：这一页最核心的东西（5 组预设 + 每组的 FOV/XYZ）必须在首屏看得见。

    原状：右列只有一张「持枪切换」卡，自 y≈450 起整列空白，
    而「视角预设」被推到两列**下面**、落在折叠线以下。
    外审 3/3 判「高」，原话是「作为『局内视角设置』页却完全找不到
    FOV/XYZ 参数与 5 组预设的编辑入口」。

    判据量**位置**，不查布局代码 —— 「在不在首屏」是个关于屏幕的断言（同 RN-076 的教训）。
    """
    page = _page("viewmodel")
    page.resize(1080, 700)          # 真实页面区尺寸（1280×800 窗口减去侧栏与顶栏）
    page.show()
    qapp.processEvents()

    # ⚠ 判据的**定位**和**阈值**各错过一次，两次都是回退验证逮出来的假绿：
    #   ① 定位认「包含预设摘要标签的 QFrame」⇒ 连祖先容器一起匹上，
    #      而 `findChildren` 按树序返回，拿到的是最外层那个（y 恒为 0）⇒ 恒绿；
    #   ② 阈值写「y < 700」⇒ 裸页 1280×800 下回退态量出 579，照样过关。
    # 现在的规则是**推导出来的**，不是拍的数：预设卡必须**和左列并排**，
    # 也就是它的顶边要在左列最后一张卡（「CFG 同步」）的底边**之上**。
    # A/B 实测（1080×700，真实页面区尺寸）：现在 328 / 回退 566，左列底 555。
    from PySide6.QtWidgets import QLabel

    def _card_of(title_text: str):
        label = next((lb for lb in page.findChildren(QLabel)
                      if lb.text() == title_text), None)
        assert label is not None, (
            f"找不到「{title_text}」那张卡的标题 —— 判据定位方式过期了，别让它悄悄空转。")
        return label.parentWidget()

    left_bottom = _card_of("CFG 同步")
    presets = _card_of("视角预设")
    left_bottom_y = left_bottom.mapTo(page, left_bottom.rect().bottomLeft()).y()
    presets_top_y = presets.mapTo(page, presets.rect().topLeft()).y()
    assert presets_top_y < left_bottom_y, (
        f"「视角预设」卡顶边在 y={presets_top_y}，而左列最后一张卡的底边才 y={left_bottom_y}"
        " —— 说明它又被推到两列**下面**去了，而右列还空着半屏。\n"
        "这一页最核心的编辑入口（5 组预设 + 每组 FOV/XYZ）不许要滚动才看得见（RN-083）。")


def _viewmodel_page_viewport(page):
    """页面级滚动区的 viewport —— 「首屏看得见什么」只能对着它量。"""
    from PySide6.QtWidgets import QScrollArea

    for sa in page.findChildren(QScrollArea):
        if sa.objectName() == "helpScrollArea":
            continue
        anc, nested = sa.parentWidget(), False
        while anc is not None and anc is not page:
            if isinstance(anc, QScrollArea):
                nested = True
                break
            anc = anc.parentWidget()
        if not nested:
            return sa.viewport()
    raise AssertionError("viewmodel 页找不到页面级滚动区 —— 判据的定位方式过期了。")


def _is_fully_drawn_in(widget, root) -> bool:
    """`widget` 在 `root` 里是不是**每一个像素都画得出来**。

    ⚠ 不能只拿 `mapTo(root)` 的坐标跟 root 的高度比 —— 那只看最外面一层。
    实测：给预设卡的外框加一句 `setMaximumHeight(320)`，卡片的**坐标**照样落在
    页面视口里，而它其实被那个外框裁掉了 —— 判据一路绿。中间任何一层
    （卡、分栏容器、页签）都可能裁，所以要**逐层与祖先求交**。

    不用 `visibleRegion()`：窗口没有映射到屏幕时它的行为依赖平台，
    而本仓的页面判据一律离屏跑（同「离屏子控件 `isVisible()` 恒假」那个坑）。
    """
    from PySide6.QtCore import QRect

    full = QRect(widget.mapTo(root, widget.rect().topLeft()), widget.size())
    rect = QRect(full)
    anc = widget.parentWidget()
    for _ in range(32):
        if anc is None:
            break
        rect = rect.intersected(
            QRect(anc.mapTo(root, anc.rect().topLeft()), anc.size()))
        if anc is root:
            break
        anc = anc.parentWidget()
    return rect == full


def _card_of_preset(preset_vars_entry):
    """从一组预设控件回溯到它那张卡（objectName="card"）。"""
    card = preset_vars_entry["fov"].parentWidget()
    while card is not None and card.objectName() != "card":
        card = card.parentWidget()
    assert card is not None, "找不到预设卡（objectName=card）—— 判据定位过期了。"
    return card


def test_viewmodel_shows_more_than_one_preset_at_a_time(qapp):
    """RN-177：卡副标题写「5 组」，屏幕上就不许只看得见 1 组。

    ⭐ 这条缺陷躲过了**所有**既有防线，值得记清楚每一道是怎么瞎的：
      · 排版审计前四条 —— 内层滚动区滚得动，既不横向溢出也不纵向裁切；
        第 1 条判据里还明写着「内层的滚动是有意设计」，等于**主动豁免**了这一类；
      · 24 轮外审 —— 出图渲染的是**窗口**，折叠线以下从来没进过画面（RN-170）；
      · 这一页 2026-08-18 已关档（RN-077/083/084），而**关档只表示那一页自己的账清了**。
    实测原状：视口 320px 装 872px，完整可见 1 组、部分 1 组、看不见 3 组。

    判据量**屏幕**不查布局代码：数有几张预设卡整个落在页面视口里。
    阈值 2 是**推导**的不是拍的：修法把卡高从 168 压到 122，视口 464px 扣掉
    卡头 90px 还剩 374px ⇒ 至少放得下 2 张（374/130≈2.9）。回退到 320px 内层
    滚动区时这个数是 1 —— 两边差得开，判据才有分辨力。
    """
    page = _page("viewmodel")
    page.resize(1280, 800)
    page.show()
    qapp.processEvents()

    vp = _viewmodel_page_viewport(page)
    assert len(page.preset_vars) >= 5, (
        f"只数到 {len(page.preset_vars)} 组预设 —— 判据在空转，先修取卡那一段。")

    fully = sum(1 for pv in page.preset_vars
                if _is_fully_drawn_in(_card_of_preset(pv), vp))

    # ⚠ 自检：先证明这个数**会随几何变化**，再拿它下结论。
    # 一条"数出来 N 张"的判据最容易的失效方式不是数错，是**恒定**——
    # 定位选错一层、或者拿到的是构造期的陈旧几何，它就会稳定返回一个好看的数。
    # 把页面压到 420px（放不下两张 122px 的卡 + 90px 卡头）再数一次：必须掉下来。
    page.resize(1280, 420)
    qapp.processEvents()
    shrunk = sum(1 for pv in page.preset_vars
                 if _is_fully_drawn_in(_card_of_preset(pv), _viewmodel_page_viewport(page)))
    page.resize(1280, 800)
    qapp.processEvents()
    assert shrunk < fully, (
        f"把页面从 800px 压到 420px，完整可见的预设卡还是 {shrunk} 张（原 {fully} 张）"
        " —— 这个数不随几何变化，说明判据没在量屏幕，先修测量那一段再看结论。")

    assert fully >= 2, (
        f"页面视口 {vp.height()}px 里只有 {fully} 张预设卡是完整可见的，"
        "而这张卡的副标题写着「5 组持枪视角参数」、状态条写着「共 5 组预设」。\n"
        "文案承诺 5 组、屏幕给 1 组，就是 RN-177。"
        "别用「加个内层滚动区」来省地方 —— 那正是原来的做法。")


def test_the_preset_summary_names_every_preset_not_just_the_first_few(qapp):
    """RN-177：摘要自称「共 5 组」就得把 5 组都列出来。

    原状是 `[:3]` —— 摘要说 5 组、只列 3 组，而屏幕上又只看得见 1 组。
    **三个地方三个数，没有一处能互相印证。** 现在摘要本身就是「5 组确实都在」
    的凭证：不必先滚到底才能确认。
    """
    page = _page("viewmodel")
    page.show()
    qapp.processEvents()

    text = page.presets_summary_label.text()
    names = [pv["name"].text().strip() for pv in page.preset_vars]
    assert len(names) >= 5, f"只数到 {len(names)} 组预设 —— 判据在空转。"
    missing = [n for n in names if n and n not in text]
    assert not missing, (
        f"预设摘要漏了 {missing}（当前文案：{text!r}）—— "
        "摘要自称「共 N 组」就得列得出 N 组，否则那个数字没有任何东西能印证它。")


def test_viewmodel_tab_order_follows_the_screen(qapp):
    """RN-069/RN-083：Tab 顺序必须跟屏幕顺序一致，**改完版面要重新验**。

    ⚠ 这条判据是补上来的。RN-069 当年的修法是一行
    `setTabOrder(auto_switch_interval_input, save_btn)`，而它的回退断点挂在
    `test_focus_audit_covers_every_page_with_a_class` 上 —— 那是条**覆盖面**判据，
    管的是「焦点巡检有没有看这一页」，不是「这一页顺序对不对」。
    RN-083 把「视角预设」挪进右列之后，那一行补丁**反而成了错的**
    （焦点巡检报「需挪动 1 个」，去掉它就是 0 个），而当时没有任何判据直接盯顺序。

    ⇒ 显式 `setTabOrder` 是对**某个具体版面**的断言，改版面就得重新验它。
    """
    import sys

    sys.path.insert(0, str(REPO / "scripts"))
    from tab_order_audit import focusable_chain, min_moves, reading_order

    page = _page("viewmodel")
    page.resize(1280, 800)
    page.show()
    qapp.processEvents()

    chain = focusable_chain(page)
    assert len(chain) > 20, (
        f"只数到 {len(chain)} 个可聚焦控件（实测应有 40+）—— 判据在空转，先修取链那一段。")
    moves = min_moves(chain, reading_order(chain, page, page.layout()))
    assert moves == 0, (
        f"viewmodel 的 Tab 顺序有 {moves} 处跟屏幕顺序对不上（RN-069/RN-083）。"
        "键盘用户会在两列之间来回跳。")


def test_the_two_save_buttons_have_the_same_name(qapp):
    """RN-078：同一个动作在一屏里出现两次时，至少不许有两个名字。

    卡内那颗曾叫「保存设置到CFG」、底栏那颗叫「保存到CFG」——
    两个名字会让人以为是两件事（外审报「同一操作出现两次」）。
    """
    from PySide6.QtWidgets import QPushButton

    page = _page("viewmodel")
    page._sync_action_bar()
    bar_label = page.action_bar.primary_btn.text()
    saves = {b.text() for b in page.findChildren(QPushButton)
             if "保存" in b.text() and "CFG" in b.text().upper()}
    saves.add(bar_label)
    assert len(saves) == 1, (
        f"同一个「写入 CFG」动作有 {len(saves)} 个名字：{sorted(saves)}（RN-078）。")


@pytest.mark.parametrize("page_id", ["flash", "viewmodel"])
def test_no_invisible_summary_label_survives_on_these_two_pages(qapp, page_id):
    """RN-009：这两页的死控件已经清掉，别再回来。

    棘轮（`test_no_invisible_summary_label.py`）只钉总数，钉不住"具体哪两页"——
    换一页清、这两页回来，总数不变而棘轮全绿。
    """
    page = _page(page_id)
    assert not hasattr(page, "summary_label"), (
        f"{page_id} 又建了 `summary_label`。这个控件建出来就 `hide()`、"
        "全仓没人再让它显示，而每次状态同步还照给它算文本。"
        "状态详情已由徽章 tooltip 和 `status_card` 的 tooltip 给出了。")

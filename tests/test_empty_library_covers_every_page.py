# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""空库引导铺到**八页**（RN-165，RN-153 的剩余四页）。

## 为什么剩下四页要单独一轮

RN-153 那轮只做了共用 `SoundPageBase` 的四页 —— 它们共用一个骨架，
逻辑写一处、零重复。`gun_sound` / `death_sound` / `special_sound` / `flash`
**各有各的结构**（风格目录一个是 `dict[str, list]`、一个是 `list`、
一个要跨四大类问、一个是两个下拉框），要各写一遍。

⭐ 当时判「那是"顺手"不是"必须一起"，而且**不做也不欠债**」。本轮补上。

## 这一轮真正的设计问题：**别长出八个略有差别的空状态**

八页「库空不空」必须各问各的（数据结构完全不同），
但**"空了该长什么样"只能有一份** —— 否则八页会各自演化，
而没有任何东西会发现它们不一样了。

⇒ `widgets/community_library.guide_empty_library()` 是那唯一一份；
每页只回答两件事：**我空不空**、**原来那颗按钮是哪一颗**。

## 这份文件里最要紧的三条

1. `test_no_page_grows_its_own_empty_state`
   ⭐ AST 扫全仓：不许有第二处自己拼空状态底栏。**这是整轮的命门。**
2. `test_every_wired_page_keeps_the_second_step`
   ⚠ RN-153 的血教训：第一版把「打开资源目录」整个换掉了，
   ⭐ **修好第一步却删掉第二步，等于没修** —— 文案还在说"放进资源目录"。
3. `test_flash_only_guides_on_the_two_asset_tabs`
   `flash` 的主按钮本来就是个状态机（启用 / 启动 / 前往预览）。
   ⭐ 引导只该插在"打开一个空文件夹"那两个页签上，**别把状态机顶掉**。
"""
from __future__ import annotations

import ast
import sys
from pathlib import Path

import pytest

REPO = Path(__file__).resolve().parents[1]
if str(REPO / "scripts") not in sys.path:
    sys.path.insert(0, str(REPO / "scripts"))

from widgets import community_library as lib  # noqa: E402

#: 八页 → 社区分类键。⭐ 独立于产品的一份清单，不读产品的类属性当答案。
ALL_WIRED = {
    "kill_sound_page.py": "kill_sound",
    "kill_voice_page.py": "kill_voice",
    "switch_weapon_page.py": "switch_weapon",
    "reload_sound_page.py": "reload_sound",
    "gun_sound_page.py": "gun_sound",
    "death_sound_page.py": "death_sound",
    "special_sound_page.py": "special_sound",
    "flash_page.py": "flash",
}

TEST_URLS = {key: f"https://example.invalid/category.php?id={i}"
             for i, key in enumerate(sorted(set(ALL_WIRED.values())), start=1)}


@pytest.fixture(autouse=True)
def _pin_urls(monkeypatch):
    """⚠ RN-157：判据自己钉住地址表，别读"这个发行版有没有社区站"的实际值。"""
    monkeypatch.setattr(lib, "COMMUNITY_CATEGORY_URLS", dict(TEST_URLS))


def _module_of(filename: str):
    import importlib

    return importlib.import_module(f"pages.{filename[:-3]}")


def _page_class(module):
    return next(obj for name, obj in vars(module).items()
                if name.endswith("Page") and hasattr(obj, "COMMUNITY_CATEGORY_KEY"))


# ==================================================== 1. 八页都接上了

@pytest.mark.parametrize("filename,key", sorted(ALL_WIRED.items()))
def test_every_page_declares_its_community_category(filename, key):
    """填错一个键 = **静默送错地方**：按钮画得出来、点得动，落到别的分类页。"""
    cls = _page_class(_module_of(filename))
    assert cls.COMMUNITY_CATEGORY_KEY == key, (
        f"{filename} 声明的分类是 {cls.COMMUNITY_CATEGORY_KEY!r}，应该是 {key!r}")
    assert lib.category_url(key), f"分类键 {key!r} 在地址表里查不到"


@pytest.mark.parametrize("filename", sorted(ALL_WIRED))
def test_every_page_can_answer_whether_it_is_empty(filename):
    """每页必须自己回答「我空不空」—— 这是唯一不能共用的那一半。

    ⭐ 少了它，共用件永远收到 `empty=False`，整条引导**静默不生效**。
    """
    src = (REPO / "pages" / filename).read_text(encoding="utf-8")
    names = {n.name for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.FunctionDef)}
    has_own = bool(names & {"_library_is_empty", "_image_library_is_empty",
                            "_audio_library_is_empty"})
    # 音效家族四页从基类继承，这里放行
    if not has_own:
        base = ast.parse(
            (REPO / "pages" / "sound_page_base.py").read_text(encoding="utf-8"))
        base_names = {n.name for n in ast.walk(base)
                      if isinstance(n, ast.FunctionDef)}
        has_own = "_library_is_empty" in base_names and "SoundPageBase" in src
    assert has_own, f"{filename} 没有任何「我空不空」的实现"


@pytest.mark.parametrize("filename", sorted(
    f for f in ALL_WIRED if f != "flash_page.py"))
def test_every_page_actually_calls_the_guidance(filename):
    """⭐ 逻辑共用，但**调用点每页一行** —— 抄漏一处不会报错。

    ⚠ 这条是**回退验证逼出来的**：我原本以为
    `test_every_page_can_answer_whether_it_is_empty` 够了，
    结果把 `special_sound` 的调用点注释掉之后它**照样绿**（0/1）——
    那条只验"方法在不在"，验不到"有没有人叫它"。

    ⭐ **「东西存在」和「东西被用上」是两条判据**，
    而只写前一条时，后一条的缺失是完全静默的（RN-138 / RN-163 同族）。

    （`flash` 不在此列：它在 `_sync_action_bar` 里按页签调两次，
    由 `test_flash_only_guides_on_the_two_asset_tabs` 单独盯。）
    """
    src = (REPO / "pages" / filename).read_text(encoding="utf-8")
    tree = ast.parse(src)
    called = {n.func.attr for n in ast.walk(tree)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    assert "_sync_community_guidance" in called, (
        f"{filename} 从来没有调用 _sync_community_guidance() —— "
        f"这一页的空库引导是死的，而**不会有任何一处报错**")


# ==================================================== 2. ⭐ 命门：只有一份空状态

def test_no_page_grows_its_own_empty_state():
    """⭐⭐ 不许有第二处自己拼空状态底栏。

    八页「库空不空」各问各的（数据结构完全不同），
    但**"空了该长什么样"只能有一份** —— 否则八页会各自演化成
    八个略有差别的空状态，而**没有任何东西会发现它们不一样了**。

    判据：凡是提到社区 CTA 文案（「去社区拿」）的地方，
    都必须是**把它当参数交给共用件**，不许自己 `configure_primary`。
    """
    offenders = []
    for filename in sorted(ALL_WIRED):
        path = REPO / "pages" / filename
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in ast.walk(tree):
            if not (isinstance(node, ast.Call)
                    and isinstance(node.func, ast.Attribute)
                    and node.func.attr == "configure_primary"):
                continue
            # 第一个实参若是「去社区拿…」字面量，说明这一页自己拼了空状态
            if node.args and isinstance(node.args[0], ast.Constant) \
                    and isinstance(node.args[0].value, str) \
                    and "去社区拿" in node.args[0].value:
                offenders.append((filename, node.lineno, node.args[0].value))
    assert not offenders, (
        "这些页自己拼了空状态底栏，绕开了共用件：\n"
        + "\n".join(f"  {f}:{ln}  {t}" for f, ln, t in offenders)
        + "\n⭐ 八份空状态会各自演化，而没有任何东西会发现它们不一样了。")


def test_the_shared_helper_is_the_only_place_that_opens_the_category():
    """空转守卫：共用件必须真的存在且真的接着 `open_category`。

    ⭐ 上面那条只验"没人自己拼"。如果共用件本身是个空壳，它照样绿。
    """
    src = (REPO / "widgets" / "community_library.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "guide_empty_library"), None)
    assert fn is not None, "共用件 guide_empty_library 不见了 —— 判据锚点失效"
    called = {n.func.attr for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)}
    called |= {n.func.id for n in ast.walk(fn)
               if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)}
    assert "configure_primary" in called, "共用件没有真的换主按钮"
    assert "configure_extra" in called, (
        "共用件没有保住第二步（把原来那颗按钮挪到 extra）")


@pytest.mark.parametrize("filename", sorted(ALL_WIRED))
def test_every_wired_page_keeps_the_second_step(filename):
    """⭐⭐ 每一页交给共用件的 `keep_text` 都必须是**真的打开目录**那颗。

    ⚠ RN-153 的血教训：第一版把「打开资源目录」整个换掉了，
    而底栏文案还在说"放进资源目录" —— **指着一个不存在的按钮**。
    ⭐ 我修好了第一步（去哪儿拿），却顺手删掉了第二步（放哪儿去）。

    判据扫每页调用共用件时给的 `keep_text`，必须含「打开」。
    """
    src = (REPO / "pages" / filename).read_text(encoding="utf-8")
    tree = ast.parse(src)
    keeps = []
    for node in ast.walk(tree):
        if not (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "guide_empty_library"):
            continue
        for kw in node.keywords:
            if kw.arg == "keep_text" and isinstance(kw.value, ast.Constant):
                keeps.append(kw.value.value)
        # flash 走自己的薄封装，位置参数
        for arg in node.args[1:]:
            if isinstance(arg, ast.Constant) and isinstance(arg.value, str):
                keeps.append(arg.value)
    if not keeps:
        # 音效家族四页在基类里调
        src = (REPO / "pages" / "sound_page_base.py").read_text(encoding="utf-8")
        keeps = ["打开音频资源"] if "打开音频资源" in src else []
    assert keeps, f"{filename} 找不到交给共用件的 keep_text"
    assert any("打开" in k for k in keeps), (
        f"{filename} 交出去的第二步不是「打开目录」：{keeps}\n"
        "⭐ 修好第一步却删掉第二步，等于没修")


def test_flash_only_guides_on_the_two_asset_tabs():
    """`flash` 的主按钮本来就是个状态机，**别把它顶掉**。

    它按页签在「打开图片文件夹 / 打开音频文件夹 / 自定义强度预览 /
    启用自定闪光 / 启动 / 前往效果预览」之间切。
    ⭐ 引导只该插在"打开一个空文件夹"那两个页签上 ——
    插到「启用/启动」那一支就等于**把用户唯一的启动入口换成了逛社区**。
    """
    src = (REPO / "pages" / "flash_page.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree) if isinstance(n, ast.FunctionDef)
               and n.name == "_sync_action_bar"), None)
    assert fn is not None, "flash 没有 _sync_action_bar —— 判据锚点失效"

    guides = [n for n in ast.walk(fn)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
              and n.func.attr == "_guide_empty_library"]
    assert len(guides) == 2, (
        f"flash 里有 {len(guides)} 处空库引导，应该恰好 2 处"
        "（图片设置 / 音频设置两个页签）")

    # 启用/启动那一支不许被引导挤掉
    starters = [n for n in ast.walk(fn)
                if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                and n.func.attr == "configure_primary"
                and n.args and isinstance(n.args[0], ast.Constant)
                and n.args[0].value in ("启用自定闪光", "启动")]
    assert len(starters) == 2, (
        "flash 的「启用自定闪光 / 启动」入口不见了 —— "
        "那是全页唯一能让功能真正跑起来的按钮（RN-079）")


#: 八页各自"重算空库形态"的入口。⭐ 判据自己列，不读产品的类属性当答案 ——
#: 读产品的答案就等于"产品说它覆盖了几页，判据就信几页"。
EMPTY_SYNC = {
    "kill_sound_page.py": "_sync_community_guidance",
    "kill_voice_page.py": "_sync_community_guidance",
    "switch_weapon_page.py": "_sync_community_guidance",
    "reload_sound_page.py": "_sync_community_guidance",
    "gun_sound_page.py": "_sync_community_guidance",
    "death_sound_page.py": "_sync_community_guidance",
    "special_sound_page.py": "_sync_community_guidance",
    "flash_page.py": "_sync_action_bar",
}

#: 「点了也不会有反应」的按钮文案。空库时这些按钮背后没有任何素材可播。
DEAD_BUTTON_WORDS = ("测试", "试听", "预览", "播放")

#: 下拉框里等于"什么都没选"的占位项。只剩这些 = 没得选。
PLACEHOLDER_ITEMS = {"不启用", "未启用", "不使用", "无", "关闭", "默认", ""}


def _combo_has_nothing_to_pick(combo) -> bool:
    """这个下拉框是不是**没得选**。

    ⭐⭐ 判据的范围必须**自己算出来**，不能由我手抄。第一版写的是
    「空库页面上的所有下拉框」，当场诬告了 `flash` 的 4 个下拉框和 5 颗预览按钮 ——
    闪光效果是软件**自己合成的颜色叠加**，一个素材都不用，那些控件完全正常。
    ⇒ **分母划错的判据不只是漏，它还会逼人去改对的代码**（RN-167 同款）。

    改成问控件自己：**它有没有东西可选**。`flash` 的颜色下拉框有真实选项 ⇒ 放行；
    `flash` 的 `image_style_combo` 空库时 `count()==0` ⇒ 照样逮住。
    同一条判据，范围自己就对了。
    """
    if combo.count() == 0:
        return True
    return all(combo.itemText(i).strip() in PLACEHOLDER_ITEMS
               for i in range(combo.count()))


def _combo_driving(button, page):
    """这颗按钮试听的是哪个下拉框选中的东西；找不到就返回 None。

    从按钮往上走，第一个**恰好含一个下拉框**的祖先就是它那一行。
    ⚠ 上界是页面：`flash` 的预览按钮住在底部操作栏（0 个下拉框），
    再往上就是整页（4 个）—— 永远凑不出"恰好一个"，于是**不配对、不误报**。
    这个上界不是为了省事，它就是"这颗按钮到底受不受风格库支配"的判据本身。
    """
    from PySide6.QtWidgets import QComboBox

    anc = button.parentWidget()
    for _ in range(8):
        if anc is None:
            return None
        combos = anc.findChildren(QComboBox)
        if len(combos) == 1:
            return combos[0]
        if anc is page:
            return None
        anc = anc.parentWidget()
    return None


def _build_empty_page(filename, qapp, monkeypatch):
    """离屏建一页，并把它的"我空不空"全部按成 True。"""
    from PySide6.QtCore import Qt

    from _audit_neutralize import block_modal_dialogs
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes(verbose=False)
    block_modal_dialogs()
    cls = _page_class(_module_of(filename))
    page = cls()
    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    patched = 0
    for name in ("_library_is_empty", "_image_library_is_empty",
                 "_audio_library_is_empty"):
        if hasattr(page, name):
            monkeypatch.setattr(page, name, lambda: True)
            patched += 1
    assert patched, f"{filename} 一个「我空不空」的钩子都没有 —— 判据没法造空库态"
    getattr(page, EMPTY_SYNC[filename])()
    qapp.processEvents()
    return page


def _enabled_dead_controls(page):
    """空库时**点了也不会有反应**、却仍然可点的控件。

    通用扫描（下拉框 + 试听类按钮），不读页面自己报的清单 ——
    ⭐ 手抄清单是会扩大的盲区：页面加了一排新控件，清单不会自己跟上，
    而"清单里的都置灰了"读起来跟"全都置灰了"一模一样。
    """
    from PySide6.QtWidgets import QAbstractButton, QComboBox

    combos = [c for c in page.findChildren(QComboBox)
              if c.isEnabled() and _combo_has_nothing_to_pick(c)]
    buttons = []
    for b in page.findChildren(QAbstractButton):
        if not b.isEnabled() or not any(w in b.text() for w in DEAD_BUTTON_WORDS):
            continue
        driver = _combo_driving(b, page)
        if driver is not None and _combo_has_nothing_to_pick(driver):
            buttons.append(b)
    return combos, buttons


@pytest.mark.parametrize("filename", sorted(EMPTY_SYNC))
def test_empty_library_leaves_no_control_that_does_nothing(filename, qapp,
                                                           monkeypatch):
    """⭐⭐ RN-179：库是空的时候，不许留下一堆点了没反应的控件。

    外审 **21 发 / 跨 9 页**，原话是「误以为功能损坏 / 界面卡死」。
    实测原状（2026-08-22）：

        switch_weapon   下拉框 37/39 可点   试听按钮 39/39 可点
        gun_sound       15/18               18/18
        special_sound   14/18               18/18

    点下去什么都不会发生。⭐ **一个可点却什么都不做的控件，比一个置灰的控件更糟** ——
    置灰说的是「你还没准备好」，可点却无反应说的是「这软件坏了」。

    与 RN-040/047「试听静默」同族但**轴不同**：那次问的是响不响，
    这次问的是**该不该能点**。修好了响不响，不等于修好了该不该能点。

    ⚠ 扫描是**通用**的（所有下拉框 + 所有试听类按钮），动作才是各页显式给的。
    这么分是有理由的：如果判据也只看各页自己报的清单，那么页面新加一排控件时
    判据会**跟着一起瞎**，而它报出来的绿和真的全绿长得一模一样。
    """
    page = _build_empty_page(filename, qapp, monkeypatch)
    try:
        combos, buttons = _enabled_dead_controls(page)
        assert not combos and not buttons, (
            f"{filename} 空库时还有 {len(combos)} 个下拉框、{len(buttons)} 颗试听类按钮"
            f"可以点：下拉框如 {[c.objectName() or '(无名)' for c in combos[:3]]}，"
            f"按钮如 {[b.text() for b in buttons[:3]]} —— "
            "点下去什么都不会发生（RN-179）。")

        # ⭐ 反面：**素材补上了就得还回去**。少了这一条，"把控件全部 setEnabled(False)"
        # 也能过关，而那是一次静默的功能丢失（同 RN-153「借了要还」那条）。
        #
        # ⚠ 取样不能写成"页面上所有灰着的下拉框" —— 第一版就是这么写的，当场把
        # `flash` 上**本来就因为别的原因是灰的**那 2 个也算成了受害者，
        # 于是共用件按约定把它们还原成"原来的灰"，判据却判成了"借了不还"。
        # ⭐ **判据分不清"谁弄灰的"，就不能拿"现在是灰的"当证据。**
        # 改成自己造一次 A/B：明确挑一个**亮的**下拉框，清空 → 同步（应变灰）→
        # 加一项 → 同步（应变亮）。两头都是判据自己设的，不用猜。
        from PySide6.QtWidgets import QComboBox

        probe = next(iter(page.findChildren(QComboBox)), None)
        assert probe is not None, (
            f"{filename} 上一个下拉框都没有 —— 造不出 A/B，这条反面在空转。")
        # 先把它推回一个**干净的亮着的起点**：给一项让共用件把它还原、
        # 再显式置亮。这样接下来两步的因果只可能来自这条机制本身。
        probe.addItem("判据造的一个风格")
        getattr(page, EMPTY_SYNC[filename])()
        probe.setEnabled(True)
        qapp.processEvents()

        probe.clear()
        getattr(page, EMPTY_SYNC[filename])()
        qapp.processEvents()
        assert not probe.isEnabled(), (
            f"{filename}：把一个下拉框清空之后它还是亮的 —— "
            "置灰这一步没在看这个控件（RN-179）。")

        probe.addItem("判据造的一个风格")
        getattr(page, EMPTY_SYNC[filename])()
        qapp.processEvents()
        assert probe.isEnabled(), (
            f"{filename}：下拉框有风格之后仍然是灰的 —— "
            "借了不还，用户再也选不了（RN-179）。")
    finally:
        page.deleteLater()


@pytest.mark.parametrize("filename", sorted(EMPTY_SYNC))
def test_the_empty_state_always_keeps_a_way_to_put_the_files_in(
        filename, qapp, monkeypatch):
    """⭐⭐ RN-153 的血教训要**量行为**，不能靠 AST 找一个函数名。

    原来守这条的是上面那条 AST 判据（「共用件里必须出现 `configure_extra`」）。
    RN-180 之后它变成了**假绿**，而且假得很隐蔽：CTA 搬进引导卡以后，
    第二步（打开资源目录）成了底栏那颗**没被碰过**的主按钮，
    共用件根本不需要再动 extra —— 可 `configure_extra` 这个名字**仍然出现在源码里**
    （用来把「新建风格」收掉），于是那条 AST 判据照样绿。
    回退验证把 `configure_extra(keep_text, ...)` 换成 `pass`，它一声不吭。

    ⭐ **「源码里出现过这个调用」和「用户真的还有那条路」是两回事。**
    这条改成直接问屏幕：空库时页面上必须存在一颗**看得见、点得动**、
    能打开资源目录的按钮。

    ⚠ RN-153 那次的原话值得再抄一遍 ——「文案提示『放进资源目录』却没有打开目录的
    入口，从社区下载后卡在找路径」。⭐ 一条三步的路，只把第一步做顺是走不通的。
    """
    from PySide6.QtWidgets import QAbstractButton

    page = _build_empty_page(filename, qapp, monkeypatch)
    try:
        if filename == "flash_page.py":
            tabs = page.tab_widget
            index = next((i for i in range(tabs.count())
                          if tabs.tabText(i) == "图片设置"), None)
            tabs.setCurrentIndex(index)
            page._sync_action_bar()
            qapp.processEvents()

        openers = [b.text().strip() for b in page.findChildren(QAbstractButton)
                   if not b.isHidden() and b.isEnabled()
                   and "打开" in b.text() and (
                       "资源" in b.text() or "文件夹" in b.text() or "目录" in b.text())]
        assert openers, (
            f"{filename} 空库时没有任何一颗看得见又点得动的「打开…资源/文件夹」按钮 —— "
            "文案让用户把素材放进资源目录，却没有入口能打开那个目录（RN-153）。")
    finally:
        page.deleteLater()


# ==================================================== 3. 第二步不许丢

@pytest.mark.parametrize("filename", sorted(EMPTY_SYNC))
def test_the_first_step_is_in_the_card_not_the_bottom_bar(filename, qapp,
                                                          monkeypatch):
    """⭐⭐ RN-180：空库时的第一步必须在**空白发生的地方**，不在页尾。

    外审 **20 发 / 跨 9 页**：「核心流程倒置」「玩家会在满屏不可用的控件里乱点受挫」。
    RN-153/165 把社区 CTA 放进的正是底部操作栏。

    ⭐ 而 CLAUDE.md 里早就写着这条 ——「**解释性文字放在困惑发生的位置之前，
    不是页尾；放页尾 = 没放**」，是做官网那一轮拿两轮外审换来的。
    我自己写下的教训自己没照做，因为**它归档在「网站」小节里**，而我在做桌面版。
    ⇒ **教训是按场景归档的，而缺陷不认场景。**

    判据同时守两头（只守一头就会被"两边都放"蒙混过去 —— 那正是 RN-171 在
    `kill_icon` 上判掉的「同一个行动在页面出现 3 次」）：
      1. 引导卡**看得见**，而且卡上那颗按钮就是 CTA；
      2. 底栏**任何一颗**按钮都不许再叫这个名字。
    """
    page = _build_empty_page(filename, qapp, monkeypatch)
    try:
        # ⚠ `flash` 的"空"是**按页签**算的（图片库 / 音频库各一份），引导只插在
        # 那两个资源页签上 —— 这是 RN-153 就定下的、由
        # `test_flash_only_guides_on_the_two_asset_tabs` 锁着的行为，不是缺陷。
        # 判据得先切到资源页签，否则量的是"基础设置页签上没有引导"，那当然没有。
        if filename == "flash_page.py":
            tabs = page.tab_widget
            index = next((i for i in range(tabs.count())
                          if tabs.tabText(i) == "图片设置"), None)
            assert index is not None, "flash 的「图片设置」页签不见了 —— 判据锚点失效"
            tabs.setCurrentIndex(index)
            page._sync_action_bar()
            qapp.processEvents()

        callout = getattr(page, "empty_callout", None)
        assert callout is not None, (
            f"{filename} 没有空库引导卡 —— 第一步还留在底栏（RN-180）")
        # ⚠ 用 `isHidden()` 不用 `isVisible()`：页面是离屏建的，
        # 离屏窗口的子控件 `isVisible()` 恒为 False，拿它断言等于判据空转。
        assert not callout.frame.isHidden(), (
            f"{filename} 空库时引导卡没有亮起来 —— 引导等于没做")
        cta = callout.button.text().strip()
        assert cta, f"{filename} 引导卡上那颗按钮没有文案"

        bar = page.action_bar
        bottom = [b.text().strip() for b in
                  (bar.primary_btn, bar.secondary_btn, bar.extra_btn)
                  if not b.isHidden()]
        assert cta not in bottom, (
            f"{filename} 底栏还有一颗「{cta}」（底栏现有：{bottom}）—— "
            "同一个行动同时出现在卡里和页尾，用户不知道该点哪一个（RN-171/RN-180）。")
    finally:
        page.deleteLater()


@pytest.mark.parametrize("filename", sorted(EMPTY_SYNC))
def test_the_empty_state_has_exactly_one_purple_button(filename, qapp,
                                                       monkeypatch):
    """⭐⭐ RN-186：空库时全页只许有一颗主按钮，就是引导卡上那颗。

    外审 3/3（多页）：「同时存在两个高亮紫色主按钮」「首步动作焦点冲突」
    「不知先点哪个」。实测确认：引导卡的「去社区拿一套…」和底栏的
    「打开音频资源」**都是 `primaryButton`**。

    ⭐⭐ 本仓早就判过这件事 —— RN-139 的原话就是
    「**两颗紫的等于零颗 ——「主」是相对的**」，而且还专门留了一条棘轮
    `test_there_is_exactly_one_primary_button`。它没逮住这一次，
    因为**它只盯 `basic` 一页**。

    ⇒ ⭐ **判据的页面范围就是它的分母。** 一条只保一页的规则，
      在登记册上、在注释里、在我脑子里都写着"这条规则在生效"，
      而它实际覆盖 1/28。这跟"没有这条规则"的区别，只在出事的那一页上才看得出来。

    ⚠ 只断言**空库这一态**，不做全站棘轮：本仓有页面刻意让同一个动作在卡里和
    底栏各出现一次（RN-078 的 viewmodel「保存到CFG」），那是判过的设计，
    一条全站铁规会当场诬告它。全站口径记在 RN-188，单独判。
    """
    from PySide6.QtWidgets import QPushButton

    page = _build_empty_page(filename, qapp, monkeypatch)
    try:
        if filename == "flash_page.py":
            tabs = page.tab_widget
            index = next((i for i in range(tabs.count())
                          if tabs.tabText(i) == "图片设置"), None)
            tabs.setCurrentIndex(index)
            page._sync_action_bar()
            qapp.processEvents()

        purple = [b.text().strip() for b in page.findChildren(QPushButton)
                  if b.objectName() == "primaryButton" and not b.isHidden()]
        assert len(purple) == 1, (
            f"{filename} 空库时有 {len(purple)} 颗主按钮：{purple} —— "
            "两颗紫的等于零颗（RN-139/RN-186）。"
            "此刻唯一该抢眼的是引导卡上那颗「去社区拿一套…」。")
        assert "社区" in purple[0], (
            f"{filename} 空库时唯一那颗主按钮是「{purple[0]}」，不是去社区拿素材 —— "
            "主按钮该指向第一步")
    finally:
        page.deleteLater()


def test_kill_icon_empty_state_offers_exactly_one_call_to_action(qapp, monkeypatch):
    """⭐⭐ 空库时，`kill_icon` 的底栏不许再劝人「自己做一套」。

    RN-171（2026-08-22，外审 **6/6 票**，两档各 3 发）：

    > 空状态下底部主按钮导向了最高门槛的「打开素材工坊」（自制），
    > 与中间主推的「去拿一套图标包」产生行动冲突与误导。

    机制：RN-145 已经把底栏**主**按钮在空库时收掉了，于是底栏唯一还亮着的
    就成了**次**按钮「打开素材工坊」——一个全新用户，卡里被告诉去社区拿现成的，
    页尾却在推自己做。

    ⭐⭐ 这是 RN-154 那条的又一次现身：**修一个问题时留下的旧形态，
    会变成下一个问题。** RN-145 收掉三份重复，反而让剩下这一份升格成了主张。

    ⚠ 顺带记一条工艺：**这条只有"整页无折线"的截图才看得见**（RN-170）——
    两颗互相冲突的按钮以前从来没有同时出现在一张图里，
    而**外审看不见的东西不会报**。
    """
    from PySide6.QtCore import Qt

    from pages.kill_icon_page import KillIconPage

    page = KillIconPage()
    page.setAttribute(Qt.WA_DontShowOnScreen, True)
    monkeypatch.setattr(page, "_library_is_empty", lambda: True)
    page._sync_action_bar()
    qapp.processEvents()
    try:
        # ⚠ 用 `isHidden()` 不用 `isVisible()`：这个页面是离屏建的（铁律），
        # 而**离屏窗口的子控件 `isVisible()` 恒为 False** —— 拿它做断言的话
        # 「空库时不可见」这一条**不管代码怎么写都成立**，判据当场变空转。
        # `isHidden()` 反映的是**显式隐藏状态**，不受祖先可见性影响。
        assert page.action_bar.primary_btn.isHidden(), (
            "空库时底栏主按钮又回来了（RN-145 收掉的那颗）")
        assert page.action_bar.secondary_btn.isHidden(), (
            f"空库时底栏还亮着「{page.action_bar.secondary_btn.text()}」—— "
            "全新用户此时唯一该看到的行动是「去拿一套图标包」，"
            "而它在首屏那张卡里（空白发生的地方）。")

        # 反面：**库不空的时候它必须回来**。少了这一条，"把按钮删掉"也能过关。
        monkeypatch.setattr(page, "_library_is_empty", lambda: False)
        page._sync_action_bar()
        qapp.processEvents()
        assert not page.action_bar.secondary_btn.isHidden(), (
            "库不空了，「打开素材工坊」却没回来 —— 这一页少了做素材的入口")
    finally:
        page.deleteLater()

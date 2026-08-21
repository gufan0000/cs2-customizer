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


# ==================================================== 3. 第二步不许丢

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

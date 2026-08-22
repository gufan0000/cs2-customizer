# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""风格库是空的时候，给一条走得通的路（RN-153，RN-145 的音频版）。

## 缺陷长什么样

**本软件不内置任何音效素材。** 全新安装打开「换弹音效」，34 把枪的下拉框
全是「不启用」，而底栏最抢眼的那颗主按钮是「打开音频资源」——
点开是一个**空文件夹**。外审原话：

    「无内置预设且概念抽象，用户不知道需经历"打开目录放音频 → 刷新 →
      新建风格 → 逐枪绑定"的冷启动流程」
    「操作路径极其割裂……缺乏直观闭环引导」

⭐ **"打开一个空文件夹"不是一条路** —— 用户手上没有文件，
这颗按钮把他送到的地方什么也解决不了。

RN-145 在击杀图标页已经裁过同一件事：**不内置，改成引导**。
这份判据把同一条口径套到音效家族四页。

## 裁定范围（为什么是四页不是八页）

社区站九个分类都在（击杀音效 1 / 击杀语音 2 / 换弹 3 / 切枪 4 / 枪声 5 /
被击杀 6 / 击杀图标 7 / 特殊音效 22 / 自定闪光 23），所以**八个页面都能接**。
本轮只接**共用 `SoundPageBase` 的四页**：

  · 四页共用一个骨架 ⇒ 逻辑写一处、零重复、无返工；
  · `gun_sound` / `death_sound` / `special_sound` / `flash` 各有各的结构，
    要各写一遍 —— 那是"顺手"，不是"必须一起"。
  · ⭐ 而且**不做也不欠债**：它们不像 RN-147 那样"不一起做就要先补一个
    马上要拆的形态"。⇒ 单独立案 RN-165，下一轮按同一机制接。

## 这份文件里最要紧的三条

1. `test_every_sound_page_calls_the_shared_guidance`
   ⭐ 逻辑在基类只有一份，但**调用点每页一行** —— 这正是"抄漏一处不报错"的
   经典位置（RN-138 / RN-163 都是这么发生的）。这条判据把"抄漏"变成红灯。
2. `test_the_url_table_and_the_legacy_constant_do_not_drift`
   `COMMUNITY_KILL_ICON_URL` 是 RN-145 留下的老常量，现在由表派生。
   ⭐ **两份要么合并、要么会分叉**；这里合并了，判据钉住它没再分叉。
3. `test_a_build_without_the_community_falls_back_to_a_real_path`
   ⚠ RN-157 的教训：开源版的 `service_urls.py` **归它自己所有**，没有社区站。
   那时空库主按钮必须退成一条**真的走得通的路**，不是一颗指向空地址的按钮。
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

#: 四页 → 它在社区站的分类键。⭐ 写死在判据里是故意的：
#: 拿一份**独立于产品**的清单去对，而不是读产品的类属性当答案。
EXPECTED_CATEGORY = {
    "kill_sound": "kill_sound",
    "kill_voice": "kill_voice",
    "switch_weapon": "switch_weapon",
    "reload_sound": "reload_sound",
}

SOUND_PAGE_FILES = {
    "kill_sound": "kill_sound_page.py",
    "kill_voice": "kill_voice_page.py",
    "switch_weapon": "switch_weapon_page.py",
    "reload_sound": "reload_sound_page.py",
}


#: ⚠ RN-157：**判据自己钉住地址表，不许读产品常量的实际值。**
#: 开源版的 `service_urls.py` 归它自己所有、没有社区站 —— 读实际值的话，
#: 这一整份判据同步过去会**整体假红**（而本仓怎么跑都是绿的，看不出来）。
TEST_URLS = {key: f"https://example.invalid/category.php?id={i}"
             for i, key in enumerate(sorted(EXPECTED_CATEGORY.values()), start=1)}
TEST_URLS["kill_icon"] = "https://example.invalid/category.php?id=7"


@pytest.fixture(autouse=True)
def _pin_community_urls(monkeypatch):
    monkeypatch.setattr(lib, "COMMUNITY_CATEGORY_URLS", dict(TEST_URLS))


@pytest.fixture
def empty_page(qapp, monkeypatch):
    """一个**风格库全空**的换弹音效页（全新安装的样子）。"""
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    from pages.reload_sound_page import ReloadSoundPage

    page = ReloadSoundPage()
    # ⚠ 直接把扫描结果清空，而不是指望夹具的磁盘恰好是空的 ——
    # 「绿不绿取决于这台机器上有没有素材」是本仓踩过的判据错法（RN-141/142 族）。
    page.weapon_reload_styles = {}
    page._refresh_status_badge()
    qapp.processEvents()
    yield page
    page.deleteLater()
    qapp.processEvents()


@pytest.fixture
def stocked_page(qapp, monkeypatch):
    """一个**有素材**的换弹音效页（反面对照）。"""
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    from pages.reload_sound_page import ReloadSoundPage

    page = ReloadSoundPage()
    page.weapon_reload_styles = {w: ["测试风格"] for w in page._get_all_weapons()}
    page._refresh_status_badge()
    qapp.processEvents()
    yield page
    page.deleteLater()
    qapp.processEvents()


# ============================================ 1. 空库时主按钮换成一条真的路

def test_an_empty_library_leads_with_the_community_not_an_empty_folder(empty_page):
    """⭐ 空库时，**最显眼的那一步**不许是「打开一个空文件夹」。

    点开一个空文件夹解决不了任何问题 —— 用户手上没有文件。

    ⚠ RN-180 改了这条判据量的**位置**，没改它量的**东西**：
    第一步从底栏搬进了引导卡（空白发生的地方），所以这里改问引导卡。
    底栏那颗「打开音频资源」现在是**第 2 步**，是对的 ——
    人下载完包之后确实需要它。⭐ 判据跟着修法搬家，但守的还是同一句话：
    **别把"没得挑"包装成"去这个空目录看看"。**
    """
    callout = empty_page.empty_callout
    assert not callout.frame.isHidden(), "空库时引导卡没亮 —— 第一步等于没给"
    text = callout.button.text()
    assert "打开音频资源" not in text, (
        "风格库是空的，最显眼的那一步却还在把用户送去一个空文件夹")
    assert "社区" in text, f"引导卡上那颗按钮不是「去社区拿」：{text!r}"


def test_the_empty_state_call_to_action_actually_opens_the_community(
        empty_page, monkeypatch):
    """文案对 ≠ 接线对。"""
    opened = []
    monkeypatch.setattr(lib, "open_category",
                        lambda key: (opened.append(key), True)[1])
    empty_page.empty_callout.button.click()
    assert opened == [EXPECTED_CATEGORY["reload_sound"]], (
        f"点了引导卡上那颗按钮，实际去向：{opened}")


def test_a_stocked_library_keeps_the_original_primary(stocked_page):
    """反面守卫：**有素材时不许把原来那颗按钮换掉**。

    ⭐ 少了这条，"永远显示引导按钮"也能让上面两条全绿 ——
    而那会把一个正常用户每次都送去社区站。
    """
    assert "打开音频资源" in stocked_page.action_bar.primary_btn.text(), (
        "有素材了，主按钮却还停在引导态")
    # ⚠ RN-180 之后底栏主按钮在**两种状态下都是**「打开音频资源」——
    # 只看它已经分不出引导态了（回退验证当场判假绿）。真正的分辨点是引导卡。
    # ⭐ **判据盯的那个位置一旦在两种状态下取值相同，它就已经停止工作了。**
    assert stocked_page.empty_callout.frame.isHidden(), (
        "有素材了，空库引导卡却还亮着 —— 正常用户每次进来都被劝去社区站")


def test_the_page_says_out_loud_that_it_ships_no_assets(empty_page):
    """空库时要**明说**软件不带素材，别让用户以为是自己装坏了。

    ⭐ RN-145 的原话：「没得挑」要变成一条走得通的路，
    而第一步是承认「本来就没有」。
    """
    # RN-180：这句话跟着第一步一起搬进了引导卡 —— 它要出现在**看到空白的地方**，
    # 而不是页尾。判据两边都收：卡里说了算数，底栏说了也算数，但不能两边都没说。
    said = " ".join([empty_page.empty_callout.title.text(),
                     empty_page.empty_callout.hint.text(),
                     empty_page.action_bar.message_label.text()])
    assert said.strip(), "空库时一句解释都没有"
    assert "不带素材" in said or "不内置" in said, (
        f"没说清「软件本来就不带素材」：{said!r}")


def test_the_empty_state_keeps_a_way_to_put_the_files_in(empty_page):
    """⭐⭐ 空库态必须同时给出**三步**：拿 → 放 → 刷新。

    ⚠ 第一版只做了第一步：把「打开音频资源」整个换成了「去社区拿一套」。
    外审当场两发独立点破：

        「文案提示『放进资源目录』却没有打开目录的入口，
          从社区下载后容易卡在找路径环节」

    ⭐ **我修好了第一步（去哪儿拿），却顺手删掉了第二步（放哪儿去）** ——
    一条三步的路，只把第一步做顺是走不通的。
    而且底栏那句话还在说"放进资源目录"，等于**指着一个不存在的按钮**。
    """
    # RN-180：三步现在**分居两处** —— 第 1 步在引导卡，第 2/3 步在底栏。
    # ⚠ 判据必须把两处一起收：只看底栏就会把"第一步搬走了"误判成"第一步没了"，
    # 只看卡就会漏掉 RN-153 那条血教训（第二步被顺手删掉）。
    texts = [empty_page.empty_callout.button.text(),
             empty_page.action_bar.primary_btn.text(),
             empty_page.action_bar.secondary_btn.text(),
             empty_page.action_bar.extra_btn.text()]
    joined = " / ".join(t for t in texts if t.strip())
    assert any("社区" in t for t in texts), f"没有「去拿」这一步：{joined}"
    assert any("打开音频资源" in t for t in texts), (
        f"没有「放进去」这一步：{joined}\n"
        "文案让用户把音频放进资源目录，却没有任何入口能打开那个目录")
    assert any("刷新" in t for t in texts), f"没有「刷新」这一步：{joined}"

    # ⭐ 三步要**说得出顺序**，不只是三颗按钮都在。底栏那句话必须自报是第几步 ——
    # 否则用户在页尾看到它会以为那就是开头。
    # ⚠ 这里一度写成「第 1 步在上面那张卡里」，外审 3/3 判「用生硬文字打补丁」
    # 「视线上下割裂」。⭐ **编号本身就够了**：写着「第 2 步」的人自然知道
    # 第 1 步在别处，不必再告诉他往哪儿看（RN-187）。
    message = empty_page.action_bar.message_label.text()
    # ⚠ RN-193：原来断言底栏必须写「第 2 步 / 第 3 步」。复跑当场判
    # 「直接从第 2 步开始，与第 1 步脱节」—— 编号本身制造了那个孤儿。
    # ⭐ 判据现在要的是**这句话自己站得住**：说清放哪儿、说清放完点什么，
    #   不依赖屏幕上别处有没有一个「第 1 步」。
    assert "资源目录" in message and "刷新" in message, (
        f"底栏没说清「放哪儿、放完点什么」：{message!r}")
    assert "第 1 步" not in message and "第 2 步" not in message, (
        f"底栏又开始编号了：{message!r} —— 编号会产生「第 1 步去哪了」这个问题，"
        "而第 1 步在另一个区域里（RN-187/RN-193）。")
    for phrase in ("上面", "下面", "上方", "下方", "那张卡", "左边", "右边"):
        assert phrase not in message, (
            f"底栏文案又开始描述版面了（「{phrase}」）：{message!r} —— "
            "界面不该跟用户解释自己长什么样，版面一动这句话就是错的")


def test_a_stocked_library_puts_the_style_tools_back(stocked_page):
    """反面守卫：有素材之后，「新建风格 / 风格工具」必须原样回来。

    ⭐ 空库态借用了那个位置。**借了不还就是一次静默的功能丢失** ——
    用户再也建不了风格，而没有任何一处会报错。
    """
    text = stocked_page.action_bar.extra_btn.text()
    assert "打开音频资源" not in text, (
        f"有素材了，「新建风格」的位置还被空库态占着：{text!r}")
    assert text.strip(), "extra 按钮成了空文案"


# ============================================ 2. 四页都要接上（抄漏 = 红灯）

@pytest.mark.parametrize("page_id", sorted(EXPECTED_CATEGORY))
def test_every_sound_page_declares_its_community_category(page_id):
    """四页各自声明的分类键必须对。

    ⭐ 填错一个键的后果是**静默送错地方** —— 用户点「去拿一套换弹音效」
    落到击杀音效的列表页，而没有任何一处会报错。
    """
    import importlib

    module = importlib.import_module(f"pages.{SOUND_PAGE_FILES[page_id][:-3]}")
    cls = next(obj for name, obj in vars(module).items()
               if name.endswith("Page") and hasattr(obj, "COMMUNITY_CATEGORY_KEY"))
    assert cls.COMMUNITY_CATEGORY_KEY == EXPECTED_CATEGORY[page_id], (
        f"{page_id} 声明的社区分类是 {cls.COMMUNITY_CATEGORY_KEY!r}，"
        f"应该是 {EXPECTED_CATEGORY[page_id]!r}")


@pytest.mark.parametrize("page_id", sorted(EXPECTED_CATEGORY))
def test_every_sound_page_calls_the_shared_guidance(page_id):
    """⭐ 逻辑在基类只有一份，但**调用点每页一行** —— 抄漏一处不会报错。

    AST 扫每页的 `_refresh_status_badge`，里面必须真的调到
    `_sync_community_guidance()`。
    ⭐ 这正是 RN-138 / RN-163 那个形状：**一处改动不会去通知它的所有调用点。**
    """
    path = REPO / "pages" / SOUND_PAGE_FILES[page_id]
    tree = ast.parse(path.read_text(encoding="utf-8"))
    target = next((n for n in ast.walk(tree)
                   if isinstance(n, ast.FunctionDef)
                   and n.name == "_refresh_status_badge"), None)
    assert target is not None, f"{page_id} 没有 _refresh_status_badge —— 判据锚点失效"

    called = [n.func.attr for n in ast.walk(target)
              if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)]
    assert "_sync_community_guidance" in called, (
        f"{page_id} 的 _refresh_status_badge 没调 _sync_community_guidance() —— "
        f"这一页的空库引导是死的，而**不会有任何一处报错**")


def test_the_shared_logic_really_lives_in_the_base_class():
    """空转守卫：逻辑必须在基类，不许四页各抄一份。

    ⭐ 上面那条只验"调了" —— 如果四页各自实现一份同名方法，它照样绿。
    """
    base = ast.parse((REPO / "pages" / "sound_page_base.py").read_text(encoding="utf-8"))
    names = [n.name for n in ast.walk(base) if isinstance(n, ast.FunctionDef)]
    assert "_sync_community_guidance" in names, "基类里没有 _sync_community_guidance"
    assert "_library_is_empty" in names, "基类里没有 _library_is_empty"

    for page_id, filename in sorted(SOUND_PAGE_FILES.items()):
        tree = ast.parse((REPO / "pages" / filename).read_text(encoding="utf-8"))
        dupes = [n.name for n in ast.walk(tree)
                 if isinstance(n, ast.FunctionDef)
                 and n.name in ("_sync_community_guidance", "_library_is_empty")]
        assert not dupes, (
            f"{page_id} 自己又实现了一份 {dupes} —— 基类那份就白写了。"
            f"⭐ 只要还有第二份副本，修好一份就等于没修")


# ============================================ 3. 单一真源与开源版退路

def test_the_url_table_and_the_legacy_constant_do_not_drift():
    """`COMMUNITY_KILL_ICON_URL` 必须**由表派生**，不许再各写一份。

    ⭐ **两份要么合并、要么会分叉。** RN-145 留下的那个老常量现在是表的
    一个视图；这条判据钉住它没有被人手写回去。

    ⚠ 判据看的是**源码写法**（AST），不是运行时的值 —— 开源版的
    `service_urls.py` 归它自己所有，里面这两个名字都可能不存在，
    读实际值会让这条判据在那边假红（RN-157 的教训）。
    """
    import ast

    tree = ast.parse((REPO / "service_urls.py").read_text(encoding="utf-8"))
    names_here = {t.id for node in tree.body if isinstance(node, ast.Assign)
                  for t in node.targets if isinstance(t, ast.Name)}
    if "COMMUNITY_KILL_ICON_URL" not in names_here:
        # ⚠ RN-157/158 那一族：开源版的 `service_urls.py` **归它自己所有**，
        # 里面根本没有社区站 —— 那是一个**真实的发行版形态**，不是缺陷。
        # ⭐ 判据要么容得下这个形态，要么它一同步过去就必红。
        pytest.skip("这个发行版没有社区站地址（开源版），本条不适用")
    derived = False
    for node in tree.body:
        if not isinstance(node, ast.Assign):
            continue
        names = {t.id for t in node.targets if isinstance(t, ast.Name)}
        if "COMMUNITY_KILL_ICON_URL" not in names:
            continue
        # 必须写成 `COMMUNITY_CATEGORY_URLS[...]`，不许是字面量或 f-string
        derived = (isinstance(node.value, ast.Subscript)
                   and isinstance(node.value.value, ast.Name)
                   and node.value.value.id == "COMMUNITY_CATEGORY_URLS")
    assert derived, (
        "COMMUNITY_KILL_ICON_URL 又被手写成一个独立地址了 —— "
        "它和分类表描述的是同一件事，两份早晚分叉，而且不会有人发现")


def test_every_declared_category_has_a_url():
    """四页声明的键必须在表里查得到。

    ⭐ 查不到的后果是**静默空转**：按钮画得出来、点得动，什么也不发生。
    """
    missing = sorted(k for k in EXPECTED_CATEGORY.values()
                     if not lib.category_url(k))
    assert not missing, f"这些分类键在 URL 表里没有地址：{missing}"


def test_a_build_without_the_community_falls_back_to_a_real_path(
        qapp, monkeypatch):
    """⚠ 开源版没有社区站 —— 那时主按钮必须退成一条**真的走得通的路**。

    RN-157 的教训：开源版的 `service_urls.py` 归它自己所有，里面没有社区站
    地址。⭐ **不能留一颗指向空地址的按钮** —— 那比没有按钮更糟。
    退路是回到「打开音频资源」（至少它是个真动作）。
    """
    monkeypatch.setattr("config.config.save_config", lambda: None, raising=False)
    monkeypatch.setattr(lib, "COMMUNITY_CATEGORY_URLS", {})
    from pages.reload_sound_page import ReloadSoundPage

    page = ReloadSoundPage()
    try:
        page.weapon_reload_styles = {}
        page._refresh_status_badge()
        qapp.processEvents()
        text = page.action_bar.primary_btn.text()
        assert text.strip(), "没有社区站时主按钮成了空文案"
        assert "打开音频资源" in text, (
            f"没有社区站时主按钮是 {text!r} —— 它多半指向一个空地址。"
            f"应该退回一条真的能走的路")
        # ⚠ RN-180 之后这条判据**必须也看引导卡**：CTA 已经从底栏搬进卡里，
        # 只看底栏的话「没有社区站却照样弹出引导卡」会一路绿。
        # 回退验证当场把它判成假绿，就是这个原因。
        assert page.empty_callout.frame.isHidden(), (
            f"没有社区站，引导卡却亮着「{page.empty_callout.button.text()}」—— "
            "那颗按钮指向一个空地址，比没有按钮更糟（RN-157）")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_fixture_would_notice_a_stocked_library(stocked_page, empty_page):
    """空转守卫：两个夹具必须真的**不一样**。

    ⭐ 如果 `_library_is_empty()` 恒真或恒假，上面那堆判据会一半永远绿。
    """
    assert empty_page._library_is_empty() is True
    assert stocked_page._library_is_empty() is False

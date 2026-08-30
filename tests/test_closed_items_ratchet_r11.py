# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R11-D：判为「不做」的几条，用棘轮把现状钉住——只许变好，不许变差。

「不做」不等于「不管」。这个专项已经出现过好几次"上一轮修好的东西被下一轮
悄悄改回去"，所以每条关闭的问题单都要留一个能变红的数字，而不是留一句话。

关的三条与理由：

* **UP-058** `theme_manager.generate_stylesheet` 1541 行（占文件 68%）。
  不拆的依据是 R2/R4 的实测：**生成 QSS 文本只要 0.18ms**，拆它对用户
  零收益；而它的输出喂给 9 个主题 × 26 个页面，动它的回归面是全站视觉。
  真要拆，唯一安全的判据是"9 个主题生成的 QSS 全文逐字节一致"，那得单开一轮。
* **UP-097** `SettingsRow`/`IconLabel`/`StatusChip` 采用率为 0，另有 45 处
  手搓 `QFrame#card` 散在 16 个文件。不做的依据有两条：① 登记册自己写着
  "这不是用户看得见的缺陷，是内部整洁度"；② **45 处里有 14 处（31%）落在
  flash/kill_icon/music/viewmodel/voice_output 这 5 个没有指纹基线的页面上**，
  而 R9-D 证明过这类"逐像素不变"的重构会悄悄弄丢 36 个按钮、ruff 和单测全绿、
  只有指纹逮得住。唯一有效的裁决工具覆盖不到三分之一的作业面，就不该动手。
* **UP-008** show 后 exec 前的同步 import。R2 做了又回退，理由写在
  `main_widget.py` 的注释里（模块级 `audio_manager` → `pygame.mixer.init()`，
  预热线程等于把音频设备初始化搬到后台守护线程）。R8a 之后到 show 的总账
  已从 2459.7 降到 1189.2ms。这里只钉住"那段回退理由不许被人删掉"——
  删了注释，下一个人就会再踩一次同样的坑。
"""
from __future__ import annotations

import ast
import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]

# --------------------------------------------------------------- UP-058

#: `generate_stylesheet` 当前行数（R11 实测 261-1801）。只许减不许增。
#:
#: ⚠ 2026-08-18 破例 +2（1541 → 1543）：RN-066/076 修单选钮形状，
#: `:checked` 里**必须补一行 `border-radius`**（缺陷就长在缺这一行上），
#: 外加一行指路注释。这条棘轮的本意是「别再往这一坨里堆**新样式**」，
#: 而不是「不许修这一坨里的缺陷」—— 一条禁止修缺陷的棘轮是坏棘轮。
#: 破例必须写清是哪一行、为什么；**不写理由的抬高等于把棘轮拆了**。
#:
#: ⚠ 2026-08-29 破例 +4（1543 → 1547）：RN-150 修「禁用的主按钮看着还能点」。
#: 改的是 `#primaryButton:disabled` 的两条属性（`accent_disabled` → 中性），
#: 那不新增行；多出来的 4 行是**一段四行的指路注释**，指向判据里那份完整实测
#: （四把尺子给了四个不同的数，以及为什么最后这把才对）。
#: ⭐ 第一版我把那整段 20 行的说明写进了 QSS，这条棘轮当场报 +20 ——
#:   它是对的：**理由该住在判据里，QSS 里只留一行指路**。
#:   ⇒ 一条「不许长」的棘轮，逼出来的不是「别修」，是「把话写到该写的地方」。
#: ⚠ 2026-08-30 破例 +21（1547 → 1568）：RN-103 把状态胶囊从「闭合的圆角空框」
#: 改成「无框 + 左侧 3px 色条」。五条规则（基础 / success·positive·info /
#: warn·warning / neutral / danger·error）各要把 `background-color` + `border`
#: 换成 `border: none` + `border-left`，**每条净 +2~3 行**，加上
#: `masterOffHost` 那条（它原来会把闭合轮廓加回来）—— 属性行合计约 +13；
#: 其余 8 行是三段指路注释。
#: ⭐ 第一版我把整套实测（全站分母、四个候选票数、八主题对比度）写进了 QSS，
#:   这条棘轮当场报 **+37** —— 和批 23 那次一模一样，它又一次是对的：
#:   **理由该住在判据里，QSS 里只留一行指路**。⇒ 已把说明搬进
#:   `tests/test_status_chips_do_not_look_clickable.py`，QSS 只留指针。
#: ⚠ 2026-08-30 破例 +14（1568 → 1582）：RN-414 给准心预览框加「它此刻是入口」
#: 那一档外观（`[clickable="true"]` 的描边 + hover），两条规则共 8 行 +
#: 6 行指路注释。⭐ 用的是批 26 刚立下的形状语言（闭合轮廓 = 可点），
#: **不用品牌色**（批 22：饱和色读作「在运行」）。
#: 完整实测在 `tests/test_crosshair_says_what_it_actually_does.py`。
GENERATE_STYLESHEET_MAX_LINES = 1582


def test_generate_stylesheet_does_not_grow():
    src = (ROOT / "theme_manager.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next((n for n in ast.walk(tree)
               if isinstance(n, ast.FunctionDef) and n.name == "generate_stylesheet"), None)
    assert fn is not None, "theme_manager.generate_stylesheet 不见了"
    lines = fn.end_lineno - fn.lineno + 1
    assert lines <= GENERATE_STYLESHEET_MAX_LINES, (
        f"generate_stylesheet 从 {GENERATE_STYLESHEET_MAX_LINES} 行涨到了 {lines} 行。"
        "UP-058 判为不拆，但**不许继续长**——新样式请开新方法，别再往这一坨里堆。"
    )


# --------------------------------------------------------------- UP-097

#: 手搓 `QFrame#card` 的处数（`scripts/component_adoption.py` 实测）。只许减不许增。
#:
#: ⚠ 这个数**必须等于实测值**，不能留富余。R11 定的是 45，而 KI-6 把击杀图标页
#: 重构成清单板时那页从 3 处减到 2 处，实测值掉到 44——棘轮于是空出一格，
#: 「再加一处手搓卡片」照样绿。2026-08-16 的回退验证台就是这么逮出来的：
#: **棘轮的档位高于现状一格，它就不是棘轮。** 减少手搓卡片时记得同步压这个数。
#: ⚠⚠ **同一个错法犯第二次了**（2026-08-22 回退验证逮出来）：实测值又掉到 43，
#: 而这个数还停在 44 —— 棘轮再一次空出一格，「再加一处手搓卡片」照样绿。
#: 上面那段注释白纸黑字写着 KI-6 那次一模一样的事。
#: ⭐ **一条"只许减不许增"的棘轮，会被每一次真实的减少悄悄放松。**
#:   减少是好事，可它同时就是这条判据失效的时刻，而没有任何东西会提醒你。
#: ⇒ 现在的数 = pages 43 + widgets 4 + dialogs 1。
HANDROLLED_CARD_MAX = 48

#: ⚠ 它数的是**字面形态**，分不出「这是在调用」还是「这是在注释里谈论它」。
#: 2026-08-27（批 16）实测：`widgets/master_switch_effect.py` 的一句解释性注释
#: 里写了这个调用的样子，当场被算成第 49 处手搓卡片。
#: ⭐ **一条按正则数「有没有做某件事」的棘轮，会把「谈论那件事」也算进去。**
#: ⇒ 处置是**改注释**，不是放宽棘轮：写文档的人绕开一句话，比棘轮空出一格便宜。
_SETOBJECTNAME_CARD = re.compile(r"""setObjectName\(\s*["']card["']\s*\)""")

#: ⚠⚠ 扫描范围原来**只有 `pages/`**。RN-180 加空库引导卡时我第一版手搓了一个
#: `QFrame` + `objectName("card")`，而它住在 `widgets/` —— **这条棘轮完全看不见它**。
#: 那张卡是八个页面共用的，也就是说：最容易被复制到全站的那一类新卡片，
#: 恰好落在判据的盲区里。⭐ **判据的目录范围也是分母。**
_CARD_SCAN_DIRS = ("pages", "widgets", "dialogs")


def _handrolled_card_sites() -> dict[str, int]:
    """统计把控件 objectName 直接设成 "card" 的处数（pages / widgets / dialogs）。

    口径要和 `scripts/component_adoption.py` 对得上——两处数不一样的话，
    这个数字就没有意义了（R8d 的教训：文档说的判据和代码里的判据
    可以是两回事，对着文档推理会推错）。
    """
    out = {}
    for folder in _CARD_SCAN_DIRS:
        for path in sorted((ROOT / folder).glob("*.py")):
            n = len(_SETOBJECTNAME_CARD.findall(path.read_text(encoding="utf-8")))
            if n:
                out[f"{folder}/{path.name}"] = n
    return out


def test_handrolled_cards_do_not_grow():
    sites = _handrolled_card_sites()
    total = sum(sites.values())
    assert total <= HANDROLLED_CARD_MAX, (
        f"手搓 QFrame#card 从 {HANDROLLED_CARD_MAX} 处涨到了 {total} 处：{sites}。"
        "UP-097 判为不做统一迁移（31% 的作业面没有指纹基线守着），"
        "但**新代码请用 SettingsCard.make(...)**，别再加手搓的。"
    )


def test_zero_adoption_components_are_kept_on_purpose():
    """三个零采用组件**故意留着**，不是忘了删。

    R11 设计阶段一度打算删掉它们（`SettingsRow` 85 行 + `IconLabel` 58 +
    `StatusChip` 31 = 174 行，采用率各为 0）。真去看引用才发现它们被
    `scripts/widget_showcase.py`（目视检查工具）和 `tests/test_widget_components.py`
    引着——删一个组件要动 5 个文件，而收益是零。更要紧的是：它们是
    UP-097 那次迁移的**目标词汇表**，先删掉词汇再谈迁移是本末倒置。
    所以改判为留着，并在这里写清楚为什么，免得下一个人再纠结一遍。
    """
    for rel in ("widgets/settings_row.py", "widgets/icon_label.py",
                "widgets/status_chip.py"):
        assert (ROOT / rel).exists(), (
            f"{rel} 被删了。它采用率是 0 没错，但那是**已决定保留**的状态："
            "它是 UP-097 迁移的目标词汇表，也被 widget_showcase 目视工具引用。"
            "要删请连同 UP-097 的处置一起重新拍板。"
        )


# --------------------------------------------------------------- UP-008


def test_up008_revert_rationale_is_still_recorded():
    """UP-008 的回退理由必须留在代码里。

    这条不是"守着一段注释"。R2 做了又回退，而回退的三条理由里有两条是
    **安全性**（音频设备初始化被搬到后台守护线程；pygame/SDL 与首帧渲染并发
    是记录在案的原生崩溃路径）。注释一删，下一个人看到"show 后冻 1.5 秒"
    的问题单，第一反应就是再去起一个预热线程——同一个坑踩第二次。
    """
    # ⚠ 第一版是"整个文件里有没有这几个词"，回退验证判它假绿：
    # 把开头那句 `# UP-008（本轮回退…）` 删掉之后，`UP-008` / `audio_manager` /
    # `pygame` / `预热` 在文件别处照样出现，判据全绿。
    # 改成：这几个关键点必须落在**同一段连续的 UP-008 注释块**里。
    lines = (ROOT / "main_widget.py").read_text(encoding="utf-8").splitlines()
    blocks, cur = [], []
    for line in lines:
        if line.lstrip().startswith("#"):
            cur.append(line)
        else:
            if cur:
                blocks.append("\n".join(cur))
            cur = []
    if cur:
        blocks.append("\n".join(cur))

    up008 = [b for b in blocks if "UP-008" in b]
    assert up008, "main_widget.py 里 UP-008 的回退说明整段没了"
    complete = [
        b for b in up008
        if all(k in b for k in ("回退", "audio_manager", "pygame", "预热"))
    ]
    assert complete, (
        "UP-008 的注释还在，但**回退理由被削掉了**。"
        "那三条理由（模块级 audio_manager → pygame.mixer.init()、"
        "pygame/SDL 与首帧渲染并发是记录在案的崩溃路径、show 前只剩 80ms 余量）"
        "是防止下一个人再起一次预热线程的唯一屏障。缺的关键点见上面的断言条件。"
    )


def test_the_blocker_of_up008_is_still_where_the_comment_says():
    """回退理由指的那行代码还在不在——注释指错地方比没有注释更坏。

    R8d 的教训：文档写的判据和代码里的判据可以是两回事。
    """
    src = (ROOT / "gsi_handler_kills.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    module_level = [
        n for n in tree.body
        if isinstance(n, ast.Assign)
        and any(isinstance(t, ast.Name) and t.id == "audio_manager" for t in n.targets)
    ]
    assert module_level, (
        "gsi_handler_kills.py 里模块级的 `audio_manager = get_runtime_audio_manager()` "
        "不见了。如果是**有意改成惰性初始化**，那 UP-008 的阻塞点就消失了，"
        "请回 02_问题清单.md 重新评估它，并更新 main_widget.py 里的回退说明。"
    )

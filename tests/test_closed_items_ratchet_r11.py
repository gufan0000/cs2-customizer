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
GENERATE_STYLESHEET_MAX_LINES = 1541


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
HANDROLLED_CARD_MAX = 45

_SETOBJECTNAME_CARD = re.compile(r"""setObjectName\(\s*["']card["']\s*\)""")


def _handrolled_card_sites() -> dict[str, int]:
    """统计 `pages/` 下把控件 objectName 直接设成 "card" 的处数。

    口径要和 `scripts/component_adoption.py` 对得上——两处数不一样的话，
    "45"这个数字就没有意义了（R8d 的教训：文档说的判据和代码里的判据
    可以是两回事，对着文档推理会推错）。
    """
    out = {}
    for path in sorted((ROOT / "pages").glob("*.py")):
        n = len(_SETOBJECTNAME_CARD.findall(path.read_text(encoding="utf-8")))
        if n:
            out[path.name] = n
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

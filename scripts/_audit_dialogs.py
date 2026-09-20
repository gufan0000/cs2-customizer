# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""对话框清单 —— 审计能看见 `dialogs/` 的唯一入口（RN-672，2026-09-20）。

## 为什么要有这个文件

排版审计与挤压审计遍历的都是 `win.pages`。**对话框一个都不在里面** ——
`dialogs/` 下 8 个 `QDialog`、3000 多行界面，从建仓起没有任何一条排版判据看过，
而报告年年写着「覆盖面 27/27 个页面（全覆盖）」。

⭐⭐⭐ **「全覆盖」的分母是页面，而界面不只有页面。**
这与 UP-096（页面轴少 5 页）、UP-100（尺寸轴少一档）、RN-666（`--tabs`×`--whole`
的乘积）是同一个形状的第四次：**判据的世界由它遍历的那个容器定义，
容器之外的东西不是"绿"，是"不在"。**

## 三条纪律

1. ⛔ **绝不 `exec()`**。模态对话框在无人值守的进程里是**卡死不是失败**
   （`kill_icon_workshop.py` 的模块头就写着这条）。一律 `show()` +
   `WA_DontShowOnScreen`：参与布局、拿真实字体度量，但永不映射到屏幕（§3 不打扰前台）。
2. ⛔ **样本参数不许抄产品里的数据**。`AddURLDialog` 的「支持平台」页要一个
   真的 `url_resolver` —— 在这里手抄一份平台清单，产品加了新平台它不会跟着变，
   而审计会一直对着一份过期样本报绿（RN-005 那一族）。所以样本一律**从产品那边取**。
3. ⭐ **样本要让所有状态同屏**。只给一个平台、一个组，撑不开的那一格就永远不会被量到；
   实测本模块第一版给 `AddURLDialog` 传 `player=None`，「支持平台」页退化成 1 条，
   而真实是 6~7 条 —— 那一页的「复制」按钮文案被裁，**就藏在被样本削掉的那几条里**。

## 新增一个对话框时

把它加进下面的 `DIALOGS`。⛔ 别忘了 —— `tests/test_the_dialogs_are_all_audited.py`
会拿 `dialogs/` 里真实存在的 `QDialog` 子类跟这张表对账，漏登记直接红。
⭐ 那条判据存在的理由就是本文件的开头那一段：**清单类的东西一定会漏登记，
而漏掉的那一个从此隐形。**
"""
from __future__ import annotations

import os
import tempfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable, Iterator

#: `dialogs/` 目录。清单对账与样本构造都以它为准。
DIALOGS_DIR = Path(__file__).resolve().parent.parent / "dialogs"

#: 样本素材落在这里（进程级临时目录，不碰用户数据、不留在仓库里）。
_SAMPLE_DIR: Path | None = None


def _sample_dir() -> Path:
    global _SAMPLE_DIR
    if _SAMPLE_DIR is None:
        _SAMPLE_DIR = Path(tempfile.mkdtemp(prefix="cs2customizer_dialog_audit_"))
    return _SAMPLE_DIR


def _sample_png(name: str, size: int = 64) -> str:
    """给击杀图标导入向导一张**真图**（它会真的解码，给假路径直接抛异常）。"""
    from PIL import Image

    path = _sample_dir() / name
    if not path.is_file():
        Image.new("RGBA", (size, size), (200, 40, 40, 255)).save(path)
    return str(path)


def _sample_groups():
    """资源导入确认框的样本：两组「认不出」的素材。

    ⭐ 形状照 `core.resource_identify.Group` 的真定义构造，不自己捏字典 ——
    对话框是按 `Group.guesses` / `common_dir` 渲染证据行的，字典少一个字段
    就会在审计里走进另一条分支，量的就不是用户看到的那一版。
    """
    from core.resource_identify import UNSURE, Group, Guess

    return [
        Group(
            paths=[f"AK47/burst/{i}.wav" for i in range(1, 13)],
            shape="dir2/audio",
            guesses=[Guess("gun_sounds", "枪声替换", UNSURE,
                           ["这 12 个文件都在 `AK47/` 下，分成 3 个子目录",
                            "全是 .wav，采样率一致"])],
            common_dir="AK47",
        ),
        Group(
            paths=[f"icons/{i}.png" for i in range(1, 6)],
            shape="dir1/image",
            guesses=[Guess("kill_icons", "击杀图标", UNSURE,
                           ["5 个 PNG，命名 1~5，符合击杀等级的形状"])],
            common_dir="icons",
        ),
    ]


class _SamplePlayer:
    """`AddURLDialog` 只从 player 上取 `url_resolver`（用来列支持的平台）。

    ⭐ 用**真的** `MusicURLResolver`，不手抄平台清单 —— 见模块头第 2 条。
    它的构造只读一个缓存 json，不联网；缓存目录指向临时目录。
    """

    def __init__(self):
        self.url_resolver = None
        try:
            from url_resolver import MusicURLResolver

            cache = _sample_dir() / "url_cache"
            os.makedirs(cache, exist_ok=True)
            self.url_resolver = MusicURLResolver(str(cache))
        except Exception:
            # 拿不到就拿不到 —— 对话框自己有降级分支。
            # ⛔ 但**不能假装拿到了**：那一页会缩成 1 条样本，见模块头第 3 条。
            self.url_resolver = None


@dataclass(frozen=True)
class DialogSpec:
    """一个对话框在审计里的身份。"""

    #: 报告里用的短名（也是判据里点名的那个键）。
    key: str
    #: 类名，用来跟 `dialogs/` 里真实存在的类对账。
    cls_name: str
    #: 构造函数。入参是父窗口（真 MainWindow），返回一个**没有 exec 过**的对话框。
    build: Callable[[object], object]
    #: 这个样本代表什么场景。⭐ 写出来是为了下一个人能判断它还具不具代表性。
    sample: str
    #: 它住在哪个模块文件（相对 `dialogs/`）。**用来判「这个检出里到底有没有它」。**
    module: str = ""

    @property
    def path(self) -> Path:
        return DIALOGS_DIR / (self.module or f"{self.key}.py")

    @property
    def available(self) -> bool:
        """这个检出里有没有这个对话框。

        ⭐⭐⭐ 这一格是拿 RN-671 的教训**提前**补上的：开源版是功能子集，
        音乐链路整条被裁 ⇒ `dialogs/add_url_dialog.py` 在那边根本不存在。
        一份「8 个对话框」的清单照搬过去，会让两支审计当场报「建不起来」、
        让对账判据报「清单点名了一个不存在的类」—— 而那既不是缺陷也不是腐烂，
        是**这个仓里没有这件东西**。
        ⚠ 同 RN-671：修了断点那一处，不等于修了同族的第二处（清单就是第二处）。
        """
        return self.path.is_file()


def _build_onboarding(parent):
    from dialogs.onboarding_dialog import OnboardingDialog

    return OnboardingDialog(parent)


def _build_resource_import_decision(parent):
    from dialogs.resource_import_decision_dialog import ResourceImportDecisionDialog

    return ResourceImportDecisionDialog(
        _sample_groups(), parent=parent, default_style_name="社区包·突击步枪")


def _build_kill_icon_workshop(parent):
    from dialogs.kill_icon_workshop import KillIconWorkshop

    return KillIconWorkshop("classic", parent=parent)


def _build_kill_icon_import_wizard(parent):
    from dialogs.kill_icon_import_wizard import KillIconImportWizard

    return KillIconImportWizard(_sample_png("3.png"), parent=parent)


def _build_sprite_sheet_maker(parent):
    from dialogs.sprite_sheet_maker import SpriteSheetMaker

    return SpriteSheetMaker(parent)


def _build_style_creator(parent):
    from dialogs.style_creator_dialog import StyleCreatorDialog

    return StyleCreatorDialog("kill_sound", parent)


def _build_style_manager(parent):
    from dialogs.style_manager_dialog import StyleManagerDialog

    # ⚠ 第三个故意起个长名字（撑宽列表那一列）。
    #   ⛔ 别拿用户素材库里的真名字当样本 —— 这个文件会同步进**公开仓**。
    return StyleManagerDialog("kill_sound", "击杀音效",
                              ["经典", "一枪一个小朋友", "连杀播报·加长风格名"], parent)


def _build_add_url(parent):
    from dialogs.add_url_dialog import AddURLDialog

    return AddURLDialog(parent, _SamplePlayer())


#: ⚠ 顺序 = 报告里的顺序，按「用户多半先撞上哪个」排，不按字母。
DIALOGS: tuple[DialogSpec, ...] = (
    DialogSpec("onboarding", "OnboardingDialog", _build_onboarding,
               "第一次启动的引导，全新配置下的空状态", "onboarding_dialog.py"),
    DialogSpec("resource_import_decision", "ResourceImportDecisionDialog",
               _build_resource_import_decision,
               "导入一包认不出的素材：两组，各带证据行与下拉框",
               "resource_import_decision_dialog.py"),
    DialogSpec("kill_icon_workshop", "KillIconWorkshop", _build_kill_icon_workshop,
               "击杀图标素材工坊，默认风格、空素材库", "kill_icon_workshop.py"),
    DialogSpec("kill_icon_import_wizard", "KillIconImportWizard",
               _build_kill_icon_import_wizard,
               "拖一张 64×64 的 PNG 进来（文件名认得出等级）",
               "kill_icon_import_wizard.py"),
    DialogSpec("sprite_sheet_maker", "SpriteSheetMaker", _build_sprite_sheet_maker,
               "图集生成器，未选目录的初始态", "sprite_sheet_maker.py"),
    DialogSpec("style_creator", "StyleCreatorDialog", _build_style_creator,
               "新建击杀音效风格，未加文件的初始态", "style_creator_dialog.py"),
    DialogSpec("style_manager", "StyleManagerDialog", _build_style_manager,
               "管理三套已有风格（第三个是个长名字，用来撑宽列表那一列）",
               "style_manager_dialog.py"),
    # ⚠ 开源版没有这一个（音乐链路整条被裁）—— 见 `DialogSpec.available`。
    DialogSpec("add_url", "AddURLDialog", _build_add_url,
               "添加在线音乐，三个页签 + 真实平台清单（6~7 条）", "add_url_dialog.py"),
)


def available_dialogs() -> tuple[DialogSpec, ...]:
    """这个检出里**真的有**的那些。功能子集里缺的不算失败，只是不适用。"""
    return tuple(spec for spec in DIALOGS if spec.available)


def missing_dialogs() -> tuple[DialogSpec, ...]:
    """清单里有、这个检出里没有的。⭐ 报告要把它说出来，别让它变成静默少测。"""
    return tuple(spec for spec in DIALOGS if not spec.available)


def registered_keys() -> tuple[str, ...]:
    return tuple(spec.key for spec in DIALOGS)


def registered_classes() -> set[str]:
    """⚠ 只算**这个检出里有的**，否则功能子集里对账必红。"""
    return {spec.cls_name for spec in available_dialogs()}


def discover_dialog_classes() -> set[str]:
    """AST 扫 `dialogs/`，列出所有 `QDialog` 子类的类名。

    ⛔ 不用 `grep`：查「有没有 X」一律走 AST（CLAUDE.md §1 红线 2）。
    ⛔ 不 import：那会真的把 8 个模块连同它们的产品依赖全拉起来，
      而这个函数的调用方之一是一条**不该起 Qt** 的判据。
    """
    import ast

    found: set[str] = set()
    for path in sorted(DIALOGS_DIR.glob("*.py")):
        if path.name == "__init__.py":
            continue
        tree = ast.parse(path.read_text(encoding="utf-8"))
        for node in tree.body:
            if not isinstance(node, ast.ClassDef):
                continue
            for base in node.bases:
                name = base.attr if isinstance(base, ast.Attribute) else getattr(base, "id", "")
                if name == "QDialog":
                    found.add(node.name)
    return found


def build_all(parent, app) -> Iterator[tuple[DialogSpec, object, str]]:
    """逐个构造对话框，yield `(spec, dialog_or_None, 出错信息)`。

    ⛔ 构造失败**不吞**：吞掉就等于静默少测，而报告会写成"这一个没问题"。
    调用方负责 `close()` / `deleteLater()`（这里不收，因为判据要在外面量）。
    """
    from PySide6.QtCore import Qt

    for spec in available_dialogs():
        try:
            dlg = spec.build(parent)
        except Exception as exc:     # noqa: BLE001 —— 要的就是"什么都逮住并报出来"
            yield (spec, None, f"{type(exc).__name__}: {exc}")
            continue
        dlg.setAttribute(Qt.WA_DontShowOnScreen, True)
        dlg.show()
        for _ in range(3):
            app.processEvents()
        yield (spec, dlg, "")


def floor_of(dlg) -> tuple[int, int]:
    """对话框**自己声明**的最小尺寸（`setMinimumSize` 一类钉下来的地板）。"""
    size = dlg.minimumSize()
    return (size.width(), size.height())


def floor_verdict(dlg, budget: tuple[int, int]) -> str:
    """地板体检：声明的最小尺寸不许超过紧凑档窗口。返回空串 = 没问题。

    ## 为什么阈值正好是紧凑档窗口，不多不少

    产品自己承诺紧凑档可用（`gui_widget` 的紧凑分支把窗口**固定**成 860×640，
    最小尺寸也是它）。用户能把主窗开成 860×640，说明他的屏幕至少装得下
    「860×640 的客户区 + 一层窗框」。对话框是从这个窗口里开出来的，
    **它和主窗付的是同一层窗框** —— 于是窗框在两边约掉，条件干净地落成：

        对话框的最小尺寸 ≤ 860×640

    地板比这还大 ⇒ 在那台机器上**拖不小、也滚不动**，被屏幕切掉的那一条
    永远看不见。⭐ 这一格是前五条判据结构上看不见的：它们量的是
    「内容 vs 可用空间」，而这里坏在**控件自己声明的下限**上 ——
    内容再少也没用，地板钉在那儿。

    ⚠ 取等号是对的：地板正好 640 的对话框（`sprite_sheet_maker`）与主窗一样高，
    主窗装得下它就装得下。
    """
    fw, fh = floor_of(dlg)
    bw, bh = budget
    bad = []
    if fw > bw:
        bad.append(f"宽 {fw} > {bw}")
    if fh > bh:
        bad.append(f"高 {fh} > {bh}")
    if not bad:
        return ""
    return ("最小尺寸地板比紧凑档窗口还大（" + "，".join(bad)
            + "）—— 小屏上拖不小、也滚不动")

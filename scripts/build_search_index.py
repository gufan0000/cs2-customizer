# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""设置项级搜索索引生成器（S2，2026-08-10）。

**要解决的事**：顶栏搜索此前只有**页级**索引（27 页 / 365 个手工关键词）。
用户搜「观战静音」能跳到基础设置页，是因为跳转后 `_find_setting_row` 在
**已经建好的页面上**就地按文案找；而词表里没有的项——「保存FPS设置」
「按地图切换预设」这类——**连跳都跳不过去**，因为 `search()` 压根不返回结果。

本脚本把 27 个页面上**用户看得见的每一个设置项**收成 `core/search_index.json`，
随包发布，运行时零开销直接读。

---------------------------------------------------------------------------
为什么是"离线生成"而不是运行时收割
---------------------------------------------------------------------------
页面是懒加载的（`gui_widget.ensure_page_loaded`）。运行时要收全 27 页的控件树，
就得在启动时把 27 页全建一遍——实测建页基准在这个项目里是被专门优化过的
（`scripts/bench_page_build.py`、空闲预载只建 Top4），为了搜索索引把它推翻
不划算。离线生成把这份成本挪到构建期，运行时只多读一个 ~40KB 的 JSON。

---------------------------------------------------------------------------
为什么是"两条通道"而不是一条
---------------------------------------------------------------------------
两条通道各有一片**测量不到的盲区**，而且盲区正好互补——这是实测出来的，
不是设计出来的：

* **通道 A（离屏运行时）**：`WA_DontShowOnScreen` 真把页面建出来，遍历控件树。
  盲区 = 曾经是 6 个设备页。RN-005/RN-059 之后已全部纳入（中和条件见 `scripts/_audit_neutralize.py`）。它们构造时会注册全局热键 /
  起音频设备 / spawn 子进程，在脚本里建它们等于真的占设备、真的打扰前台。
  **这份安全名单我不放宽**，宁可让通道 B 去补。

* **通道 B（静态 AST）**：扫 `pages/*.py` 里 `QCheckBox("…")` 之类的字面量。
  盲区 = 用工厂/循环构建 UI 的页面，源码里没有字面量。
  实测有 **4 个页面静态收割为 0**：kill_sound / kill_voice / reload_sound /
  switch_weapon —— 纯 AST 会把这四页整片漏掉，而且是**静默**漏掉。

而通道 A 建不了的那 6 页（music / voice_output / flash …），恰好是静态收割
**产出最高**的几页（各 23~25 条）。所以合起来才是完整的。

顺带一个副产品，是 QA-018 那条教训的直接应用：两条独立通道都覆盖到的页面上，
**它们的收割结果可以互相验证**。`--cross-check` 会报出只有单边看到的项，
一条通道的自洽不是证据。

---------------------------------------------------------------------------
噪声过滤：为什么是"按出现页数"而不是"按我拍脑袋的黑名单"
---------------------------------------------------------------------------
原始收割里混着大量非设置项的文案：「保存」「使用说明」「⚪ 检测中...」
「⚠️ Windows Magnification API不可用\\n放大功能已禁用…」。
主过滤器是 **文档频率**：一条文案出现在 ≥ `MAX_PAGES_PER_TEXT` 个页面上，
就按"通用词"丢掉——这是**量出来的通用**，不是我猜的通用。
硬编码黑名单只留极少数几条文档频率抓不到的（比如只出现在一页上的「使用说明」）。

用法:
    python scripts/build_search_index.py              # 生成/更新 JSON
    python scripts/build_search_index.py --check      # 只校验是否与代码同步(CI)
    python scripts/build_search_index.py --cross-check  # 打印两通道差异
    python scripts/build_search_index.py --stats      # 打印收割统计
退出码: 0=成功/已同步, 1=--check 下不同步, 2=环境不满足。

⚠ 退出码是这个脚本**唯一**的门禁信号，所以它的交付路径本身也要当判据看待。
2026-08-14 实测过一次"该报 1 却报 0"：`--check` 把不同步一字不差地打印出来了，
进程却按 0 退出——门禁静默放行。原因不在 `_emit` 的 return，而在它后面的收尾：
`teardown()` 走的是**产品自己的**窗口关闭链路，那条路上有两处会替脚本决定退出码
（15s 退出看门狗的 `os._exit(0)`、信号处理器兜底的 `sys.exit(0)`）。
详见 `_teardown_guarded` / `_hard_exit`。回归判据在
`tests/test_search_index_check_exit_code.py`（含进程级的真退出码断言）。
"""
from __future__ import annotations

import argparse
import ast
import json
import os
import re
import sys
import threading
from collections import defaultdict
from pathlib import Path

# 与 layout_overflow_audit 同款隔离：绝不碰用户真实配置/日志/游戏目录
os.environ.setdefault("CS2C_SAFE_MODE_ACTIVE", "1")
# RN-032：配置目录走共享工装。这条最要紧 —— 索引是**要随发布包出厂**的生成物，
# 页面控件文案会随配置变，拿开发机配置生成等于把个人状态烙进产品。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from _pristine_config import use_pristine_config_dir  # noqa: E402

_tmp = use_pristine_config_dir("cs2customizer_search_index")

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))
sys.path.insert(0, str(ROOT / "scripts"))
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

OUT_PATH = ROOT / "core" / "search_index.json"

# 退出码。数字散在代码里读不出意图，尤其是 1 和 2 的分工——
# 1 = "索引真的漂了，去重跑生成器"，2 = "这台机器根本没法给结论"。
# CI 把它们混成"非 0 即失败"也不会错，但排障时区别很大。
EXIT_OK = 0
EXIT_DRIFT = 1
EXIT_ENV = 2

# 收尾清理的兜底超时（秒）。产品自己那条退出看门狗是 15s，这条要明显宽于它，
# 否则正常清理会被我们误杀，看起来就像"清理总是超时"。
TEARDOWN_TIMEOUT_SEC = 60.0


class EnvironmentUnavailable(RuntimeError):
    """环境不满足（→ 退出码 2）。

    与"索引不同步"（退出码 1）**必须**分开：没装 PySide6 / 起不来 QApplication
    时，脚本对"索引同不同步"是**没有结论**的。原先这两种情况都以 traceback
    退出码 1 收场，CI 上看起来就跟真漂移一个样，会把人往"去重跑生成器"上引。
    """


# 名单取产品那一份（唯一真相源），这里不另抄——抄出来的副本不会跟着产品变。
# RN-005：中和表全仓唯一一份（这段以前在 5 支脚本里各写一遍，内容 1~3 项不等，
# 后果是 flash / viewmodel / voice_output 三页被全部 5 支跳过 —— 零覆盖）。
from _audit_neutralize import (  # noqa: E402
    apply as neutralize_apply,
    enable_audit_mode,
    unsafe_pages,
)
# RN-511：本脚本的退出码在 Qt/pygame 退出期**被实测洗掉过**（0xC0000409），
# 所以裁定要走和几支审计同一条通道：自己打一行机器可读的裁定，CI 读那一行。
from _audit_verdict import announce  # noqa: E402

enable_audit_mode()   # 必须在 import 产品模块之前

# ---------------- 噪声过滤 ----------------

# 一条文案出现在这么多个页面上就算"通用词"，丢掉。
# 4 是量出来的：3 会误伤「音量」这种真设置项（basic/gun_sound/music 三页都有），
# 5 会放进「保存」。
MAX_PAGES_PER_TEXT = 4

MIN_LEN, MAX_LEN = 2, 24

# 文档频率抓不到的（只出现在一两页，但确实不是设置项）
BLACKLIST = {
    "使用说明", "说明", "提示", "注意", "详情", "更多", "帮助", "教程",
    "确定", "取消", "关闭", "返回", "下一步", "上一步", "完成", "跳过",
    "浏览", "选择文件", "选择目录", "打开文件夹", "打开目录",
    "全选", "反选", "清空", "清除", "刷新", "重试", "开始", "暂停", "继续",
    "未设置", "未配置", "加载中", "检测中", "处理中", "已完成", "无",
    "状态", "操作", "名称", "类型", "路径", "备注",
    # 通用动作按钮：搜到它们等于没搜到（"保存"在 20 个页面上都对）
    "保存", "应用", "重置", "删除", "添加", "编辑", "新建", "修改", "设置",
    "测试", "试听", "上移", "下移", "复制", "粘贴", "确认", "提交",
}

# 以这些符号开头的多半是状态条/警告条文案，不是设置项
_LEAD_SYMBOL = re.compile(r"^[\W_]*[⚠⚪⚫✅❌❗️🔴🟢🟡🔵●○◆◇★☆✓✗•·※→←↑↓]")
_SENTENCE = re.compile(r"[，。！？；、,;]|\.{2,}|…")
_CJK = re.compile(r"[一-鿿]")
_WORD = re.compile(r"[一-鿿A-Za-z0-9]")

# ⚠ 运行时状态文案，**必须**挡掉。实测原始收割里有 99 条长这样：
#   「GSI · 未运行」「音频 · 需检查13」「分类 · 手枪 10/10」「已配置 · 37」
# 它们是状态条在**收割那一刻**的快照。进了索引就是一份永远过期的数据——
# 用户搜「未运行」跳到基础设置，那儿写的可能是「已运行」。
# 判据是中点：产品里的状态复合文案统一用 " · " 拼，真实设置项名字里没有中点。
_STATUS_COMPOSITE = re.compile(r"[·・]")
# 同一个病的另一种写法：「当前样式：十字」「当前权限：普通用户」「任务历史: 0 条」。
# 冒号**后面还有内容**就是"标签 + 收割那一刻的值"，判据同上。
# ⚠ 尾部冒号不算（normalize 前面已经把它 rstrip 掉了）：「当前风格：」是个稳定的
# 字段名，值在另一个控件里，那条该留。
_STATUS_LABELED = re.compile(r"[:：]\s*\S")
# 取值显示而非设置项名：「0.3秒」「150ms」「30 FPS」「85%」
_VALUE_ONLY = re.compile(r"^\d+(?:[.,]\d+)?\s*(?:秒|毫秒|ms|s|fps|%|px|倍|个|次|帧)?$", re.I)


def normalize(text: str) -> str:
    """把控件文案收敛成索引词；返回空串表示这条不要。"""
    s = str(text or "").strip()
    if not s or "\n" in s or "\r" in s:
        return ""
    # 状态条/警告条文案：这道防线在 keep_raw 里也有一份，但必须在这里再挡一次。
    # 否则单独调 normalize 时「⚠️ 出错了」会被下面那句"去掉首部装饰符号"洗成
    # 「出错了」直接放行 —— 防线分散在两个函数里，就等于哪个函数都不完整。
    if _LEAD_SYMBOL.match(s):
        return ""
    # 去掉 Qt 助记符与尾部冒号/箭头
    s = s.replace("&&", "\x00").replace("&", "").replace("\x00", "&")
    s = s.strip().rstrip(":：>》 ").strip()
    # 去掉首部装饰符号（"  基础设置" 这类导航按钮的缩进也在这儿被吃掉）
    s = re.sub(r"^[\s\W_]*(?=[一-鿿A-Za-z0-9])", "", s)
    s = s.strip()
    if not s:
        return ""
    if _SENTENCE.search(s):
        return ""
    if _STATUS_COMPOSITE.search(s):
        return ""
    if _STATUS_LABELED.search(s):
        return ""
    if _VALUE_ONLY.match(s):
        return ""
    if not _WORD.search(s):
        return ""
    if not (MIN_LEN <= len(s) <= MAX_LEN):
        return ""
    if s in BLACKLIST:
        return ""
    # 纯数字/纯符号型（"1.00"、"5"、"（点击设置）"）
    if not _CJK.search(s) and not re.search(r"[A-Za-z]{2,}", s):
        return ""
    return s


def keep_raw(text: str) -> bool:
    """收割阶段的粗筛：明显的状态条文案直接不进候选池。"""
    s = str(text or "").strip()
    if not s or len(s) > 60:
        return False
    if _LEAD_SYMBOL.match(s):
        return False
    return True


# ---------------- 通道 A：离屏运行时收割 ----------------


def harvest_runtime(include_unsafe: bool = False, verbose: bool = True):
    """真把页面建出来遍历控件树。返回 (items, covered_pages, skipped_pages, page_names)。"""
    # 环境类失败在这里就归口成 EnvironmentUnavailable（退出码 2）。
    # 让它以裸 ImportError 冒出去的话，进程按 1 退出，与"索引不同步"撞码。
    try:
        from PySide6.QtWidgets import QApplication
    except ImportError as exc:
        raise EnvironmentUnavailable(f"PySide6 不可用：{exc}") from exc

    try:
        app = QApplication.instance() or QApplication(sys.argv[:1])
    except Exception as exc:
        raise EnvironmentUnavailable(f"QApplication 建不起来（无显示环境？）：{exc}") from exc

    from config import config

    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes(verbose=verbose)
    config.ui_expert_mode = True          # 专家页也要进索引
    config.compact_mode = False

    import gui_widget

    # MainWindow 启动 1.5s 后会拉一条线程做源码自动快照（5700+ 文件全量复制）。
    # 它落在隔离后的临时配置目录里、不碰用户数据，但对本脚本纯属白烧几分钟 I/O。
    # 只替换本进程里的引用，产品代码一个字不动。
    gui_widget.run_startup_source_backup = lambda *a, **k: None

    from PySide6.QtCore import Qt
    from PySide6.QtWidgets import (
        QCheckBox,
        QGroupBox,
        QLabel,
        QPushButton,
        QRadioButton,
        QTabWidget,
        QWidget,
    )

    from widgets.settings_card import SettingsCard

    win = gui_widget.MainWindow(auto_background_preload=False)
    win.setAttribute(Qt.WA_DontShowOnScreen, True)   # 参与布局但永不映射到屏幕
    win.show()
    app.processEvents()

    page_names = dict(win._page_names)
    page_ids = list(page_names.keys())

    skipped = []
    if not include_unsafe:
        neutralize_apply(config, page_ids)
        skipped = sorted(p for p in page_ids if p in unsafe_pages())
        page_ids = [p for p in page_ids if p not in skipped]

    def card_title_of(widget, page):
        """这个控件落在哪张卡片里。

        ⚠ 原来只认 `SettingsCard`，实测 369 条里 **222 条 card 字段是空的**——
        因为全仓有两套卡片：`SettingsCard`(16 页在用) 和各页手写的
        `_create_card()`(准心设置 28 项全靠它，card 一条都收不到)。
        两套的**共同不变量**是 QSS 选择器：卡片容器 objectName == "card"，
        标题 QLabel objectName == "cardTitle"。按不变量认，而不是按类名认。
        """
        node = widget.parentWidget()
        while node is not None and node is not page:
            if isinstance(node, SettingsCard):
                label = getattr(node, "title_label", None)
                try:
                    return normalize(label.text()) if label is not None else ""
                except Exception:
                    return ""
            try:
                if node.objectName() == "card":
                    # 取最近的那个 cardTitle；findChildren 是深度优先按构造序，
                    # 卡片自己的标题总是先于内嵌子卡的标题被建出来。
                    for lab in node.findChildren(QLabel):
                        if lab.objectName() == "cardTitle":
                            return normalize(lab.text())
                    return ""
            except Exception:
                return ""
            node = node.parentWidget()
        return ""

    def tab_of(widget, page):
        """这个控件落在哪个页签里（没有页签返回空串）。用于跳转时先切页签。"""
        for tw in page.findChildren(QTabWidget):
            for i in range(tw.count()):
                w = tw.widget(i)
                if w is not None and (w is widget or w.isAncestorOf(widget)):
                    return normalize(tw.tabText(i))
        return ""

    items = []
    covered = []
    for pid in page_ids:
        try:
            win.show_page(pid, animated=False)
            app.processEvents()
            page = win.pages.get(pid)
            if page is None:
                continue
            covered.append(pid)

            # 页签本身也是可搜的落点（"C4"、"手雷" 这些页签名）
            for tw in page.findChildren(QTabWidget):
                for i in range(tw.count()):
                    text = normalize(tw.tabText(i))
                    if text:
                        items.append({"page": pid, "text": text, "card": "",
                                      "tab": text, "kind": "tab", "src": "runtime"})

            for widget in page.findChildren(QWidget):
                if isinstance(widget, QCheckBox):
                    kind = "check"
                elif isinstance(widget, QRadioButton):
                    kind = "radio"
                elif isinstance(widget, QGroupBox):
                    kind = "group"
                elif isinstance(widget, QPushButton):
                    kind = "button"
                elif isinstance(widget, QLabel):
                    kind = "label"
                else:
                    continue
                try:
                    raw = widget.title() if isinstance(widget, QGroupBox) else widget.text()
                except Exception:
                    continue
                if not keep_raw(raw):
                    continue
                obj = widget.objectName()
                if obj in ("titleLabel", "statusLabel", "pageTitle",
                           "pageSubtitle", "navButton"):
                    continue
                text = normalize(raw)
                if not text:
                    continue
                if obj == "cardTitle":
                    # 卡片标题**要**进索引。原来这里跟着页头一起跳过，理由是
                    # "由页级+卡片级定位负责"——实测站不住：用户搜「CFG 同步」
                    # 「准心快速回正」这些卡片名，结果面板是**空的**，
                    # 连跳都跳不过去（去重键是 (page,text)，跟卡内控件不会撞）。
                    items.append({"page": pid, "text": text, "card": text,
                                  "tab": tab_of(widget, page), "kind": "card",
                                  "src": "runtime"})
                    continue
                items.append({
                    "page": pid, "text": text, "card": card_title_of(widget, page),
                    "tab": tab_of(widget, page), "kind": kind, "src": "runtime",
                })
        except Exception as exc:
            if verbose:
                print(f"  !! 页面 {pid} 收割失败: {exc}")

    # ⚠ 这里**不关窗口**。关闭要走 closeEvent → 停线程 / 落配置 / 拆托盘，
    # 实测会把进程挂住，于是后面的静态收割和报告一个字都打不出来
    # （表现是"脚本跑完了但没有输出"，很像成功，其实是卡死）。
    # 与 layout_overflow_audit 同款：先把话说完，收尾放在 main() 的最后。
    return items, covered, skipped, page_names, win, app


# ---------------- 通道 B：静态 AST 收割 ----------------

_AST_WANTED = {"QCheckBox", "QRadioButton", "QGroupBox", "QLabel", "QPushButton",
               "SettingsCard"}
_AST_KIND = {
    "QCheckBox": "check", "QRadioButton": "radio", "QGroupBox": "group",
    "QLabel": "label", "QPushButton": "button", "SettingsCard": "card",
}
# 这些构造只取**第一个**位置参数：SettingsCard(title, description) 的第二个参数是
# 一整句说明文案。多数说明带句号会被 _SENTENCE 挡掉，但不能指望这个——
# 一句没标点的说明混进索引就是一条搜不动也跳不准的垃圾。
_AST_FIRST_ARG_ONLY = {"SettingsCard"}


def _ast_ctor_name(fn) -> str:
    """把 AST 的调用目标归一成构造名。

    `SettingsCard.make(...)` 是全仓 65 处卡片的实际写法（`SettingsCard(...)`
    直接调用一次都没有），它在 AST 里是 Attribute(attr='make')——
    只看 `fn.attr` 会得到 'make'，什么都对不上。这就是局内视角页
    「准心快速回正」「CFG 同步」这些卡片名一条都没进索引的原因。
    """
    if isinstance(fn, ast.Name):
        return fn.id
    if isinstance(fn, ast.Attribute):
        if fn.attr == "make" and isinstance(fn.value, ast.Name):
            return fn.value.id          # SettingsCard.make → SettingsCard
        return fn.attr
    return ""


def _page_id_from_module(stem: str, page_names: dict) -> str:
    """pages/xxx_page.py → page_id。只认能对上导航表的，对不上的丢掉。"""
    cand = stem[:-5] if stem.endswith("_page") else stem
    return cand if cand in page_names else ""


def harvest_static(page_names: dict):
    """AST 扫 pages/*.py 的控件字面量。返回 (items, covered_pages)。"""
    items = []
    covered = set()
    for path in sorted((ROOT / "pages").glob("*.py")):
        pid = _page_id_from_module(path.stem, page_names)
        if not pid:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8"))
        except Exception:
            continue
        found = False
        for node in ast.walk(tree):
            if not isinstance(node, ast.Call):
                continue
            name = _ast_ctor_name(node.func)
            if name not in _AST_WANTED:
                continue
            positional = node.args[:1] if name in _AST_FIRST_ARG_ONLY else list(node.args)
            args = positional + [kw.value for kw in node.keywords
                                 if kw.arg in ("text", "title", "label")]
            for a in args:
                if not (isinstance(a, ast.Constant) and isinstance(a.value, str)):
                    continue
                if not keep_raw(a.value):
                    continue
                text = normalize(a.value)
                if not text:
                    continue
                kind = _AST_KIND[name]
                items.append({"page": pid, "text": text,
                              "card": text if kind == "card" else "", "tab": "",
                              "kind": kind, "src": "static"})
                found = True
        if found:
            covered.add(pid)
    return items, sorted(covered)


# ---------------- 合并 / 落盘 ----------------

# runtime 的 card/tab 信息比 static 全，同一条文案两边都有时以 runtime 为准
_SRC_RANK = {"runtime": 0, "static": 1}
# 同一页里同一条文案出现多次时，保留信息量最高的那种控件
_KIND_RANK = {"check": 0, "radio": 1, "tab": 2, "card": 3, "group": 4,
              "button": 5, "label": 6}


def merge(runtime_items, static_items, page_names, runtime_pages, static_pages, skipped):
    """按 (page, text) 去重合并，再按文档频率过滤通用词。"""
    by_key = {}
    for it in runtime_items + static_items:
        key = (it["page"], it["text"])
        old = by_key.get(key)
        if old is None:
            by_key[key] = it
            continue
        # 同一条：src 优先 runtime，其次控件类型信息量高的
        if (_SRC_RANK[it["src"]], _KIND_RANK[it["kind"]]) < \
           (_SRC_RANK[old["src"]], _KIND_RANK[old["kind"]]):
            by_key[key] = it

    # 文档频率：一条文案跨太多页 ⇒ 通用词，丢掉
    pages_per_text = defaultdict(set)
    for (pid, text) in by_key:
        pages_per_text[text].add(pid)
    generic = {t for t, ps in pages_per_text.items() if len(ps) >= MAX_PAGES_PER_TEXT}

    order = {pid: i for i, pid in enumerate(page_names)}
    kept = [it for key, it in by_key.items() if it["text"] not in generic]
    kept.sort(key=lambda it: (order.get(it["page"], 999), it["card"], it["text"]))

    return {
        "schema": 1,
        # ⚠ 这里**不能有时间戳/随机值**：`--check` 靠"重新生成一遍再逐字节比"
        # 来判断索引有没有和代码漂移，任何非确定性字段都会让那条判据永远红。
        "generated_by": "scripts/build_search_index.py",
        "pages": page_names,
        "coverage": {
            "runtime_pages": sorted(runtime_pages),
            "static_pages": sorted(static_pages),
            "runtime_skipped": sorted(skipped),
            "total_pages": len(page_names),
        },
        "generic_dropped": sorted(generic),
        "items": kept,
    }, generic


def dumps(payload) -> str:
    return json.dumps(payload, ensure_ascii=False, indent=1, sort_keys=False) + "\n"


def build(include_unsafe=False, verbose=True):
    rt_items, rt_pages, skipped, page_names, win, app = harvest_runtime(include_unsafe, verbose)
    st_items, st_pages = harvest_static(page_names)
    payload, generic = merge(rt_items, st_items, page_names, rt_pages, st_pages, skipped)
    return payload, rt_items, st_items, generic, (win, app)


def teardown(handles):
    win, app = handles
    # ⚠ 不能直接 win.close()：产品的 closeEvent 会按 `config.close_action` 走
    # "问一下"分支，在脚本里那就是**真的弹一个模态对话框然后无限等人点**。
    # 2026-08-14 现场抓到过：`--check` 的结论都打印完了，进程停在一个标题
    # 「关闭 CS2 Customizer 」的可见窗口上不退。CI 上这就是超时（连退出码都没有），
    # 本地则要人手点一下——两种都比"退出码错了"更难看出是脚本的问题。
    # 走不走这条分支取决于托盘图标建没建好，所以它是**间歇**的。
    # `_force_exit` 是产品自己给托盘菜单"退出程序"用的旁路，正好也是这里要的语义。
    try:
        win._force_exit = True
    except Exception:
        pass
    try:
        win.close()
        win.deleteLater()
        app.processEvents()
    except Exception:
        pass


def report(payload, rt_items, st_items, generic):
    cov = payload["coverage"]
    only_static = sorted(set(cov["static_pages"]) - set(cov["runtime_pages"]))
    only_runtime = sorted(set(cov["runtime_pages"]) - set(cov["static_pages"]))
    uncovered = sorted(set(payload["pages"]) - set(cov["runtime_pages"]) - set(cov["static_pages"]))
    print(f"页面 {cov['total_pages']} 个：运行时通道覆盖 {len(cov['runtime_pages'])}，"
          f"静态通道覆盖 {len(cov['static_pages'])}")
    print(f"  运行时跳过(不安全页，由静态通道兜)：{cov['runtime_skipped'] or '无'}")
    print(f"  仅静态看得见：{only_static or '无'}")
    print(f"  仅运行时看得见：{only_runtime or '无'}")
    print(f"  ⚠ 两条通道都没覆盖：{uncovered or '无'}")
    print(f"原始收割：runtime {len(rt_items)} 条 / static {len(st_items)} 条")
    print(f"按文档频率丢弃的通用词 {len(generic)} 条：{sorted(generic)[:12]}…")
    print(f"最终入库 {len(payload['items'])} 条")
    per_page = defaultdict(int)
    for it in payload["items"]:
        per_page[it["page"]] += 1
    zero = [p for p in payload["pages"] if per_page[p] == 0]
    print(f"每页条数中位 {sorted(per_page.values())[len(per_page) // 2] if per_page else 0}，"
          f"最多 {max(per_page.values()) if per_page else 0}")
    print(f"⚠ 项级索引为 0 的页：{zero or '无'}（这些页只能靠页级词表命中）")


def cross_check(rt_items, st_items, payload):
    """QA-018 的应用：两条通道都覆盖的页面上，互相验证收割结果。"""
    cov = payload["coverage"]
    both = sorted(set(cov["runtime_pages"]) & set(cov["static_pages"]))
    rt = defaultdict(set)
    st = defaultdict(set)
    for it in rt_items:
        rt[it["page"]].add(it["text"])
    for it in st_items:
        st[it["page"]].add(it["text"])
    print(f"\n两条通道都覆盖的页面 {len(both)} 个，逐页对拉：")
    tot_r = tot_s = 0
    for pid in both:
        only_r = rt[pid] - st[pid]
        only_s = st[pid] - rt[pid]
        tot_r += len(only_r)
        tot_s += len(only_s)
        if only_r or only_s:
            print(f"  {pid:<22} 仅运行时 {len(only_r):>3}  仅静态 {len(only_s):>3}")
    print(f"合计：仅运行时可见 {tot_r} 条（工厂/动态构建的控件，AST 看不到）")
    print(f"      仅静态可见 {tot_s} 条（构造时未挂载/条件分支里的控件）")
    print("⇒ 两边都有独占项 ⇒ 任何一条通道单干都会静默漏。这就是要两条的原因。")


def _flush_streams():
    for stream in (sys.stdout, sys.stderr):
        try:
            stream.flush()
        except Exception:
            pass


def _hard_exit(code: int):
    """带着 code 立刻结束进程。

    ⚠ 这里是 `os._exit` 而不是 `sys.exit`，理由和 `_teardown_guarded` 是同一个：
    解释器收尾阶段还要跑 Qt/pygame 的析构和残留的 daemon 线程，那里面就有会
    **改写退出码**的东西。退出码是本脚本唯一的门禁信号，不能交给收尾阶段投票。
    输出在 `_flush_streams` 里已经落干净，`os._exit` 不跑 atexit 也不会丢字。
    """
    _flush_streams()
    os._exit(code)


def _teardown_guarded(handles, code: int):
    """跑收尾清理，但**不让清理链路改写退出码**。

    `teardown()` 里那句 `win.close()` 走的是产品自己的退出链路，那条路上有两处
    会替脚本决定退出码，而且都赢 —— 它们比 `sys.exit(main())` 更晚或更硬：

    * `gui_widget._run_shutdown_steps` 装了 15s 硬超时看门狗，超时直接
      `os._exit(0)`（v2.2.1 为"关不掉挂死"加的，产品侧是对的）。它跑在 Timer
      线程里，一旦触发，`--check` 刚打印出来的不同步就被洗成 0。
    * `core/shutdown` 的信号处理器兜底是 `sys.exit(0)`。SystemExit **不是**
      Exception，`teardown()` 里的 `except Exception` 兜不住，它会一路穿出
      `main()`，于是 `sys.exit(main())` 压根没机会执行，进程按 0 退出。

    两处都是产品代码里正确的东西，不该为了一个构建脚本去动。所以在这里就地接管：
    清理期间把 `os._exit` 换成"带着我们的 code 退出"，SystemExit 单独吃掉。

    第三种走法是**根本不退出**——清理卡在某一步上（见 `teardown` 里那条模态
    对话框的注释）。对门禁来说"没有退出码"和"退出码错了"一样坏，所以这里再压
    一条自己的超时线：到点就带着 code 硬退。它比产品那条 15s 看门狗宽，
    正常清理轮不到它。
    """
    real_os_exit = os._exit

    def _exit_with_our_code(_status, _code=code, _real=real_os_exit):
        _flush_streams()
        _real(_code)

    def _timed_out():
        print(f"!! 收尾清理超过 {TEARDOWN_TIMEOUT_SEC:.0f}s 未结束，按既得结论退出（code={code}）")
        _flush_streams()
        real_os_exit(code)

    timer = threading.Timer(TEARDOWN_TIMEOUT_SEC, _timed_out)
    timer.daemon = True
    timer.start()

    os._exit = _exit_with_our_code
    try:
        teardown(handles)
    except SystemExit:
        pass          # 清理链路想退出可以，但退出码由我们说了算
    except Exception:
        pass
    finally:
        timer.cancel()
        os._exit = real_os_exit


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--check", action="store_true", help="只校验磁盘上的 JSON 是否与代码同步")
    ap.add_argument("--cross-check", action="store_true", help="打印两通道差异")
    ap.add_argument("--stats", action="store_true", help="打印收割统计")
    ap.add_argument("--include-unsafe", action="store_true", help="连不安全页也真建（会打扰前台）")
    args = ap.parse_args()

    quiet = args.check and not (args.stats or args.cross_check)
    try:
        payload, rt_items, st_items, generic, handles = build(args.include_unsafe, verbose=not quiet)
    except EnvironmentUnavailable as exc:
        print(f"!! 环境不满足，本次不给结论（这不是「索引不同步」）：{exc}")
        return EXIT_ENV
    code = _emit(args, payload, rt_items, st_items, generic)
    if args.check:
        # ⭐⭐⭐ **裁定行必须落在退出链路之前。** RN-511 实测：本进程的退出码
        #   在收尾阶段被洗成过 **-1073740791（0xC0000409）** —— 而那一刻
        #   「索引与代码同步。」早就打完了，`退出清理完成，共 18 步` 也打完了。
        #   ⇒ 只要裁定行在**判定那一刻**就落进日志，收尾阶段再怎么崩都改不了它；
        #     反过来，脚本要是**没走到判定**（环境不满足 / 中途死），日志里
        #     一行裁定都没有 ⇒ `verdict.ps1` 按失败处理。**洗不成假绿。**
        announce("search_index", code)
    _flush_streams()
    _teardown_guarded(handles, code)
    return code


def _emit(args, payload, rt_items, st_items, generic):
    text = dumps(payload)

    if args.stats or args.cross_check or not args.check:
        report(payload, rt_items, st_items, generic)
    if args.cross_check:
        cross_check(rt_items, st_items, payload)

    if args.check:
        if not OUT_PATH.exists():
            print(f"!! 索引文件不存在: {OUT_PATH}")
            return EXIT_DRIFT
        current = OUT_PATH.read_text(encoding="utf-8")
        if current != text:
            print("!! 索引与代码不同步：页面控件文案变了但没重新生成索引。")
            print("   跑一次 `python scripts/build_search_index.py` 修复。")
            cur = json.loads(current)
            old = {(i["page"], i["text"]) for i in cur.get("items", [])}
            new = {(i["page"], i["text"]) for i in payload["items"]}
            added, removed = sorted(new - old), sorted(old - new)
            print(f"   新增 {len(added)} 条，消失 {len(removed)} 条")
            for p, t in added[:8]:
                print(f"     + {p}: {t}")
            for p, t in removed[:8]:
                print(f"     - {p}: {t}")
            return EXIT_DRIFT
        print("索引与代码同步。")
        return EXIT_OK

    OUT_PATH.parent.mkdir(parents=True, exist_ok=True)
    OUT_PATH.write_text(text, encoding="utf-8")
    print(f"\n已写入 {OUT_PATH.relative_to(ROOT)}（{len(text.encode('utf-8')) / 1024:.1f} KB）")
    return EXIT_OK


if __name__ == "__main__":
    # 不用 `sys.exit(main())`：SystemExit 之后还有一整段解释器收尾，
    # 那段里有能把退出码改掉的东西（见 _hard_exit）。
    _hard_exit(main())

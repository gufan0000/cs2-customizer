# -*- coding: utf-8 -*-
"""R8d 前置度量：焦点错位到底是页面的错，还是判据的错（UP-077）。

`scripts/tab_order_audit.py` 报 crosshair 7 / gun_sound 12 / music 16 /
voice_output 17 处错位，但它的输出是
`链上=QRadioButton(QRadioButton)  阅读序=QRadioButton(QRadioButton)`
——**两边一模一样，照着它没法修**，甚至没法判断那是不是真缺陷。

本探针把每一处错位的**可识别身份**（文案 / 父卡片 / 窗口坐标）打出来，
另外顺手验两件事：

1. 阅读序用的是 `pos.y() // 24`。那是**分桶不是容差**：y=47 与 y=48
   只差 1px 却会掉进不同的桶，而 y=0 与 y=23 差 23px 反而同桶。
   这里并排给出「分桶版」与「真行带聚类版」两种阅读序，看结论会不会变。
2. 错位是按**下标逐位比对**的：一个控件插错位置，会让它之后的全部计为错位。
   这里另外报「相邻同行互换」有多少——那类严格说不影响可用性。

隔离：配置/日志都指向临时目录（这个坑我踩过 4 次）。
"""
from __future__ import annotations

import os
import sys
import tempfile
from pathlib import Path

os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

_tmp = Path(tempfile.gettempdir()) / "fanpai_probe_r8d"
(_tmp / "config").mkdir(parents=True, exist_ok=True)
(_tmp / "logs").mkdir(parents=True, exist_ok=True)
os.environ.setdefault("FANPAI_CONFIG_DIR", str(_tmp / "config"))
os.environ.setdefault("FANPAI_LOG_DIR", str(_tmp / "logs"))
os.environ.setdefault("FANPAI_SAFE_MODE_ACTIVE", "1")

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))
sys.stdout.reconfigure(encoding="utf-8")

from PySide6.QtCore import Qt  # noqa: E402
from PySide6.QtWidgets import QApplication, QWidget  # noqa: E402

PAGES = {
    "crosshair": ("pages.crosshair_page", "CrosshairPage"),
    "gun_sound": ("pages.gun_sound_page", "GunSoundPage"),
    "music": ("pages.music_page", "MusicPage"),
    "voice_output": ("pages.voice_output_page", "VoiceOutputPage"),
    "kill_sound": ("pages.kill_sound_page", "KillSoundPage"),
}

ROW_TOLERANCE = 24


def focusable_chain(root: QWidget):
    seen = []
    w = root.nextInFocusChain()
    guard = 0
    while w is not None and w is not root and guard < 4000:
        guard += 1
        if w.isVisibleTo(root) and w.focusPolicy() & Qt.TabFocus and root.isAncestorOf(w):
            seen.append(w)
        w = w.nextInFocusChain()
    return seen


def _pos(w):
    p = w.mapTo(w.window(), w.rect().topLeft())
    return p.x(), p.y()


def order_bucketed(widgets):
    """现行判据：y 整除分桶。"""
    return sorted(widgets, key=lambda w: (_pos(w)[1] // ROW_TOLERANCE, _pos(w)[0]))


def order_clustered(widgets):
    """真·行带聚类：按 y 排序后，与**当前行基线**差值在容差内就算同一行。

    与分桶的区别：行带的边界跟着内容走，不是钉在 24 的整数倍上。
    """
    by_y = sorted(widgets, key=lambda w: (_pos(w)[1], _pos(w)[0]))
    rows, cur, base = [], [], None
    for w in by_y:
        y = _pos(w)[1]
        if base is None or y - base <= ROW_TOLERANCE:
            if base is None:
                base = y
            cur.append(w)
        else:
            rows.append(cur)
            cur, base = [w], y
    if cur:
        rows.append(cur)
    out = []
    for row in rows:
        out.extend(sorted(row, key=lambda w: _pos(w)[0]))
    return out


#: 「块」= 读的时候会被当成一个整体、读完再读下一个的东西。
BLOCK_NAMES = {"card", "settingsCard", "pageActionBar"}
BLOCK_TYPES = {"SettingsCard", "PageActionBar", "QScrollArea", "QTabWidget"}


def is_block(w) -> bool:
    return w.objectName() in BLOCK_NAMES or type(w).__name__ in BLOCK_TYPES


def _outermost_block_under(w, container):
    """w 在 container 之内所属的**最外层**块（没有则 None）。"""
    found = None
    p = w.parentWidget()
    while p is not None and p is not container:
        if is_block(p):
            found = p
        p = p.parentWidget()
    return found


def _pos_in(w, container):
    p = w.mapTo(container, w.rect().topLeft())
    return p.x(), p.y()


def _container_of(w, root):
    """兼容旧签名：只用于 describe() 里找卡片标题。"""
    p = w.parentWidget()
    while p is not None and p is not root:
        if is_block(p):
            return p
        p = p.parentWidget()
    return root


def _order_rows(items, container):
    """把一组东西按「同行 + 从左到右」排（坐标相对 container）。

    「同行」判据是**矩形垂直重叠**，不是固定像素容差。
    固定容差有两个毛病：① 边界脆——voice_output 的主音量行与模式行正好差
    24px（= 原容差），于是被并成一行、再按 x 排就把顺序排反了，而页面是对的；
    ② 不随字号缩放——1.25 档下行距变大，同一个 24px 会突然从"同行"变"跨行"。
    重叠判据自带缩放不变性：控件长高了，行距也长高了。
    """
    def band(w):
        x, y = _pos_in(w, container)
        return x, y, y + max(1, w.height())

    by_y = sorted(items, key=lambda w: (band(w)[1], band(w)[0]))
    rows, cur, cur_bottom = [], [], None
    for w in by_y:
        _x, top, bottom = band(w)
        if cur and top >= cur_bottom:
            rows.append(cur)
            cur, cur_bottom = [w], bottom
        else:
            cur.append(w)
            cur_bottom = bottom if cur_bottom is None else max(cur_bottom, bottom)
    if cur:
        rows.append(cur)

    out = []
    for row in rows:
        out.extend(sorted(row, key=lambda w: band(w)[0]))
    return out


def order_hierarchical(widgets, container):
    """**递归**的阅读序：块之间按 (行带, x)，块内部再递归同样的规则。

    现行判据缺的就是这一层，而且缺了会同时造出两类假错位：

    1. **并排卡片**——准心页两张卡左右并排，右卡的单选比左卡高 25px，
       平铺排序就把**整张右卡排到左卡前面**；而 Tab 链走的是「读完左卡再读右卡」，
       那才是对的。7 处错位全是这么来的。
    2. **滚动区内外**——gun_sound 的动作条在滚动区**外**（y=838），
       滚动区**内**的内容绝对坐标能到 y=1045（早就滚出视口了）。
       拿这两个 y 直接比大小没有意义。滚动区必须当成一个块，
       它整体占据视口那个位置，内部再按自己的内容坐标排。

    所以块 = 卡片 / 动作条 / **滚动区** / **页签**。
    """
    groups = {}
    for w in widgets:
        block = _outermost_block_under(w, container)
        # 不在任何块里的控件**各自成组**：它们散落在各处，
        # 并成一个"位于 (0,0) 的容器"会让它们整体排到最前面
        # （music / voice_output 各 6 处的假错位就是这么来的）。
        groups.setdefault(block if block is not None else w, []).append(w)

    out = []
    for key in _order_rows(list(groups), container):
        members = groups[key]
        inner = [m for m in members if m is not key]
        if key in members:
            # 块自身也能聚焦（QScrollArea 就是）→ 先落在块上，再进它内部
            out.append(key)
        if inner:
            out.extend(order_hierarchical(inner, key))
    return out


def min_moves(chain, ideal):
    """最少要挪动几个控件才能把焦点链排成阅读序 = n − 最长上升子序列长度。

    为什么不用「逐位比对」：那个指标里**一个控件插错位置，会让它之后的
    全部计为错位**。music 页 28 个控件报 16 处错位，实际只是动作条被排到了
    最前面，一处错误滚成了 16。修的人照着 16 去找，会找不到 16 个东西。
    """
    rank = {w: i for i, w in enumerate(ideal)}
    seq = [rank[w] for w in chain if w in rank]
    import bisect

    tails = []
    for v in seq:
        i = bisect.bisect_left(tails, v)
        if i == len(tails):
            tails.append(v)
        else:
            tails[i] = v
    return len(seq) - len(tails)


def describe(w):
    text = ""
    for attr in ("text", "currentText", "title"):
        if hasattr(w, attr):
            try:
                text = str(getattr(w, attr)()) or ""
            except Exception:
                text = ""
            if text:
                break
    parent_card = ""
    p = w.parentWidget()
    while p is not None:
        if p.objectName() in ("card", "settingsCard") or type(p).__name__ == "SettingsCard":
            for child in p.findChildren(QWidget):
                if child.objectName() in ("cardTitle", "title_label"):
                    try:
                        parent_card = child.text()
                    except Exception:
                        pass
                    break
            break
        p = p.parentWidget()
    x, y = _pos(w)
    return f"{type(w).__name__}[{text[:14] or w.objectName() or '—'}] @({x},{y}) 卡片<{parent_card[:10]}>"


def count_mismatch(chain, ideal):
    return [i for i, (a, b) in enumerate(zip(chain, ideal)) if a is not b]


def adjacent_same_row_swaps(chain, ideal):
    """错位里有多少只是「同一行内相邻两个互换」——那类不影响可用性。"""
    swaps = 0
    idx = {w: i for i, w in enumerate(ideal)}
    for i, w in enumerate(chain):
        j = idx.get(w)
        if j is None or j == i:
            continue
        if abs(j - i) == 1 and abs(_pos(w)[1] - _pos(ideal[i])[1]) <= ROW_TOLERANCE:
            swaps += 1
    return swaps


def audit(page_id):
    mod_name, cls_name = PAGES[page_id]
    mod = __import__(mod_name, fromlist=[cls_name])
    page = getattr(mod, cls_name)()
    page.resize(1200, 900)
    page.show()
    QApplication.processEvents()

    chain = focusable_chain(page)
    bucketed = order_bucketed(chain)
    clustered = order_clustered(chain)
    hier = order_hierarchical(chain, page)

    print(f"\n=== {page_id} ===  可聚焦 {len(chain)} 个")
    print(f"  {'模型':<22}{'逐位错位':>10}{'最少挪动':>10}")
    print(f"  {'现行(y//24 平铺)':<22}{len(count_mismatch(chain, bucketed)):>10}"
          f"{min_moves(chain, bucketed):>10}")
    print(f"  {'真行带聚类(仍平铺)':<22}{len(count_mismatch(chain, clustered)):>10}"
          f"{min_moves(chain, clustered):>10}")
    print(f"  {'按卡片分组(本探针)':<22}{len(count_mismatch(chain, hier)):>10}"
          f"{min_moves(chain, hier):>10}")
    print(f"  同行相邻互换(可忽略): {adjacent_same_row_swaps(chain, hier)}")

    real = count_mismatch(chain, hier)
    for idx in real[:8]:
        print(f"   #{idx}")
        print(f"      链上  = {describe(chain[idx])}")
        print(f"      阅读序= {describe(hier[idx])}")

    page.close()
    page.deleteLater()
    QApplication.processEvents()


def main():
    QApplication.instance() or QApplication([])
    targets = sys.argv[1:] or list(PAGES)
    for pid in targets:
        try:
            audit(pid)
        except Exception as exc:
            print(f"[{pid}] 失败: {exc}")


if __name__ == "__main__":
    main()

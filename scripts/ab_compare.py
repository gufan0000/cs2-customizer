# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""A/B 对照：**先量这一轮的噪声地板，再读改动页的位移**（RN-570）。

## 为什么要有这个脚本

批 70 拿**逐字节相同**的两组图跑同一题面两轮，`compact_advanced` 的 render 档
从 **5/6 掉到 1/6** ⇒ 「有几发报了『高』」这个指标的噪声地板是 **±4/6**。
同一轮里我改过那页的位移全部 ≤ +1 —— **全部淹在地板下，证不了也证不伪**。

批 69 也撞到过同一件事（`advanced` 4/6 → 1/6），当时判成「偶发」。
两轮之后才看清：**它不是偶发，是那个指标的属性。**

⭐⭐⭐ 于是这条规矩：**不量地板的位移读数没有意义。**
而规矩写在文档里是会被跳过的（RN-408/468/560/567 同族四次）——
所以把它做成**这个脚本的前置条件**：没有对照页，它拒绝出结论。

## 对照页的两个硬要求

1. **它这一轮不该被改动**；
2. **它的改前/改后图必须逐字节相同**（本脚本自己核 md5）。

⚠ 第 2 条不是形式主义：只要有一个像素不同，那一页的位移里就混进了真实变化，
它就不再是纯噪声，量出来的地板会偏大 —— **而偏大的地板会把真实位移一起吃掉**。

## 用法

    python scripts/ab_compare.py \\
        --before H:/tmp/rev_before --after H:/tmp/rev_after \\
        --before-shots H:/tmp/shots_before --after-shots H:/tmp/shots_after \\
        --control advanced,viewmodel --changed magnifier

退出码：0 = 出了结论（不管结论是「有位移」还是「读不出」）；
2 = **拒绝出结论**（没给对照页 / 对照页的图不是逐字节相同 / 数据不全）。
"""
from __future__ import annotations

import argparse
import hashlib
import re
import sys
from pathlib import Path

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

#: 一行缺陷长这样：`高|位置|一句话`
_SEV_LINE = re.compile(r"^\s*(高|中|低)\s*\|")
#: 一行判断题长这样：`判断|会`
_VERDICT_LINE = re.compile(r"^\s*判断\s*\|\s*(会|不会|说不准)\s*$")
_REP = re.compile(r"__r\d+$")


def _page_of(stem: str) -> str:
    return _REP.sub("", stem)


def _load(round_dir: Path) -> dict[str, dict]:
    """→ {页: {"发数": n, "报高的发数": n, "判断": {会/不会/说不准: n}}}"""
    out: dict[str, dict] = {}
    for mode_dir in sorted(p for p in round_dir.iterdir() if p.is_dir()):
        if mode_dir.name == "_images":
            continue
        for f in sorted(mode_dir.glob("*.txt")):
            page = _page_of(f.stem)
            rec = out.setdefault(page, {"发数": 0, "报高的发数": 0, "判断": {}})
            rec["发数"] += 1
            text = f.read_text(encoding="utf-8", errors="replace")
            high = False
            for line in text.splitlines():
                mv = _VERDICT_LINE.match(line.strip().strip("`"))
                if mv:
                    rec["判断"][mv.group(1)] = rec["判断"].get(mv.group(1), 0) + 1
                    continue
                ms = _SEV_LINE.match(line)
                if ms and ms.group(1) == "高":
                    high = True
            if high:
                rec["报高的发数"] += 1
    return out


def _md5(p: Path) -> str:
    return hashlib.md5(p.read_bytes()).hexdigest()


#: 对照页允许的差异上限（RN-606）。
#: ⚠ **老实说这两个数是挑的**，只有它们的**起点**是量出来的：批 81 那次真实的
#: 抗锯齿抖动是 **0.21% / 中位 8**，这里留了约 5 倍与 2 倍的余量。
#: ⭐⭐⭐ 批 40 的教训逐字是「一条判据绿着，可能是因为我选的参数，而不是因为缺陷修好了」。
#: ⇒ 所以拿**批 81 的三张真图**各考了一遍（合成夹具替代不了真现象）：
#:
#:   | 真实案例 | 差异 | 中位 | 四向平移后 | 判定 |
#:   |---|---|---|---|---|
#:   | 地板页 · 逐字节相同 | 0 (0.00%) | 0 | 56091 | ✅ 采信 |
#:   | 地板页 · 抗锯齿抖动 | 2150 (**0.21%**) | 8 | 56156 | ✅ 采信 |
#:   | 被测页 · 真改了版面 | 40947 (**4.00%**) | 26 | 100668 | ⛔ 拒绝 |
#:
#: ⚠⚠ **这张表推翻了我原本写在这里的一句话。** 我原先写「挡住真实改动的是几何位移判定」——
#: 而真实案例里 `aligned` **仍然是 True**：删掉两个控件**不会平移整张图**，
#: 它只是让某一块内容消失。挡住它的是**差异比例**（4.00% vs 上限 1%）。
#: ⭐⭐ 两条判定各管一种形状，缺一不可：
#:   **平移判定认「整体挪了位置」，比例/中位认「某一块内容变了」。**
#: 余量：真实改动 4.00% 是上限的 4 倍、是噪声 0.21% 的 19 倍 —— 分得开。
CONTROL_MAX_DIFF_RATIO = 0.01     # 1%
CONTROL_MAX_DIFF_MEDIAN = 16      # 255 分之


def _image_delta(before: Path, after: Path) -> dict:
    """两张图差在哪：是**位移**还是**抗锯齿**？（RN-606）

    ⭐⭐⭐ 批 81 实测：照 RN-594 用同一条命令、同一轮现拍，地板页**仍然不是逐字节相同**
    —— 改了 A 页的代码，同一进程里**后面渲染的 B 页**字形就变了
    （出图工装一次进程走多页，字体缓存状态被前面那页带着走）。
    量下来 **0.21% 像素、差值中位 8/255、散在文字边缘**。
    ⇒ 「逐字节相同」做不到；而**做不到的标准会让下一个人要么忽略它、
    要么把真信号当噪声退回去**。

    ⛔ 判「有没有位移」要给得出反例：把其中一张往**四个方向**各平移一格，
    若差异都**变大**，说明原来那两张是对齐的。批 81 实测平移后差异涨了 **65 倍**。
    ⚠ 必须四个方向都试 —— 只试一个方向的话，**正好朝那个方向的真位移会被判成对齐**。
    """
    try:
        from PIL import Image, ImageChops
    except ImportError:      # 出图工装装了 Pillow；没有就退回逐字节
        return {"available": False}

    try:
        a = Image.open(before).convert("RGB")
        c = Image.open(after).convert("RGB")
    except Exception:        # noqa: BLE001
        # ⛔ 读不开就是**量不出来**，而量不出来必须朝「拒绝」倒 ——
        #   ⭐ 朝「采信」倒的话，一个损坏的对照页会被当成「抗锯齿级差异」放行。
        return {"available": False}
    if a.size != c.size:
        return {"available": True, "same_size": False}
    d = ImageChops.difference(a, c)
    mags = sorted(max(p) for p in d.getdata() if p != (0, 0, 0))
    total = a.size[0] * a.size[1]
    # 平移反例：对齐的两张图，**往哪边平移都会更差**。
    # ⛔⛔ 必须双向试。第一版只试 +1 —— 而真实位移正好是 +1 时，
    #   再往 +1 移当然更差，于是它把**位移判成了对齐**。
    #   ⭐⭐⭐ 阳性对照当场逮到了这个：**一个只往一个方向验的反例，
    #   在那个方向上的真缺陷面前恰好失效。**
    def _shift_diff(dy: int, dx: int = 0) -> int:
        return sum(1 for p in ImageChops.difference(
            a, ImageChops.offset(c, dx, dy)).getdata() if p != (0, 0, 0))

    probes = {(0, 1): _shift_diff(1), (0, -1): _shift_diff(-1),
              (1, 0): _shift_diff(0, 1), (-1, 0): _shift_diff(0, -1)}
    best = min(probes.values())
    return {
        "available": True, "same_size": True, "total": total,
        "diff": len(mags), "ratio": len(mags) / total if total else 0.0,
        "median": mags[len(mags) // 2] if mags else 0,
        "shifted_diff": best,
        # 四个方向**都**更差 ⇒ 原本是对齐的；任何一个方向更好 ⇒ 有位移
        "aligned": best > len(mags),
    }


def _match_pages(names: list[str], pages: list[str]) -> list[str]:
    """`advanced` → `full_advanced` / `compact_advanced`（两档都算）。"""
    out = []
    for n in names:
        hit = [p for p in pages if p == n or p.endswith("_" + n)]
        if not hit:
            raise SystemExit(f"❌ 认不出页面 `{n}`；这一轮里有：{sorted(pages)}")
        out.extend(hit)
    return sorted(set(out))


def main() -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--before", required=True, help="改前那一轮的 --out 目录")
    ap.add_argument("--after", required=True, help="改后那一轮的 --out 目录")
    ap.add_argument("--before-shots", default="", help="改前的图目录（核 md5 用）")
    ap.add_argument("--after-shots", default="", help="改后的图目录")
    ap.add_argument("--control", required=True,
                    help="对照页（逗号分隔）—— 这一轮**不该被改动**的页")
    ap.add_argument("--changed", required=True, help="改动过的页（逗号分隔）")
    args = ap.parse_args()

    before, after = _load(Path(args.before)), _load(Path(args.after))
    pages = sorted(set(before) & set(after))
    if not pages:
        print("❌ 两轮没有共同的页面 —— 拒绝出结论")
        return 2

    control = _match_pages([s.strip() for s in args.control.split(",") if s.strip()],
                           pages)
    changed = _match_pages([s.strip() for s in args.changed.split(",") if s.strip()],
                           pages)
    if not control:
        print("❌ 没给对照页 —— 拒绝出结论。\n"
              "⭐ 不量地板的位移读数没有意义（RN-570）。")
        return 2

    # ── 对照页的图必须逐字节相同 ────────────────────────────────
    if args.before_shots and args.after_shots:
        bad: list[str] = []
        soft: list[str] = []
        for p in control:
            b = Path(args.before_shots) / f"{p}.png"
            a = Path(args.after_shots) / f"{p}.png"
            if not (b.exists() and a.exists()):
                bad.append(f"{p}：找不到图（{b.name}）")
            elif _md5(b) != _md5(a):
                # ⭐ RN-606：md5 不同**不等于**它被改动过 —— 先量是位移还是抗锯齿。
                k = _image_delta(b, a)
                if not k.get("available"):
                    bad.append(f"{p}：md5 不同，而这台机器没有 Pillow，量不出是位移还是抗锯齿")
                elif not k.get("same_size"):
                    bad.append(f"{p}：改前/改后**尺寸都不同** —— 它这一轮被改动过")
                elif not k["aligned"]:
                    bad.append(
                        f"{p}：有**几何位移**（平移一格后差异 {k['shifted_diff']} "
                        f"不比原来的 {k['diff']} 大）—— 它这一轮被改动过")
                elif k["ratio"] > CONTROL_MAX_DIFF_RATIO or \
                        k["median"] > CONTROL_MAX_DIFF_MEDIAN:
                    bad.append(
                        f"{p}：差异 {k['ratio']*100:.2f}% / 中位 {k['median']}，"
                        f"超过抗锯齿级上限（{CONTROL_MAX_DIFF_RATIO*100:.0f}% / "
                        f"{CONTROL_MAX_DIFF_MEDIAN}）—— 它这一轮被改动过")
                else:
                    soft.append(
                        f"{p}：md5 不同，但**无几何位移**、差异 {k['ratio']*100:.2f}%、"
                        f"中位 {k['median']} ⇒ 抗锯齿级，按对照页采信（RN-606）")
        if bad:
            print("❌ 对照页不合格 —— 拒绝出结论：\n  " + "\n  ".join(bad)
                  + "\n⚠ 对照页混进真实变化之后，量出来的地板会偏大，"
                    "\n  而**偏大的地板会把真实位移一起吃掉**。")
            return 2
        if soft:
            print("⚠ 对照页不是逐字节相同，但都在抗锯齿级以内（RN-606）：\n  "
                  + "\n  ".join(soft)
                  + "\n⭐ 改了 A 页的代码，同一进程里后面渲染的 B 页字形就会变 ——"
                    "\n  「逐字节相同」是个做不到的标准，这里改判为"
                    "「无几何位移 + 差异 < 1% + 中位 ≤ 16」。\n")
    else:
        print("⚠ 没给 --before-shots/--after-shots ⇒ **没核对照页的图是否逐字节相同**。"
              "\n  下面的地板只在「那两页真的没被动过」这个前提下成立。\n")

    # ── 地板 ────────────────────────────────────────────────────
    print("== 对照页（图无几何位移、差异在抗锯齿级以内 ⇒ 差值全是噪声）==")
    floor_high = floor_verdict = 0
    for p in control:
        b, a = before[p], after[p]
        d = abs(a["报高的发数"] - b["报高的发数"])
        floor_high = max(floor_high, d)
        line = (f"  {p:<22} 报高 {b['报高的发数']}/{b['发数']} → "
                f"{a['报高的发数']}/{a['发数']}  差 {d}")
        if b["判断"] or a["判断"]:
            bw, aw = b["判断"].get("会", 0), a["判断"].get("会", 0)
            dv = abs(aw - bw)
            floor_verdict = max(floor_verdict, dv)
            line += f"   ·  判断「会」 {bw} → {aw}  差 {dv}"
        print(line)
    print(f"\n  ⇒ **噪声地板**：报高 ±{floor_high}"
          + (f" · 判断题 ±{floor_verdict}" if floor_verdict or any(
              before[p]["判断"] for p in control) else ""))

    # ── 改动页 ──────────────────────────────────────────────────
    print("\n== 改动页：位移有没有超过地板 ==")
    readable = 0
    for p in changed:
        b, a = before[p], after[p]
        d = a["报高的发数"] - b["报高的发数"]
        ok = abs(d) > floor_high
        readable += ok
        print(f"  {p:<22} 报高 {b['报高的发数']}/{b['发数']} → "
              f"{a['报高的发数']}/{a['发数']}（{d:+d}）  "
              + ("**超过地板 ⇒ 可读**" if ok else "没超过地板 ⇒ **读不出**"))
        if b["判断"] or a["判断"]:
            bw, aw = b["判断"].get("会", 0), a["判断"].get("会", 0)
            dv = aw - bw
            okv = abs(dv) > floor_verdict
            readable += okv
            print(f"  {'':<22} 判断「会」 {bw} → {aw}（{dv:+d}）  "
                  + ("**超过地板 ⇒ 可读**" if okv else "没超过地板 ⇒ **读不出**"))

    print(f"\n== 结论：{readable} 格可读 ==")
    if not readable:
        print("⚠ 一格都读不出**不等于「没效果」** —— 它等于「这一轮量不出来」。")
        print("⭐ 下一步选一个：① 换成能答「不会」的**判断题**"
              "（`--mode judgment --question ...`，实测两轮都 12/12，稳）；"
              "② 抬 --repeat（代价按 n 涨，而地板按 √n 降）。")
    return 0


if __name__ == "__main__":
    sys.exit(main())

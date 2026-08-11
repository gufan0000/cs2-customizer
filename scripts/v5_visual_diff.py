# SPDX-License-Identifier: GPL-3.0-or-later
"""
v5 视觉差异工具 — 对比两个 baseline 目录

用法:
    python scripts/v5_visual_diff.py --before v4 --after v5_phase1 [--threshold 5]

输出:
    artifacts/v5_baseline/diff_<before>_vs_<after>/
        report.html         一页 HTML 列出全部 54 对比 + 差异统计
        diff_<file>.png     差异可视化(逐像素 abs diff)
        summary.json        差异指标统计
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import datetime
from pathlib import Path

from PIL import Image, ImageChops, ImageDraw

PROJECT_ROOT = Path(__file__).resolve().parents[1]
DEFAULT_ROOT = PROJECT_ROOT / "artifacts" / "v5_baseline"


def compute_diff(a_path: Path, b_path: Path, out_path: Path, threshold: int = 5) -> dict:
    """对比两张图,返回差异指标"""
    if not a_path.exists() or not b_path.exists():
        return {"error": "missing", "a_exists": a_path.exists(), "b_exists": b_path.exists()}

    a = Image.open(a_path).convert("RGB")
    b = Image.open(b_path).convert("RGB")
    if a.size != b.size:
        # 尺寸不同直接拒绝(理论上不该发生,因为相同分辨率)
        return {"error": "size_mismatch", "a_size": a.size, "b_size": b.size}

    diff = ImageChops.difference(a, b)
    bbox = diff.getbbox()

    # 算超过 threshold 的像素数
    pixels_changed = 0
    total_pixels = a.size[0] * a.size[1]
    if bbox:
        # 用 numpy-free 的方法:遍历 diff 的 luminance > threshold
        gray = diff.convert("L")
        hist = gray.histogram()
        pixels_changed = sum(c for i, c in enumerate(hist) if i > threshold)

    pct = (pixels_changed / total_pixels * 100) if total_pixels > 0 else 0

    # 生成可视化:左原图、中差异(放大)、右新图,横向拼
    canvas_w = a.size[0] * 3 + 20
    canvas_h = a.size[1] + 30
    canvas = Image.new("RGB", (canvas_w, canvas_h), (20, 20, 24))

    # 左:before
    canvas.paste(a, (0, 30))
    # 中:差异(放大 8x 让看得见)
    diff_amp = ImageChops.difference(a, b)
    diff_amp = Image.eval(diff_amp, lambda x: min(x * 8, 255))
    canvas.paste(diff_amp, (a.size[0] + 10, 30))
    # 右:after
    canvas.paste(b, (a.size[0] * 2 + 20, 30))

    # 标签
    draw = ImageDraw.Draw(canvas)
    draw.text((5, 5), "BEFORE", fill=(200, 200, 200))
    draw.text((a.size[0] + 15, 5), f"DIFF (x8 amp, {pct:.2f}%)",
              fill=(255, 100, 100) if pct > 1 else (200, 200, 200))
    draw.text((a.size[0] * 2 + 25, 5), "AFTER", fill=(200, 200, 200))

    out_path.parent.mkdir(parents=True, exist_ok=True)
    # 缩到合理尺寸方便看
    canvas.thumbnail((2400, 800))
    canvas.save(out_path, "PNG", optimize=True)

    return {
        "size": a.size,
        "pixels_changed": pixels_changed,
        "total_pixels": total_pixels,
        "pct": round(pct, 4),
        "bbox": list(bbox) if bbox else None,
    }


def diff_all(root: Path, before_label: str, after_label: str, threshold: int = 5) -> dict:
    before_dir = root / before_label
    after_dir = root / after_label
    out_dir = root / f"diff_{before_label}_vs_{after_label}"
    out_dir.mkdir(parents=True, exist_ok=True)

    if not before_dir.exists():
        print(f"[diff] BEFORE not found: {before_dir}")
        return {"error": f"missing {before_label}"}
    if not after_dir.exists():
        print(f"[diff] AFTER not found: {after_dir}")
        return {"error": f"missing {after_label}"}

    before_files = {f.name for f in before_dir.glob("*.png")}
    after_files = {f.name for f in after_dir.glob("*.png")}
    common = sorted(before_files & after_files)
    only_before = sorted(before_files - after_files)
    only_after = sorted(after_files - before_files)

    results = []
    for fname in common:
        a = before_dir / fname
        b = after_dir / fname
        out_path = out_dir / f"diff_{fname}"
        r = compute_diff(a, b, out_path, threshold)
        r["file"] = fname
        results.append(r)
        print(f"  [{fname}] {r.get('pct', '?')}% changed")

    # 排序:差异最大在前
    results.sort(key=lambda r: -(r.get("pct") or 0))

    # 生成 HTML 报告
    html = _render_html(before_label, after_label, results, only_before, only_after, threshold)
    (out_dir / "report.html").write_text(html, encoding="utf-8")

    summary = {
        "generated_at": datetime.now().isoformat(),
        "before": before_label,
        "after": after_label,
        "threshold": threshold,
        "total_compared": len(results),
        "only_before": only_before,
        "only_after": only_after,
        "results": results,
        "max_pct": max((r.get("pct") or 0) for r in results) if results else 0,
        "avg_pct": (sum(r.get("pct") or 0 for r in results) / len(results)) if results else 0,
    }
    (out_dir / "summary.json").write_text(
        json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8"
    )
    print(f"\n[diff] saved {len(results)} comparisons to {out_dir}")
    print(f"[diff] max diff: {summary['max_pct']:.3f}%, avg: {summary['avg_pct']:.3f}%")
    return summary


def _render_html(before, after, results, only_before, only_after, threshold) -> str:
    rows = []
    for r in results:
        pct = r.get("pct") or 0
        cls = "high" if pct > 5 else ("med" if pct > 1 else "low")
        rows.append(f'<tr class="{cls}"><td>{r["file"]}</td><td>{pct:.3f}%</td>'
                    f'<td><a href="diff_{r["file"]}" target="_blank">查看</a></td></tr>')

    only_before_html = "".join(f"<li>{f}</li>" for f in only_before) or "<li>无</li>"
    only_after_html = "".join(f"<li>{f}</li>" for f in only_after) or "<li>无</li>"

    return f"""<!doctype html><meta charset="utf-8">
<title>视觉 diff: {before} vs {after}</title>
<style>
body {{ font-family: -apple-system, "Microsoft YaHei UI", sans-serif; background: #14151a; color: #e8e8ec; margin: 24px; }}
h1 {{ font-size: 22px; }}
table {{ border-collapse: collapse; width: 100%; max-width: 900px; }}
th, td {{ padding: 8px 12px; border-bottom: 1px solid #2a2c34; text-align: left; }}
th {{ background: #1c1e26; }}
tr.high td {{ background: rgba(239, 68, 68, 0.12); }}
tr.med td {{ background: rgba(245, 158, 11, 0.10); }}
tr.low td {{ color: #888; }}
a {{ color: #7c3aed; }}
.summary {{ margin: 16px 0; padding: 12px 16px; background: #1c1e26; border-left: 3px solid #7c3aed; }}
ul {{ margin: 8px 0; }}
</style>
<h1>视觉 diff: <span style="color:#7c3aed">{before}</span> vs <span style="color:#06b6d4">{after}</span></h1>
<div class="summary">
  阈值: {threshold} (像素值差) · 对比张数: {len(results)} · 仅 before: {len(only_before)} · 仅 after: {len(only_after)}
</div>
<h2>差异排序(从大到小)</h2>
<table>
<tr><th>文件</th><th>差异率</th><th>对比图</th></tr>
{"".join(rows)}
</table>
<h2>仅 before 有</h2><ul>{only_before_html}</ul>
<h2>仅 after 有</h2><ul>{only_after_html}</ul>
"""


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--before", required=True, help="参照标签,如 v4")
    parser.add_argument("--after", required=True, help="新标签,如 v5_phase1")
    parser.add_argument("--root", default=str(DEFAULT_ROOT), help="基线根目录")
    parser.add_argument("--threshold", type=int, default=5, help="像素差阈值(0-255),默认 5")
    args = parser.parse_args()

    summary = diff_all(Path(args.root), args.before, args.after, args.threshold)
    if "error" in summary:
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())

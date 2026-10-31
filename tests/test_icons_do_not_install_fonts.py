# SPDX-License-Identifier: GPL-3.0-or-later
"""图标字体只从包内加载：新机器首次启动不往用户字体目录装字体。"""
from __future__ import annotations

import json
import os
from pathlib import Path
import subprocess
import sys
import textwrap

ROOT = Path(__file__).resolve().parents[1]

_CHILD = textwrap.dedent("""
    import json, os, sys
    sys.path.insert(0, sys.argv[1])
    from PySide6.QtCore import QSize
    from PySide6.QtWidgets import QApplication
    app = QApplication([])
    from widgets import icon_provider
    icon = icon_provider.get_icon("mdi.cog-outline", color="#ffffff", size=32)
    image = icon.pixmap(QSize(32, 32)).toImage()
    alpha = {image.pixelColor(x, y).alpha() for x in range(32) for y in range(32)}
    print("RESULT " + json.dumps({
        "qtawesome": icon_provider.is_available(),
        "glyph_edges": len(alpha),
    }))
""")


def test_a_clean_profile_gets_real_icons_and_no_installed_fonts(tmp_path):
    local = tmp_path / "local"
    local.mkdir()
    child = tmp_path / "child.py"
    child.write_text(_CHILD, encoding="utf-8")
    env = {**os.environ, "LOCALAPPDATA": str(local), "QT_QPA_PLATFORM": "offscreen"}
    proc = subprocess.run([sys.executable, str(child), str(ROOT)], env=env, cwd=str(tmp_path),
                          capture_output=True, text=True, errors="replace", timeout=120)
    lines = [ln[7:] for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")]
    assert proc.returncode == 0 and lines, f"rc={proc.returncode}\n{proc.stderr[-800:]}"
    result = json.loads(lines[0])
    assert result["qtawesome"], "qtawesome 没加载上"
    # 兜底图标是圆角方块，只有少数几档透明度；真字形抗锯齿后档位多得多。
    assert result["glyph_edges"] > 8, f"画出来的不是字形：{result}"
    installed = list((local / "Microsoft/Windows/Fonts").glob("*"))
    assert not installed, f"又往用户字体目录装字体了：{[p.name for p in installed][:4]}"

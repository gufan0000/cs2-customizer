"""v5 demo run — 跳过 main_widget.py 的 admin 提权,直接启动 MainWindow.

仅用于 v5 视觉演示 / computer-use 控制.
不要用于生产(magnifier 功能需要 admin 权限).
"""

from __future__ import annotations

import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))

from PySide6.QtWidgets import QApplication

from gui_widget import MainWindow


def main() -> int:
    app = QApplication.instance() or QApplication(sys.argv)
    # UP-090: csgo_dir 是自动探测的，不沙箱化会把用户真实 CS2 目录里的
    # fanpai.cfg 覆盖成默认配置的内容。见 scripts/_audit_sandbox.py。
    from _audit_sandbox import sandbox_external_writes

    sandbox_external_writes()

    win = MainWindow()
    # 关掉首次启动的更新对话框逻辑(如果可禁用)
    try:
        win.config.show_update_dialog = False
    except Exception:
        pass
    win.show()
    win.resize(1366, 800)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

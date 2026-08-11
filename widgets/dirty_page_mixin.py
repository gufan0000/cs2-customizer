"""Shared dirty-state protocol for editable pages."""

from __future__ import annotations

from PySide6.QtWidgets import QMessageBox


class DirtyPageMixin:
    def init_dirty_state(self):
        self._dirty = False

    def is_dirty(self) -> bool:
        return bool(getattr(self, "_dirty", False))

    def mark_dirty(self):
        self._dirty = True
        refresh = getattr(self, "_refresh_dirty_ui", None)
        if callable(refresh):
            refresh()

    def clear_dirty(self):
        self._dirty = False
        refresh = getattr(self, "_refresh_dirty_ui", None)
        if callable(refresh):
            refresh()

    def discard_changes(self):
        reload_fn = getattr(self, "_load_settings", None)
        if callable(reload_fn):
            reload_fn()
            self.clear_dirty()

    def can_leave_page(self):
        if not self.is_dirty():
            return True

        msg = QMessageBox(self)
        msg.setWindowTitle("未保存修改")
        msg.setText("当前页面有未保存修改，是否保存后离开？")
        save_btn = msg.addButton("保存并离开", QMessageBox.AcceptRole)
        discard_btn = msg.addButton("不保存离开", QMessageBox.DestructiveRole)
        cancel_btn = msg.addButton("取消", QMessageBox.RejectRole)
        msg.setDefaultButton(save_btn)
        msg.exec()
        clicked = msg.clickedButton()

        if clicked == save_btn:
            save_fn = getattr(self, "_save_changes", None)
            if callable(save_fn):
                return bool(save_fn())
            return False
        if clicked == discard_btn:
            self.discard_changes()
            return True
        if clicked == cancel_btn:
            return False
        return False


# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 131：改用户自己的 autoexec.cfg 之前先给他看要加 / 挪哪几行；预览就是实际写进去的那份；
改之前留原样备份；用户选「不改」就一个字不动。"""
from __future__ import annotations

import types
from pathlib import Path

import cfg_utils


def _game(tmp_path: Path, autoexec: str | None) -> tuple[str, Path]:
    cfg = tmp_path / "cs2" / "game" / "csgo" / "cfg"
    cfg.mkdir(parents=True)
    if autoexec is not None:
        (cfg / "autoexec.cfg").write_bytes(autoexec.encode("utf-8"))
    return str(tmp_path / "cs2"), cfg / "autoexec.cfg"


def test_what_is_written_is_exactly_what_the_preview_showed(tmp_path):
    for i, original in enumerate(("bind f1 \"say hi\"\r\nexec mine.cfg\r\n",          # 没有我们那行 ⇒ 末尾加
                                  # ⚠ 第三方 cfg 别取 cs2customizer：开源版把 cs2customizer.cfg 机械替换成它，两行就成了同一行
                                  "exec cs2customizer.cfg\nexec practice.cfg\n",             # 我们不在最后 ⇒ 挪
                                  "rate 786432\nexec cs2customizer.cfg\n")):                 # 已经好了 ⇒ 不动
        game, autoexec = _game(tmp_path / str(i), original)
        plan = cfg_utils.plan_autoexec(game)
        cfg_utils.setup_autoexec(game)
        written = autoexec.read_text(encoding="utf-8")
        assert written == plan["after"], (original, plan["after"], written)
        assert plan["changed"] == (i != 2)
        if plan["changed"]:
            assert any("exec cs2customizer.cfg" in ln for ln in plan["lines"]), plan["lines"]
            bak = Path(str(autoexec) + cfg_utils.AUTOEXEC_BACKUP_SUFFIX)
            assert bak.read_bytes() == original.encode("utf-8"), "改之前没留逐字节原样的备份"
        else:
            assert autoexec.read_bytes() == original.encode("utf-8"), "不用改的时候也重写了用户的文件"


def test_saying_no_leaves_the_users_file_untouched(tmp_path):
    original = "exec cs2customizer.cfg\nexec practice.cfg\n"
    game, autoexec = _game(tmp_path, original)
    cfg_utils.setup_autoexec(game, allow_edit=False)
    assert autoexec.read_bytes() == original.encode("utf-8")
    assert not Path(str(autoexec) + cfg_utils.AUTOEXEC_BACKUP_SUFFIX).exists()


def test_setting_the_game_dir_asks_before_touching_autoexec(tmp_path, monkeypatch):
    import pages.advanced_page as ap
    from config import config

    original = "bind f1 \"say hi\"\n"
    game, autoexec = _game(tmp_path, original)
    monkeypatch.setattr(config, "csgo_dir", "", raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(ap.QFileDialog, "getExistingDirectory", staticmethod(lambda *a, **k: game))
    shown: list = []

    class _Box:
        @staticmethod
        def information(_p, title, text):
            shown.append((title, text))

        warning = critical = information

    monkeypatch.setattr(ap, "QMessageBox", _Box)
    monkeypatch.setattr(cfg_utils, "ensure_all_cfg",
                        lambda d, edit_autoexec=True: (cfg_utils.setup_autoexec(d, allow_edit=edit_autoexec), True)[1])
    asked: list = []
    page = types.SimpleNamespace(
        logger=types.SimpleNamespace(info=lambda *a: None, warning=lambda *a: None, error=lambda *a: None),
        _validate_csgo_dir=lambda d: True, _update_csgo_dir_display=lambda: None, _auto_detected=True,
        _confirm_autoexec_edit=lambda plan: (asked.append(plan), False)[1])

    ap.AdvancedPage._browse_for_csgo_dir(page)
    assert asked and asked[0]["lines"] == ["+ exec cs2customizer.cfg"], "改 autoexec 之前没问 / 问的不是要改的那一行"
    assert autoexec.read_bytes() == original.encode("utf-8"), "用户选了「不改」，文件还是被改了"
    assert shown and "exec cs2customizer.cfg" in shown[-1][1], f"选了不改，却没告诉他要自己加哪一行：{shown}"

    page._confirm_autoexec_edit = lambda plan: (asked.append(plan), True)[1]
    ap.AdvancedPage._browse_for_csgo_dir(page)
    assert autoexec.read_text(encoding="utf-8") == asked[-1]["after"]

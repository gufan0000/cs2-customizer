# SPDX-License-Identifier: GPL-3.0-or-later
"""2026-09-23 全功能扫两轮 + 闪光副屏（`--only SWEEP`）。第一轮四条列在下面，第二轮与闪光见文件后段。

每条都是「功能看着在、其实不工作」那一族，且之前没有任何判据走过那条路：

1. 音乐页「添加音乐」：把路径**字符串**传给只收曲目字典的 `add_track` ⇒ 每首都 TypeError
   被吞，却照样弹「已添加 N 个」。按钮就在页面动作栏最显眼的位置。
2. 特殊音效：GSI 发显式 `"weapons": null` 时，投掷物检测只防了第一个循环 ⇒
   同一帧后面的 C4 / 血量 / 回合 / MVP 全被跳过（kills / sounds 早就防了这一格）。
3. HUD 动态颜色：同一格，`_get_active_weapon` 的 `.get("weapons", {})` 挡不住显式 null。
4. 导入素材确认框：「回合事件 / 武器」那一格的标签存在 `self` 上 ⇒ 建完只剩最后一张卡的，
   改前面任何一张卡的类别，换字的都是最后一张。
"""
from __future__ import annotations

import types

from config import config


# ------------------------------------------------------------ 1. 音乐页添加本地文件

class _Box:
    calls: list = []

    @classmethod
    def information(cls, _parent, title, text):
        cls.calls.append(("information", title, text))

    @classmethod
    def warning(cls, _parent, title, text):
        cls.calls.append(("warning", title, text))


def _music_page_stub(monkeypatch, files, player):
    import pages.music_page as mp

    _Box.calls = []
    monkeypatch.setattr(mp, "QMessageBox", _Box)
    monkeypatch.setattr(mp.QFileDialog, "getOpenFileNames",
                        staticmethod(lambda *a, **k: (list(files), "")))
    fake = types.SimpleNamespace(
        player=player,
        logger=types.SimpleNamespace(info=lambda *a, **k: None, error=lambda *a, **k: None),
        refresh_playlist_display=lambda: None,
    )
    mp.MusicPage._add_local_files(fake)
    return _Box.calls


def _real_add_track_player():
    """用**真的** `MusicPlayer.add_track`，只把落盘换掉 —— 判的是它收不收得下页面给的东西。"""
    from music_player import MusicPlayer

    player = types.SimpleNamespace(playlist=[], _save_playlist=lambda: None)
    player.add_track = types.MethodType(MusicPlayer.add_track, player)
    player._get_track_duration = types.MethodType(MusicPlayer._get_track_duration, player)
    return player


def test_adding_local_music_files_really_puts_them_in_the_playlist(monkeypatch, tmp_path):
    a = tmp_path / "第一首.mp3"
    b = tmp_path / "second.wav"
    a.write_bytes(b"")
    b.write_bytes(b"")
    player = _real_add_track_player()

    calls = _music_page_stub(monkeypatch, [str(a), str(b)], player)

    assert [t.get("path") for t in player.playlist] == [str(a), str(b)], (
        "「添加音乐」选了两个文件，播放列表里一首都没有 —— 页面把路径字符串直接传给了只收曲目字典的 "
        "add_track（`track[\"path\"]` 对字符串抛 TypeError，被逐文件吞掉）")
    assert all(t.get("type") == "local" for t in player.playlist)
    assert [t.get("title") for t in player.playlist] == ["第一首.mp3", "second.wav"]
    assert calls == [("information", "成功", "已添加 2 个音乐文件!")]


def test_a_file_that_failed_to_add_is_not_reported_as_added(monkeypatch):
    added = []

    def add_track(track):
        if track["path"].endswith("bad.mp3"):
            raise OSError("读不了")
        added.append(track)

    calls = _music_page_stub(monkeypatch, ["C:/x/ok.mp3", "C:/x/bad.mp3"],
                             types.SimpleNamespace(add_track=add_track))

    assert len(added) == 1
    assert calls and calls[0][0] == "warning", (
        f"两个文件加进去一个，页面却报 {calls} —— 成功提示不许无条件弹（旧代码就是这样把 0/N 报成 N/N 的）")
    assert "1" in calls[0][2]


# ------------------------------------------------------ 2. 特殊音效：weapons 显式 null

class _SyncTimer:
    def __init__(self, _interval, func, args=None, kwargs=None):
        self._run = lambda: func(*(args or []), **(kwargs or {}))
        self.daemon = True

    def start(self):
        self._run()

    def cancel(self):
        return None

    def is_alive(self):
        return False


def test_a_null_weapons_frame_does_not_swallow_the_round_sounds(monkeypatch):
    import gsi_handler_special

    monkeypatch.setattr(config, "round_sound_enabled", True, raising=False)
    monkeypatch.setattr(config, "grenade_sound_enabled", True, raising=False)   # ← 这一格打开才走到那条路
    monkeypatch.setattr(config, "c4_sound_enabled", False, raising=False)
    monkeypatch.setattr(config, "health_warning_enabled", False, raising=False)
    monkeypatch.setattr(config, "spectator_mode_mute", False, raising=False)
    monkeypatch.setattr(config, "player_steamid", "s1", raising=False)
    handler = gsi_handler_special.GSIHandlerSpecial()
    handler.team_side = "ct"
    events = []
    monkeypatch.setattr(handler, "_play_event", lambda g, k: events.append((g, k)) or True)
    monkeypatch.setattr(gsi_handler_special.threading, "Timer", _SyncTimer)   # MVP 等待不留后台线程

    def frame(phase, win_team=None):
        payload = {
            "map": {"round": 3, "phase": "live"},
            "round": {"phase": phase},
            "player": {"steamid": "s1", "activity": "playing", "team": "CT",
                       "state": {"health": 100}, "weapons": None},
        }
        if win_team:
            payload["round"]["win_team"] = win_team
        return payload

    handler.process_data(frame("live"))
    handler.process_data(frame("over", win_team="T"))

    assert ("round", "lose") in events, (
        f"weapons 为 null 的帧里回合音效没报（{events}）—— 投掷物检测在前面抛了 AttributeError，"
        "整帧后面的 C4 / 血量 / 回合 / MVP 一起被跳过")


# ---------------------------------------------------------- 3. HUD 动态颜色：同一格

def test_the_hud_engine_survives_a_null_weapons_frame():
    from core.hud.rule_model import get_default_hud_rules
    from core.hud.runtime_engine import RuntimeHudEngine

    engine = RuntimeHudEngine(get_default_hud_rules("balanced_default"))
    payload = {
        "provider": {"steamid": "123"},
        "round": {"phase": "live", "win_team": ""},
        "bomb": {"state": ""},
        "player": {"steamid": "123", "activity": "playing", "team": "ct",
                   "state": {"health": 100, "round_kills": 0, "round_killhs": 0},
                   "weapons": None},
    }
    engine.evaluate(payload, now=1.0)        # 旧代码：AttributeError: 'NoneType' has no attribute 'values'
    assert engine._get_active_weapon(payload) == ""


# ------------------------------------------------ 4. 导入确认框：每张卡的标签各管各的

def test_each_import_card_relabels_its_own_bucket_row(qapp):
    from PySide6.QtCore import Qt
    from core.resource_identify import UNSURE, Group, Guess
    from dialogs.resource_import_decision_dialog import ResourceImportDecisionDialog

    def group(name):
        return Group(paths=[f"{name}/a.wav", f"{name}/b.wav"], shape=f"dir1/{name}",
                     guesses=[Guess("round_sounds", "回合音效", UNSURE),
                              Guess("gun_sounds", "枪声", UNSURE)])

    dlg = ResourceImportDecisionDialog([group("x"), group("y")])
    dlg.setAttribute(Qt.WA_DontShowOnScreen, True)
    try:
        first, last = dlg._rows[0], dlg._rows[-1]

        def label_of(row):
            return row["form"].labelForField(row["round"]).text()

        last["combo"].setCurrentIndex(last["combo"].findData("round_sounds"))
        first["combo"].setCurrentIndex(first["combo"].findData("gun_sounds"))

        assert label_of(first) == "武器：", (
            f"第一张卡选了「枪声」，它那一格的标签却是「{label_of(first)}」—— 换字换到别的卡上去了")
        assert label_of(last) == "回合事件：", (
            f"改的是第一张卡，最后一张卡的标签却变成了「{label_of(last)}」")
    finally:
        dlg.deleteLater()


# ====================================================== 第二轮（同日，最后一次扫）
#
# 5. 枪声页「应用到全部武器」：RN-676 给多取样的下拉项加了「· N 个取样」后缀，
#    这里还按**文字** `setCurrentText(风格)` 找 ⇒ 对不上就静默不动，确认框说配了、一把都没配。
# 6. 准心：已经是「自定义」时再画一次 / 再导入一个，`setChecked(True)` 不发 toggled ⇒
#    弹「已保存并应用」，游戏里还是旧图案。
# 7. 语音：总开关（首页或本页）拨动后热键不跟着注册/注销 ⇒ 关了音板键照样放声、照样吞键。
# 8. 动态 HUD：关掉时不写回默认色 ⇒ 移动/开火键仍 exec 运行时 cfg，HUD 卡在关之前那一帧的颜色。

def test_apply_to_all_really_applies_a_style_that_has_several_samples(qapp, monkeypatch):
    import shutil
    import wave
    from pathlib import Path

    from PySide6.QtWidgets import QMessageBox

    from core.audio.runtime_audio import get_runtime_audio_manager
    from core.gun_sound_profiles import SUPPORTED_GUN_SOUND_PROFILE_LIST
    from pages.gun_sound_page import GunSoundPage
    from resource_manager import ResourceManager

    style = "判据多取样风格"
    root = Path(ResourceManager.get_app_data_path("resources/audio")) / "gun_sounds"
    guns = [pf.gun_type for pf in SUPPORTED_GUN_SOUND_PROFILE_LIST[:2]]
    made_dirs = []
    for gun in guns:
        d = root / gun / style
        d.mkdir(parents=True, exist_ok=True)
        made_dirs.append(d)
        for name in ("a.wav", "b.wav"):          # ← 两个取样：下拉项才会带「· 2 个取样」
            with wave.open(str(d / name), "wb") as w:
                w.setnchannels(1)
                w.setsampwidth(2)
                w.setframerate(8000)
                w.writeframes(b"\x00\x00" * 400)
    manager = get_runtime_audio_manager()
    manager._styles_scanned = False
    manager.ensure_styles_scanned()
    page = GunSoundPage()
    try:
        page._refresh_style_catalog()
        qapp.processEvents()
        combo = page.weapon_rows[guns[0]]["style_combo"]
        label = combo.itemText(combo.findData(style))
        assert "2 个取样" in label, f"夹具没造出多取样的下拉项（{label!r}）—— 这条判据没了前提"

        index = page.apply_all_combo.findData(style)
        assert index > 0, "套系下拉里没有造的那一套"
        page.apply_all_combo.setCurrentIndex(index)
        disabled = page.DISABLED_STYLE_TEXT
        for gun in guns:
            page._on_weapon_style_changed(gun, disabled)   # 起始态自己造：都没配
        monkeypatch.setattr(QMessageBox, "question", lambda *a, **k: QMessageBox.Yes)
        monkeypatch.setattr(QMessageBox, "information", lambda *a, **k: 0)

        page._apply_style_to_all_weapons()
        qapp.processEvents()

        got = {g: page._effective_style(page.weapon_configs[g]) for g in guns}
        assert got == {g: style for g in guns}, (
            f"「应用到全部武器」确认之后这两把枪是 {got} —— 下拉项写的是「{label}」，"
            "按风格名找文字对不上，就一把都没配上（要按 data 找）")
    finally:
        for gun in guns:
            page._on_weapon_style_changed(gun, page.DISABLED_STYLE_TEXT)
        page.deleteLater()
        qapp.processEvents()
        for d in made_dirs:
            shutil.rmtree(d, ignore_errors=True)
        manager._styles_scanned = False
        manager.ensure_styles_scanned()


def test_reloading_a_custom_crosshair_reaches_the_overlay(qapp, monkeypatch, tmp_path):
    import json

    import pages.crosshair_page as cp

    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "crosshair_style", "custom", raising=False)
    monkeypatch.setattr(config, "crosshair_custom_data", [[10, 15], [15, 15]], raising=False)
    monkeypatch.setattr(cp.QMessageBox, "information", lambda *a, **k: 0)

    pushed = []

    class _Overlay:
        is_visible = True

        def update_settings(self, *args):
            pushed.append([list(p) for p in config.crosshair_custom_data])

    page = cp.CrosshairPage()
    try:
        page.set_crosshair_animation(_Overlay())
        new_points = [[1, 1], [2, 2], [3, 3]]
        f = tmp_path / "new.xchr"
        f.write_text(json.dumps({"crosshair_data": new_points}), encoding="utf-8")

        page._load_crosshair_file(str(f))     # 样式本来就是「自定义」—— 那颗单选不会再发 toggled

        assert pushed and pushed[-1] == new_points, (
            f"导入了新准心、提示「已加载并应用」，渲染端收到的却是 {pushed} —— "
            "已经是「自定义」时 setChecked 不发信号，得直接推一次")
    finally:
        page.deleteLater()
        qapp.processEvents()


def test_the_soundboard_hotkeys_follow_the_master_switch(qapp, monkeypatch):
    from core.hotkeys import registry
    from pages.voice_output_page import VoiceOutputPage

    monkeypatch.setenv("CS2C_NO_GLOBAL_HOTKEYS", "1")      # 只记账，不挂真钩子（§3）
    monkeypatch.setattr(config, "voice_output_enabled", True, raising=False)
    page = VoiceOutputPage()
    try:
        owner = page.HOTKEY_OWNER
        page.soundboard_slots[0] = {**page.soundboard_slots.get(0, {}),
                                    "key": "f13", "audio": "x.wav", "volume": 1.0}
        page._register_hotkeys_func()
        assert any(b["owner"] == owner for b in registry.list_bindings()), "开着时音板键没注册 —— 判据没了前提"

        monkeypatch.setattr(config, "voice_output_enabled", False, raising=False)
        page.on_master_switch_synced()        # 首页/本页那颗总开关拨完，走的就是这一下
        left = [b["key"] for b in registry.list_bindings() if b["owner"] == owner]
        assert not left, (
            f"「语音播放」关了，音板快捷键 {left} 还挂着 —— 按下照样放声、照样吞键，"
            "直到下次进这一页")

        monkeypatch.setattr(config, "voice_output_enabled", True, raising=False)
        page.on_master_switch_synced()
        assert any(b["owner"] == owner for b in registry.list_bindings()), "再打开，音板键没回来"
    finally:
        registry.unregister_owner(page.HOTKEY_OWNER)
        page.deleteLater()
        qapp.processEvents()


def test_turning_dynamic_hud_off_puts_the_default_color_back(monkeypatch, tmp_path):
    import gui_widget
    from core.hud.rule_compiler import get_cfg_paths, get_initial_runtime_color
    from gsi_handler_hud_color import GSIHandlerHudColor

    monkeypatch.setattr(config, "csgo_dir", str(tmp_path), raising=False)
    monkeypatch.setattr(config, "hud_rules_enabled", True, raising=False)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    handler = GSIHandlerHudColor()
    default = get_initial_runtime_color(config)
    effect = next(c for c in range(1, 11) if c != default)
    handler._maybe_write_color(effect, 1e9)             # 关之前那一帧：比如低血量的红
    _, runtime_cfg = get_cfg_paths(str(tmp_path))
    assert f"cl_hud_color {effect}" in open(runtime_cfg, encoding="utf-8").read()

    fake = types.SimpleNamespace(
        config=config, gsi_handlers={"hud_color": handler},
        logger=types.SimpleNamespace(info=lambda *a, **k: None, exception=lambda *a, **k: None),
        _sync_master_switch_rows=lambda *_: 0, sender=lambda: None,
        _flash_card_border=lambda *_: None,
    )
    gui_widget.MainWindow._on_switch_changed(fake, "hud_rules_enabled", False)

    text = open(runtime_cfg, encoding="utf-8").read()
    assert f"cl_hud_color {default}" in text, (
        f"关掉动态 HUD 之后运行时 cfg 还是「{text.strip()}」—— 移动/开火键照样 exec 它，"
        "HUD 就卡在关之前那一帧的颜色，直到退出软件")


# ============================================ 闪光白屏跟着游戏走（副屏，同日用户点名）
#
# 9. 闪光进程的窗口以前钉在 (0,0)、尺寸取主屏 ⇒ 游戏开在副屏时白屏盖在另一块屏上。
#    准心 / 击杀图标早就按「游戏在哪块屏」画了（`crosshair_overlay.game_screen_device_name`），
#    闪光是被落下的那一个。现在：闪光开始那一下父进程带上设备名，子进程主循环按它挪窗口。

#: 真值形如 `\\.\DISPLAY2`（GDI 设备名）；对这段逻辑它只是一个拿来比对的字符串。
_GAME_SCREEN = "DISPLAY2"


def test_a_flash_start_tells_the_flash_process_which_monitor_the_game_is_on(monkeypatch):
    import queue

    import flash_process_manager as fpm

    q = queue.Queue()
    fake = types.SimpleNamespace(
        is_running=True, command_queue=q, current_flash_value=0,
        config=types.SimpleNamespace(flash_image_rotation="none"),
        audio_enabled=False, audio_style="none", audio_auto_stop=False,
    )
    fake._clear_pending_flash_updates = types.MethodType(
        fpm.FlashProcessManager._clear_pending_flash_updates, fake)
    monkeypatch.setattr(fpm, "_game_monitor_device", lambda: _GAME_SCREEN)

    fpm.FlashProcessManager.update_flash_value(fake, 255)          # 0 → 255：闪光开始
    first = list(q.queue)
    assert first == [{"type": "update_flash", "value": 255, "monitor": _GAME_SCREEN}], (
        f"闪光开始那条命令没带游戏所在屏：{first} —— 子进程就只会画在主屏")

    fpm.FlashProcessManager.update_flash_value(fake, 200)          # 子进程还没取走就来了下一帧
    after = list(q.queue)
    assert after == [{"type": "update_flash", "value": 200, "monitor": _GAME_SCREEN}], (
        f"开始那条被「只留最新一帧」清掉了，屏幕信息也跟着丢了：{after}")


def test_the_flash_process_moves_its_window_to_the_game_monitor(tmp_path):
    import json
    import subprocess
    import sys
    from pathlib import Path

    repo = Path(__file__).resolve().parents[1]
    probe = tmp_path / "flash_monitor_probe.py"
    # ⚠ 子进程里跑：import flash_process 会改本进程的 DPI 感知，不许污染 pytest 进程。
    #   不调 initialize() —— 不开真窗口（§3）；显示器列表用替身，窗口移动只记账。
    probe.write_text(
        "import inspect, json, queue, sys\n"
        f"sys.path.insert(0, {str(repo)!r})\n"
        "import flash_process as fp\n"
        "mons = [('DISPLAY1', (0, 0, 1920, 1080), True),\n"
        "        ('DISPLAY2', (1920, 0, 2560, 1440), False)]\n"
        "fp._list_monitors = lambda: mons\n"
        "fe = fp.FlashEffectProcess()\n"
        "fe.is_running = True\n"
        "moved = []\n"
        "fe._move_to = lambda rect: moved.append(list(rect))\n"
        "q = queue.Queue()\n"
        "q.put({'type': 'update_flash', 'value': 200, 'monitor': mons[1][0]})\n"
        "q.put({'type': 'shutdown'})\n"
        "fp.process_commands(q, fe)\n"
        "fe._apply_pending_monitor()\n"
        "after_dispatch = [list(m) for m in moved]   # ⚠ 下面还会直接 request，别让它替命令分发把活干了\n"
        "fe.request_monitor(mons[1][0]); fe._apply_pending_monitor()   # 还在副屏 ⇒ 不动\n"
        "fe.request_monitor(mons[0][0]); fe._apply_pending_monitor()   # 游戏拖回主屏 ⇒ 挪回来\n"
        "# 单屏玩家 4:3 拉伸打独占全屏：显示模式一切，这块屏的矩形就变了 —— 还是同一块屏，不许动\n"
        "fp._list_monitors = lambda: [('DISPLAY1', (0, 0, 1280, 960), True)]\n"
        "fe.request_monitor(None); fe._apply_pending_monitor()\n"
        "single = fp.FlashEffectProcess()\n"
        "single._move_to = lambda rect: moved.append(['single'] + list(rect))\n"
        "single.request_monitor(None); single._apply_pending_monitor()   # 从没换过屏的单屏进程\n"
        "# 真的 _move_to：只替掉 pygame / Win32 两个出口，量它交给 SetWindowPos 的标志\n"
        "flags = []\n"
        "fp.pygame.display.set_mode = lambda *a, **k: None\n"
        "fp.win32gui.SetWindowPos = lambda *a: flags.append(a[-1])\n"
        "real = fp.FlashEffectProcess()\n"
        "real._style_window = lambda: 1\n"
        "real.screen_width, real.screen_height = 1920, 1080\n"
        "real._move_to((1920, 0, 2560, 1440))\n"
        "NOACT = fp.win32con.SWP_NOACTIVATE\n"
        "out = {'moved': moved, 'after_dispatch': after_dispatch,\n"
        "       'none': list(fp.monitor_rect(None, mons)),\n"
        "       'unknown': list(fp.monitor_rect('DISPLAY9', mons)),\n"
        "       'loop_applies': 'self._apply_pending_monitor()' in inspect.getsource(fe.main_loop),\n"
        "       'noactivate': bool(flags) and all(f & NOACT for f in flags),\n"
        "       'resized_to': [real.screen_width, real.screen_height]}\n"
        "print('RESULT ' + json.dumps(out))\n",
        encoding="utf-8")
    proc = subprocess.run([sys.executable, str(probe)], capture_output=True, text=True,
                          encoding="utf-8", errors="replace", timeout=120)
    line = next((ln for ln in proc.stdout.splitlines() if ln.startswith("RESULT ")), None)
    assert line, f"探针没跑完：\n{proc.stdout[-1500:]}\n{proc.stderr[-1500:]}"
    got = json.loads(line[len("RESULT "):])

    assert got["after_dispatch"] == [[1920, 0, 2560, 1440]], (
        f"只经命令队列发了一条带 DISPLAY2 的 update_flash，窗口移动记录却是 {got['after_dispatch']} —— "
        "子进程没把消息里的屏幕信息接住（两端协议只接了一半）")
    assert got["moved"] == [[1920, 0, 2560, 1440], [0, 0, 1920, 1080]], (
        f"期望：挪到副屏一次、拖回主屏再挪一次、其余一步不动；实际移动记录 {got['moved']}。"
        "少了第一条 = 白屏盖在主屏上；多出来的 = 同一块屏上也在挪 / 重建画布"
        "（单屏玩家 4:3 拉伸切显示模式时就会中招，外审 S5 复跑 1/3）")
    assert got["none"] == [0, 0, 1920, 1080] and got["unknown"] == [0, 0, 1920, 1080], (
        f"认不出游戏在哪块屏时必须退回主屏（= 改前的行为），实际 {got['none']} / {got['unknown']}")
    assert got["loop_applies"], "主循环里没调 `_apply_pending_monitor` —— 命令线程记下了也没人去挪"
    assert got["noactivate"], (
        "换屏那一下的 SetWindowPos 没带 SWP_NOACTIVATE —— 它发生在打游戏中途、被闪的那一刻，"
        "不带就会激活白屏窗口、把焦点从 CS2 抢走（外审 S5 3/3）")
    assert got["resized_to"] == [2560, 1440], f"换到分辨率不同的屏，画布没跟着换：{got['resized_to']}"


# ================================================= 收尾那三件（同日，外审 / 审查的候选）

def test_every_flash_window_placement_leaves_the_game_focused():
    """闪光进程里**每一处** SetWindowPos 都带 SWP_NOACTIVATE。

    启动时那一处以前没带：健康监控重启闪光进程时玩家可能正在游戏里，会被抢走焦点。
    ⚠ 走 AST（那一处在 `initialize()` 里、会开真窗口，§3 不许跑）；分母至少两处，防空转。
    """
    import ast
    from pathlib import Path

    src = (Path(__file__).resolve().parents[1] / "flash_process.py").read_text(encoding="utf-8")
    calls = [n for n in ast.walk(ast.parse(src))
             if isinstance(n, ast.Call) and getattr(n.func, "attr", "") == "SetWindowPos"]
    assert len(calls) >= 2, f"只找到 {len(calls)} 处 SetWindowPos —— 判据没了分母"
    missing = [c.lineno for c in calls if "SWP_NOACTIVATE" not in ast.unparse(c.args[-1])]
    assert not missing, (
        f"flash_process.py 第 {missing} 行的 SetWindowPos 没带 SWP_NOACTIVATE —— "
        "闪光窗口是全屏置顶的，一激活就把焦点从 CS2 抢走")

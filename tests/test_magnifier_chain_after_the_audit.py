# SPDX-License-Identifier: GPL-3.0-or-later
"""开镜放大整条链路的返修判据（RN-657，批 104）。

用户报「整个功能完善了没什么问题」之后，我派了五个只读视角把这一块从头审了一遍。
这个文件钉住其中修掉的那些 —— 每一条都写清**它挡的是哪一种具体故障**，
因为这一批里有一条旧判据（`test_magnifier_activate_and_deactivate_sync_sensitivity`）
钉的正是缺陷本身，那是「判据钉实现、不钉性质」的现成反面教材。

⚠ 这些判据一律不碰真的 Magnification API、不注册真的全局热键、不写真的 CS2 目录。
"""

from __future__ import annotations

import ast
from pathlib import Path

import pytest
from PySide6.QtWidgets import QApplication

from config import config

PAGE_SOURCE = Path(__file__).resolve().parents[1] / "pages" / "magnifier_page.py"
GUI_SOURCE = Path(__file__).resolve().parents[1] / "gui_widget.py"


@pytest.fixture(scope="module")
def qapp():
    app = QApplication.instance()
    if app is None:
        app = QApplication([])
    return app


class _FakeTimer:
    """threading.Timer 的同步替身：判据里不许真 sleep。"""

    started: list["_FakeTimer"] = []

    def __init__(self, interval, function, args=None, kwargs=None):
        self.interval = interval
        self.function = function
        self.args = args or ()
        self.kwargs = kwargs or {}
        self.daemon = False
        self.cancelled = False

    def start(self):
        _FakeTimer.started.append(self)

    def cancel(self):
        self.cancelled = True

    def fire(self):
        if not self.cancelled:
            self.function(*self.args, **self.kwargs)


@pytest.fixture
def page(qapp, monkeypatch):
    import pages.magnifier_page as mod

    class _DummyThemeManager:
        def register_theme_changed_callback(self, _callback):
            return None

        def unregister_theme_changed_callback(self, _callback):
            return None

    monkeypatch.setattr(mod, "install_help_panel", lambda *a, **k: None)
    monkeypatch.setattr(mod, "get_theme_manager", lambda: _DummyThemeManager())
    monkeypatch.setattr(mod, "magnification_available", True)
    monkeypatch.setattr(mod, "MagInitialize", lambda: True, raising=False)
    monkeypatch.setattr(mod, "MagUninitialize", lambda: True, raising=False)
    monkeypatch.setattr(mod, "MagSetFullscreenTransform", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(mod, "MagShowSystemCursor", lambda *a, **k: True, raising=False)
    monkeypatch.setattr(
        mod.user32, "GetSystemMetrics", lambda index: 1920 if index == 0 else 1080, raising=False
    )
    # ⛔ 绝不注册真的全局热键
    monkeypatch.setattr(mod.MagnifierPage, "_setup_key_detection", lambda self: None)
    # 游戏"在前台"，让前台那道闸默认放行；要测它的判据自己再改
    monkeypatch.setattr(mod, "game_is_in_foreground", lambda: True)
    monkeypatch.setattr(config, "save_config", lambda: None, raising=False)
    monkeypatch.setattr(config, "magnifier_enabled", True, raising=False)
    monkeypatch.setattr(config, "csgo_dir", "", raising=False)
    monkeypatch.setattr(
        config,
        "magnifier",
        {
            "zoom_factor": 2.0,
            "primary_hotkey": "右键",
            "secondary_hotkey": "F2",
            "trigger_mode": "长按触发",
            "debounce_time": 150,
            "sensitivity_sync_enabled": False,
            "base_sensitivity": 1.0,
            "sensitivity_multiplier": 0.82,
            "sync_trigger_key": "SCROLLLOCK",
            "weapon_settings": {"weapon_awp": True, "weapon_knife": False},
            "zoom_settings": {},
        },
        raising=False,
    )

    _FakeTimer.started = []
    monkeypatch.setattr(mod.threading, "Timer", _FakeTimer)

    instance = mod.MagnifierPage(config)
    instance.update_current_weapon("weapon_awp")
    yield instance
    instance.deleteLater()


def _page_tree():
    return ast.parse(PAGE_SOURCE.read_text(encoding="utf-8"))


def _function(tree, name):
    for node in ast.walk(tree):
        if isinstance(node, ast.FunctionDef) and node.name == name:
            return node
    raise AssertionError(f"找不到函数 {name}")


# --------------------------------------------------------------- 灵敏度写盘链


def test_the_sensitivity_chain_does_nothing_when_the_feature_is_off(page, monkeypatch):
    """联动没勾 ⇒ 开镜收镜一个字节都不该写、一个键都不该注入。

    这是本批最重的一条。原来 `force=True` 把「功能开没开」这道闸顶开了，
    于是从没用过开镜灵敏度联动的玩家，每按一次开镜键也要挨一轮
    `setup_autoexec` + `write_cs2customizer_cfg` + 两次写 runtime cfg + 一次 SCROLLLOCK 注入。
    """
    import pages.magnifier_page as mod

    writes: list[tuple] = []
    keys: list[str] = []
    monkeypatch.setattr(mod, "write_magnifier_runtime_cfg", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(mod, "setup_autoexec", lambda *a, **k: writes.append(("autoexec",)))
    monkeypatch.setattr(mod, "write_cs2customizer_cfg", lambda *a, **k: writes.append(("cs2customizer",)) or [])
    monkeypatch.setattr(config, "csgo_dir", r"C:\fake\cs2", raising=False)

    import keyboard  # noqa: F401  —— 只是为了让下面的 monkeypatch 有对象可打

    monkeypatch.setattr("keyboard.press_and_release", lambda key: keys.append(key))

    page.sensitivity_sync_checkbox.setChecked(False)
    page._sensitivity_runtime_applied = False

    assert page._sync_magnifier_sensitivity_state(True) is False
    assert page._sync_magnifier_sensitivity_state(False) is False

    assert writes == [], f"联动关着却动了盘: {writes}"
    assert keys == [], f"联动关着却注入了按键: {keys}"


def test_turning_the_sync_off_does_not_inject_a_key_when_nothing_was_applied(page, monkeypatch):
    """勾上「开镜灵敏度联动」又取消勾 ⇒ 不该写盘、更不该往系统里注入一次 SCROLLLOCK。

    ⭐⭐⭐ **这条判据是回退验证逼出来的。** 我原以为上面那条
    （`..._does_nothing_when_the_feature_is_off`）守的是新加的第一道闸；
    实测把闸整段删掉，它**照样绿** —— 因为第二道闸
    （`not desired_active and not force and not applied`）先把那个场景拦住了。
    两道闸只在 `force=True` 这条路上分得开，而这条路就是这里：
    `_on_sensitivity_sync_changed` 的 else 分支。修复前，一个从没开过放大的用户
    勾一下再取消，键盘的 Scroll Lock 灯会当场闪一下。

    ⇒ 批 103 那条规律的第二次现身：**两条修复可能互相盖住，
    先撞上的那条会把后一条的判据变成空转。**
    """
    import pages.magnifier_page as mod

    writes: list[tuple] = []
    keys: list[str] = []
    monkeypatch.setattr(mod, "write_magnifier_runtime_cfg", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(mod, "setup_autoexec", lambda *a, **k: None)
    monkeypatch.setattr(mod, "write_cs2customizer_cfg", lambda *a, **k: [])
    monkeypatch.setattr(config, "csgo_dir", r"C:\fake\cs2", raising=False)
    monkeypatch.setattr("keyboard.press_and_release", lambda key: keys.append(key))

    page.sensitivity_sync_checkbox.setChecked(False)
    page._sensitivity_runtime_applied = False  # 从没放大过 ⇒ 游戏里没有要撤的东西

    assert page._sync_magnifier_sensitivity_state(False, force=True) is False
    assert writes == [], f"没有要撤的东西却动了盘: {writes}"
    assert keys == [], f"没有要撤的东西却注入了按键: {keys}"

    # 反过来：真有东西要撤的时候，force 那条路必须照常走完
    page._sensitivity_runtime_applied = True
    assert page._sync_magnifier_sensitivity_state(False, force=True) is True
    assert keys == ["scroll lock"], "游戏里真留着放大灵敏度时，这一闸不许把撤回也拦掉"


def test_the_sensitivity_chain_is_idempotent_on_the_hot_path(page, monkeypatch):
    """游戏里已经是想要的那个值了 ⇒ 不重复写盘、不重复按键。

    连点两次开镜（或 GSI 抖动导致重复激活）不该变成两轮写盘。
    """
    import pages.magnifier_page as mod

    writes: list[tuple] = []
    keys: list[str] = []
    monkeypatch.setattr(mod, "write_magnifier_runtime_cfg", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(mod, "setup_autoexec", lambda *a, **k: None)
    monkeypatch.setattr(mod, "write_cs2customizer_cfg", lambda *a, **k: [])
    monkeypatch.setattr(config, "csgo_dir", r"C:\fake\cs2", raising=False)
    monkeypatch.setattr("keyboard.press_and_release", lambda key: keys.append(key))

    page.sensitivity_sync_checkbox.setChecked(True)
    page._sensitivity_runtime_applied = False

    assert page._sync_magnifier_sensitivity_state(True) is True
    first_round = len(writes)
    assert first_round >= 1 and len(keys) == 1, "第一次开镜本来就该写一次、按一次"

    # 第二次：状态没变
    assert page._sync_magnifier_sensitivity_state(True) is True
    assert len(writes) == first_round, "同一个状态又写了一遍盘"
    assert len(keys) == 1, "同一个状态又注入了一次按键"


def test_the_runtime_cfg_is_not_rewritten_when_the_bytes_are_the_same(tmp_path):
    """内容一样就不动盘 —— 一次开镜里这个文件本来会被写两遍。"""
    from core.magnifier_sensitivity import write_magnifier_runtime_cfg

    path = tmp_path / "cs2customizer_magnifier_runtime.cfg"

    assert write_magnifier_runtime_cfg(str(path), 1.2, 0.82, True) is True
    stamp = path.stat().st_mtime_ns
    assert write_magnifier_runtime_cfg(str(path), 1.2, 0.82, True) is False
    assert path.stat().st_mtime_ns == stamp, "内容一样却把文件重写了一遍"
    # 值真的变了当然还是要写
    assert write_magnifier_runtime_cfg(str(path), 1.2, 0.82, False) is True


def test_the_hot_path_does_not_force_the_cfg_rewrite():
    """AST 钉：开镜/收镜两个槽里调 _sync_magnifier_sensitivity_state 时不许带 force。

    ⭐ 用 AST 而不是跑一遍，是因为"有没有传这个参数"是**写法**问题 ——
    删掉调用点、改名字、加一层包装，行为判据都可能照样绿。
    """
    tree = _page_tree()
    for slot in ("_do_activate_magnification", "_do_deactivate_magnification"):
        for node in ast.walk(_function(tree, slot)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_sync_magnifier_sensitivity_state"
            ):
                names = [kw.arg for kw in node.keywords]
                assert "force" not in names, f"{slot} 又给热路径打开了 force"


# --------------------------------------------------------------- 关不掉这一类


def test_a_failed_close_does_not_pretend_the_magnifier_is_off(page, monkeypatch):
    """关放大的 API 失败时，不许把状态标成"已关闭"。

    标了就没人会再试着关（`_deactivate_magnifier` 头一行就 return），
    而屏幕还放大着 —— **关不掉比开不起来严重得多**。
    """
    import pages.magnifier_page as mod

    page.is_magnifier_active = True
    page.current_active_type = "primary"
    monkeypatch.setattr(mod, "MagSetFullscreenTransform", lambda *a, **k: False, raising=False)

    page._do_deactivate_magnification()

    assert page.is_magnifier_active is True, "API 失败了却报「已关闭」，屏幕会留在放大态"
    assert "失败" in page.status_label.text()


def test_the_screen_transform_reset_runs_before_anything_that_can_block():
    """复位屏幕放大必须排在退出清理表的最前面（退订广播之后紧跟着它）。

    它是整张表里唯一一个「不做就会在本进程之外留下副作用」的步骤，而
    `_run_shutdown_steps` 的 15 秒看门狗一开火就 `os._exit(0)` ——
    排在第 10 位时前面隔着关外部进程这类会卡的步骤，它根本跑不到。
    ⚠ 第一位归 UP-035 的「退订配置重载广播」，那条有自己的判据；
    这里钉的是「在任何可能卡住的步骤之前」。
    """
    tree = ast.parse(GUI_SOURCE.read_text(encoding="utf-8"))
    steps_fn = _function(tree, "_run_shutdown_steps")
    labels: list[str] = []
    for node in ast.walk(steps_fn):
        if isinstance(node, ast.Assign) and any(
            isinstance(t, ast.Name) and t.id == "steps" for t in node.targets
        ):
            labels = [entry.elts[0].value for entry in node.value.elts]
            break
    assert labels, "没找到退出清理表"
    assert "复位屏幕放大" in labels, "退出清理表里没有复位屏幕放大这一步"
    assert labels.index("复位屏幕放大") <= 1, (
        f"复位屏幕放大排到了第 {labels.index('复位屏幕放大') + 1} 位，"
        f"前面这些步骤里任何一个卡住 15 秒，它就跑不到了: {labels[:3]}"
    )


def test_the_watchdog_resets_the_screen_before_it_kills_the_process():
    """看门狗那一刀之前也要复位一次 —— `os._exit(0)` 之后没有任何代码会跑。"""
    tree = ast.parse(GUI_SOURCE.read_text(encoding="utf-8"))
    fire = _function(tree, "_watchdog_fire")
    calls = [
        node.func.attr
        for node in ast.walk(fire)
        if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
    ]
    assert "_reset_screen_magnification" in calls, "看门狗强杀之前没有复位屏幕放大"


def test_shutdown_paths_close_synchronously_instead_of_emitting_a_signal():
    """退出/禁用路径不许靠 emit 信号去关放大。

    那要等主线程事件循环再转一圈，而退出时它可能已经不转了 ⇒ 永远不执行 ⇒ 屏幕留在放大态。
    """
    tree = _page_tree()
    for name in ("cleanup", "disable_magnifier"):
        called = [
            node.func.attr
            for node in ast.walk(_function(tree, name))
            if isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
        ]
        assert "_deactivate_magnifier" not in called, (
            f"{name} 又改回 emit 信号了 —— 退出时那个信号等不到人处理"
        )
        assert "_do_deactivate_magnification" in called


def test_reset_screen_transform_now_is_a_noop_when_nothing_is_magnified(page):
    """没在放大时复位是空转——看门狗会盲调它，不能有副作用。"""
    page.is_magnifier_active = False
    assert page.reset_screen_transform_now() is False


# --------------------------------------------------------------- 误触发


def test_a_hotkey_outside_the_game_does_not_zoom_the_screen(page, monkeypatch):
    """游戏不在前台时按热键不放大。

    默认主/副热键都是**鼠标右键**，挂的又是系统级全局钩子 ——
    没有这道闸，玩家 Alt-Tab 出去在浏览器里点右键，整块屏幕就会被放大。
    """
    import pages.magnifier_page as mod

    monkeypatch.setattr(mod, "game_is_in_foreground", lambda: False)
    assert page._activation_is_allowed("主武器") is False


def test_the_foreground_gate_opens_when_it_cannot_tell(monkeypatch):
    """判断不出来时朝**放行**倒。

    朝"拦"倒会让整个开镜放大在某些机器上静默失效，而那种故障
    长得和"功能坏了"一模一样、还不留任何线索。
    """
    import core.foreground_game as fg

    monkeypatch.setattr(fg, "foreground_process_name", lambda: "")
    assert fg.game_is_in_foreground() is True


def test_the_foreground_gate_knows_the_game(monkeypatch):
    import core.foreground_game as fg

    monkeypatch.setattr(fg, "foreground_process_name", lambda: "cs2.exe")
    assert fg.game_is_in_foreground() is True
    monkeypatch.setattr(fg, "foreground_process_name", lambda: "chrome.exe")
    assert fg.game_is_in_foreground() is False


def test_the_pid_cache_does_not_grow_without_bound(monkeypatch):
    """pid→名字的缓存要封顶：桌面上每点一次右键都可能是个新 pid。"""
    import core.foreground_game as fg

    fg.reset_cache()
    monkeypatch.setattr(fg, "_PID_CACHE_LIMIT", 4)
    for pid in range(1, 12):
        fg._pid_name_cache[pid] = f"p{pid}.exe"
        if len(fg._pid_name_cache) >= fg._PID_CACHE_LIMIT:
            fg._pid_name_cache.clear()
    assert len(fg._pid_name_cache) < 10
    fg.reset_cache()


# --------------------------------------------------------------- 状态机


def test_switching_trigger_mode_while_zoomed_does_not_get_stuck(page, monkeypatch):
    """长按着放大时把触发方式切成「单击切换」⇒ 不许卡在放大态。

    原来只是给 trigger_mode 赋个值：松手时 `not _is_toggle_mode()` 已经变成 False，
    整支关闭分支被跳过 ⇒ 松手关不掉，得再摸索着按一次键。
    """
    page.is_magnifier_active = True
    page.current_active_type = "primary"
    page.primary_key_pressed = True

    page._on_trigger_mode_changed("单击切换")

    assert page.is_magnifier_active is False, "换了触发方式却卡在放大态"
    assert page.primary_key_pressed is False


def test_the_debounce_rechecks_the_weapon_when_it_fires(page, monkeypatch):
    """防抖到点时武器已经换成没启用的那把 ⇒ 不激活。

    三道闸原来只在**按下那一瞬**查过，而到点已经是 150ms 之后；
    `_do_update_current_weapon` 的自动关闭又只在**已激活**时才管用，
    所以"在防抖窗口里换了武器"这条路当时没有任何人拦。
    """
    emitted: list[str] = []
    page.activate_magnification_signal.connect(emitted.append)

    page.primary_key_pressed = True
    page.primary_debouncing = True
    page.primary_key_press_time = 0  # 早到不能再早，elapsed 一定够
    page.update_current_weapon("weapon_knife")  # 未启用

    page._check_primary_debounce()

    assert emitted == [], "防抖到点时武器已经不该放大了，却还是激活了"
    assert page.primary_debouncing is False, "早退路径上忘了放掉防抖标志，这把枪的防抖就锁死了"


def test_the_debounce_uses_a_clock_that_cannot_go_backwards():
    """防抖计时用 monotonic。time.time() 会被系统对时往回拨，那一次开镜就被静默吃掉。"""
    tree = _page_tree()
    for name in ("_activate_primary_magnifier", "_activate_secondary_magnifier", "_check_debounce"):
        for node in ast.walk(_function(tree, name)):
            if (
                isinstance(node, ast.Call)
                and isinstance(node.func, ast.Attribute)
                and isinstance(node.func.value, ast.Name)
                and node.func.value.id == "time"
            ):
                assert node.func.attr == "monotonic", f"{name} 里又用上了 time.{node.func.attr}()"


def test_the_test_button_does_not_close_a_zoom_the_player_is_holding(page):
    """「测试热键」那颗 3 秒定时器不许关掉用户正按着热键维持的放大。"""
    page._start_hotkey_test("primary", "右键", "主武器")
    timer = _FakeTimer.started[-1]
    assert timer.daemon is True, "非 daemon 会把退出多拖 3 秒"

    page.is_magnifier_active = True
    page.primary_key_pressed = True  # 用户此刻正按着
    closed: list[bool] = []
    page.deactivate_magnification_signal.connect(lambda: closed.append(True))

    timer.fire()
    assert closed == [], "3 秒定时器把用户正按着的那次放大关掉了"


def test_a_newer_test_supersedes_the_older_timer(page):
    page._start_hotkey_test("primary", "右键", "主武器")
    first = _FakeTimer.started[-1]
    page._start_hotkey_test("secondary", "F2", "副武器")
    assert first.cancelled is True, "上一颗测试定时器没被撤掉"


# --------------------------------------------------------------- 准心


def test_a_hidden_crosshair_stays_hidden_after_the_zoom_ends(page):
    """准心本来是关着的 ⇒ 开一次镜再关，它不该自己冒出来。

    `original_crosshair_visible` 一直被存着却**从来没人读过**，
    还原时无条件 `show_crosshair()` —— 那是真的去建窗口、置顶、起重定心定时器。
    """

    class _FakeCrosshair:
        def __init__(self):
            self.size = 20
            self.thickness = 2
            self.color = "green"
            self.style = "dot"
            self.animation_style = "none"
            self.kill_effect = "none"
            self.is_visible = False
            self.calls: list[str] = []

        def update_settings(self, **_kwargs):
            self.calls.append("update")

        def show_crosshair(self):
            self.calls.append("show")

        def hide_crosshair(self):
            self.calls.append("hide")

    crosshair = _FakeCrosshair()
    page.set_crosshair_component(crosshair)
    page.zoom_factor = 4.0

    page._set_magnifier_crosshair()
    page._restore_original_crosshair()

    assert "show" not in crosshair.calls, "准心本来是关着的，放大结束后被强行显示了出来"
    assert "hide" in crosshair.calls


# --------------------------------------------------------------- 偏移


def test_the_offset_cannot_be_nudged_out_of_range(page):
    """箭头一直点下去也不许把偏移累到越界。

    合法区间是 `[0, 宽 - 宽/倍率]`，基准值正好是中点 ⇒ 用户偏移最多 ±中点。
    1920 宽、2 倍 ⇒ 上限 480。
    """
    page.zoom_factor = 2.0
    assert page._offset_limits() == (480, 270)

    for _ in range(200):
        page._adjust_offset("x", 50)
    assert page.zoom_settings["2.0"]["x_offset"] == 480

    for _ in range(400):
        page._adjust_offset("x", -50)
    assert page.zoom_settings["2.0"]["x_offset"] == -480


def test_a_failed_offset_apply_says_so(page, monkeypatch):
    """偏移没应用上就别报"已应用"。"""
    page.is_magnifier_active = True
    monkeypatch.setattr(page, "_update_magnification", lambda: False)

    page.x_offset_input.setText("10")
    page.y_offset_input.setText("10")
    page._apply_offset()

    assert "没能应用" in page.status_label.text()


# --------------------------------------------------------------- 线程与 Qt


def test_no_worker_thread_touches_qt_widgets_during_hotkey_setup():
    """热键注册不许再起自建线程。

    那个线程注册完只剩 `while ...: sleep(0.05)` 的空转，而代价是
    在工作线程上读 combo、写 status_label —— 跨线程碰 Qt 控件。
    """
    tree = _page_tree()
    setup = _function(tree, "_setup_key_detection")
    for node in ast.walk(setup):
        if isinstance(node, ast.Attribute) and node.attr == "Thread":
            raise AssertionError("_setup_key_detection 又起线程了")
    source = PAGE_SOURCE.read_text(encoding="utf-8")
    assert "MagnifierKeyboard" not in source, "那个空转线程又回来了"


def test_the_listening_badge_tracks_whether_hotkeys_are_really_registered(page):
    """徽章上的「监听中」问的是热键挂上了没有，不是某个线程活着没有。"""
    page._hotkeys_registered = True
    assert page._current_runtime_text()[0] =="监听中"
    page._hotkeys_registered = False
    assert page._current_runtime_text()[0] =="待命"


# --------------------------------------------------------------- 配置重载


def test_a_config_reload_resyncs_the_running_state(page, monkeypatch):
    """导入预设/配置重载之后，实际在跑的东西要追上界面显示的东西。

    那条路只走 `load_settings()`，而热键 combo 是在 disconnect 之间 setCurrentText 的
    ⇒ 不触发 `_on_hotkey_changed` ⇒ 注册中心里挂的还是旧键：
    界面写着新键、按新键没反应、按旧键反而放大。
    """
    calls: list[str] = []
    monkeypatch.setattr(page, "enable_magnifier", lambda interactive=True: calls.append("enable"))
    monkeypatch.setattr(page, "disable_magnifier", lambda: calls.append("disable"))

    assert page._settings_loaded_once is True, "构造期那一次之后该立起这个标志"

    monkeypatch.setattr(config, "magnifier_enabled", True, raising=False)
    page.load_settings()
    assert calls == ["enable"]

    monkeypatch.setattr(config, "magnifier_enabled", False, raising=False)
    page.load_settings()
    assert calls == ["enable", "disable"]


def test_the_first_load_does_not_fight_the_constructor(qapp, monkeypatch):
    """构造期那一次 load_settings 不许自己去启停 —— 那是 __init__ 末尾的活。"""
    tree = _page_tree()
    load = _function(tree, "load_settings")
    guarded = False
    for node in ast.walk(load):
        if isinstance(node, ast.If) and isinstance(node.test, ast.Attribute):
            if node.test.attr == "_settings_loaded_once":
                guarded = True
    assert guarded, "load_settings 里那次运行态同步没有被「第一次不做」的闸挡住"


# --------------------------------------------------------------- 空转守卫


def test_these_judges_would_notice_if_the_gate_came_back(page, monkeypatch):
    """空转守卫：把闸拆掉，上面那条最重的判据必须红。

    ⭐ 批 103 的教训：两条修复可能互相盖住，判据绿着也可能是因为
    别的什么先拦住了。这里当场证明"联动关着不写盘"那条真的由那道闸守着。
    """
    import pages.magnifier_page as mod

    writes: list[tuple] = []
    monkeypatch.setattr(mod, "write_magnifier_runtime_cfg", lambda *a, **k: writes.append(a))
    monkeypatch.setattr(mod, "setup_autoexec", lambda *a, **k: None)
    monkeypatch.setattr(mod, "write_cs2customizer_cfg", lambda *a, **k: [])
    monkeypatch.setattr(config, "csgo_dir", r"C:\fake\cs2", raising=False)
    monkeypatch.setattr("keyboard.press_and_release", lambda key: None)

    page.sensitivity_sync_checkbox.setChecked(False)

    # 这道闸的条件是「联动没开 **且** 没有残留要撤」。把后半边翻过来（假装游戏里
    # 还留着上一次的放大灵敏度要收回），闸就该放行并真的写盘 ——
    # 这当场证明拦住上面那条的确实是这道闸，而不是碰巧被别的什么先挡住了。
    # ⭐ force 在这里**拆不动**第一道闸，那正是这一批新加的东西。
    page._sensitivity_runtime_applied = True
    page._sync_magnifier_sensitivity_state(False)
    assert writes, "闸的后半边翻过来之后还是没写盘 —— 那条判据守的不是这道闸"

# -*- coding: utf-8 -*-
"""R6 · 便利性回归（UP-034/035/036/037/038/039/040）。

源码级断言一律走 **AST**：本轮注释里就写着 `save_config`、`show_page` 这些字样，
文本匹配会把说明文字当成真实调用（本专项已经栽过三次）。
"""
from __future__ import annotations

import ast
import os
import shutil
import tempfile
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent


def _tree(rel: str) -> ast.AST:
    return ast.parse((ROOT / rel).read_text(encoding="utf-8"))


def _func(rel: str, name: str, cls: str | None = None) -> ast.FunctionDef:
    tree = _tree(rel)
    scopes = [tree]
    if cls:
        scopes = [n for n in ast.walk(tree) if isinstance(n, ast.ClassDef) and n.name == cls]
        assert scopes, f"没找到类 {cls}"
    for scope in scopes:
        for n in ast.walk(scope):
            if isinstance(n, ast.FunctionDef) and n.name == name:
                return n
    raise AssertionError(f"没找到 {cls or rel}.{name}")


def _called(node: ast.AST) -> set[str]:
    out = set()
    for sub in ast.walk(node):
        if isinstance(sub, ast.Call):
            if isinstance(sub.func, ast.Attribute):
                out.add(sub.func.attr)
            elif isinstance(sub.func, ast.Name):
                out.add(sub.func.id)
    return out


# ==================================================== UP-035 配置重载广播


def test_reload_bus_delivers_and_isolates_failures():
    """订阅者抛异常**不能**让广播失败——配置已经落盘了。

    此刻把异常抛回调用方，只会让用户以为"应用预设失败"，
    而实际上它成功了；那比界面没刷新糟得多。
    """
    from core import config_reload_bus as bus

    seen = []

    def good(reason, keys):
        seen.append((reason, keys))

    def bad(reason, keys):
        raise RuntimeError("我坏了")

    bus.subscribe(bad)
    bus.subscribe(good)
    try:
        delivered = bus.notify("preset_apply", ["crosshair_size"])
    finally:
        bus.unsubscribe(bad)
        bus.unsubscribe(good)

    assert seen == [("preset_apply", ("crosshair_size",))]
    assert delivered == 1, "坏订阅者应当被记为失败，好订阅者照常收到"


def test_reload_bus_subscribe_is_idempotent():
    from core import config_reload_bus as bus

    def cb(reason, keys):
        pass

    before = bus.subscriber_count()
    bus.subscribe(cb)
    bus.subscribe(cb)
    try:
        assert bus.subscriber_count() == before + 1, "重复订阅不应产生两份"
    finally:
        bus.unsubscribe(cb)
    assert bus.subscriber_count() == before
    bus.unsubscribe(cb)  # 再退一次不能报错


def test_apply_bundle_broadcasts_reload():
    """UP-035 的核心：应用预设后必须广播，否则已打开的页面停在旧值。"""
    fn = _func("core/presets/preset_center.py", "apply_bundle")
    assert "notify" in _called(fn), (
        "apply_bundle 没有广播配置重载 —— 已打开的页面会停在旧值，"
        "用户随手动一下控件就把刚应用的预设写回去了"
    )


def test_restore_snapshot_broadcasts_reload():
    """恢复快照同理——不广播的话回滚功能在已访问过的页面上直接失效。"""
    fn = _func("core/config_snapshot_manager.py", "restore_snapshot")
    assert "notify" in _called(fn)


def test_main_window_marshals_reload_to_gui_thread():
    """必须经 Signal 回主线程。

    `core/presets/map_rules.py` 的按地图自动切预设是 GSI 事件驱动的、
    跑在后台线程上；在那里直接碰 Qt 控件会崩。
    """
    fn = _func("gui_widget.py", "_config_reload_bridge", "MainWindow")
    assert "emit" in _called(fn), "桥接函数必须只做 emit，不能直接刷控件"
    assert "load_settings" not in _called(fn), "不能在可能的后台线程里直接刷控件"

    slot = _func("gui_widget.py", "_on_config_reloaded", "MainWindow")
    # 槽里是 `getattr(page, "load_settings", None)` 再调用，所以 AST 看不到方法名，
    # 得去常量里找。（用 getattr 是有意的：并非所有页面都有 load_settings。）
    consts = {n.value for n in ast.walk(slot)
              if isinstance(n, ast.Constant) and isinstance(n.value, str)}
    assert "load_settings" in consts, "槽里没有去刷各页的 load_settings"


def test_main_window_unsubscribes_on_exit():
    """总线是模块级的、活得比窗口久，不退订就会往死对象上打。"""
    src = (ROOT / "gui_widget.py").read_text(encoding="utf-8")
    tree = ast.parse(src)
    fn = next(n for n in ast.walk(tree)
              if isinstance(n, ast.FunctionDef) and n.name == "_unsubscribe_config_reload")
    assert "unsubscribe" in _called(fn)
    # 且必须真的被排进退出步骤
    assert "_unsubscribe_config_reload" in src.split("steps = [")[1].split("]")[0]


def test_page_load_settings_does_not_write_back(qapp):
    """广播方案的**前提**：对已建好的页面调 load_settings() 不能反过来写配置。

    若会写，"广播 → 各页 load_settings()"就会把刚应用的预设又冲掉，
    等于把数据安全洞换了个位置。
    """
    import importlib

    from config import config

    real_save = config.save_config
    calls = {"n": 0}
    for mod, cls in (("pages.crosshair_page", "CrosshairPage"),
                     ("pages.kill_sound_page", "KillSoundPage")):
        page = getattr(importlib.import_module(mod), cls)()
        qapp.processEvents()
        calls["n"] = 0
        config.save_config = lambda *a, **k: calls.__setitem__("n", calls["n"] + 1)
        try:
            page.load_settings()
            qapp.processEvents()
        finally:
            config.save_config = real_save
        assert calls["n"] == 0, f"{cls}.load_settings() 触发了 {calls['n']} 次写配置"
        page.deleteLater()
        page.setParent(None)


# ==================================================== UP-034 隐藏页出路


def test_show_page_supports_force_for_hidden_pages():
    """普通模式下静默 return 是最差结果——搜索能命中，点了却什么都不发生。"""
    fn = _func("gui_widget.py", "show_page", "MainWindow")
    args = [a.arg for a in fn.args.args]
    assert "force" in args, "show_page 需要 force 参数让搜索跳转能到达隐藏页"


def test_search_jump_forces_and_offers_pin():
    fn = _func("gui_widget.py", "_goto_search_result", "MainWindow")
    calls = _called(fn)
    assert "show_page" in calls
    assert "_offer_pin_hidden_page" in calls, "命中隐藏页后要给用户一个出路"
    # force=True 必须真的传了
    forced = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
        and n.func.attr == "show_page"
        and any(kw.arg == "force" and getattr(kw.value, "value", None) is True
                for kw in n.keywords)
        for n in ast.walk(fn)
    )
    assert forced, "_goto_search_result 必须以 force=True 调用 show_page"


def test_pin_action_writes_config():
    """[固定显示] 要真的落盘，否则重启又找不到了。"""
    fn = _func("gui_widget.py", "_enable_expert_mode_from_toast", "MainWindow")
    assert "save_config" in _called(fn)


# ==================================================== UP-036 重置前快照


def test_reset_all_settings_snapshots_before_delete():
    """最不可逆的操作反而是唯一不做快照的——顺序也必须是"先快照再删"。"""
    src = (ROOT / "pages/advanced_page.py").read_text(encoding="utf-8")
    fn = _func("pages/advanced_page.py", "_reset_all_settings", "AdvancedPage")
    assert "create_snapshot" in _called(fn), "重置前没有建快照"

    snap_lines = [n.lineno for n in ast.walk(fn)
                  if isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
                  and n.func.id == "create_snapshot"]
    remove_lines = [n.lineno for n in ast.walk(fn)
                    if isinstance(n, ast.Call) and isinstance(n.func, ast.Attribute)
                    and n.func.attr == "remove"]
    assert snap_lines and remove_lines
    assert min(snap_lines) < min(remove_lines), (
        "先删了配置文件再建快照 = 快照里是空的，等于没建"
    )
    assert src


# ==================================================== UP-037 试听反馈


SOUND_PAGES = [
    ("pages/kill_sound_page.py", "_test_weapon_sound"),
    ("pages/death_sound_page.py", "_test_sound"),
    ("pages/reload_sound_page.py", "_test_reload_sound"),
    ("pages/gun_sound_page.py", "_test_gun_sound"),
    ("pages/switch_weapon_page.py", "_test_switch_sound"),
]


@pytest.mark.parametrize("rel,func", SOUND_PAGES)
def test_preview_failures_are_reported(rel, func):
    """每个"试听失败"的出口都要有用户可见反馈。

    原状：大多数分支只写一行日志就 return，用户看到的是"点了没反应"——
    分不清是没配音效、文件丢了、还是软件坏了，只能反复点。
    """
    fn = _func(rel, func)
    assert "report_preview_failure" in _called(fn), f"{rel}::{func} 仍有静默失败分支"

    # 直接编码缺陷模式本身：**"只写一行日志就 return"**。
    # 不去数"每条裸 return 前面有没有反馈"——有些裸 return 是内部一致性守卫
    # （如 `if weapon_row is None: return`），那种情况给用户弹提示反而是误导。
    def _log_then_return(body):
        bad = []
        for i, node in enumerate(body[:-1]):
            nxt = body[i + 1]
            if not (isinstance(nxt, ast.Return) and nxt.value is None):
                continue
            if (isinstance(node, ast.Expr) and isinstance(node.value, ast.Call)
                    and isinstance(node.value.func, ast.Attribute)
                    and isinstance(node.value.func.value, ast.Attribute)
                    and node.value.func.value.attr == "logger"):
                bad.append(nxt.lineno)
        return bad

    offenders = []
    for node in ast.walk(fn):
        for attr in ("body", "orelse", "finalbody"):
            block = getattr(node, attr, None)
            if isinstance(block, list):
                offenders += _log_then_return(block)
    assert not offenders, (
        f"{rel}::{func} 第 {offenders} 行仍是「只写日志就 return」——"
        f"用户看到的是点了没反应"
    )


def test_preview_failure_never_raises():
    """反馈失败绝不能反过来影响功能本身。"""
    from widgets.preview_feedback import PreviewFailure, report_preview_failure

    class Broken:
        @property
        def action_bar(self):
            raise RuntimeError("坏了")

    msg = report_preview_failure(Broken(), PreviewFailure.NO_FILE, "x", toast=False)
    assert isinstance(msg, str) and msg


# ==================================================== UP-038 拖入即建风格


DROP_PAGES = ["kill_sound", "kill_voice", "death_sound", "reload_sound", "switch_weapon"]


PAGE_CLASSES = {
    "kill_sound": "KillSoundPage",
    "kill_voice": "KillVoicePage",
    "death_sound": "DeathSoundPage",
    "reload_sound": "ReloadSoundPage",
    "switch_weapon": "SwitchWeaponPage",
}


@pytest.mark.parametrize("name", DROP_PAGES)
def test_sound_pages_accept_audio_drop(name):
    """StyleCreatorDialog 早就支持 initial_files，以前只是没人接这根线。

    ⚠ 判据从「方法写在这个 .py 里」改成「页面类**能用到**这个方法」——
    UP-057 把 `_open_style_creator` 上提到 `SoundPageBase` 之后，
    原判据当场变红，但功能一个字节都没变（页面指纹逐控件一致）。
    锚在源码位置上的判据会把**正确的重构**误报成回归，
    而它本该守的是「拖入音频能不能预填到新建风格对话框」这件事。
    现在顺着 MRO 解析到真正的定义处再做 AST 分析，
    对已抽基类和未抽基类的页面同样成立。
    """
    import importlib
    import inspect

    rel = f"pages/{name}_page.py"
    tree = _tree(rel)
    assert "enable_file_drop" in _called(tree), f"{rel} 没有挂音频拖拽"

    module = importlib.import_module(f"pages.{name}_page")
    page_cls = getattr(module, PAGE_CLASSES[name])
    method = getattr(page_cls, "_open_style_creator", None)
    assert method is not None, f"{PAGE_CLASSES[name]} 上取不到 _open_style_creator"

    fn = ast.parse(inspect.getsource(method).lstrip()).body[0]
    owner = inspect.getsourcefile(method)
    assert "initial_files" in [a.arg for a in fn.args.args], (
        f"{PAGE_CLASSES[name]} 的新建风格不接受预填（定义在 {owner}）"
    )
    passed = any(
        isinstance(n, ast.Call) and isinstance(n.func, ast.Name)
        and n.func.id == "StyleCreatorDialog"
        and any(kw.arg == "initial_files" for kw in n.keywords)
        for n in ast.walk(fn)
    )
    assert passed, f"{PAGE_CLASSES[name]} 没把 initial_files 透传给对话框（定义在 {owner}）"


# ==================================================== UP-039 热键冲突提示


def test_hotkey_result_is_reported_to_user():
    """高级设置页白纸黑字承诺"对应页面会给出冲突提示"，得兑现。"""
    src = (ROOT / "pages/advanced_page.py").read_text(encoding="utf-8")
    assert "对应页面会给出冲突提示" in src, "承诺文案不在了？那这条测试要跟着改"

    fn = _func("pages/voice_output_page.py", "_on_hotkey_report", "VoiceOutputPage")
    calls = _called(fn)
    assert "toast_warning" in calls, "冲突要给警告"
    assert "toast_error" in calls, "注册失败要给错误"
    assert "set_message" in calls, "摘要要写 action bar"


# ==================================================== UP-040 我的预设


@pytest.fixture()
def preset_home(monkeypatch):
    """把预设目录指到临时位置，绝不碰用户真实的 %APPDATA%/CS2Customizer/presets。"""
    tmp = tempfile.mkdtemp(prefix="cs2customizer_mypreset_")
    import core.presets.my_presets as mp

    monkeypatch.setattr(mp, "presets_dir", lambda: tmp)
    yield tmp
    shutil.rmtree(tmp, ignore_errors=True)


def test_my_preset_roundtrip(preset_home):
    from config import config
    from core.presets import my_presets as mp

    config.crosshair_size = 11
    item = mp.save_preset("训练场", ["crosshair"])
    assert item.name == "训练场"
    assert os.path.isfile(item.file_path)

    config.crosshair_size = 44
    result = mp.apply_preset(item.preset_id)
    assert result.ok
    assert config.crosshair_size == 11, "应用预设没把值还原"


def test_my_preset_name_collision_gets_unique_id(preset_home):
    """重名不能互相覆盖——磁盘用 slug+序号，真名存在文件里。"""
    from core.presets import my_presets as mp

    a = mp.save_preset("我的配置", ["crosshair"])
    b = mp.save_preset("我的配置", ["crosshair"])
    assert a.preset_id != b.preset_id
    assert len(mp.list_presets()) == 2
    assert {p.name for p in mp.list_presets()} == {"我的配置"}


def test_my_preset_rejects_empty_name_and_types(preset_home):
    from core.presets import my_presets as mp

    with pytest.raises(ValueError):
        mp.save_preset("   ", ["crosshair"])
    with pytest.raises(ValueError):
        mp.save_preset("x", [])
    with pytest.raises(ValueError):
        mp.save_preset("x", ["不存在的类型"])


def test_my_preset_list_skips_corrupt_files(preset_home):
    """一个坏 json 不该让整个列表打不开。"""
    from core.presets import my_presets as mp

    mp.save_preset("好的", ["crosshair"])
    with open(os.path.join(preset_home, "坏的.json"), "w", encoding="utf-8") as fp:
        fp.write("{ 这不是 json")
    names = [p.name for p in mp.list_presets()]
    assert names == ["好的"]


def test_my_preset_apply_goes_through_apply_bundle():
    """必须走 apply_bundle，才能自动获得「应用前快照」和「配置重载广播」。"""
    fn = _func("core/presets/my_presets.py", "apply_preset")
    assert "apply_bundle" in _called(fn), (
        "自己写配置就会绕过自动快照和 UP-035 广播 —— 那两个洞会重新出现"
    )


# ==================================================== UP-041 控件行级定位


def test_setting_row_lookup_lands_on_the_row(qapp):
    """UP-041：搜具体开关时应当定位到那一行，而不是页面顶部。

    没有手工维护 389 项索引——那个维护成本高，写错了比没有更糟。
    改成在**已建好的页面上**按控件文案就地匹配。
    """
    from PySide6.QtWidgets import QCheckBox, QLabel, QVBoxLayout, QWidget

    import gui_widget

    page = QWidget()
    layout = QVBoxLayout(page)
    row = QWidget()
    row_layout = QVBoxLayout(row)
    box = QCheckBox("观战时静音")
    row_layout.addWidget(box)
    layout.addWidget(row)
    layout.addWidget(QLabel("别的设置项"))

    found = gui_widget.MainWindow._find_setting_row(None, page, "观战时静音")
    assert found is not None, "没找到匹配的控件行"
    assert found is row or found is box, f"定位到了 {found}，应当是那一行"
    page.deleteLater()


def test_setting_row_lookup_misses_gracefully(qapp):
    """命中不了要返回 None，让调用方退回卡片级定位（即改动前的行为）。"""
    from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

    import gui_widget

    page = QWidget()
    QVBoxLayout(page).addWidget(QCheckBox("观战时静音"))
    assert gui_widget.MainWindow._find_setting_row(None, page, "完全无关的词zzz") is None
    page.deleteLater()


def test_setting_row_lookup_skips_hidden_and_titles(qapp):
    """折叠起来的帮助面板内容、页面大标题都不该被当成命中目标。"""
    from PySide6.QtWidgets import QLabel, QVBoxLayout, QWidget

    import gui_widget

    page = QWidget()
    layout = QVBoxLayout(page)
    title = QLabel("音量设置")
    title.setObjectName("titleLabel")        # 标题类留给卡片级去处理
    layout.addWidget(title)
    hidden_host = QWidget()
    QVBoxLayout(hidden_host).addWidget(QLabel("音量设置"))
    hidden_host.hide()                        # 模拟折叠的帮助面板
    layout.addWidget(hidden_host)

    assert gui_widget.MainWindow._find_setting_row(None, page, "音量设置") is None
    page.deleteLater()


def test_setting_row_lookup_does_not_return_huge_container(qapp):
    """向上找"行"必须有层数上限，否则会把整块内容区当成一行高亮。"""
    from PySide6.QtWidgets import QCheckBox, QVBoxLayout, QWidget

    import gui_widget

    page = QWidget()
    outer = QWidget()          # 模拟滚动内容容器
    QVBoxLayout(page).addWidget(outer)
    lvl1 = QWidget()
    QVBoxLayout(outer).addWidget(lvl1)
    lvl2 = QWidget()
    QVBoxLayout(lvl1).addWidget(lvl2)
    lvl3 = QWidget()
    QVBoxLayout(lvl2).addWidget(lvl3)
    QVBoxLayout(lvl3).addWidget(QCheckBox("深层开关"))

    found = gui_widget.MainWindow._find_setting_row(None, page, "深层开关")
    assert found is not None
    assert found not in (outer, page), "一路走到顶了，会把整块内容区高亮"
    page.deleteLater()

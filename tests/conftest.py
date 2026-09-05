# SPDX-License-Identifier: GPL-3.0-or-later
"""
测试配置
"""
import sys
import os
import tempfile

# UI tests run headless in CI/local terminal environments.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 批 47：并行跑全量时，几个 pytest 进程会同时读写下面这两个目录（它们是固定名，
# 理由见 RN-141）。⇒ `run_tests.py --jobs N` 给每一路传一个 `CS2C_TEST_WORKER=_wI`，
# 配置目录和日志目录各自加这个后缀；串行档拿到空串，路径与批 47 之前逐字节一样。
#
# ⛔⛔ **只有这两个能加后缀，游戏沙箱（下面那个）不许加** —— 那条路径
# **被高级设置页原样显示在屏幕上**，指纹钉着它。第一版我图省事直接把整个 TEMP
# 换掉（三个目录一起搬），等价验收当场红：`advanced` 页指纹里那两行
# 「当前使用的 CS2 目录：…」对不上。⭐ **换隔离手段之前，先问这个路径会不会被人看见。**
_cs2customizer_worker = os.environ.get("CS2C_TEST_WORKER", "")

# 测试隔离：把配置目录重定向到临时目录，避免测试中对 config 的夹具改动
# （如 weapon_switch_sounds=styleSwitch）经防抖/atexit/显式 save 写进用户真实配置。
# 必须在任何测试 import config 之前设置（conftest 在收集阶段最先执行）。
_cs2customizer_test_cfg_dir = os.path.join(tempfile.gettempdir(),
                                    "cs2customizer_test_config" + _cs2customizer_worker)
os.makedirs(_cs2customizer_test_cfg_dir, exist_ok=True)
os.environ["CS2C_CONFIG_DIR"] = _cs2customizer_test_cfg_dir

# 同理隔离日志目录（UP-004）：否则测试会往用户真实的
# %LOCALAPPDATA%\CS2Customizer\logs 写入，而且过期清理会真的删掉用户的历史日志
# —— 这在开发 UP-004 时已经真实发生过一次（误删 45 个历史日志）。
_cs2customizer_test_log_dir = os.path.join(tempfile.gettempdir(),
                                    "cs2customizer_test_logs" + _cs2customizer_worker)
os.makedirs(_cs2customizer_test_log_dir, exist_ok=True)
os.environ["CS2C_LOG_DIR"] = _cs2customizer_test_log_dir

# ==================== 第三个出口：CS2 游戏目录（UP-090）====================
# 上面两条隔离管的是配置和日志，管不到 `config.csgo_dir`——那是**存在配置里**
# 的一个路径。隔离配置一旦被自动探测填过一次（实测填成了用户的
# <盘符>:\SteamLibrary\...\Counter-Strike Global Offensive），之后每一次 pytest 都会
# 让建页的测试往用户真机的游戏目录写 cs2customizer.cfg，内容还是测试环境编译出来的。
#
# 实测：一次 `python -m pytest -q` 就会改写那个文件的 mtime。这事已经无声发生
# 很久了——测试全绿，因为没有任何判据看着"测试有没有写仓库外的东西"。
#
# 这里在**任何测试 import config 之前**把持久化的 csgo_dir 按到沙箱目录上。
# 用固定路径而不是 mkdtemp：`page_fingerprint.py` 要求指纹可复现，而高级设置页
# 会把这个路径原样显示出来。与 `scripts/_audit_sandbox.py` 用的是同一个目录。
# ⛔ **不加 `_cs2customizer_worker` 后缀**（批 47 实测过代价，见上面那段）：它出现在屏幕上，
#    一加后缀 `advanced` 页的指纹立刻对不上。并行的几路共用它是**有意为之**。
_cs2customizer_game_sandbox = os.path.join(tempfile.gettempdir(), "cs2customizer_audit_game_sandbox")
os.makedirs(os.path.join(_cs2customizer_game_sandbox, "game", "csgo", "cfg"), exist_ok=True)

# RN-473：这个沙箱是**固定路径、跨轮次累积**的（理由同下面 RN-141 那段），
# 于是它会攒下**产品自己写进去的** cfg —— 实测一份 GSI cfg 在里面躺了 18 天，
# 让 `utility` 的关档基线在本机走「已装好」那一支、在 CI 上走「还没装」那一支。
# ⭐ RN-141 已经认出「固定路径会攒东西」这条规律，但只钉了 config 那一半；
#   游戏目录这一半一个字都没钉 —— 补上，且**共用 `_audit_sandbox` 那一份名单**。
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", "scripts"))
try:
    from _audit_sandbox import reset_sandbox_game_dir

    reset_sandbox_game_dir(_cs2customizer_game_sandbox)
except Exception:
    # 隔离设施本身绝不能让测试跑不起来；真失效了由
    # tests/test_the_sandbox_does_not_remember_yesterday.py 当场报出来
    pass

_cs2customizer_test_cfg_file = os.path.join(_cs2customizer_test_cfg_dir, "config.json")
try:
    import json as _json

    _seed = {}
    if os.path.exists(_cs2customizer_test_cfg_file):
        with open(_cs2customizer_test_cfg_file, encoding="utf-8") as _fp:
            _seed = _json.load(_fp)
    # RN-141：**界面模式也要按死在产品默认上。**
    # 上面这个配置目录是**固定路径、跨轮次累积**的（为了 csgo_dir 可复现）。
    # 代价是本机跑久了它会攒下一堆设置，而 CI 每次都是全新配置 ——
    # 于是「不钉前置状态的判据」在两边给出不同结论：
    # `test_advanced_page_ui_polish` 断言 4 颗状态徽章，本机（攒成专家模式）绿、
    # CI（普通模式，RN-138 之后只剩 3 颗）当场红，而红的原因跟被判的改动无关。
    #
    # ⭐ 判据的前置状态要么它自己钉，要么这里统一钉死；**不许"看命"**。
    # 需要专家模式的判据自己 monkeypatch 打开（本仓已有数条这么写）。
    _want = {"csgo_dir": _cs2customizer_game_sandbox, "ui_expert_mode": False}
    if any(_seed.get(k) != v for k, v in _want.items()):
        _seed.update(_want)
        with open(_cs2customizer_test_cfg_file, "w", encoding="utf-8") as _fp:
            _json.dump(_seed, _fp, ensure_ascii=False, indent=1)
except Exception:
    # 隔离设施本身绝不能让测试跑不起来；真失效了由
    # tests/test_audit_side_effects_r9a.py 的判据兜住
    pass

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

# ⭐ 批 42（RN-469）：把 `tests/` 自己也加进来，判据才 import 得到同目录的
# 共用件 `_denominator.py`（分母守卫 `must_scan`）。
# ⚠ 这一行是被**逐文件跑**逼出来的：整目录跑 `pytest tests/` 时 pytest 会把
# 测试文件所在目录塞进 sys.path，于是 `from _denominator import must_scan` 能过；
# 而 `build_tools/run_tests.py` 是 `pytest tests/test_x.py` 一个文件一个进程，
# 这条路径就不一定在了 —— 40 个文件同时 collect error。
# ⭐ **「在我这儿跑得起来」和「在门禁那条路上跑得起来」是两件事**，
#   而本仓的门禁一直是逐文件跑（进程级退出码，不信汇总输出）。
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

# ==================== 全局 QApplication（UP-001）====================
# 背景:pytest 在"收集阶段"就会 import 全部测试模块。其中 test_single_instance.py
# 在模块级建了一个 QCoreApplication(QLockFile 需要 Qt 初始化)。之后各 UI 测试的
# `app = QApplication.instance()` 拿到的是这个 QCoreApplication——它不是 None,
# 于是守卫失效、不再新建 QApplication,接着在"只有 QCoreApplication"的进程里构造
# QWidget → Qt 原生 abort,整个进程静默消失(无 Python 回溯、stdout 全丢)。
# 表现为:单个测试文件跑得好好的,`pytest tests/` 全量却在第一个 UI 用例上崩掉,
# 625 个用例的回归网形同虚设。
#
# 解法:conftest 比任何测试模块都先执行,在这里就把 QApplication 建好。
# 这样 test_single_instance 的 `if QCoreApplication.instance() is None` 为假,
# 不会再建 QCoreApplication;所有 UI 测试也都拿到类型正确的 QApplication。
# 仅影响测试进程,不进打包产物,对软件功能零影响。
_qapp = None


def _ensure_qapplication():
    """在任何测试模块被 import 之前建立唯一的 QApplication。"""
    global _qapp
    try:
        from PySide6.QtWidgets import QApplication
    except Exception:
        return  # 没装 Qt 的纯逻辑测试环境:静默跳过
    try:
        existing = QApplication.instance()
        _qapp = existing if existing is not None else QApplication([])
    except Exception:
        # 构造失败（Qt 平台插件加载不了、session 0 服务态等）不能让 conftest 抛异常:
        # build_release.py 把 pytest 当打包前置闸门(run(check=True)),收集阶段一报错
        # 整个打包就中断,而纯逻辑测试本不该被绑死到 GUI 栈上。
        _qapp = None


_ensure_qapplication()


import pytest  # noqa: E402


@pytest.fixture(scope="session")
def qapp():
    """交出上面那个唯一的 QApplication。

    需要真建控件的用例用它，而不是各自 `QApplication.instance() or QApplication([])`
    —— 那种写法正是 UP-001 崩溃的成因（拿到的可能是 QCoreApplication）。
    Qt 起不来的纯逻辑环境直接 skip，不让 GUI 依赖拖垮整个套件。
    """
    if _qapp is None:
        pytest.skip("当前环境没有可用的 QApplication")
    return _qapp


@pytest.fixture(autouse=True)
def _config_singleton_is_not_swapped():
    """每个用例跑完后确认 `config.config` 还是同一个对象。

    **这条是防"整个进程被污染"的**，不是防某个值被改脏。

    `importlib.reload(config)` 会重新执行 `config = Config()`，于是模块属性指向
    一个**新实例**，而所有早已 `from config import config` 的模块（各个 page、
    preset_center、gsi_handler…）仍持有**旧实例**。此后"同一个 config"就分了家：
    测试往新实例写值，产品代码读写旧实例，两边再也对不上。

    2026-08-15 查实：这一个原因同时造成三条判据"逐文件跑全绿、同进程跑全量红"
    （预设往返、局内视角状态条、自定闪光状态卡）。症状各不相同、看着像三个功能
    各自坏了，其实是同一个病——而且**红在受害者身上，不在肇事者身上**，所以
    光看报错永远找不到根因。

    这条 fixture 让肇事的那个用例自己红，把"下游三处莫名其妙"变成"上游一处指名道姓"。
    需要 reload 的用例请照 `test_qa_non_ui_r12._load_config_module` 的写法把单例还原。
    """
    import config as config_mod

    original = config_mod.config
    yield
    assert config_mod.config is original, (
        "这个用例把 config 单例换掉了且没还原（多半是 importlib.reload(config)）。\n"
        "后果是进程里出现两个 Config：产品代码读旧的、测试读新的，"
        "污染会一直传到后面**别的**测试文件，红在受害者身上而不是这里。\n"
        "还原写法见 tests/test_qa_non_ui_r12._load_config_module。"
    )

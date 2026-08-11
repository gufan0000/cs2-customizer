"""
测试配置
"""
import sys
import os
import tempfile

# UI tests run headless in CI/local terminal environments.
os.environ.setdefault("QT_QPA_PLATFORM", "offscreen")

# 测试隔离：把配置目录重定向到临时目录，避免测试中对 config 的夹具改动
# （如 weapon_switch_sounds=styleSwitch）经防抖/atexit/显式 save 写进用户真实配置。
# 必须在任何测试 import config 之前设置（conftest 在收集阶段最先执行）。
_fanpai_test_cfg_dir = os.path.join(tempfile.gettempdir(), "fanpai_test_config")
os.makedirs(_fanpai_test_cfg_dir, exist_ok=True)
os.environ["FANPAI_CONFIG_DIR"] = _fanpai_test_cfg_dir

# 同理隔离日志目录（UP-004）：否则测试会往用户真实的
# %LOCALAPPDATA%\FanTool\logs 写入，而且过期清理会真的删掉用户的历史日志
# —— 这在开发 UP-004 时已经真实发生过一次（误删 45 个历史日志）。
_fanpai_test_log_dir = os.path.join(tempfile.gettempdir(), "fanpai_test_logs")
os.makedirs(_fanpai_test_log_dir, exist_ok=True)
os.environ["FANPAI_LOG_DIR"] = _fanpai_test_log_dir

# ==================== 第三个出口：CS2 游戏目录（UP-090）====================
# 上面两条隔离管的是配置和日志，管不到 `config.csgo_dir`——那是**存在配置里**
# 的一个路径。隔离配置一旦被自动探测填过一次（实测填成了用户的
# <盘符>:\SteamLibrary\...\Counter-Strike Global Offensive），之后每一次 pytest 都会
# 让建页的测试往用户真机的游戏目录写 fanpai.cfg，内容还是测试环境编译出来的。
#
# 实测：一次 `python -m pytest -q` 就会改写那个文件的 mtime。这事已经无声发生
# 很久了——测试全绿，因为没有任何判据看着"测试有没有写仓库外的东西"。
#
# 这里在**任何测试 import config 之前**把持久化的 csgo_dir 按到沙箱目录上。
# 用固定路径而不是 mkdtemp：`page_fingerprint.py` 要求指纹可复现，而高级设置页
# 会把这个路径原样显示出来。与 `scripts/_audit_sandbox.py` 用的是同一个目录。
_fanpai_game_sandbox = os.path.join(tempfile.gettempdir(), "fanpai_audit_game_sandbox")
os.makedirs(os.path.join(_fanpai_game_sandbox, "game", "csgo", "cfg"), exist_ok=True)
_fanpai_test_cfg_file = os.path.join(_fanpai_test_cfg_dir, "config.json")
try:
    import json as _json

    _seed = {}
    if os.path.exists(_fanpai_test_cfg_file):
        with open(_fanpai_test_cfg_file, encoding="utf-8") as _fp:
            _seed = _json.load(_fp)
    if _seed.get("csgo_dir") != _fanpai_game_sandbox:
        _seed["csgo_dir"] = _fanpai_game_sandbox
        with open(_fanpai_test_cfg_file, "w", encoding="utf-8") as _fp:
            _json.dump(_seed, _fp, ensure_ascii=False, indent=1)
except Exception:
    # 隔离设施本身绝不能让测试跑不起来；真失效了由
    # tests/test_audit_side_effects_r9a.py 的判据兜住
    pass

# 将项目根目录加入 sys.path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

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

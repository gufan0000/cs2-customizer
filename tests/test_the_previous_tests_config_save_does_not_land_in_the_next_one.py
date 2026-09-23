# SPDX-License-Identifier: GPL-3.0-or-later
"""上一个用例让模块单例排下的防抖保存，不许在下一个用例切目录之后才落盘。

⭐ `tests/_config_isolation.py` 那段冲刷只有 conftest 的 autouse 调它才覆盖全仓；
  这一对判据量的就是「接线」本身：第一条故意留下一个排着的保存，第二条开跑时
  它必须已经落进它自己的目录，切到 tmp_path 之后等过防抖时长也不许冒出来。
⚠ 两条靠文件内定义顺序配对（pytest 按定义顺序跑）；单挑第二条会因分母为空而红，
  不会假绿。
"""
import time

_state = {"left_one_behind": False}


def test_1_a_test_leaves_a_pending_singleton_save_behind():
    import config as C

    C.config.save_config()                      # 排一个 0.5s 的防抖保存，**不**冲刷
    assert C.config._save_timer is not None, "save_config 没排定时器 —— 这对判据的前提不成立"
    _state["left_one_behind"] = True


def test_2_the_next_test_starts_with_it_already_flushed(tmp_path, monkeypatch):
    import config as C

    assert _state["left_one_behind"], (
        "上一条没跑，这一条没有分母（单挑它跑时会这样）—— 两条要一起跑")
    assert C.config._save_timer is None, (
        "上一个用例排下的单例防抖保存到这个用例开跑时还排着 —— "
        "conftest 的 autouse 没调 flush_config_singletons_pending_save")
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    time.sleep(1.2)                             # 防抖时长 0.5s，多给一倍余量
    assert not (tmp_path / "config.json").exists(), (
        "单例的防抖保存在切目录之后才到点，把它的状态写进了本用例的 config.json")

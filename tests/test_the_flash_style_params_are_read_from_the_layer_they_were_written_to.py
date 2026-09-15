# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""RN-621（S3）：闪光样式参数**写的是两层，读的是一层** ⇒ 改完重启回默认。

## 实测的链路（`scripts/x4_flash_params_repro.py`，跑的是产品代码）

  · 写：`pages/flash_page._on_param_changed` ⇒
    `config.flash_style_params[当前样式][参数名] = 值`（**两层**）
  · 读：`flash_process_manager.load_settings_from_config` 原来是
    `self.style_parameters = config.flash_style_params`（**整个 dict**），
    再交给 `flash_process.FlashEffectProcess.update_style_parameters`，
    那边按 `if "blur_factor" in parameters` **一层**取。

⭐⭐⭐ 而 `config.py` 里那份默认值**恰好是一层的**（8 个参数名平铺）——
于是全新安装一切正常，**只有真的调过参数的用户才坏**：
他调的那一份进了 `{"standard": {...}}`，读的一方永远看不见。
落到用户身上是「拖完滑块、重启，又变回去了」，界面上一个字提示都没有
（和 RN-619 一模一样的症状，而根因完全不同）。

⭐⭐ **用户的值一直好好躺在盘上**（实测读回内存也还在）—— 从来没人去那一层拿。
⇒ 修法只动读侧，不需要迁移任何数据。

## 这份判据刻意避开的两个坑

⛔ ① **被测的那一侧必须由产品自己执行。** 探针第一版在自己体内抄了一份读逻辑，
   于是修好之后它照样报「复现」（RN-616 同款）。这里一律构造真的
   `FlashProcessManager`，不 monkeypatch 它的读法。
⛔ ② **「平铺的 8 个默认值 == 进程自己的内置默认」这件事要有人盯着。**
   修法之所以对没调过参数的用户零影响，全靠这条为真；它一旦漂了，
   这条修法就会**静默地**改变一批用户的画面。⇒ 单列一条判据，用 AST 对读。
"""
from __future__ import annotations

import ast
import io
import json
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

PARAM = "blur_factor"
USER_VALUE = 0.77


@pytest.fixture
def isolated_config(tmp_path, monkeypatch):
    """一个落在 tmp 的 Config —— 绝不碰用户真实配置。"""
    monkeypatch.setenv("CS2C_CONFIG_DIR", str(tmp_path))
    monkeypatch.setenv("CS2C_LOG_DIR", str(tmp_path / "logs"))
    import config as config_mod

    cfg = config_mod.Config()
    cfg.config_file = str(tmp_path / "config.json")
    return cfg


def _restart(tmp_path):
    """模拟下一次启动：新建 Config 再 load_config。"""
    import config as config_mod

    cfg = config_mod.Config()
    cfg.config_file = str(tmp_path / "config.json")
    cfg.load_config()
    return cfg


def _manager_for(cfg):
    """真的构造一个 FlashProcessManager（构造函数只读配置，不起进程）。"""
    from flash_process_manager import FlashProcessManager

    return FlashProcessManager(cfg)


def test_a_style_parameter_the_user_changed_survives_a_restart(
    isolated_config, tmp_path
):
    cfg = isolated_config
    style = cfg.flash_style

    # 用户拖了一次滑块（照 pages/flash_page.py:1268~1277 的写法）
    cfg.flash_style_params.setdefault(style, {})[PARAM] = USER_VALUE
    cfg.save_config_now()

    # 值确实落到盘上的那一层里了（前提；不成立的话下面测的就不是同一件事）
    on_disk = json.loads(io.open(cfg.config_file, encoding="utf-8").read())
    assert on_disk["flash_style_params"][style][PARAM] == USER_VALUE

    manager = _manager_for(_restart(tmp_path))
    assert manager.style_parameters.get(PARAM) == USER_VALUE, (
        f"用户设的 {PARAM}={USER_VALUE} 没有活过重启 —— "
        f"进程拿到的是 {manager.style_parameters.get(PARAM)!r}。\n"
        "⚠ 写的一方按「样式名 → 参数表」两层存；读的一方必须去那一层取。"
    )


def test_a_user_who_never_touched_a_slider_gets_exactly_the_shipped_default(
    isolated_config, tmp_path
):
    """⭐ 阳性对照的另一半：上一条的绿不是「不管盘上是什么都返回 0.77」。

    没有任何 per-style 那一层时，读到的必须是平铺的那份出厂值。
    """
    cfg = isolated_config
    shipped = cfg.flash_style_params[PARAM]
    assert shipped != USER_VALUE, "（前提）出厂值不能碰巧等于上一条用的那个值"
    cfg.save_config_now()

    manager = _manager_for(_restart(tmp_path))
    assert manager.style_parameters.get(PARAM) == shipped


def test_two_styles_do_not_leak_into_each_other(isolated_config, tmp_path):
    """样式 A 调过的参数，不许在样式 B 上生效。"""
    cfg = isolated_config
    other = "blur" if cfg.flash_style != "blur" else "rainbow"
    cfg.flash_style_params.setdefault(other, {})[PARAM] = USER_VALUE
    cfg.save_config_now()

    manager = _manager_for(_restart(tmp_path))
    assert manager.style_parameters.get(PARAM) == cfg.flash_style_params[PARAM], (
        f"当前样式是 {cfg.flash_style!r}，却读到了 {other!r} 那一份的参数"
    )


def test_the_per_style_layer_never_leaks_into_the_parameter_table(
    isolated_config, tmp_path
):
    """交给进程的那张表里，不许出现「样式名」这种键。

    进程那边是 `if "blur_factor" in parameters` 逐个取的，多余的键它不会报错、
    只会忽略 —— ⭐ 也就是说这类污染**不会有任何症状**，只能靠判据看住。
    """
    cfg = isolated_config
    cfg.flash_style_params.setdefault(cfg.flash_style, {})[PARAM] = USER_VALUE
    cfg.save_config_now()

    manager = _manager_for(_restart(tmp_path))
    for key, value in manager.style_parameters.items():
        assert not isinstance(value, dict), (
            f"参数表里混进了一层嵌套：{key!r} -> {type(value).__name__}"
        )


# ============ 修法成立的前提：平铺默认值 == 进程自己的内置默认 ============

def _flash_effect_init_defaults() -> dict[str, float]:
    """用 AST 读 `flash_process.FlashEffectProcess.__init__` 里的默认赋值。

    ⚠ 不 import 它：`flash_process.py` 模块级就 `import pygame` / `win32gui`，
    在判据里 import 等于打开音频/窗口子系统（§3「不许打扰前台」）。
    """
    src = io.open(ROOT / "flash_process.py", encoding="utf-8").read()
    tree = ast.parse(src)
    cls = next(n for n in ast.walk(tree)
               if isinstance(n, ast.ClassDef) and n.name == "FlashEffectProcess")
    init = next(n for n in cls.body
                if isinstance(n, ast.FunctionDef) and n.name == "__init__")
    out: dict[str, float] = {}
    for node in init.body:
        if not isinstance(node, ast.Assign) or len(node.targets) != 1:
            continue
        tgt = node.targets[0]
        if (isinstance(tgt, ast.Attribute)
                and isinstance(tgt.value, ast.Name) and tgt.value.id == "self"
                and isinstance(node.value, ast.Constant)
                and isinstance(node.value.value, (int, float))
                and not isinstance(node.value.value, bool)):
            out[tgt.attr] = node.value.value
    return out


def test_the_flat_defaults_still_match_the_process_own_defaults(isolated_config):
    """⭐ 这条为真，上面那条修法才对「没调过参数的用户」零影响。

    它一旦漂了，修法就会**静默地**改一批用户的画面 ——
    所以它不能只活在一句注释里。
    """
    cfg = isolated_config
    flat = {k: v for k, v in cfg.flash_style_params.items()
            if not isinstance(v, dict)}
    assert flat, "config 里那份平铺默认值没了 —— 请先确认修法的前提还成不成立"

    effect = _flash_effect_init_defaults()
    missing = [k for k in flat if k not in effect]
    assert not missing, (
        f"`config.flash_style_params` 里这些键在 `FlashEffectProcess.__init__` 里没有对应的默认："
        f"{missing}"
    )
    drifted = {k: (flat[k], effect[k]) for k in flat if flat[k] != effect[k]}
    assert not drifted, (
        f"平铺默认值和进程内置默认已经不一致了：{drifted}\n"
        "⇒ 请重新确认 RN-621 的修法（读 per-style 那一层）对老用户仍然零影响。"
    )


def test_the_reader_no_longer_hands_over_the_whole_dict():
    """产品里那一行必须是「按样式取那一层」，不是「整个 dict 端过去」。

    ⚠ 这是一条**文本**判据，守的是修法本身没被顺手改回去；
    上面那几条才是行为判据。两者都要有：行为判据证明它现在是对的，
    这一条让「改回旧写法」在 diff 阶段就红。
    """
    src = io.open(ROOT / "flash_process_manager.py", encoding="utf-8").read()
    assert "self.style_parameters = self.config.flash_style_params" not in src, (
        "又变回「整个 flash_style_params 当参数表」了 —— 那正是 RN-621。"
    )
    assert "_style_parameters_for" in src

# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""批 85（RN-614 / 615 / 616）：配置层读老文件时，不许悄悄改变它已经表达过的东西。

三条互不相干的缺陷，共一个形状：**读的那一侧做了写的那一侧没打算让它做的事。**

 ① RN-614：版本号被**往回**改。`_run_schema_migrations` 原来无条件
    `self.config_schema_version = CONFIG_SCHEMA_VERSION` —— 用户装过新版
    （配置已是 v3）、又退回只认 v2 的旧版跑一次，迁移循环一次都不进，
    而**版本号被改写成 2 并落盘**；再升回去时新版会把 2→3 的迁移
    在已经是 v3 的数据上再跑一遍。
    ⭐ 版本号是**唯一**记录「这份数据是什么形状」的东西。

 ② RN-615：**陌生的键被当成正经条目收下**。两处，而两处的病不一样：
    · `sfx_forwarding_options` 用 `dict.update()`，而它上面那行注释逐字写着
      「只更新存在的键」—— ⭐ **一句注释写的是它想要的语义，下面那行给的是相反的**；
    · `hud_color_dynamic_map` 是**同一个循环里两条分支互相矛盾**：`dict` 那支守
      `key in ...`，而兼容 V1 旧格式的 `int` 那支不守 ——
      ⚠ 而不守的那一支，正是**老配置文件会走的那一支**。

 ③ RN-616：防抖 timer 自然触发后从不清空 ⇒ `_atexit_flush` 里那句
    「有没有待写改动」恒为真，每次正常退出都多写一次。
    ⚠ 不是数据丢失，⭐ 但它让退出路径唯一依据的那个信号失真。

⛔ 每条都配阳性对照：判据绿着，可能是修好了，也可能是**这条判据根本没跑到那一格**。
"""
from __future__ import annotations

import json

import config as C
import pytest


@pytest.fixture()
def cfg(tmp_path, monkeypatch):
    """一份独立的配置对象 + 独立的磁盘位置（不碰真配置，也不碰别的用例）。"""
    path = tmp_path / "config.json"
    monkeypatch.setattr(C, "get_config_path", lambda: str(path))
    monkeypatch.setattr(C, "get_config_dir", lambda: str(tmp_path))
    return C.Config()


# ────────────────────────────────────── ① RN-614 版本号只许前进

def test_a_config_from_a_newer_version_does_not_get_its_version_lowered(cfg):
    """⛔ 旧版本读到「比自己新」的配置时，不许把版本号改小。"""
    future = C.CONFIG_SCHEMA_VERSION + 1
    cfg._run_schema_migrations({"config_schema_version": future})
    assert cfg.config_schema_version == future, (
        f"配置里写着 v{future}（比本版本认识的 v{C.CONFIG_SCHEMA_VERSION} 新），"
        f"而读完之后变成了 v{cfg.config_schema_version}。\n"
        "⇒ 旧版本跑一次就把「这份数据是什么形状」这条唯一的记录抹掉了；"
        "再升回新版时，那些迁移会在已经迁过的数据上再跑一遍。")


def test_a_config_from_an_older_version_still_gets_migrated_forward(cfg):
    """⭐ 阳性对照：上一条不是靠「干脆什么都不改」通过的。

    ⚠ 没有这一条，把整个函数体删空也能让上一条变绿。
    """
    cfg._run_schema_migrations({"config_schema_version": 0})
    assert cfg.config_schema_version == C.CONFIG_SCHEMA_VERSION, (
        "老配置读完之后版本号没有被推到最新 —— 迁移这条路已经断了")


# ────────────────────────────────────── ② RN-615 陌生的键不算数

#: 批 85 **实测核实过**的两处：注释/分支明确声称要过滤，而实际没有过滤。
#: ⛔ 这两个名字是写死的，而这是**故意的** —— 见下面那条判据的说明。
VERIFIED_CLOSED_BUCKETS = ("sfx_forwarding_options", "hud_color_dynamic_map")

#: RN-618（**批 86 结**）：批 85 量出「另有 5 个字典型配置项也收陌生键，而我没查过」，
#: 本批照 RN-588 那条（先把那个文件打开）逐个核实完了。结论有三条值得记下来：
#:
#: ⭐⭐⭐ ① **那把尺子只有两格，而世界有三种。** 「收不收陌生键」把五个分成
#:    「开放集合 / 封闭 schema」两类，而实际量出来的是三类：完全开放（键是用户起的名字）、
#:    **开放但键有格式**（`voice_output_slots` 的键必须能 `int()`）、
#:    以及「顶层像固定表、而每一处读都是容错的」（`magnifier`）。
#:    —— RN-596「判据只有两格而世界有三种」同款。
#: ⭐⭐⭐ ② **一个「陌生的键」，可能根本不是用户塞的，是产品自己另一半写的。**
#:    `flash_style_params` 就是：闪光页按 `{样式名: {参数名: 值}}` 两层写，
#:    于是「样式名」在这把尺子上读作一个陌生键。它压根不属于这个问题 ⇒ 见 **RN-621**。
#: ⭐⭐ ③ 五个**没有一个**需要白名单。⇒ 这一轮的产出是「查清楚了」，不是「改了代码」。
#:
#: ⛔ 列在这里要付代价：每条都要写**为什么它是开放的**，空理由不算数（同 R9-A 的豁免表口径）。
VERIFIED_OPEN_BUCKETS = {
    "music_playlists":
        "键 = 用户自己起的歌单名（出厂只有一个「默认」）。"
        "陌生的键正是这项配置的数据本身。",
    "map_preset_rules":
        "键 = 地图名（`de_dust2` 之类），出厂是空的 `{}`；"
        "由 `core/presets/map_rules.py` 在用户保存预设时逐个加。",
    "voice_output_slots":
        "键 = 音板槽位 id 的**字符串形式**，出厂空 `{}`。"
        "⚠ 这是「开放但键有格式」的那一类：`pages/voice_output_page._initialize_slots` "
        "按 `int(key)` 求最大槽位号，非整数键会被 `except (TypeError, ValueError): continue` "
        "静默跳过 —— 跳过之后它**仍然留在盘上**，只是永远不做事。"
        "⭐ 本批不改：清理它要区分「用户的槽位」和「垃圾」，而误判的代价是删用户数据。",
    "magnifier":
        "顶层看着像固定的 10 个键，**而每一处读都是容错的**"
        "（`pages/magnifier_page.py` 全走 `if k in config.magnifier` 或 `.get(k, 默认)`）；"
        "且实际在用的 `debounce_time` / `weapon_settings` **根本不在出厂默认里**。"
        "⇒ 它是一个**版本容错的开放 dict**，加白名单反而会把老配置里的键吃掉。",
    "flash_style_params":
        "⭐ 它收下的那个「陌生键」不是用户塞的，是**产品自己另一半**写的："
        "`pages/flash_page._on_param_changed` 按 `{样式名: {参数名: 值}}` 两层存。"
        "⇒ 这不是「该不该收陌生键」，是**写两层读一层** ⇒ 见 RN-621"
        "（判据 `test_the_flash_style_params_are_read_from_the_layer_they_were_written_to.py`）。",
}

#: 还没查清「该不该收陌生键」的字典型配置项还剩几个。
#: ⛔ 这个数**只许变小**：它记的是「欠着几条没查」，不是「允许有几个」。
#: RN-618 结案后归零；再冒出来就是新账，要查了才准往上面两张表里写。
UNCHECKED_OPEN_DICTS = 0


def _dict_config_buckets(obj) -> list[str]:
    return sorted(k for k, v in vars(obj).items()
                  if isinstance(v, dict) and not k.startswith("_"))


def _buckets_that_swallow_a_stranger(tmp_path, buckets) -> list[str]:
    payload = {b: {"__stranger__": 1} for b in buckets}
    payload["config_schema_version"] = C.CONFIG_SCHEMA_VERSION
    (tmp_path / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")
    fresh = C.Config()
    fresh.load_config()
    return [b for b in buckets
            if "__stranger__" in (getattr(fresh, b, None) or {})]


def test_the_two_buckets_that_promise_to_filter_actually_filter(cfg, tmp_path):
    """⛔ 这两处**声称**只收认识的键，那就必须真的只收认识的键。

    ⭐⭐⭐ 这两个名字写死在 `VERIFIED_CLOSED_BUCKETS` 里，而这是**故意的**。
    我第一版把分母写成「`load_config` 里出现过 `key in self.X` 守卫的那些」——
    看起来漂亮（分母由机器找），**而破坏验证当场判它假绿**：
    把守卫删掉之后，那个桶**同时也就离开了分母**，判据照样全绿。
    ⭐⭐ **一个从「被测的那道守卫」推出来的分母，抓不住那道守卫被拆掉**
    （RN-609 同款：一条判据抓不住自己被解除武装）。
    ⇒ 分母必须来自**独立于修法的东西**；这里来自「我逐个核实过的清单」。
    """
    leaked = _buckets_that_swallow_a_stranger(tmp_path, VERIFIED_CLOSED_BUCKETS)
    assert not leaked, (
        f"这些配置项收下了一个陌生键：{leaked}\n"
        "⇒ 它会被原样写回盘并一直留在用户的配置文件里，界面上没有地方清得掉。\n"
        "⚠ `hud_color_dynamic_map` 那一处尤其要紧：不守陌生键的是**兼容 V1 旧格式**"
        "的那条分支，而那正是老配置文件会走的那一支。\n"
        "⚠ `sfx_forwarding_options` 那一处的病是**注释和代码说反了**："
        "注释写「只更新存在的键」，而 `dict.update()` 对陌生键是插入。")


def test_the_number_of_unchecked_stranger_swallowing_dicts_only_shrinks(cfg, tmp_path):
    """⛔ 棘轮：还没查清「该不该收陌生键」的字典型配置项，只许变少。

    ⭐ 这一条替代了「把那五个写进白名单」—— **白名单会让「还没查」看起来像「查过了」。**
    这里记的是一个数，而那个数的名字叫「欠着几条没查」。
    """
    buckets = _dict_config_buckets(cfg)
    assert len(buckets) >= 10, f"只找到 {len(buckets)} 个字典型配置项 —— 分母塌了"
    swallow = _buckets_that_swallow_a_stranger(tmp_path, buckets)
    known = set(VERIFIED_CLOSED_BUCKETS) | set(VERIFIED_OPEN_BUCKETS)
    unchecked = [b for b in swallow if b not in known]
    assert len(unchecked) <= UNCHECKED_OPEN_DICTS, (
        f"会收下陌生键、而又没被核实过的字典型配置项变多了："
        f"{sorted(unchecked)}（{len(unchecked)} 个 > 在册 {UNCHECKED_OPEN_DICTS}）\n"
        "⇒ 要么这一批新加的配置项该过滤而没过滤，要么它是开放集合。\n"
        "⛔ **先把那个文件打开看一遍**（RN-588），再决定写进 "
        "`VERIFIED_CLOSED_BUCKETS` 还是 `VERIFIED_OPEN_BUCKETS`；"
        "开放的那张表要求写明**为什么**开放，空理由不算数。")


def test_every_open_bucket_has_a_real_attribute_and_a_real_reason(cfg):
    """⭐ 防这张表烂掉：名字要对得上真东西，理由不许是空的。

    ⚠ 参照的是 `Config` 实例上**真有哪些属性**（独立的一侧），
    不是从 `load_config` 的源码里捞的 —— 从被测对象推出来的分母，
    抓不住那个对象被拆掉（RN-615 / RN-609 同款）。
    """
    for name, why in VERIFIED_OPEN_BUCKETS.items():
        assert hasattr(cfg, name), (
            f"`{name}` 已经不是 `Config` 上的配置项了 —— "
            "这张表该删掉这一行，而不是留着当摆设")
        assert isinstance(getattr(cfg, name), dict), f"`{name}` 已经不是字典了"
        assert len(why.strip()) >= 20, (
            f"`{name}` 的理由太短 —— 豁免要有代价，"
            "否则这张表会无声地变长（同 R9-A 那张豁免表的口径）")

    overlap = set(VERIFIED_OPEN_BUCKETS) & set(VERIFIED_CLOSED_BUCKETS)
    assert not overlap, f"同一个配置项既在开放表又在封闭表里：{sorted(overlap)}"


def test_a_known_key_in_the_file_is_still_honoured(cfg, tmp_path):
    """⭐ 阳性对照：上一条不是靠「整个字典都不读」通过的。

    ⚠ 把那几处 `if key in ...` 写成 `if False`，上一条照样绿。
    """
    bucket = "sfx_forwarding_options"
    known = sorted(getattr(cfg, bucket))
    assert known, f"`{bucket}` 是空的 —— 这条阳性对照没有落点"
    key = known[0]
    flipped = not bool(getattr(cfg, bucket)[key])
    (tmp_path / "config.json").write_text(
        json.dumps({bucket: {key: flipped},
                    "config_schema_version": C.CONFIG_SCHEMA_VERSION},
                   ensure_ascii=False), encoding="utf-8")

    fresh = C.Config()
    fresh.load_config()
    assert getattr(fresh, bucket)[key] == flipped, (
        f"`{bucket}[{key}]` 在文件里写着 {flipped}，读回来却不是 —— "
        "白名单收紧得过头了，认识的键也被丢掉了")


# ────────────────────────────────────── ④ 存进去的，必须读得回来

def test_every_plain_load_key_is_a_real_attribute(cfg):
    """⛔⛔ `_load_plain` 收到的每一个键，都必须是 `Config` 上真有的属性。

    ⭐⭐⭐ 这一条专治**今晚真的发生过的那个缺陷**，而它比下面那条往返判据更早生效。
    X3 减重时生成器漏了续行末尾的逗号：

        "csgo_dir", "kill_icon_enabled"
        "debug_mode")

    Python 把相邻字符串字面量**悄悄拼起来** ⇒ 它去找一个叫
    `"kill_icon_enableddebug_mode"` 的键，两个配置项从此都读不回来。
    ⭐⭐ **语法合法、`ruff` 全绿、全套判据全绿，而 16 个配置项已经坏了。**
    ⭐⭐⭐ **在这门语言里，「少了一个逗号」不是语法错误，是语义错误。**

    ⚠⚠ 而下面那条「往返」判据**逮不住它**，理由值得记住：
    那条判据的键名列表是从**同一批 `_load_plain` 参数**里读出来的 ——
    逗号一漏，两个键在产品里消失，**在判据的分母里也同时消失**。
    ⭐⭐⭐ 这是今晚第三次撞上同一个形状：
    **一个从「被测对象」推出来的分母，抓不住那个对象被拆掉。**
    ⇒ 这条判据的参照物换成**独立的一侧**：`Config` 实例上真有哪些属性。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(C.Config.load_config).lstrip())
    keys = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_load_plain"):
            keys += [a.value for a in node.args
                     if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    assert len(keys) >= 150, f"只扫到 {len(keys)} 个键 —— 分母塌了，这条在空转"

    # ⚠ 不能只看 `vars(cfg)`：`hud_color_enabled` 是个 **property**（`hud_rules_enabled`
    #   的兼容别名），它不在实例字典里，于是第一版把一个真配置项报成了「不存在」。
    #   ⭐ 而那正好是批 84 盘点里唯一一个「有读写但 `__init__` 里没有默认值」的名字 ——
    #     ⚠ 一份盘点表已经写下过这件事，而我写判据时没有回头看它。
    bogus = sorted(k for k in keys if not hasattr(cfg, k))
    assert not bogus, (
        f"`_load_plain` 里这些键在 `Config` 上根本不存在：{bogus}\n"
        "⭐ 最可能的成因是**某一行末尾少了个逗号** —— "
        "Python 会把相邻的字符串字面量拼成一个键，而语法完全合法。\n"
        "⇒ 去那一行把逗号补回来；被拼进去的那两个配置项现在都读不回来。")


# ────────────────────────────────────── ⑤ 存进去的，必须读得回来

def test_every_plain_config_key_survives_a_round_trip(cfg, tmp_path):
    """⛔ 改一个值、存盘、重新读回来 —— 每一个「没有校验的普通配置项」都必须还在。

    ⭐⭐⭐ 这条判据的存在理由是批 85 的一次**静默损坏**，而它是本仓从没有过的一类。
    X3 关档减重时我把 167 条 `self.X = config_data.get("X", self.X)` 折叠成
    `self._load_plain(config_data, "a", "b", …)`，而生成器**漏了续行末尾的逗号**：

        "kill_icon_enabled"
        "debug_mode")

    Python 把相邻的字符串字面量**悄悄拼起来**，于是它去找一个叫
    `"kill_icon_enableddebug_mode"` 的键 —— 找不到，两个配置项从此都读不回来。
    ⭐⭐ **语法合法、`ruff` 全绿、全套判据也全绿，而 16 个配置项已经坏了。**
    ⭐⭐⭐ **在这门语言里，「少了一个逗号」不是语法错误，是语义错误。**
    ⇒ 唯一逮住它的是「改一个值再读回来」这件事本身，那就把它做成一道门。

    ⚠ 只查**普通项**（`_load_plain` 报的那些）：带钳位/归一化/迁移的项
    本来就可能读回别的值，混进来这条会天天假红。
    """
    import ast
    import inspect

    tree = ast.parse(inspect.getsource(C.Config.load_config).lstrip())
    plain = []
    for node in ast.walk(tree):
        if (isinstance(node, ast.Call) and isinstance(node.func, ast.Attribute)
                and node.func.attr == "_load_plain"):
            plain += [a.value for a in node.args
                      if isinstance(a, ast.Constant) and isinstance(a.value, str)]
    assert len(plain) >= 120, (
        f"只扫到 {len(plain)} 个普通配置项 —— 分母塌了，这条在空转")

    # ⚠ 「走了 `_load_plain`」不等于「没人再动它」：有五个键在**读完之后**
    #   还会被别处改（`csgo_dir` 被 `_repair_seeded_config` 按目录存不存在清掉，
    #   四个 `hud_*` 被 `migrate_hud_legacy_to_rules` 归一化）。
    # ⭐ 第一版没排掉它们，当场报 5 条假缺陷 —— 和批 84 那次往返探针同一个坑：
    #   **我造的值不合法，而校验在正常工作。**
    # ⇒ 排掉「在 `load_config` / 两个后处理里还被赋过值」的那些，分母由机器算。
    touched = set()
    for fname in ("load_config", "migrate_hud_legacy_to_rules",
                  "_repair_seeded_config"):
        t = ast.parse(inspect.getsource(getattr(C.Config, fname)).lstrip())
        for node in ast.walk(t):
            if isinstance(node, ast.Assign):
                for tgt in node.targets:
                    if (isinstance(tgt, ast.Attribute)
                            and getattr(tgt.value, "id", None) == "self"):
                        touched.add(tgt.attr)
    plain = [k for k in plain if k not in touched]
    assert len(plain) >= 120, (
        f"排掉后处理过的键之后只剩 {len(plain)} 个 —— 分母塌了")

    def _other(v):
        if isinstance(v, bool):
            return not v
        if isinstance(v, int):
            return v + 7
        if isinstance(v, float):
            return round(v + 0.25, 6)
        if isinstance(v, str):
            return (v + "_rt") if v else "rt"
        return None

    want = {}
    for k in plain:
        nv = _other(getattr(cfg, k, None))
        if nv is not None:
            want[k] = nv
    assert len(want) >= 100, f"只造得出 {len(want)} 个可比的值 —— 分母塌了"

    payload = dict(want)
    payload["config_schema_version"] = C.CONFIG_SCHEMA_VERSION
    (tmp_path / "config.json").write_text(
        json.dumps(payload, ensure_ascii=False), encoding="utf-8")

    fresh = C.Config()
    fresh.load_config()
    lost = sorted(k for k, v in want.items() if getattr(fresh, k, None) != v)
    assert not lost, (
        f"这些配置项存进文件了，却读不回来（{len(lost)} 个）：\n  {lost}\n"
        "⇒ 用户改了设置、重启之后又变回去了，而界面上什么提示都没有。\n"
        "⚠ 最可能的成因：`_load_plain` 的键名列表里**少了一个逗号** —— "
        "相邻字符串字面量会被 Python 悄悄拼成一个不存在的键，而语法是合法的。")


# ────────────────────────────────────── ③ RN-616 「有没有待写改动」要说实话

def test_a_timer_that_already_fired_is_no_longer_pending(cfg):
    """⛔ 防抖 timer 自然触发之后，`_save_timer` 必须回到 `None`。

    ⚠⚠ 这条判据第一版**把真实现 monkeypatch 掉了**，自己在夹具里抄了一份清空逻辑 ——
    于是它测的是那份抄件，**把产品里的清空整段删掉照样绿**（破坏验证当场逮到）。
    ⭐⭐⭐ **一条判据只要在夹具里复制了被测的那段逻辑，它守的就是那份复制品。**
    ⇒ 现在跑的是真的 `_do_save_config`（写进 tmp_path 下的真文件）。
    """
    cfg.save_config()
    timer = cfg._save_timer
    assert timer is not None, "刚排好的 timer 不该是 None —— 夹具坏了"
    timer.join(timeout=10)
    assert not timer.is_alive(), "防抖 timer 10 秒没跑完 —— 这条判据量不到东西"
    assert cfg._save_timer is None, (
        "防抖 timer 已经跑完了，`_save_timer` 还挂着。\n"
        "⇒ `_atexit_flush` 里的 `has_pending` 就恒为真，"
        "每次正常退出都会多做一次内容相同的同步写盘，"
        "而那是退出路径唯一用来决定「要不要在关机时动磁盘」的依据。")


def test_the_clearing_looks_at_thread_identity_not_liveness():
    """⭐⭐⭐ 阳性对照 —— 而它守的是**我第一版真的写错的那一句**。

    `threading.Timer` 就是一个线程，它到点之后正是**在它自己那个线程里**
    调 `_do_save_config` ⇒ 那一刻 `is_alive()` 必然为真。
    照 `not _t.is_alive()` 判，就永远清不掉，而上面那条会红得莫名其妙。
    ⇒ 这里把那条规矩钉在源码形状上：清空的条件必须问**线程身份**。
    """
    import ast
    import inspect

    src = inspect.getsource(C.Config._do_save_config)
    tree = ast.parse(src.lstrip())
    names = {n.attr for n in ast.walk(tree) if isinstance(n, ast.Attribute)}
    assert "current_thread" in names, (
        "`_do_save_config` 里清空 `_save_timer` 的条件没有用 "
        "`threading.current_thread()`。\n"
        "⚠ 如果改成了 `is_alive()`：timer 到点时是在它自己的线程里调这个函数，"
        "`is_alive()` 恒为真 ⇒ 永远清不掉。")
    assert "is_alive" not in names, (
        "`_do_save_config` 里出现了 `is_alive()` —— 见上：它在这一刻恒为真。")

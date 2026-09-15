# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""**模块形状**的链路契约快照：这一层对外暴露了哪些名字，外面真的用了哪几个。

## 它是 `x3_contract_snapshot.py` 的通用版，而**不是** X1 那份的通用版

⛔ 共享层规划 §二-9 设想的是「一个 `--target` 同时吃 X1 和 X3」，
而 `x3_contract_snapshot.py` 的文档里**已经把这条否掉了，并且写明了理由**：
两边的接收者判定没有公共部分 —— X1 靠「接收者名字像主窗」（一个类的实例面），
X3 靠「谁 import 了这个模块」（模块面）。**硬做通用只会让两边都变糊。**

⭐ 本脚本做的是另一件事：D4 那四条链路（X9 搜索 / X10 热键 / X12 资源 / X13 utils）
**全是模块形状**，和 X3 一模一样 ⇒ 把 X3 那份里写死的 `LAYER` 字典**变成参数**。
X1 那份原地不动 —— 它是这整个工程里唯一的类实例形状。

⭐⭐⭐ 批 88 开工时我差点反过来做：从**文件名前缀**（`x1_` / `x3_`）推出
「按站点各抄一份、该通用化没通用」，并把这句话写进了状态文件。
真去开那个文件才看见它开头就写着裁定理由。
**一句描述和它描述的那件事，在文本上长得一模一样。**

## 等价验收

`--layer X3` 的输出必须和 `x3_contract_snapshot.py` **逐字节相同**
（`--verify-x3` 当场跑这一条）。⛔ 没过这一关之前不许拿它去冻任何新基线 ——
一个「重写版」和一个「重写并且悄悄改了口径的版本」，输出格式一模一样。

## 怎么量的（三条自查，全部继承自 X3 那份）

⚠ ① `self.config.xxx` 这类实例访问不算模块契约，单独一栏（`instance` 段）。
⚠ ② 排掉 `.build/` / `_manual_backup*` / `_archive*` / `output/` / `.claude/worktrees/`。
⚠ ③ 实例属性按「在不在 `__init__` 里」分两类：`__init__` 里的大多是配置项默认值，
   它们的契约是**键名**不是属性名；混在一起数会得到一个虚胖到没法用的契约面。

用法：
    python scripts/layer_contract_snapshot.py --layer X9
    python scripts/layer_contract_snapshot.py --layer X9 --write
    python scripts/layer_contract_snapshot.py --verify-x3
"""
from __future__ import annotations

import argparse
import ast
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.stdout.reconfigure(encoding="utf-8", errors="replace")

ROOT = Path(__file__).resolve().parents[1]

#: 一层的定义。`modules` 的键 = 外面 import 时写的那个名字。
#: `instance` 可选：(模块键, 类名, 输出里那一栏叫什么)。
#: ⭐ 「输出里那一栏叫什么」也做成参数，是为了让 X3 的输出**逐字节**对得上 ——
#:   否则等价验收会因为一个键名而失败，而那种失败读起来像「口径变了」。
LAYERS: dict[str, dict] = {
    "X3": {
        "modules": {
            "config": "config.py",
            "core.config_reload_bus": "core/config_reload_bus.py",
            "core.io_validation": "core/io_validation.py",
            "core.config_snapshot_manager": "core/config_snapshot_manager.py",
        },
        "instance": ("config", "Config", "config_instance"),
    },
    "X9": {
        "modules": {
            "core.settings_search": "core/settings_search.py",
            "build_search_index": "scripts/build_search_index.py",
        },
        "instance": None,
    },
    "X10": {
        "modules": {
            "core.hotkeys": "core/hotkeys/__init__.py",
            "core.hotkeys.registry": "core/hotkeys/registry.py",
        },
        "instance": None,
    },
    "X12": {
        "modules": {
            "resource_manager": "resource_manager.py",
            "core.resource_catalog": "core/resource_catalog.py",
            "core.resource_health": "core/resource_health.py",
            "core.resource_import_wizard": "core/resource_import_wizard.py",
        },
        "instance": ("resource_manager", "ResourceManager", "resource_manager_instance"),
    },
    "X13": {
        "modules": {
            f"core.utils.{p.stem}": f"core/utils/{p.name}"
            for p in sorted((ROOT / "core" / "utils").glob("*.py"))
        },
        "instance": None,
    },
    # ── D5 冻结档（批 89）：**只冻不动刀** ──────────────────────────────
    # 这三条「只有进游戏才验得出来」（`后续批次规划_20260903.md` §5）。
    # 契约快照在这里的作用不是「准备动刀」，是**「之后没人悄悄改它」的证据**。
    "X6": {
        "modules": {
            "gsi_server": "gsi_server.py",
            **{f"gsi_handler_{p.stem.split('gsi_handler_')[1]}": p.name
               for p in sorted(ROOT.glob("gsi_handler_*.py"))},
        },
        "instance": None,
    },
    "X7": {
        "modules": {
            f"core.audio.{p.stem}": f"core/audio/{p.name}"
            for p in sorted((ROOT / "core" / "audio").glob("*.py"))
        },
        "instance": ("core.audio.audio_manager", "AudioManager", "audio_manager_instance"),
    },
    "X8": {
        "modules": {
            "core.cfg_compiler": "core/cfg_compiler.py",
            "core.gun_sound_profiles": "core/gun_sound_profiles.py",
            "core.crosshair_reset": "core/crosshair_reset.py",
            "core.magnifier_sensitivity": "core/magnifier_sensitivity.py",
            **{f"core.hud.{p.stem}": f"core/hud/{p.name}"
               for p in sorted((ROOT / "core" / "hud").glob("*.py"))},
        },
        "instance": None,
    },
    # ── D5 钉住档：⛔ 只取契约快照 + 一条断点，**不盘点、不动刀、不改验证逻辑** ──
    # ⚠ 这一层挨着凭据与服务地址。本工具只记**名字**（函数/类/常量名），
    #   从不读取也从不打印任何**值** —— 这句话已由判据钉住，见
    #   `test_the_pinned_layer_snapshot_records_no_values`。
    "X11": {
        "modules": {
            # ⚠ 这里本来还写着 `update_checker.py` —— 它**只存在于 `.build/` 里那几份
            #   历史发布快照**，活树上早就没有了。层定义那道 `assert` 当场逮住。
            #   ⭐ 我是从一次 grep 的结果里记住这个文件名的，而那次 grep 扫到了 `.build/`。
            "update_runtime": "update_runtime.py",
            "account_auth_client": "account_auth_client.py",
            "account_help": "account_help.py",
            "account_session_store": "account_session_store.py",
            "service_urls": "service_urls.py",
            "core.cloud.config_sync": "core/cloud/config_sync.py",
            "core.cloud.resource_provenance": "core/cloud/resource_provenance.py",
        },
        "instance": None,
    },
}

SKIP_PARTS = {".build", "__pycache__", "output", "node_modules", ".git"}
SKIP_PREFIX = ("release/", "build_tools/oss_sync/", ".claude/")


def _skip(rel: str) -> bool:
    parts = set(Path(rel).parts)
    if parts & SKIP_PARTS:
        return True
    if any("_manual_backup" in p or p.startswith("_archive") for p in parts):
        return True
    return rel.startswith(SKIP_PREFIX)


def live_py_files() -> list[Path]:
    out = []
    for p in ROOT.rglob("*.py"):
        rel = p.relative_to(ROOT).as_posix()
        if not _skip(rel):
            out.append(p)
    return sorted(out)


def module_surface(path: Path) -> dict:
    """模块级的公开名字：函数、类、常量。

    下划线开头的也收 —— X1 实测 284 个名字里 41 个下划线名被外部引用，
    **「私有」这个约定保护不了任何人**。
    """
    tree = ast.parse(path.read_text(encoding="utf-8"))
    funcs, classes, consts = [], [], []
    for node in tree.body:
        if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef)):
            funcs.append(node.name)
        elif isinstance(node, ast.ClassDef):
            classes.append(node.name)
        elif isinstance(node, ast.Assign):
            for t in node.targets:
                if isinstance(t, ast.Name):
                    consts.append(t.id)
        elif isinstance(node, ast.AnnAssign) and isinstance(node.target, ast.Name):
            consts.append(node.target.id)
    return {"functions": sorted(funcs), "classes": sorted(classes),
            "constants": sorted(consts)}


def instance_surface(path: Path, class_name: str) -> dict:
    """一个类的实例面：方法，以及 `self.x = ...` 按「在不在 `__init__` 里」分两栏。"""
    tree = ast.parse(path.read_text(encoding="utf-8"))
    cls = next((n for n in tree.body
                if isinstance(n, ast.ClassDef) and n.name == class_name), None)
    if cls is None:
        return {"methods": [], "init_keys": [], "other_attrs": []}
    methods = sorted(n.name for n in cls.body
                     if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)))
    init_keys, other = set(), set()
    for n in cls.body:
        if isinstance(n, (ast.FunctionDef, ast.AsyncFunctionDef)):
            bucket = init_keys if n.name == "__init__" else other
            for sub in ast.walk(n):
                if isinstance(sub, ast.Assign):
                    for t in sub.targets:
                        if isinstance(t, ast.Attribute) \
                                and getattr(t.value, "id", None) == "self":
                            bucket.add(t.attr)
    return {"methods": methods, "init_keys": sorted(init_keys),
            "other_attrs": sorted(other - init_keys)}


def importers(layer: dict[str, Path], *, inside: bool = False) -> dict:
    """谁 import 了这一层的模块，以及从里面取了哪些名字。

    `inside=True` 时只看**层内**的互相 import —— ⭐ 这是为了把「0 个外部依赖」
    劈成两种：**层内自用**（合理，它就是个内部件）和**真的没人用**（可疑）。
    ⛔ 不劈开的代价很具体：`core.resource_catalog` 外部引用是 0，
    而它被同层的 `resource_health` / `resource_import_wizard` 各 import 了一次 ——
    读成「死模块」就会有人去删它。RN-596「尺子只有两格而世界有三种」同款。
    """
    by_module: dict[str, dict] = {m: {"files": set(), "names": Counter()} for m in layer}
    alias_hits: dict[str, Counter] = defaultdict(Counter)
    own = {p.relative_to(ROOT).as_posix() for p in layer.values()}

    for path in (sorted(layer.values()) if inside else live_py_files()):
        rel = path.relative_to(ROOT).as_posix()
        if (rel in own) is not inside:
            continue
        try:
            tree = ast.parse(path.read_text(encoding="utf-8", errors="replace"))
        except SyntaxError:
            continue
        aliases: dict[str, str] = {}
        for node in ast.walk(tree):
            if isinstance(node, ast.Import):
                for a in node.names:
                    if a.name in layer:
                        aliases[a.asname or a.name.split(".")[0]] = a.name
                        by_module[a.name]["files"].add(rel)
            elif isinstance(node, ast.ImportFrom):
                mod = node.module or ""
                if mod in layer:
                    by_module[mod]["files"].add(rel)
                    for a in node.names:
                        # ⭐⭐⭐ RN-626：`from core.hotkeys import registry as hk` ——
                        #   这里的 `registry` **不是 `__init__.py` 里的一个名字，
                        #   是一个子模块**。老口径把它当普通名字记进 `core.hotkeys`
                        #   的 names，而 `__init__.py` 一个函数都没定义 ⇒ 交集为空 ⇒
                        #   **X10 整层的契约读数是 0，而实际有 7 个文件在用它。**
                        #   ⛔ 一个「没人依赖」的读数，和一把量不到的尺子，
                        #   在快照里长得一模一样 —— 而前者会licence别人随便改名。
                        sub = f"{mod}.{a.name}"
                        if sub in layer:
                            aliases[a.asname or a.name] = sub
                            by_module[sub]["files"].add(rel)
                        else:
                            by_module[mod]["names"][a.name] += 1
        for node in ast.walk(tree):
            if isinstance(node, ast.Attribute) and isinstance(node.value, ast.Name):
                mod = aliases.get(node.value.id)
                if mod:
                    by_module[mod]["names"][node.attr] += 1
                    alias_hits[mod][rel] += 1
    return {m: {"files": sorted(v["files"]), "names": dict(sorted(v["names"].items()))}
            for m, v in by_module.items()}


def build(layer_name: str) -> dict:
    spec = LAYERS[layer_name]
    layer = {m: ROOT / rel for m, rel in spec["modules"].items()}
    missing = [m for m, p in layer.items() if not p.exists()]
    assert not missing, (
        f"{layer_name} 的这几个文件不存在：{missing} —— "
        "层定义过期了（文件被改名或挪走），先把 LAYERS 改对再量。")

    surfaces = {m: module_surface(p) for m, p in layer.items()}
    used = importers(layer)

    contract = {}
    for m, s in surfaces.items():
        defined = set(s["functions"]) | set(s["classes"]) | set(s["constants"])
        contract[m] = sorted(defined & set(used[m]["names"]))

    # ⛔⛔ 工具自己的分母守卫（RN-626 换来的）：**有人 import 它，却一个契约名都数不出来**
    #   —— 这个组合几乎一定是尺子够不到，不是真的没人依赖。
    #   ⭐ 不守这一条的代价是具体的：X10 会被冻成「契约 0 个名字」，
    #   而那份基线等于**批准任何人随便改 `registry.py` 里的每一个名字**，棘轮永远绿。
    blind = [m for m in layer
             if used[m]["files"] and not contract[m]
             and not surfaces[m]["functions"] and not surfaces[m]["classes"]]
    real_blind = [m for m in layer if used[m]["files"] and not contract[m]
                  and m not in blind]
    # 「外部 0 个」再劈成两种：层内自用 vs 真的没人用。
    inner = importers(layer, inside=True)
    internal_only = [m for m in layer
                     if not used[m]["files"] and inner[m]["files"]]
    unreferenced = [m for m in layer
                    if not used[m]["files"] and not inner[m]["files"]]

    data = {
        "loc": {m: len(p.read_text(encoding="utf-8").splitlines())
                for m, p in layer.items()},
        "surface": surfaces,
        "external_use": used,
        "contract": contract,
        "contract_total": sum(len(v) for v in contract.values()),
        # ⭐ 两栏分开记：一栏是「它本来就是个只做转发的 `__init__`」（合理），
        #   一栏是「它定义了东西、也有人 import，却一个都没对上」（可疑，要人看）。
        "reexport_only_modules": sorted(blind),
        "imported_but_no_contract": sorted(real_blind),
        "internal_only_modules": sorted(internal_only),
        "unreferenced_modules": sorted(unreferenced),
    }
    if spec["instance"]:
        mod_key, cls_name, out_key = spec["instance"]
        data[out_key] = instance_surface(layer[mod_key], cls_name)
    return data


def _dump(data: dict) -> str:
    return json.dumps(data, ensure_ascii=False, indent=2, sort_keys=True) + "\n"


def verify_x3() -> int:
    """⭐ 等价验收：**老工具产出的每一个键，新工具都给出逐字节相同的值。**

    ⚠⚠ 这条判据的措辞被改过一次，而改它的理由必须留在这里 ——
    原来写的是「两份输出逐字节相同」。RN-626 的修法给新工具加了两个**新键**
    （`reexport_only_modules` / `imported_but_no_contract`），于是它当场红了。
    ⭐⭐⭐ 这种时候有两条路，而它们看起来一样合理：
      · 把尺子放松成「差不多就行」—— **那是让自己绿**；
      · 把尺子的**问题**改对 —— 我要问的从来不是「字节一样吗」，是「**口径变了吗**」。
    ⇒ 现在量三件事：① 老键一个不少；② 每个老键的值逐字节相同；
       ③ 新增的键**只能是新增**，不许顶替老键。
    ⛔ 第 ③ 条是防我自己的：没有它，「把一个老键改个名字」就能从这条检查底下走过去。
    """
    sys.path.insert(0, str(ROOT / "scripts"))
    import x3_contract_snapshot as old

    mine, theirs = build("X3"), old.build()
    missing = sorted(set(theirs) - set(mine))
    if missing:
        print(f"⛔ 等价验收没过：老工具有这些键而新工具没有 —— {missing}")
        return 1

    bad = []
    for k in sorted(theirs):
        a, b = json.dumps(mine[k], ensure_ascii=False, sort_keys=True), \
               json.dumps(theirs[k], ensure_ascii=False, sort_keys=True)
        if a != b:
            bad.append((k, a[:160], b[:160]))
    if bad:
        print(f"⛔ 等价验收没过：{len(bad)} 个键的值不同")
        for k, a, b in bad[:3]:
            print(f"   键 {k}：\n     新：{a}\n     旧：{b}")
        return 1

    added = sorted(set(mine) - set(theirs))
    print(f"✅ 等价验收通过：老工具的 {len(theirs)} 个键**逐字节相同**；"
          f"新工具另有 {len(added)} 个新增键 {added}")
    return 0


def main() -> int:
    ap = argparse.ArgumentParser()
    ap.add_argument("--layer", choices=sorted(LAYERS))
    ap.add_argument("--write", action="store_true")
    ap.add_argument("--verify-x3", action="store_true")
    args = ap.parse_args()

    if args.verify_x3:
        return verify_x3()
    if not args.layer:
        ap.error("要么给 --layer，要么给 --verify-x3")

    data = build(args.layer)
    total_loc = sum(data["loc"].values())
    print(f"{args.layer} 层行数合计 {total_loc}（{len(data['loc'])} 个模块）")
    for m, n in data["loc"].items():
        print(f"  {m:36s} {n:5d}")
    print()
    for m in data["surface"]:
        s = data["surface"][m]
        print(f"{m}: 定义 函数 {len(s['functions'])} / 类 {len(s['classes'])} / "
              f"常量 {len(s['constants'])}  ⇒ 外部真用到 {len(data['contract'][m])}"
              f"（{len(data['external_use'][m]['files'])} 个文件 import）")
    print(f"\n契约名合计 {data['contract_total']}")
    for key, label in (("reexport_only_modules", "只做转发的包入口（外部契约当然是 0）"),
                       ("internal_only_modules", "⭐ 只被同层用（是内部件，不是死模块）"),
                       ("unreferenced_modules", "⛔ 层内层外都没人 import（要人看一眼）"),
                       ("imported_but_no_contract", "⛔ 有人 import、定义也有，却一个都没对上")):
        if data.get(key):
            print(f"{label}：{data[key]}")

    if args.write:
        out = ROOT / "tests" / "baselines" / f"{args.layer.lower()}_contract.json"
        out.parent.mkdir(parents=True, exist_ok=True)
        out.write_text(_dump(data), encoding="utf-8")
        print(f"\n已写入 {out.relative_to(ROOT)}")
    else:
        print("\n（没给 --write，什么都没写）")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

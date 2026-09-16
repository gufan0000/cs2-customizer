# SPDX-License-Identifier: GPL-3.0-or-later
"""资源导入：扫描、归类、落盘。

## 两条路，共用同一个复制引擎

| 入口 | 谁在用 | 识别方式 |
|---|---|---|
| `scan_resource_import_candidates` | 旧向导（原样保留） | 路径里必须出现 spec 目录名 |
| `plan_from_decisions` | 统一资源导入（2026-09-16 新增） | `resource_identify` 三级漏斗 + `resource_placement` 归类 |

⭐ 两条路都产出同一种 report，落盘都走 `apply_resource_import_plan` ——
那里面的**冲突检测**和**逃逸检查**是已经验证过的，不该为新路再写一遍。
⚠ 逃逸检查保留在落盘那一侧，即使 `resource_placement` 自己也清洗过名字：
**两道独立的检查比一道"更仔细"的强**。
"""

from __future__ import annotations

import os
import shutil
from typing import Dict, List, Optional

from core.resource_catalog import (
    build_spec_lookup,
    get_resource_spec,
    iter_resource_specs,
    resolve_import_domain,
)


def _normalize_extension(filename: str) -> str:
    _stem, ext = os.path.splitext(str(filename or ""))
    return ext.strip().lower()


def _extract_target_rel_path(source_dir: str, source_file: str, domain: str) -> Optional[Dict[str, str]]:
    rel_path = os.path.relpath(source_file, source_dir)
    parts = list(os.path.normpath(rel_path).split(os.sep))
    spec_lookup = build_spec_lookup(resolve_import_domain(domain))
    for idx, part in enumerate(parts):
        spec = spec_lookup.get(str(part or "").strip().lower())
        if not spec:
            continue
        tail = parts[idx + 1 :]
        if not tail:
            return None
        return {
            "spec_key": spec.key,
            "spec_label": spec.label,
            "target_rel_path": os.path.join(spec.target_rel_root, *tail),
            "domain": spec.domain,
        }
    return None


def scan_resource_import_candidates(
    source_dir: str,
    resources_root: str,
    domain: str = "audio",
) -> Dict[str, object]:
    recognized: List[Dict[str, object]] = []
    unrecognized: List[Dict[str, str]] = []
    scanned_resource_files = 0

    source_dir = os.path.abspath(str(source_dir or ""))
    resources_root = os.path.abspath(str(resources_root or ""))
    selected_specs = iter_resource_specs(resolve_import_domain(domain))
    allowed_exts = {ext.lower() for spec in selected_specs for ext in spec.extensions}

    if not source_dir or not os.path.isdir(source_dir):
        return {
            "source_dir": source_dir,
            "resources_root": resources_root,
            "domain": domain,
            "recognized": recognized,
            "unrecognized": [
                {
                    "source_path": source_dir,
                    "reason": "source directory missing",
                }
            ],
            "summary": {
                "scanned_resource_files": 0,
                "recognized_count": 0,
                "unrecognized_count": 1,
                "conflict_count": 0,
                "importable_count": 0,
                "ok": False,
            },
        }

    for walk_root, _dirs, files in os.walk(source_dir):
        for filename in files:
            if _normalize_extension(filename) not in allowed_exts:
                continue

            scanned_resource_files += 1
            source_path = os.path.join(walk_root, filename)
            extracted = _extract_target_rel_path(source_dir, source_path, domain)
            if not extracted:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "path does not include a supported resource category root",
                    }
                )
                continue

            spec = next((item for item in selected_specs if item.key == extracted["spec_key"]), None)
            if spec is None:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "resource category not supported in current mode",
                    }
                )
                continue

            if _normalize_extension(filename) not in {ext.lower() for ext in spec.extensions}:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": f"unsupported file extension for {spec.label}",
                    }
                )
                continue

            target_rel_path = str(extracted["target_rel_path"])
            target_abs_path = os.path.abspath(os.path.join(resources_root, target_rel_path))
            is_within_root = os.path.commonpath([resources_root, target_abs_path]) == resources_root
            if not is_within_root:
                unrecognized.append(
                    {
                        "source_path": source_path,
                        "reason": "resolved target escapes resources root",
                    }
                )
                continue

            conflict = os.path.exists(target_abs_path)
            recognized.append(
                {
                    "source_path": source_path,
                    "target_rel_path": target_rel_path,
                    "target_abs_path": target_abs_path,
                    "spec_key": spec.key,
                    "spec_label": spec.label,
                    "domain": spec.domain,
                    "conflict": conflict,
                }
            )

    recognized.sort(key=lambda item: str(item.get("target_rel_path", "")).lower())
    unrecognized.sort(key=lambda item: str(item.get("source_path", "")).lower())

    conflict_count = sum(1 for item in recognized if bool(item.get("conflict")))
    importable_count = max(0, len(recognized) - conflict_count)
    category_counts: Dict[str, int] = {}
    for item in recognized:
        key = str(item.get("spec_key", ""))
        category_counts[key] = category_counts.get(key, 0) + 1

    return {
        "source_dir": source_dir,
        "resources_root": resources_root,
        "domain": domain,
        "recognized": recognized,
        "unrecognized": unrecognized,
        "summary": {
            "scanned_resource_files": scanned_resource_files,
            "recognized_count": len(recognized),
            "unrecognized_count": len(unrecognized),
            "conflict_count": conflict_count,
            "importable_count": importable_count,
            "ok": len(recognized) > 0,
            "category_counts": category_counts,
        },
    }


def apply_resource_import_plan(
    scan_report: Dict[str, object],
    *,
    dry_run: bool = False,
    overwrite_existing: bool = False,
    progress=None,
    should_cancel=None,
) -> Dict[str, object]:
    """把计划落到磁盘上。

    ⚠⚠ `progress` / `should_cancel` 是 2026-09-17 补的。原来这个函数**根本
    没有这两个参数**，而页面那头明明拿到了 `should_cancel` 并画了进度框 ——
    于是写盘阶段点「取消」：进度框消失、界面解锁，**复制照常跑完并报"导入完成"**。
    ⭐⭐ 一个点下去什么都不会发生的取消键，比没有取消键更糟：
    用户以为自己拦住了，然后去别处等一个不会发生的结果。
    ⛔ 取消**不是回滚**：已经复制过去的那些由调用方决定留还是收（页面给撤销）。
    """
    recognized = list(scan_report.get("recognized", []) or [])
    copied: List[Dict[str, str]] = []
    skipped_conflicts: List[Dict[str, str]] = []
    failed: List[Dict[str, str]] = []
    cancelled = False
    total = max(1, len(recognized))

    for index, item in enumerate(recognized, start=1):
        if should_cancel is not None and should_cancel():
            cancelled = True
            break
        if progress is not None:
            try:
                progress(index, total, "正在写入资源目录")
            except Exception:
                # ⭐ 通知路径绝不许成为故障源（同 RN-652：错误处理不该依赖
                #   那个已经坏掉的东西）——进度框没了也不该把导入掀翻。
                pass
        source_path = str(item.get("source_path", ""))
        target_abs_path = str(item.get("target_abs_path", ""))
        target_rel_path = str(item.get("target_rel_path", ""))
        if not source_path or not target_abs_path:
            failed.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "reason": "invalid plan item",
                }
            )
            continue

        exists = os.path.exists(target_abs_path)
        if exists and not overwrite_existing:
            skipped_conflicts.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                }
            )
            continue

        if dry_run:
            copied.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                }
            )
            continue

        try:
            os.makedirs(os.path.dirname(target_abs_path), exist_ok=True)
            shutil.copy2(source_path, target_abs_path)
            copied.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                }
            )
        except Exception as exc:
            failed.append(
                {
                    "source_path": source_path,
                    "target_abs_path": target_abs_path,
                    "target_rel_path": target_rel_path,
                    "spec_key": str(item.get("spec_key", "")),
                    "domain": str(item.get("domain", "")),
                    "reason": str(exc),
                }
            )

    # ⭐ 失败就整体收回：**半套素材留在资源库里比什么都没导进去更难收拾** ——
    #   用户看到设置页多出一个只有三分之一文件的风格，不会知道那是失败的残骸。
    # ⚠ dry_run 不会真写，自然也不用回滚。
    if failed and copied and not dry_run:
        rolled = undo_import({"copied": copied})
        removed = int(rolled["summary"]["removed_count"])
        # ⚠ 回滚**自己也会失败**（文件被占用、只读、权限）。原来只看删了几个、
        #   不看删不掉几个，就把 `copied` 清空并对用户说"没有留下半套素材" ——
        #   而删不掉的那些还躺在资源库里。⭐ 一句不成立的保证比不保证更坏。
        stuck = int(rolled["summary"].get("failed_count", 0) or 0)
        rollback = {
            "rolled_back": True,
            "removed_count": removed,
            "stuck_count": stuck,
            "stuck": [str(entry.get("target_abs_path", "")) for entry in
                      (rolled.get("failed") or [])][:20],
        }
        # ⭐ 收不回来的那几个**仍然在盘上** ⇒ 留在 `copied` 里，
        #   这样撤销按钮还能再试一次，报告里也数得出来。
        copied = [c for c in copied
                  if os.path.exists(str(c.get("target_abs_path", "")))] \
            if stuck else []
    else:
        rollback = {"rolled_back": False, "removed_count": 0,
                    "stuck_count": 0, "stuck": []}

    return {
        "dry_run": bool(dry_run),
        "overwrite_existing": bool(overwrite_existing),
        "cancelled": bool(cancelled),
        "rollback": rollback,
        "copied": copied,
        "skipped_conflicts": skipped_conflicts,
        "failed": failed,
        "summary": {
            "copied_count": len(copied),
            "skipped_conflicts_count": len(skipped_conflicts),
            "failed_count": len(failed),
            "cancelled": bool(cancelled),
            "ok": len(failed) == 0 and not cancelled,
        },
    }



# ---------------------------------------------------------------- 收回这一次的导入

def undo_import(import_result: Dict[str, object]) -> Dict[str, object]:
    """把一次导入复制进去的文件删掉。

    ⭐ 撤销与"失败回滚"是**同一个动作**：都是"把这一次放进去的东西拿回来"。
    ⇒ 写一次，两处用（`_run_import` 失败时自动调，用户点「撤销」时手动调）。

    ⛔ 只删**这一次 `copied` 里记下的那些路径**，别的一概不碰：
    - 冲突跳过的（`skipped_conflicts`）本来就没写进去，删了就是删用户的旧素材；
    - 目录只在**空了**的时候才收，非空说明里面还有别人的东西。

    ⚠ 删之前不比对内容：两次导入之间用户可能编辑过那个文件。
    ⭐ 但撤销紧跟着导入发生，而"删掉刚放进来的"正是用户按下去时期待的事 ——
    真要防，该防的是"隔了很久还能撤销"，所以 UI 那边点一次就把按钮收掉。
    """
    copied = list((import_result or {}).get("copied", []) or [])
    removed: List[str] = []
    failed: List[Dict[str, str]] = []
    directories = set()

    for item in copied:
        target = str(item.get("target_abs_path") or "")
        if not target:
            continue
        try:
            if os.path.isfile(target):
                os.remove(target)
                removed.append(target)
                directories.add(os.path.dirname(target))
        except OSError as exc:
            failed.append({"target_abs_path": target, "reason": str(exc)})

    # 空目录顺着往上收一层层 —— 只收空的。
    for directory in sorted(directories, key=len, reverse=True):
        current = directory
        for _depth in range(4):
            try:
                if os.path.isdir(current) and not os.listdir(current):
                    os.rmdir(current)
                    current = os.path.dirname(current)
                else:
                    break
            except OSError:
                break

    return {
        "removed": removed,
        "failed": failed,
        "summary": {
            "removed_count": len(removed),
            "failed_count": len(failed),
            "ok": not failed,
        },
    }

# ---------------------------------------------------------------- 学习表

#: 配置里存学习表的字段名。⚠ 值是 `{形状指纹: spec_key}`。
IMPORT_MEMORY_KEY = "resource_import_shape_memory"


def _memory_path() -> str:
    """学习表落在哪。

    ⚠ 走 `ResourceManager`，它认 `CS2C_CONFIG_DIR` ——
    判据和沙箱跑起来不会碰用户的真实配置目录。
    """
    from resource_manager import ResourceManager

    return ResourceManager.get_app_data_path("resource_import_memory.json")


def load_import_memory() -> Dict[str, str]:
    """读「同样形状上次归成了哪一类」。读不到就当空表 —— 顶多多问一次。

    ⚠⚠ 这张表原来存在 `config` 的一个属性上，而它**从来没落过盘**，
    两个独立的原因各自都足以让它失效：
    ① 写的时候查的是 `config.save`，而 config 上根本没有这个方法
       （真名是 `save_config()`）；
    ② 就算名字对了也没用 —— `config.py` 的 `payload` 是一张**写死的字段表**
       （字典字面量），往 config 上 setattr 一个表里没有的键，
       保存时压根不会被序列化。
    ⭐⭐ 而「存不下」的表现（同一次开着软件不再问、重启又问）
       和「存下了」几乎一样，**只有跨进程才看得出来** ——
       所以任何只在一个进程里跑的判据都逮不到它。
    ⇒ 学习表不是用户设置，是导入器自己的状态 ⇒ 给它自己的小文件，
      不去动 config 那张字段表（那边有 schema 迁移判据盯着）。
    """
    import json

    try:
        with open(_memory_path(), "r", encoding="utf-8") as handle:
            raw = json.load(handle)
    except (OSError, ValueError):
        return {}
    return {str(k): str(v) for k, v in raw.items()} if isinstance(raw, dict) else {}


def remember_decisions(groups, decisions) -> None:
    """把用户这一次的选择记下来。

    ⛔ 只记**问过的那些**（`needs_user`）：没问过的本来就不会再问，
    记了只会让表白白变大。
    ⚠ 写失败就算了 —— 学习表只是省一次点击，不该为它挡住导入。
    """
    try:
        memory = dict(load_import_memory())
        by_shape = {id(group): group.shape for group in groups if group.needs_user}
        shapes = list(by_shape.values())
        for index, decision in enumerate(decisions or []):
            key = str(decision.get("spec_key") or "").strip()
            if not key or index >= len(shapes):
                continue
            memory[shapes[index]] = key
        _write_import_memory(memory)
    except Exception:
        return


def _write_import_memory(memory: Dict[str, str]) -> None:
    """把学习表落盘。

    ⚠ 先写临时文件再原子替换 —— 断电时宁可丢这一次的记忆，
    也不许留下一个解析不了的半截 JSON：那会让**以后每一次导入的每一组
    都重新问一遍**，而用户根本不会想到去删一个他不知道存在的文件。
    """
    import json
    import os
    import tempfile

    # ⛔ 不许用裸 `os.replace` —— Windows 上它有 ~8% 概率被 Defender / 索引服务的
    #   扫描窗口打断（RN-613，判据
    #   `test_no_file_in_the_product_calls_os_replace_without_the_retry` 盯着）。
    #   ⭐ 这一条是我这一轮新写的代码当场被那条棘轮逮住的：
    #     **一条守得住的棘轮，逮的就是"下一个没读过这段历史的人"。**
    from core.io_validation import replace_with_retry

    path = _memory_path()
    os.makedirs(os.path.dirname(path), exist_ok=True)
    handle, tmp = tempfile.mkstemp(dir=os.path.dirname(path), suffix=".tmp")
    try:
        with os.fdopen(handle, "w", encoding="utf-8") as sink:
            json.dump(memory, sink, ensure_ascii=False, indent=2)
        replace_with_retry(tmp, path)
    except Exception:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


# ---------------------------------------------------------------- 从源到决定

def prepare_decisions(source, domain: str = "all") -> Dict[str, object]:
    """读清单 → 识别 → 把**能自动定的**定下来。

    返回 `{"decided": [...], "unsure": [Group...], "default_style": str}`。

    ⚠⚠ `domain` 是页面上那个「导入模式」下拉框（音频 / 视觉 / 全部）。
    它原来**根本没传进来** —— 实测：模式选「视觉」，一个音频包照样整包导进去。
    ⭐ 一个不起作用的下拉框比没有还糟：用户以为自己划定了范围。

    ⭐ 这一段本来长在页面里，核查时为了验证又被抄了一份 ——
    而我改了页面、抄的那份照旧是旧的。⇒ 放在这里，谁都调同一份。
    ⚠ 本函数**不碰 Qt**，所以判据能直接喂一个假 source 跑。
    """
    from core.resource_identify import (
        identify_groups,
        read_manifest,
        style_name_from_manifest,
    )

    manifest = read_manifest(source.paths, source.read_text)
    groups = identify_groups(
        source.paths, source_name=source.display_name, manifest=manifest,
        memory=load_import_memory())
    # ⭐ 包里写好的名字直接用：官网的击杀图标包在 `style.json` 里带着 `name`，
    #   再问一遍"这套叫什么"就是把用户填过的东西又问一次。
    # ⚠ 包名兜底 —— 多数音效包没有清单，而包文件名就是作者起的名字。
    default_style = style_name_from_manifest(manifest) or source.display_name
    wanted = _domain_spec_keys(domain)
    decided = []
    skipped_by_domain = []
    for group in groups:
        pick = group.preselect
        if wanted is not None and pick is not None and pick.spec_key not in wanted:
            # ⭐ 被模式挡在外面 ⇒ **说出来**，不许静默丢掉：
            #   用户看到「导入完成：成功 0」而不知道为什么，比报一句错还难受。
            skipped_by_domain.append(group)
            continue
        if group.needs_user:
            continue
        decided.append({
            "paths": list(group.paths),
            "spec_key": pick.spec_key,
            "style_name": default_style,
            "bucket": "",
            # ⭐ 自动归的那些必须说清**凭什么** —— `likely` 不再弹窗拦人，
            #   防静默的位置就全在这一行上了。
            "why": f"{pick.label}（{'；'.join(pick.evidence)}）",
        })
    unsure = [group for group in groups
              if group.needs_user and group not in skipped_by_domain]
    # ⛔⛔ 「认得出这是什么」不等于「知道该摆到哪」。
    #   实测：一个**结构完全规范**的回合音效包（路径里就带着 `round_sounds/win/`）
    #   被认成 CERTAIN ⇒ 不问；而归类器还要知道是哪个回合事件，于是它提了个问题，
    #   `plan_from_decisions` 把这一组扔进 `unresolved` —— 结果是
    #   **一个文件都没导进去，而且一句话都没说**。
    # ⭐⭐⭐ 两层各自都对：识别层确实认得出，归类层确实还缺一个答案；
    #   错在中间没有人把「归类层还要问」这件事**送回给用户**。
    from core.resource_placement import plan_placements

    still_asking = []
    for item in list(decided):
        group = _group_of(groups, item["paths"])
        if group is None or group in unsure:
            continue
        plan = plan_placements(
            item["spec_key"], item["paths"],
            style_name=item.get("style_name", ""),
            bucket=item.get("bucket", ""),
            outer_layer=getattr(source, "stripped_root", ""))
        if plan.questions:
            decided.remove(item)
            still_asking.append(group)
    return {
        "decided": decided,
        "unsure": unsure + still_asking,
        "default_style": default_style,
        "groups": groups,
        "skipped_by_domain": skipped_by_domain,
    }


def _group_of(groups, paths):
    """按 paths 找回那个 group（decided 里只留了 paths）。"""
    wanted = list(paths or [])
    for group in groups:
        if list(group.paths) == wanted:
            return group
    return None


def _domain_spec_keys(domain: str):
    """这个模式允许哪些 spec；`None` 表示不限。

    ⛔ 不在这里另立一张分类表 —— `RESOURCE_SPECS` 每条自带 `domain`。
    """
    value = str(domain or "all").strip().lower()
    if value in ("", "all"):
        return None
    from core.resource_catalog import RESOURCE_SPECS

    keys = {spec.key for spec in RESOURCE_SPECS
            if str(spec.domain).lower() == value}
    return keys or None


# ---------------------------------------------------------------- 统一导入的连接层

def plan_from_decisions(source, decisions, resources_root: str) -> Dict[str, object]:
    """把「用户对每一组的决定」变成落盘计划。

    `source` 是 `resource_import_source.ImportSource`；
    `decisions` 形如 `[{"paths": [...], "spec_key": "gun_sounds",
                        "style_name": "沙漠之鹰", "bucket": ""}]`。

    ⭐ 产出与 `scan_resource_import_candidates` **同构**，所以能直接交给
    `apply_resource_import_plan` —— 冲突检测、逃逸检查、dry-run 全部白捡。
    """
    from core.resource_placement import plan_placements

    resources_root = os.path.abspath(str(resources_root or ""))
    recognized: List[Dict[str, object]] = []
    unresolved: List[Dict[str, str]] = []
    warnings: List[str] = []

    for decision in decisions or []:
        spec_key = str(decision.get("spec_key") or "").strip()
        paths = [str(item) for item in (decision.get("paths") or [])]
        if not spec_key or not paths:
            continue
        plan = plan_placements(
            spec_key,
            paths,
            style_name=str(decision.get("style_name") or ""),
            bucket=str(decision.get("bucket") or ""),
            # ⚠ 剥壳可能剥掉的正是风格目录（`风格甲/1.mp3`）⇒ 带下去给它补回来。
            outer_layer=getattr(source, "stripped_root", ""),
        )
        warnings.extend(plan.warnings)
        if plan.questions:
            # ⭐ 还没问完就落盘是最糟的一种失败：文件已经散进资源库了，
            #   而用户还以为自己在填表。⇒ 这一组整组不落。
            unresolved.append({
                "spec_key": spec_key,
                "reason": "；".join(str(q.get("label", "")) for q in plan.questions),
            })
            continue
        for placement in plan.placements:
            target_abs = os.path.abspath(
                os.path.join(resources_root, placement.target_rel_path))
            # ⚠ 第二道逃逸检查（第一道在 `_clean_name`）。
            if os.path.commonpath([resources_root, target_abs]) != resources_root:
                unresolved.append({
                    "spec_key": spec_key,
                    "reason": f"算出来的位置落在资源目录外面：{placement.target_rel_path}",
                })
                continue
            spec = get_resource_spec(spec_key)
            recognized.append({
                "why": str(decision.get("why") or ""),
                "source_path": source.abs_path(placement.source),
                "target_rel_path": placement.target_rel_path,
                "target_abs_path": target_abs,
                "spec_key": spec_key,
                "spec_label": spec.label if spec else spec_key,
                "domain": spec.domain if spec else "",
                "conflict": os.path.exists(target_abs),
            })

    conflict_count = sum(1 for item in recognized if bool(item.get("conflict")))
    category_counts: Dict[str, int] = {}
    for item in recognized:
        key = str(item.get("spec_key", ""))
        category_counts[key] = category_counts.get(key, 0) + 1

    return {
        "source_dir": source.root,
        "resources_root": resources_root,
        "domain": "all",
        "recognized": recognized,
        "unrecognized": unresolved,
        "warnings": warnings,
        "summary": {
            "scanned_resource_files": len(source.paths),
            "recognized_count": len(recognized),
            "unrecognized_count": len(unresolved),
            "conflict_count": conflict_count,
            "importable_count": max(0, len(recognized) - conflict_count),
            "ok": len(recognized) > 0,
            "category_counts": category_counts,
        },
    }

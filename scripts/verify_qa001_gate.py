# -*- coding: utf-8 -*-
"""QA-001 门禁的**真产物**回退验证。

`verify_onedir_tree()` 里那条「产物里不许出现 config.json」的反向断言，此前只在
`tests/test_qa_non_ui_r12.py` 里对**造出来的假目录**跑过。假目录证明不了它在真实
打包产物上也成立（真产物的目录结构、大小写、以及 `verify_onefile_archive` 那一步
都可能让流程在断言之前就走岔）。

做法（两问两答，缺一不可）：
  ① 真产物原样过一遍 → 必须**通过**（否则判据太严，会把好包也拦掉）
  ② 往真产物里塞一份 config.json 再过一遍 → 必须**抛错**（否则判据是假绿的）

塞进去的是临时副本，无论成败都会删掉，不改动发布产物。

    python scripts/verify_qa001_gate.py --folder "release/CS2 Customizer 2.2.2"

退出码：0=两问都答对；1=有一问答错。
"""
from __future__ import annotations

import argparse
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT / "build_tools"))

try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

from build_release import verify_onedir_tree  # noqa: E402


def main() -> int:
    parser = argparse.ArgumentParser(description="QA-001 门禁真产物回退验证")
    parser.add_argument("--folder", required=True, help="onedir 发布产物目录")
    parser.add_argument("--app-name", default="CS2 Customizer", help="产物内 exe 主名")
    args = parser.parse_args()

    folder = Path(args.folder)
    if not folder.is_dir():
        print(f"[FAIL] 产物目录不存在: {folder}")
        return 1

    internal = folder / "_internal"
    planted = internal / "config.json"
    if planted.exists():
        print(f"[FAIL] 验证开始前产物里就已经有 {planted} —— 这本身就是 QA-001 复发")
        return 1

    ok = True

    # ① 真产物原样：必须通过
    print("[1/2] 真产物原样过门禁（期望：通过）")
    try:
        verify_onedir_tree(folder, args.app_name, require_obfuscation=True)
        print("      → 通过 ✔")
    except Exception as exc:
        print(f"      → 未通过 ✘ 判据过严，会把好包也拦掉: {exc}")
        ok = False

    # ② 塞一份 config.json 进去：必须抛错
    print("[2/2] 往 _internal 塞一份 config.json 再过门禁（期望：抛错）")
    src = ROOT / "config.json"
    try:
        if src.exists():
            shutil.copy2(src, planted)
        else:
            planted.write_text('{"csgo_dir": "G:/fake"}', encoding="utf-8")
        try:
            verify_onedir_tree(folder, args.app_name, require_obfuscation=True)
        except RuntimeError as exc:
            if "config.json" in str(exc):
                print(f"      → 如期抛错 ✔ {str(exc).splitlines()[0]}")
            else:
                print(f"      → 抛错了但理由不对 ✘: {exc}")
                ok = False
        else:
            print("      → 放行了 ✘ **这条判据是假绿的**")
            ok = False
    finally:
        if planted.exists():
            planted.unlink()
            print(f"      （已清理临时塞入的 {planted}）")

    # 收尾自检：确认清理干净，没把发布产物弄脏
    if planted.exists():
        print("[FAIL] 临时文件没清理干净，产物已被污染")
        ok = False

    print()
    print("[PASS] QA-001 门禁在真实打包产物上成立" if ok else "[FAIL] QA-001 门禁未通过真产物验证")
    return 0 if ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

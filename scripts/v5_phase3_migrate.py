# SPDX-License-Identifier: GPL-3.0-or-later
"""v5 Phase 3 迁移脚本 — 把 16 个 page 的 _create_section_card 替换为 SettingsCard.make().

每个 page 改 3 处:
  1. 删除 _create_section_card 方法定义
  2. 加 'from widgets.settings_card import SettingsCard' import
  3. 把所有 self._create_section_card(...) 替换为 SettingsCard.make(...)

针对每个 page 的视觉特殊性(margins/spacing 差异),给 .make() 加额外参数.
"""

from __future__ import annotations

import re
import sys
from pathlib import Path

PROJECT_ROOT = Path(__file__).resolve().parents[1]


# 每个 page 的迁移配置:(margins, spacing) 自定义参数
# None 表示用默认 (14,12,14,12), 8
PAGE_OVERRIDES: dict[str, tuple[str, str] | None] = {
    "about_page.py":          ("(14, 14, 14, 14)", "10"),
    "advanced_page.py":       None,  # 默认
    "audio_health_page.py":   None,
    "audio_import_wizard_page.py": None,
    "audio_replay_page.py":   None,
    "audio_task_panel_page.py": None,
    "config_snapshot_page.py": None,
    "flash_page.py":          None,
    "hud_color_page.py":      (None, "10"),  # 仅 spacing 改 10
    "kill_icon_page.py":      None,
    "magnifier_page.py":      (None, "10"),
    "preset_center_page.py":  (None, "10"),
    "screen_effects_page.py": None,
    "special_sound_page.py":  None,
    "viewmodel_page.py":      None,
}


def remove_create_section_card_method(content: str) -> str:
    """删除 _create_section_card 方法定义.

    匹配: def _create_section_card(...): 直到 return card, card_layout
    """
    # 匹配从 'def _create_section_card' 到第一次 'return card, card_layout' (含)
    pattern = re.compile(
        r'    def _create_section_card\([^)]*?\):.*?return card, card_layout\s*\n',
        re.DOTALL,
    )
    new = pattern.sub("", content, count=1)
    if new == content:
        # 看看实际内容是 'return card_layout' 还是变种
        m = re.search(r'    def _create_section_card\([^)]*?\):.*?(return [^\n]+)\n', content, re.DOTALL)
        if m:
            print(f"  [warn] 方法体不以 'return card, card_layout' 结尾,实际: {m.group(1)}")
            # 尝试用更宽松的匹配
            pattern_loose = re.compile(
                r'    def _create_section_card\([^)]*?\):.*?(?=\n    def |\nclass |\Z)',
                re.DOTALL,
            )
            new = pattern_loose.sub("", content, count=1)
    return new


def add_import(content: str) -> str:
    """在合适位置加 'from widgets.settings_card import SettingsCard'."""
    if "from widgets.settings_card import SettingsCard" in content:
        return content

    # 找最后一个 'from widgets...' 或 'from pages...' 附近
    lines = content.splitlines(keepends=True)
    insert_at = None
    for i, line in enumerate(lines):
        if line.startswith(("from widgets.", "from pages.", "from ui_help_panel")):
            insert_at = i
    if insert_at is None:
        # 找最后一个 import
        for i, line in enumerate(lines):
            if line.startswith(("from ", "import ")) and not line.startswith("from __future__"):
                insert_at = i

    if insert_at is None:
        raise RuntimeError("找不到合适的 import 插入位置")

    # 在 insert_at 之后插入
    new_lines = (
        lines[: insert_at + 1]
        + ["from widgets.settings_card import SettingsCard\n"]
        + lines[insert_at + 1 :]
    )
    return "".join(new_lines)


def replace_calls(content: str, override: tuple[str, str] | None) -> str:
    """把 self._create_section_card(args) 替换为 SettingsCard.make(args, [extra]).

    若有 override,在原参数后追加 margins=... spacing=... 关键字参数.
    """
    if override is None:
        # 简单替换
        return content.replace("self._create_section_card(", "SettingsCard.make(")

    margins, spacing = override
    extras = []
    if margins is not None:
        extras.append(f"margins={margins}")
    if spacing is not None:
        extras.append(f"spacing={spacing}")
    extras_str = ", ".join(extras)

    # 匹配每个 self._create_section_card(...) 调用,在闭合 ) 前插入 extras
    # 这里小心处理多行调用
    # 简化:先做扁平替换 self._create_section_card -> SettingsCard.make
    # 然后用正则在每个 SettingsCard.make(...) 末尾参数处加 extras
    new = content.replace("self._create_section_card(", "SettingsCard.make(")

    # 在每个 SettingsCard.make( ... ) 调用末尾加 extras
    # 用 brace counting 找到对应闭合 )
    out = []
    i = 0
    KEY = "SettingsCard.make("
    while i < len(new):
        idx = new.find(KEY, i)
        if idx < 0:
            out.append(new[i:])
            break
        out.append(new[i:idx])
        # 找到对应的 )
        depth = 1
        j = idx + len(KEY)
        in_str = None
        while j < len(new) and depth > 0:
            ch = new[j]
            if in_str:
                if ch == "\\":
                    j += 2
                    continue
                if ch == in_str:
                    in_str = None
            elif ch in ('"', "'"):
                in_str = ch
            elif ch == "(":
                depth += 1
            elif ch == ")":
                depth -= 1
                if depth == 0:
                    break
            j += 1
        # 现在 j 指向闭合 )
        if depth != 0:
            raise RuntimeError(f"unmatched parens at {idx}")
        # 提取参数区
        args_segment = new[idx + len(KEY): j]
        # 在末尾追加 extras
        # 注意:可能末尾有 \n + 缩进,需要谨慎
        rstripped = args_segment.rstrip()
        if rstripped.endswith(","):
            new_args = f"{rstripped} {extras_str}"
        else:
            new_args = f"{rstripped}, {extras_str}"
        # 保留末尾的空白(换行/缩进)
        trailing_ws = args_segment[len(rstripped):]
        out.append(KEY + new_args + trailing_ws + ")")
        i = j + 1

    return "".join(out)


def migrate_page(page_path: Path) -> dict:
    name = page_path.name
    if name not in PAGE_OVERRIDES:
        return {"name": name, "skipped": True, "reason": "not in target list"}

    content = page_path.read_text(encoding="utf-8")
    original = content

    if "def _create_section_card" not in content:
        return {"name": name, "skipped": True, "reason": "already migrated or no method"}

    # 1. 替换调用
    content = replace_calls(content, PAGE_OVERRIDES[name])
    # 2. 删除方法定义
    content = remove_create_section_card_method(content)
    # 3. 加 import
    content = add_import(content)

    # 防御:确保没有"还在调用 self._create_section_card 但已删了方法"
    if "self._create_section_card(" in content:
        return {"name": name, "skipped": True, "reason": "残留 self._create_section_card 调用"}
    if "def _create_section_card" in content:
        return {"name": name, "skipped": True, "reason": "方法定义未删除"}

    page_path.write_text(content, encoding="utf-8")
    delta = len(content) - len(original)
    return {
        "name": name,
        "skipped": False,
        "delta_chars": delta,
        "removed_lines": original.count("\n") - content.count("\n"),
    }


def main() -> int:
    pages_dir = PROJECT_ROOT / "pages"
    results = []
    for name in PAGE_OVERRIDES:
        page_path = pages_dir / name
        if not page_path.exists():
            print(f"  [skip] {name} 不存在")
            continue
        r = migrate_page(page_path)
        results.append(r)
        if r.get("skipped"):
            print(f"  [skip] {name}: {r.get('reason', '?')}")
        else:
            print(f"  [ok] {name}: -{r['removed_lines']} lines, delta {r['delta_chars']:+d} chars")

    migrated = [r for r in results if not r.get("skipped")]
    print(f"\n迁移完成: {len(migrated)} 个 page,总减 {sum(r['removed_lines'] for r in migrated)} 行")
    return 0


if __name__ == "__main__":
    sys.exit(main())

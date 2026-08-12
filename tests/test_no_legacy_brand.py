# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""旧品牌不得回流（2026-08-12 开源改名时建立）。

**为什么需要它**：本项目是从闭源版「帆派助手 / FanTool」裁出来的，改名那一轮
动了 107 个文件 507 处。这类机械改名的失败方式不是"改错"，而是**改漏**——
漏掉的那一处往往正是运行时标识（数据目录名、注册表值名、锁文件名），
而漏掉它不会让任何用例变红：程序照跑，只是把数据写进了另一个产品的目录。

所以这里有两条判据，强度不同：

1. **文本判据**（`test_no_legacy_brand_outside_allowlist`）：全仓扫旧名，
   只在白名单文件里允许——那几处是**溯源与商标声明**，是它们的功能，不是残留。
2. **行为判据**（其余几条）：直接读运行时真正用的那些常量，
   确认它们不再是旧名。文本判据能被一句注释绕过，这几条不能。

⚠ **这两条都看不见图片里的字。** 下面的 `BINARY_EXT` 是必须跳过的（你没法对
一张 PNG 做字符串替换），代价是印在启动闪屏、安装向导图上的旧产品名可以
一路全绿地留到公开。这个漏洞真的发生了，2026-08-12 公开前审计才查出来。
补它的判据在 `tests/test_brand_assets.py`：入库的品牌图必须与生成器的产物
逐字节一致——**本文件保证生成器里的文案常量不含旧名，那条保证图就是该生成器
出来的**，两条合起来才闭合。改这里的 `BINARY_EXT` 时记得那边还连着。

第 2 类比第 1 类重要。改名漏在注释里只是不好看；漏在 APP_NAME 上，
装了开源版的用户会和闭源版共用 `%LOCALAPPDATA%`——而两边的配置键集合
并不相同（`config.save_config` 写的是显式白名单 dict），
后写的那一方会把对方独有的键**静默删掉**。
"""
from __future__ import annotations

import re
import subprocess
from pathlib import Path

import pytest

ROOT = Path(__file__).resolve().parent.parent

#: 旧品牌的各种写法。大小写不敏感匹配。
LEGACY_TOKENS = ("帆派", "FanTool", "FanPai")

#: 允许出现旧名的文件，及其**理由**。理由必须是"这里非有它不可"，
#: 而不是"这里改起来麻烦"——后者应该去改，不是加进这个表。
ALLOWLIST = {
    "NOTICE": "商标声明必须逐字点名它保留的是哪些标识，否则那段声明没有对象",
    "README.md": "出处声明（本项目由哪个闭源产品裁出）与商标保留段落",
    "README.en.md": "同上，英文版",
    "CHANGELOG.md": "开源之前的版本历史，说明这份代码的来历",
    "tests/test_no_legacy_brand.py": "判据自身要写出它在找什么",
    "scripts/revert_verify.py": (
        "BRAND 组的回退断点必须逐字写出要模拟的旧名，否则没法验证"
        "「旧名回流时判据会不会变红」"
    ),
    "core/presets/share_file.py": (
        "导入对话框要认前身导出的 .fanpai 分享文件——容器格式和安检逻辑完全一致，"
        "没有理由逼用户改扩展名才能导入。**只读不写**：导出一律用新扩展名。"
    ),
}

BINARY_EXT = {".png", ".ico", ".bmp", ".jpg", ".jpeg", ".gif", ".zip",
              ".exe", ".dll", ".ttf", ".otf", ".mp3", ".wav", ".ogg"}


def _tracked_files() -> list[str]:
    out = subprocess.run(
        ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
    ).stdout
    return [p for p in out.decode("utf-8").split("\0") if p]


def test_no_legacy_brand_outside_allowlist():
    """白名单之外的任何文件都不得出现旧品牌名。"""
    pattern = re.compile("|".join(re.escape(t) for t in LEGACY_TOKENS), re.IGNORECASE)
    offenders: dict[str, list[str]] = {}
    for rel in _tracked_files():
        if rel in ALLOWLIST or Path(rel).suffix.lower() in BINARY_EXT:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        hits = [
            f"L{i}: {line.strip()[:100]}"
            for i, line in enumerate(text.splitlines(), 1)
            if pattern.search(line)
        ]
        if hits:
            offenders[rel] = hits[:3]
    assert not offenders, (
        "这些文件里还有旧品牌名，改名那一轮漏了：\n"
        + "\n".join(f"  {f}\n    " + "\n    ".join(h) for f, h in offenders.items())
        + "\n（确实需要保留的，连同理由一起加进本文件的 ALLOWLIST）"
    )


def test_allowlist_entries_still_exist():
    """白名单不许腐烂：里面的文件必须还在，且**确实**还含旧名。

    没有这条，白名单会随着时间变成一张只增不减的免检清单——
    文件早就不含旧名了，条目还挂着，下次有人往里加东西就免检了。
    """
    tracked = set(_tracked_files())
    pattern = re.compile("|".join(re.escape(t) for t in LEGACY_TOKENS), re.IGNORECASE)
    for rel, reason in ALLOWLIST.items():
        assert rel in tracked, f"白名单条目 {rel} 已不在仓库里，请删掉该条目（理由：{reason}）"
        text = (ROOT / rel).read_text(encoding="utf-8")
        assert pattern.search(text), (
            f"白名单条目 {rel} 里已经没有旧名了，说明这条豁免过期了，请删掉"
        )


# ------------------------------------------------------------------ 行为判据

def test_runtime_app_name_is_not_legacy():
    """数据目录名 / 日志目录名的真源，不得是旧名。

    漏改这里 = 开源版与闭源版共用 `%LOCALAPPDATA%` 下同一个目录。
    """
    import config
    from core.utils import logger as logger_mod

    for mod, label in ((config, "config.APP_NAME"), (logger_mod, "logger.APP_NAME")):
        name = mod.APP_NAME
        assert not any(t.lower() in name.lower() for t in LEGACY_TOKENS), (
            f"{label} = {name!r}，仍是旧品牌名"
        )

    assert config.APP_NAME == logger_mod.APP_NAME, (
        f"两处 APP_NAME 不一致：config={config.APP_NAME!r} logger={logger_mod.APP_NAME!r}。"
        "它们各自决定配置目录和日志目录，不一致会把两者散到两个文件夹里。"
    )


def test_single_instance_and_autostart_keys_are_not_legacy():
    """单实例锁文件名与开机自启注册表值名，不得是旧名。

    锁文件同名 → 闭源版在跑时开源版会以为"自己已经在运行"而直接退出。
    注册表值名同名 → 两者的开机自启项互相覆盖，用户只能自启其中一个。
    """
    from core.single_instance import LOCK_FILENAME
    from core.utils import autostart

    for value, label in (
        (LOCK_FILENAME, "single_instance.LOCK_FILENAME"),
        (autostart._VALUE_NAME, "autostart._VALUE_NAME"),
    ):
        assert not any(t.lower() in value.lower() for t in LEGACY_TOKENS), (
            f"{label} = {value!r}，仍是旧品牌名"
        )


#: 官网地址。2026-08-12 起允许写进 README（运营决定：开源代码给开发者，
#: 终端用户去官网注册下载闭源版），但**只允许出现在这两份 README 里**。
OFFICIAL_SITE = "fantool.online"
OFFICIAL_SITE_ALLOWED = {
    "README.md",
    "README.en.md",
    # 判据自身与它的回退断点必须逐字写出要找的东西，否则没法验证
    # 「漏进代码时会不会变红」。与 ALLOWLIST 里同两条豁免同一个理由。
    "tests/test_no_legacy_brand.py",
    "scripts/revert_verify.py",
}


def test_official_site_url_only_in_readme():
    """官网地址只允许出现在两份 README 里。

    **它防的是"默认不连任何服务器"那条硬前提被悄悄破坏。**
    一旦这个域名出现在 `service_urls.py`、上报器、更新检查这类会发请求的地方，
    每个 fork 出去的客户端都会开始打原作者的服务器——带宽是他的，
    崩溃堆栈里的用户数据责任也是他的，而那些用户已经不是他的用户了。

    README 里写它是**展示**，代码里写它是**连接**。这条判据分的就是这两件事。
    （出现在文档/注释里也一律拦下：想在别处提官网，先在这里放行，
    顺手就会被迫想一遍"我到底是要展示还是要连接"。）
    """
    offenders = []
    for rel in _tracked_files():
        if rel in OFFICIAL_SITE_ALLOWED or Path(rel).suffix.lower() in BINARY_EXT:
            continue
        try:
            text = (ROOT / rel).read_text(encoding="utf-8")
        except (UnicodeDecodeError, OSError):
            continue
        if OFFICIAL_SITE in text.lower():
            offenders.append(rel)
    assert not offenders, (
        f"官网地址 {OFFICIAL_SITE!r} 只允许出现在 {sorted(OFFICIAL_SITE_ALLOWED)}，"
        f"但这些文件里也有: {offenders}\n"
        "如果是要发网络请求——别这么做，见 service_urls.py 里 TELEMETRY_BASE_URL 的说明。"
    )


@pytest.mark.parametrize("func_name", ["get_cs2customizer_cfg_path"])
def test_generated_game_cfg_names_are_not_legacy(func_name, tmp_path):
    """写进用户 CS2 目录的 cfg 文件名不得是旧名。

    这几个文件会长期躺在用户的游戏目录里，是旧品牌最显眼的残留位置。
    """
    from core import cfg_compiler

    func = getattr(cfg_compiler, func_name, None)
    if func is None:  # pragma: no cover - 函数改名时由下面的断言给出可读信息
        pytest.fail(f"core.cfg_compiler 里找不到 {func_name}，判据的落点变了，请更新本条")
    path = func(str(tmp_path))
    assert path is not None
    assert not any(t.lower() in Path(path).name.lower() for t in LEGACY_TOKENS), (
        f"生成的 cfg 文件名 {Path(path).name!r} 仍是旧品牌名"
    )

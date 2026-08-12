# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""已入库的品牌图必须与生成器同步（2026-08-12 公开前审计时建立）。

**它补的是 BRAND 判据组的一个结构性盲区。**

`tests/test_no_legacy_brand.py` 扫的是**文本**，而且明确跳过 `BINARY_EXT`——
不跳不行，你没法对一张 PNG 做字符串替换。代价是：**印在图片里的字，
判据一个字也看不见。**

实际发生的事：开源改名那一轮改了 107 个文本文件 507 处，二进制**一处没动**
（实测两个仓库里 `splash.png` / `wizard_large.bmp` 的 md5 完全相同）。于是
公开前的仓库里，代码、文档、注册表键、数据目录名全是新名字，只有
**用户第一眼看到的启动闪屏**和**安装向导左侧那张大图**还印着旧产品名，
其中向导图上连旧官网域名都还在。全部判据、ruff、CI 一路全绿。

这里的两条判据合起来堵住它：

1. **已入库的图 == 现在重跑生成器的产物**（`test_committed_brand_images_are_not_stale`）。
   这是治根的那条：生成物入了库就会和生成器脱钩，而脱钩是静默的。
2. **生成器画的字必须落在安全框内**（`test_wizard_large_text_fits_inside_safe_boxes`）。
   改名顺带改了字宽——4 个汉字换成 14 个拉丁字符，同字号下宽一倍多，
   标题左右两端直接被裁掉，脚本照样退出码 0。

配合原有的文本判据，链条是闭合的：文本判据保证生成器里的**文案常量**
不含旧名 → 判据 1 保证入库的图**就是**该生成器的产物 → 因此入库的图
不可能印着旧名。任何一条断了，这个推理就不成立。
"""
from __future__ import annotations

import filecmp
import subprocess
import sys
from pathlib import Path

import pytest
from PIL import Image, ImageDraw

from build_tools import make_installer_assets as mia

sys.path.insert(0, str(Path(__file__).resolve().parent.parent / "scripts"))
import make_social_preview  # noqa: E402  (scripts/ 不是包，只能这样进来)

ROOT = Path(__file__).resolve().parent.parent

#: 由 `python build_tools/make_installer_assets.py` 生成、且**已入库**的品牌图。
#: 相对仓库根。
GENERATED_BRAND_IMAGES = (
    "splash.png",
    "build_tools/installer_assets/wizard_large.bmp",
    "build_tools/installer_assets/wizard_small.bmp",
    "docs/images/social-preview.png",
)


def _has_cjk_font() -> bool:
    """生成器缺中文字体时是**故意抛错**的（见 make_installer_assets._font）。
    在那种环境下本文件的判据没有意义，跳过而不是报红。
    """
    return any(p.is_file() for p in mia.CJK_REGULAR_FONT_CANDIDATES) and any(
        p.is_file() for p in mia.CJK_BOLD_FONT_CANDIDATES
    )


requires_cjk_font = pytest.mark.skipif(
    not _has_cjk_font(), reason="本机没有 CJK 字体，生成器按约定会直接失败，判据无从比对"
)


def _box_contains(outer, inner) -> bool:
    return (
        inner[0] >= outer[0]
        and inner[1] >= outer[1]
        and inner[2] <= outer[2]
        and inner[3] <= outer[3]
    )


# ------------------------------------------------------------------ 治根：不许脱钩

@requires_cjk_font
def test_committed_brand_images_are_not_stale(tmp_path, monkeypatch):
    """已入库的品牌图必须与当前生成器的产物逐字节一致。

    生成到临时目录再比对——**不能**直接跑生成器再看 git 有没有变，
    那样判据自己就把仓库改了，"红"和"已经被修好"分不出来。
    """
    if mia.SPLASH_ART_SOURCE.is_file():
        pytest.skip(
            f"本机存在美术源图 {mia.SPLASH_ART_SOURCE.name}（未入库），"
            "闪屏走的是合成分支而非占位分支，与入库那份不可比"
        )

    staged = tmp_path / "installer_assets"
    staged.mkdir()
    monkeypatch.setattr(mia, "OUT", staged)
    mia.make_large()
    mia.make_small()
    mia.make_splash(tmp_path / "splash.png")

    fresh = {
        "splash.png": tmp_path / "splash.png",
        "build_tools/installer_assets/wizard_large.bmp": staged / "wizard_large.bmp",
        "build_tools/installer_assets/wizard_small.bmp": staged / "wizard_small.bmp",
    }
    # 社交预览图归另一个脚本，但属于同一类东西：印着字的、已入库的品牌图。
    preview_out = tmp_path / "social-preview.png"
    monkeypatch.setattr(make_social_preview, "OUT", preview_out)
    assert make_social_preview.main() == 0
    fresh["docs/images/social-preview.png"] = preview_out

    # 清单与实际重跑出来的产物必须一一对应。少了就是漏防，多了就是清单过期——
    # 两种都会让下面那句比对**在不知不觉中少比一张图**。
    assert set(fresh) == set(GENERATED_BRAND_IMAGES), "清单和实际生成的产物对不上了"

    stale = [
        rel
        for rel, new in fresh.items()
        if not filecmp.cmp(new, ROOT / rel, shallow=False)
    ]
    assert not stale, (
        "这些已入库的品牌图和生成器脱钩了：" + ", ".join(stale) + "\n"
        "重跑 `python build_tools/make_installer_assets.py` 并提交产物。\n"
        "（如果只是 Pillow 版本变化带来的像素微差，处理方式相同：重跑并提交。）"
    )


def test_legacy_splash_art_is_not_tracked():
    """旧品牌的 AI 美术底图不许入库。

    它是**旧产品名的美术**，且来源是 AI 生成——公开仓库里既是品牌残留
    也是来源不清的素材。生成器对它的缺失是有预案的（退回占位图）。
    """
    tracked = {
        p
        for p in subprocess.run(
            ["git", "ls-files", "-z"], cwd=ROOT, capture_output=True, check=True
        ).stdout.decode("utf-8").split("\0")
        if p
    }
    # ⚠ 必须拿**仓库相对路径**去比，不能拿 `.name`。`git ls-files` 吐的是
    # `build_tools/installer_assets/xxx.png` 这种带目录的路径，用裸文件名去
    # `in` 一个路径集合永远为假——这条判据第一版就是这么写的，回退验证当场
    # 判它假绿（第五种「判据错法」：量错了通道）。
    rel = mia.SPLASH_ART_SOURCE.resolve().relative_to(ROOT).as_posix()
    assert rel not in tracked, f"{rel} 被加进了版本库"


# ------------------------------------------------------------------ 程序图标

#: 三个路径内容必须完全相同，见 make_app_icon.OUTPUTS 的说明。
ICON_PATHS = (
    "icon.ico",
    "myicon.ico",
    "build_tools/installer_assets/setup_icon.ico",
)


@pytest.fixture(scope="module")
def fresh_icon(tmp_path_factory) -> Path:
    """现跑一遍生成器产出的图标。

    下面几条"图标该长什么样"的判据**必须看这一份，不能看已入库的那份**。
    第一版看的是入库的文件，结果回退验证当场判它们假绿：断点改的是生成器，
    而入库的文件一个字节都没动，判据自然还是绿的。

    入库的那份由 `test_committed_icons_are_not_stale` 单独钉在这一份上——
    链条就闭合了：生成器的产物满足这些性质 + 入库的就是生成器的产物。
    """
    from build_tools import make_app_icon

    path = tmp_path_factory.mktemp("icon") / "icon.ico"
    make_app_icon.build_ico(path)
    return path


def test_committed_icons_are_not_stale(fresh_icon):
    """三个已入库的图标必须与生成器的产物逐字节一致，且三份彼此相同。

    图标不含文字，所以这条**不受 CJK 字体门限制**——它在任何环境都该跑。
    """
    expected = fresh_icon.read_bytes()
    stale = [rel for rel in ICON_PATHS if (ROOT / rel).read_bytes() != expected]
    assert not stale, (
        "这些图标和生成器脱钩了：" + ", ".join(stale) + "\n"
        "重跑 `python build_tools/make_app_icon.py` 并提交产物。"
    )


def test_icon_has_every_size_windows_asks_for(fresh_icon):
    """图标必须自带全部尺寸帧。

    原来那张是**单帧 64×64**：16px 的资源管理器列表和任务栏全靠系统缩放，发虚。
    少一档不会报错，只会在那个场景里难看。
    """
    with Image.open(fresh_icon) as img:
        have = {s[0] for s in img.ico.sizes()}
    # 16 是最吃紧的一档（资源管理器列表 / 任务栏），单独点名，
    # 免得有人把 SIZES 缩到只剩大尺寸还能过。
    assert 16 in have, f"没有 16×16 帧，小图标场景只能靠系统缩放（现有 {sorted(have)}）"
    assert len(have) >= 5, f"尺寸档位只有 {len(have)} 档，太少：{sorted(have)}"


def test_icon_frames_are_bmp_not_png(fresh_icon):
    """所有帧必须是 BMP/DIB 编码，不能是 PNG。

    **Inno Setup 不接受 PNG 帧的 ICO。** 历史上正因为项目根的 icon.ico 是 PNG 帧，
    才有人手工重铸了一份 setup_icon.ico 给安装器；那种手工步骤没人记得，
    下一个改图标的人会原地踩回去。这条判据把"能不能被安装器吃下"变成可验证的。
    """
    import struct

    raw = fresh_icon.read_bytes()
    count = struct.unpack_from("<H", raw, 4)[0]
    png_frames = []
    for i in range(count):
        offset = struct.unpack_from("<I", raw, 6 + i * 16 + 12)[0]
        if raw[offset:offset + 8] == b"\x89PNG\r\n\x1a\n":
            size = struct.unpack_from("<BB", raw, 6 + i * 16)
            png_frames.append(size[0] or 256)
    assert not png_frames, (
        f"这些尺寸的帧是 PNG 编码：{png_frames}。Inno Setup 不接受，"
        "生成器要带 bitmap_format=\"bmp\"。"
    )


def test_smallest_icon_frame_is_actually_legible(fresh_icon):
    """16×16 那一帧的**中心点必须还在**。

    这条防的是"小尺寸没单独画"。判据落在中心点上，是**量出来的**，不是猜的：

        单独画（SIMPLIFY_BELOW=40）  accent 36/256   中心 4×4 的 accent = 4/16
        原样缩小（=0）              accent 30/256   中心 4×4 的 accent = 0/16

    第一版判据写的是"accent 像素总数 >= 24"——两种情况都过，假绿，
    回退验证当场逮住。**总墨量根本不是会坏的那个量**：原样缩小时中心点半径
    只有 0.045×16 ≈ 0.7px，直接消失，而细线糊成中间调后也不再是纯 accent，
    所以坏的那版墨量反而更少。会坏的量是"中心还有没有东西"。
    （又一次量错通道，这已经是这轮的第三次。）
    """
    from build_tools.make_installer_assets import ACCENT

    def is_accent(pixel) -> bool:
        return all(abs(c - e) <= 60 for c, e in zip(pixel, ACCENT))

    with Image.open(fresh_icon) as img:
        frame = img.ico.getimage((16, 16)).convert("RGB")

    core = sum(
        1
        for y in range(6, 10)
        for x in range(6, 10)
        if is_accent(frame.getpixel((x, y)))
    )
    total = sum(
        1
        for y in range(frame.height)
        for x in range(frame.width)
        if is_accent(frame.getpixel((x, y)))
    )
    assert core >= 2, (
        f"16×16 帧中心 4×4 只有 {core} 个 accent 像素，中心点没画出来——"
        "小尺寸没有单独简化几何（见 make_app_icon.SIMPLIFY_BELOW）"
    )
    assert total >= 20, f"16×16 帧总共只有 {total} 个 accent 像素，图基本是空的"


def test_qt_can_actually_load_the_committed_icon(qapp):
    """Qt 必须能从入库的 icon.ico 取出非空图像。

    上面几条判据都在验"文件长得对不对"，这条验的是**产品真的用得上**：
    任务栏/窗口图标走的是 `QIcon`，而这次换了帧编码（PNG → 32bpp BMP）。
    格式判据全绿但 Qt 读不出来，是完全可能的一种失败——那时用户看到的是
    一个空白图标，而所有测试还是绿的。
    """
    from PySide6.QtGui import QIcon

    icon = QIcon(str(ROOT / "icon.ico"))
    assert not icon.isNull(), "QIcon 读不出 icon.ico"
    for edge in (16, 32, 256):
        pixmap = icon.pixmap(edge, edge)
        assert not pixmap.isNull(), f"{edge}px 取不到图像"
        assert pixmap.width() == edge, f"{edge}px 请求拿到的是 {pixmap.width()}px"


# ------------------------------------------------------------------ 截图不许带个人信息

def test_screenshot_guard_rejects_username_in_sandbox_path(monkeypatch):
    """截图脚本必须在按快门之前拦下含用户名的沙箱路径。

    **真实发生过**：沙箱默认落在 `%TEMP%`，而 Windows 的 `%TEMP%` 是
    `C:\\Users\\<用户名>\\AppData\\Local\\Temp`；高级设置页把 CS2 目录原样显示出来，
    于是 `docs/images/advanced.png` 里印着真实用户名，并随 README 推到了公开仓库。
    讽刺的是这个项目自己的日志脱敏器专门干的就是这个串（PRIVACY.md 也承诺了脱敏）。

    只能拦在快门之前：图片里的字没有任何判据读得到。
    """
    import capture_readme_shots as shots

    monkeypatch.setenv("USERNAME", "someuser")
    monkeypatch.delenv("USER", raising=False)
    with pytest.raises(SystemExit) as excinfo:
        shots.assert_sandbox_is_publishable(
            r"C:\Users\someuser\AppData\Local\Temp\cs2customizer_audit_game_sandbox"
        )
    assert "someuser" in str(excinfo.value)


def test_screenshot_guard_accepts_path_without_personal_info(monkeypatch):
    """反面：不含用户名的路径必须放行，否则这条门就没人能过去了。"""
    import capture_readme_shots as shots

    monkeypatch.setenv("USERNAME", "someuser")
    monkeypatch.delenv("USER", raising=False)
    shots.assert_sandbox_is_publishable(
        r"D:\shots\SteamLibrary\steamapps\common\Counter-Strike Global Offensive"
    )


# ------------------------------------------------------------------ 排版：不许溢出

@requires_cjk_font
def test_wizard_large_text_fits_inside_safe_boxes():
    """向导大图三条文案的实际包围盒必须落在各自安全框内。

    没有这条时的失败样子：标题 `CS2 Customizer` 在 328px 宽的图上按字号 44
    渲染，左右各被裁掉一个字母，而底部的仓库地址顶到图片边缘。
    """
    fonts = mia.wizard_fonts()
    cases = (
        ("标题", mia.WIZARD_TITLE, mia.WIZARD_TITLE_POSITION, mia.WIZARD_TITLE_BOX, fonts[0]),
        ("副标", mia.WIZARD_TAGLINE, mia.WIZARD_TAGLINE_POSITION, mia.WIZARD_TAGLINE_BOX, fonts[1]),
        ("地址", mia.WIZARD_URL, mia.WIZARD_URL_POSITION, mia.WIZARD_URL_BOX, fonts[2]),
    )
    draw = ImageDraw.Draw(Image.new("RGB", mia.WIZARD_SIZE))
    bad = []
    for label, text, position, box, font in cases:
        bbox = draw.textbbox(position, text, font=font, anchor="mm")
        if not _box_contains(box, bbox):
            bad.append(f"{label} {text!r}: 包围盒 {bbox} 越出安全框 {box}")
    assert not bad, "向导大图排版越界：\n  " + "\n  ".join(bad)


@requires_cjk_font
def test_wizard_large_safe_boxes_are_inside_the_canvas():
    """安全框本身必须落在画布内。

    上一条判据比的是"文字在框内"。如果框自己越出画布，那条判据会在
    文字明明被裁掉的情况下照样通过——**框是判据的量具，量具得先校准。**
    """
    w, h = mia.WIZARD_SIZE
    for name, box in (
        ("WIZARD_TITLE_BOX", mia.WIZARD_TITLE_BOX),
        ("WIZARD_TAGLINE_BOX", mia.WIZARD_TAGLINE_BOX),
        ("WIZARD_URL_BOX", mia.WIZARD_URL_BOX),
    ):
        assert _box_contains((0, 0, w, h), box), f"{name}={box} 越出画布 {w}x{h}"


@requires_cjk_font
def test_wizard_large_actually_has_ink_where_the_text_should_be():
    """已入库的向导大图在标题框里确实有亮色像素。

    只验"包围盒在框内"是可以被空文案骗过去的（空串的包围盒必然在框内）。
    这条直接看图上有没有字。
    """
    with Image.open(ROOT / "build_tools/installer_assets/wizard_large.bmp") as img:
        crop = img.convert("RGB").crop(mia.WIZARD_TITLE_BOX)
        lit = sum(
            1
            for y in range(crop.height)
            for x in range(crop.width)
            if all(abs(c - e) <= 24 for c, e in zip(crop.getpixel((x, y)), mia.TEXT))
        )
    assert lit >= 300, f"标题安全框内只有 {lit} 个接近正文色的像素，图上大概没字"

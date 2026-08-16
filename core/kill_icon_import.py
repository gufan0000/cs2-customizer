# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""击杀图标素材导入（KI-2 建立 / KI-4 扩容 / KI-5 自动修正）。

**这个模块存在的理由是"入口断了"**，不是格式不够多。KI-2 之前，用户手里
有一张动图想当击杀图标用，唯一的路径是：自己找到 %LOCALAPPDATA% 下的资源
目录、自己建风格文件夹、自己把文件改名成 `1.png`…`5.png`、自己手搓一份
JSON 写对 frame_width/frames/cols。

所以这里做的是一件事：**把任何常见素材形态收敛成风格库里的标准条目**。

    GIF / 动图 WebP / APNG / AVIF     ┐
    单张 PNG / JPG / BMP              │
    PNG 帧序列目录                     ├─→  <风格>/<等级>.png + <等级>.json
    现成的图集 + 我们的 JSON            │
    Aseprite / 网格图集                ┘

运行时格式一个字节没改，仍是图集 —— 这不是偷懒，是调研的结论：图集是
**一次解码、播放期零解码**，逐帧裁切绘制，CPU 最省、帧控最准。同类工具
（KillConfirmGameBar）用的 PNG 帧序列本质就是"没打包的图集"。动图格式
只适合当**入口**，不适合当运行时格式。

KI-4 补的是四条**静默失败**——它们的共同点是全程零报错：

1. 拖一张静态 PNG 进来 → 图标只显示 33 毫秒（1 帧 @30fps），等于看不见。
   现在单帧素材自动带 `hold_seconds` 定格时长。
2. 图集旁边躺着 `x.png` 和 `x.json`，用户选中 `x.png` → 整张图集被当成
   "一张静态图"，屏幕上是一条巨大的马赛克。现在选 png 会自动去找同名 json。
3. `.jpg` 单文件被拒，同一个 `.jpg` 放进文件夹里却能进——两条路的格式表
   各写各的。现在合成一张表。
4. 不认识的格式只回一句"不认识这个格式"。现在按类别给出路（视频→先转动图）。

⚠ GIF 的透明度是 1-bit 的（一个像素要么全透明要么全不透明），边缘会有
硬白边。这不是我们能修的，只能在导入时明确告诉用户——所以 `probe_source`
会带回一条 warning，UI 必须把它显示出来。
"""
from __future__ import annotations

import json
import os
import shutil
import tempfile
from dataclasses import dataclass, field

from core.utils.logger import get_logger

logger = get_logger("KillIconImport")

#: 能当"一整段动画"读进来的单文件格式。
#: `.png` 在列表里是因为 APNG 用的就是 .png 扩展名。
ANIMATED_EXTENSIONS = (".gif", ".webp", ".apng", ".png", ".avif")

#: 只有一帧的静态图片格式。
#:
#: 这张表与 `SEQUENCE_EXTENSIONS` 曾经**各写各的**：`.jpg` 放进文件夹能进、
#: 单独拖进来却报"不认识这个格式"。用户感受是"这软件挑食挑得莫名其妙"。
STATIC_EXTENSIONS = (".jpg", ".jpeg", ".bmp", ".tga", ".tif", ".tiff")

#: 帧序列目录里认的图片格式 —— 就是上面两张表的并集，不再单独维护。
SEQUENCE_EXTENSIONS = tuple(sorted(set(ANIMATED_EXTENSIONS + STATIC_EXTENSIONS)))

#: 单文件入口认的全部后缀。
SINGLE_FILE_EXTENSIONS = tuple(sorted(set(ANIMATED_EXTENSIONS + STATIC_EXTENSIONS)))

#: 明确"认得出来但不支持"的格式。报错要给出路，不是甩一句不认识。
UNSUPPORTED_HINTS = {
    (".mp4", ".webm", ".mkv", ".avi", ".mov", ".flv", ".m4v", ".wmv"):
        "是视频文件，击杀图标不支持直接导入视频。"
        "先用在线工具或 ffmpeg 转成 WebP 动图（边缘最干净）或 GIF 再拖进来。",
    (".psd", ".ai", ".xcf", ".clip"):
        "是分层工程文件。请先在原软件里导出成 PNG 序列、WebP 动图或 APNG。",
    (".svg", ".eps", ".pdf"):
        "是矢量文件。请先导出成 PNG（建议 512px 以内）或 PNG 序列。",
    (".zip", ".rar", ".7z"):
        "是压缩包。zip 图标包可以直接拖到设置页上；rar/7z 请先解压。",
    (".mp3", ".wav", ".ogg", ".flac"):
        "是音频文件，不是图片。",
}

#: 帧数上限。素材是用户自己给的，这里只做"别把内存吃干"的兜底。
#: 与 `kill_icon_overlay.MAX_FRAMES` 对齐——那边装载时也会截断，
#: 两边不一致的话表现是"导入说 800 帧、播放只播 600 帧"。
MAX_FRAMES = 600

#: 单帧最长边。超过就等比缩小——不是报错。
#: 用户从网上拿的动图动辄 1000+ 像素，而图标在屏幕上就 350 宽，
#: 原样存下来只是白占磁盘和内存。
MAX_FRAME_EDGE = 1024

#: 图集单行最大宽度（与老的制作工具一致，也是常见 GPU 纹理边长）。
MAX_SHEET_WIDTH = 4096

#: 探测节奏时最多回看多少帧。
#:
#: 每帧时长要 `seek` 才拿得到，而 GIF 的 seek 是要解码的。我们本来就把
#: 逐帧变速抹平成一个平均帧率（运行时格式是定帧率的），所以采样前 N 帧
#: estimate 与全量平均是同一个量级的近似，没必要为它把 600 帧解一遍。
RATE_SAMPLE_FRAMES = 30

#: 抠背景色的默认容差（每通道，0~255）。
DEFAULT_CHROMA_TOLERANCE = 24

DEFAULT_FPS = 30


class KillIconImportError(Exception):
    """导入失败。消息是直接给用户看的中文，不要往里塞堆栈。"""


class KillIconImportCancelled(Exception):
    """用户中途取消。**不是错误**，UI 不该把它当失败报出来。"""


@dataclass
class SourceProbe:
    """探测结果。UI 拿它做导入前的预览与确认。"""

    kind: str                 # "animation" | "sequence" | "spritesheet"
    path: str
    frame_count: int
    frame_width: int
    frame_height: int
    fps: int
    warnings: list = field(default_factory=list)
    #: 单帧素材的建议定格时长；多帧素材是 0。
    hold_seconds: float = 0.0
    #: 只有 `analyze=True` 时才有值——这几项要读像素，探测默认不做。
    opaque_background: bool = False
    suggested_key_color: tuple = ()
    trim_box: tuple = ()
    #: 图集类专用：`(cols, rows)`；靠猜出来的会同时带一条 warning。
    grid: tuple = ()

    @property
    def duration(self) -> float:
        return self.frame_count / float(max(1, self.fps)) + float(self.hold_seconds or 0.0)


def _pil():
    """PIL 是既有依赖（制作工具一直在用），这里只是集中做一次导入错误的翻译。"""
    try:
        from PIL import Image, ImageSequence

        return Image, ImageSequence
    except ImportError as exc:  # pragma: no cover - 环境缺依赖才会走到
        raise KillIconImportError(f"缺少图像处理库 Pillow：{exc}") from exc


def _check_cancelled(cancel):
    if cancel is not None and cancel():
        raise KillIconImportCancelled()


def _report(progress, done, total, stage):
    if progress is not None:
        try:
            progress(int(done), int(total), str(stage))
        except Exception:  # 进度回调不该把导入带崩
            pass


def _unsupported_message(path):
    """给不支持的格式一条**带出路**的报错。

    KI-4 之前这里统一回"不认识这个格式"。用户拿着一个 mp4 站在原地，
    既不知道为什么不行、也不知道下一步该干嘛。
    """
    name = os.path.basename(str(path))
    lower = str(path).lower()
    for extensions, hint in UNSUPPORTED_HINTS.items():
        if lower.endswith(extensions):
            return f"{name} {hint}"
    return (
        f"不认识这个格式：{name}。\n"
        f"支持 GIF / WebP 动图 / APNG / AVIF / PNG / JPG / BMP，"
        f"或者一个装着帧序列的文件夹、一个 zip 图标包。"
    )


#: 批量导入时"这个文件/文件夹是几杀"的别名表。
#:
#: KI-4 之前只认严格的 `1`~`5`。社区素材包里叫 `kill1` / `ace` / `三杀` 的
#: 比比皆是，一律被静默跳过（提示里只有一句"名字不是 1~5"）。
LEVEL_ALIASES = {
    "1": 1, "kill1": 1, "1kill": 1, "single": 1, "一杀": 1, "单杀": 1,
    "2": 2, "kill2": 2, "2kill": 2, "double": 2, "二杀": 2, "双杀": 2,
    "3": 3, "kill3": 3, "3kill": 3, "triple": 3, "三杀": 3,
    "4": 4, "kill4": 4, "4kill": 4, "quad": 4, "四杀": 4,
    "5": 5, "kill5": 5, "5kill": 5, "ace": 5, "penta": 5, "五杀": 5, "团灭": 5,
}

#: 爆头变体的后缀别名。
HEADSHOT_ALIASES = ("hs", "headshot", "head", "爆头")


def parse_level_name(name):
    """`("3hs.gif") → (3, "hs")`；认不出来返回 None。

    批量导入与 zip 包都靠它把"文件名"翻译成"哪一个击杀等级"。
    """
    stem = os.path.splitext(os.path.basename(str(name or "")))[0].strip().lower()
    if not stem:
        return None

    variant = ""
    for alias in HEADSHOT_ALIASES:
        if stem.endswith(alias) and len(stem) > len(alias):
            stem = stem[: -len(alias)].strip(" -_")
            variant = "hs"
            break

    level = LEVEL_ALIASES.get(stem)
    if level is None:
        return None
    return (level, variant)


def _sorted_sequence_files(directory):
    """帧序列按文件名里的**数字**排序，不是按字典序。

    字典序会把 `frame-10.png` 排在 `frame-2.png` 前面——动画会倒着抽风。
    这套排序规则照搬老的制作工具（`dialogs/sprite_sheet_maker._smart_sort_files`），
    存量用户的素材目录就是按那套命名的。
    """
    import re

    def _key(name):
        numbers = re.findall(r"\d+", name)
        return (int(numbers[-1]) if numbers else 0, name)

    names = [
        name
        for name in os.listdir(directory)
        if name.lower().endswith(SEQUENCE_EXTENSIONS)
        and os.path.isfile(os.path.join(directory, name))
    ]
    return [os.path.join(directory, name) for name in sorted(names, key=_key)]


def _fps_from_durations(durations):
    """从动图的每帧毫秒数推回帧率。

    动图的每帧时长可以各不相同，而我们的运行时格式是**定帧率**的，
    所以只能取平均。这是有损的（逐帧变速的素材会被抹平），
    但换来的是播放期零解码——这个取舍在模块头部说明过。
    """
    valid = [d for d in durations if d and d > 0]
    if not valid:
        return DEFAULT_FPS
    average_ms = sum(valid) / len(valid)
    if average_ms <= 0:
        return DEFAULT_FPS
    return max(1, min(60, int(round(1000.0 / average_ms))))


def _fit(width, height, max_edge=MAX_FRAME_EDGE):
    longest = max(width, height)
    if longest <= max_edge:
        return width, height
    ratio = max_edge / float(longest)
    return max(1, int(round(width * ratio))), max(1, int(round(height * ratio)))


# ==================================================== 读入：动图 / 序列 / 图集


def _read_animation_frames(path, progress=None, cancel=None):
    """读单文件动图 → (帧列表 RGBA, fps, 警告)。"""
    Image, ImageSequence = _pil()
    warnings = []
    try:
        source = Image.open(path)
    except (OSError, ValueError) as exc:
        raise KillIconImportError(f"这个文件读不出来：{os.path.basename(path)}（{exc}）") from exc

    frames = []
    durations = []
    with source:
        image_format = (source.format or "").upper()
        total = getattr(source, "n_frames", 1) or 1
        for frame in ImageSequence.Iterator(source):
            _check_cancelled(cancel)
            durations.append(frame.info.get("duration", 0))
            frames.append(frame.convert("RGBA"))
            _report(progress, len(frames), min(total, MAX_FRAMES), "读取帧")
            if len(frames) >= MAX_FRAMES:
                warnings.append(f"帧数超过 {MAX_FRAMES}，只取前 {MAX_FRAMES} 帧。")
                break

    if not frames:
        raise KillIconImportError(f"没能从 {os.path.basename(path)} 里读出任何一帧。")

    if image_format == "GIF":
        warnings.append(
            "GIF 的透明度是 1-bit 的（像素只能全透明或全不透明），"
            "叠在游戏画面上时边缘会有硬白边。想要干净的半透明边缘，"
            "建议改用 WebP 动图、APNG 或 PNG 帧序列。"
        )
    return frames, _fps_from_durations(durations), warnings


def _read_sequence_frames(directory, progress=None, cancel=None):
    Image, _ImageSequence = _pil()
    paths = _sorted_sequence_files(directory)
    if not paths:
        raise KillIconImportError(f"目录里没有可用的图片：{directory}")

    warnings = []
    if len(paths) > MAX_FRAMES:
        warnings.append(f"帧数超过 {MAX_FRAMES}，只取前 {MAX_FRAMES} 张。")
        paths = paths[:MAX_FRAMES]

    frames = []
    for index, path in enumerate(paths):
        _check_cancelled(cancel)
        try:
            with Image.open(path) as image:
                frames.append(image.convert("RGBA"))
        except (OSError, ValueError) as exc:
            warnings.append(f"跳过读不出来的图片 {os.path.basename(path)}（{exc}）。")
        _report(progress, index + 1, len(paths), "读取帧")
    if not frames:
        raise KillIconImportError(f"目录里的图片一张都读不出来：{directory}")
    return frames, DEFAULT_FPS, warnings


def _aseprite_rects(data):
    """把 Aseprite 导出的 JSON 翻译成 `[(x, y, w, h, duration_ms), ...]`。

    Aseprite 是做像素图标的人真正在用的工具，它的导出 schema 与我们的
    完全不同（`frames` 是一堆带 `frame:{x,y,w,h}` 的条目，而不是
    `frame_width`/`cols`）。KI-4 之前选中它只会得到一句"这份配置缺少
    frame_width"，用户根本猜不到问题出在哪。

    hash 和 array 两种导出都要认——Aseprite 的对话框里那是个下拉框，
    用户不会知道我们只认其中一种。
    """
    raw = data.get("frames")
    entries = []
    if isinstance(raw, dict):
        entries = list(raw.values())
    elif isinstance(raw, list):
        entries = list(raw)
    if not entries:
        return []

    rects = []
    for entry in entries:
        if not isinstance(entry, dict):
            continue
        box = entry.get("frame")
        if not isinstance(box, dict):
            continue
        try:
            rects.append((
                int(box["x"]), int(box["y"]), int(box["w"]), int(box["h"]),
                int(entry.get("duration") or 0),
            ))
        except (KeyError, TypeError, ValueError):
            continue
    return rects


def guess_grid(width, height):
    """只在**毫无歧义**的情况下猜图集的行列，猜不出就返回 None。

    故意不做"试所有除数挑一个最像的"那种猜法：猜错的表现是切出一堆错位的
    半张图，而且照样"导入成功"——比直接问用户要行列数糟得多。
    这里只认两种一眼就是的情况：一整行的正方形帧、一整列的正方形帧。
    """
    width = max(1, int(width))
    height = max(1, int(height))
    if width > height and height > 0 and width % height == 0 and width // height >= 2:
        return (width // height, 1)
    if height > width and width > 0 and height % width == 0 and height // width >= 2:
        return (1, height // width)
    return None


def _read_spritesheet_frames(sprite_path, cols, rows, frame_count, rects=None):
    """从一张图集里切出 PIL 帧。`rects` 优先（Aseprite 那种不规则分帧）。"""
    Image, _ImageSequence = _pil()
    try:
        sheet = Image.open(sprite_path).convert("RGBA")
    except (OSError, ValueError) as exc:
        raise KillIconImportError(
            f"图集读不出来：{os.path.basename(sprite_path)}（{exc}）"
        ) from exc

    frames = []
    if rects:
        for x, y, w, h, _duration in rects[:MAX_FRAMES]:
            if w <= 0 or h <= 0 or x + w > sheet.width or y + h > sheet.height:
                continue
            frames.append(sheet.crop((x, y, x + w, y + h)))
    else:
        cols = max(1, int(cols))
        rows = max(1, int(rows))
        frame_width = sheet.width // cols
        frame_height = sheet.height // rows
        if frame_width <= 0 or frame_height <= 0:
            raise KillIconImportError(
                f"按 {cols} 列 {rows} 行切不出有效画格（图集是 "
                f"{sheet.width}x{sheet.height}）。"
            )
        total = min(int(frame_count or cols * rows), cols * rows, MAX_FRAMES)
        for index in range(total):
            left = (index % cols) * frame_width
            top = (index // cols) * frame_height
            frames.append(sheet.crop((left, top, left + frame_width, top + frame_height)))

    if not frames:
        raise KillIconImportError(f"从 {os.path.basename(sprite_path)} 里一帧都没切出来。")
    return frames


# ==================================================== 归一化 / 自动修正


def _frames_union_bbox(frames):
    """所有帧**并集**的非透明包围盒。

    ⚠ 必须是并集，绝不能逐帧各裁各的：逐帧裁会让每一帧的内容都被推到画格
    正中，播放时整个动画在原地抖动。这个错误做出来非常好看，只有连着看才
    能发现不对。
    """
    left = top = None
    right = bottom = None
    for frame in frames:
        box = frame.getbbox()      # PIL：alpha 全 0 的边被排除
        if box is None:
            continue
        if left is None:
            left, top, right, bottom = box
            continue
        left = min(left, box[0])
        top = min(top, box[1])
        right = max(right, box[2])
        bottom = max(bottom, box[3])
    if left is None:
        return None
    return (left, top, right, bottom)


def _apply_chroma_key(frames, color, tolerance=DEFAULT_CHROMA_TOLERANCE):
    """把接近 `color` 的像素抠成透明。

    为什么需要它：从视频转出来的 GIF/WebP 大多是**不透明**的，叠在游戏画面
    上就是一个方块。更要紧的是 pygame 老版本靠"纯黑当透明"抠图，老用户为
    那一版自制的黑底素材迁到 Qt 版会变成黑框——随包的默认素材是真 alpha，
    不受影响，中招的只会是用户自己做的。
    """
    Image, _ImageSequence = _pil()
    red, green, blue = (int(c) for c in color[:3])
    tolerance = max(0, int(tolerance))
    keyed = []
    for frame in frames:
        rgba = frame.convert("RGBA")
        pixels = rgba.load()
        for y in range(rgba.height):
            for x in range(rgba.width):
                r, g, b, a = pixels[x, y]
                if a and abs(r - red) <= tolerance and abs(g - green) <= tolerance \
                        and abs(b - blue) <= tolerance:
                    pixels[x, y] = (r, g, b, 0)
        keyed.append(rgba)
    return keyed


def analyze_frames(frames):
    """看一眼这套帧需要不需要自动修正。**要读像素，别放在建页路径上。**

    返回 `{opaque_background, suggested_key_color, trim_box, transparent_margin}`。
    只报告，不动手——动不动手是用户在导入向导里勾的。
    """
    if not frames:
        return {}
    first = frames[0].convert("RGBA")
    corners = [
        first.getpixel((0, 0)),
        first.getpixel((first.width - 1, 0)),
        first.getpixel((0, first.height - 1)),
        first.getpixel((first.width - 1, first.height - 1)),
    ]
    opaque = all(pixel[3] == 255 for pixel in corners)

    suggested = ()
    if opaque:
        # 四角一致才敢建议抠这个色；四角都不一样多半是有内容顶到边了。
        if all(abs(c[i] - corners[0][i]) <= 8 for c in corners for i in range(3)):
            suggested = tuple(corners[0][:3])

    box = _frames_union_bbox(frames)
    margin = 0
    if box is not None:
        margin = min(box[0], box[1], first.width - box[2], first.height - box[3])
    return {
        "opaque_background": opaque,
        "suggested_key_color": suggested,
        "trim_box": box or (),
        "transparent_margin": max(0, int(margin)),
    }


def _normalize_frames(frames, trim=False, chroma_key=None,
                      chroma_tolerance=DEFAULT_CHROMA_TOLERANCE):
    """把所有帧对齐到同一尺寸，并按需抠背景 / 裁边 / 等比缩小。

    尺寸不一的帧序列在老的制作工具里会**默默画歪**——它拿第一张的尺寸当
    画格尺寸，别的帧直接 paste 到左上角，大的被裁、小的留黑边，而且不报错。
    这里统一居中贴到同一画格里，并把这件事写进 warning 告诉用户。
    """
    Image, _ImageSequence = _pil()
    warnings = []

    if chroma_key:
        frames = _apply_chroma_key(frames, chroma_key, chroma_tolerance)
        warnings.append(
            f"已把接近 RGB{tuple(int(c) for c in chroma_key[:3])} 的背景抠成透明"
            f"（容差 {int(chroma_tolerance)}）。"
        )

    if trim:
        box = _frames_union_bbox(frames)
        if box is not None and box != (0, 0, frames[0].width, frames[0].height):
            frames = [frame.crop(box) for frame in frames]
            warnings.append(
                f"已裁掉四周的全透明边（保留 {box[2] - box[0]}x{box[3] - box[1]}）。"
            )

    widths = {frame.width for frame in frames}
    heights = {frame.height for frame in frames}

    frame_width = max(widths)
    frame_height = max(heights)
    if len(widths) > 1 or len(heights) > 1:
        warnings.append(
            f"各帧尺寸不一致，已统一按最大画格 {frame_width}x{frame_height} 居中对齐。"
        )

    target_w, target_h = _fit(frame_width, frame_height)
    if (target_w, target_h) != (frame_width, frame_height):
        warnings.append(
            f"单帧尺寸 {frame_width}x{frame_height} 超过 {MAX_FRAME_EDGE}px，"
            f"已等比缩小到 {target_w}x{target_h}。"
        )

    normalized = []
    for frame in frames:
        canvas = Image.new("RGBA", (frame_width, frame_height), (0, 0, 0, 0))
        canvas.paste(frame, ((frame_width - frame.width) // 2,
                             (frame_height - frame.height) // 2))
        if (target_w, target_h) != (frame_width, frame_height):
            canvas = canvas.resize((target_w, target_h), Image.LANCZOS)
        normalized.append(canvas)
    return normalized, target_w, target_h, warnings


# ==================================================== 探测


def _sibling_metadata_path(path):
    """`x.png` 旁边的 `x.json`。

    KI-4 之前，用户拿到一份 `sheet.png` + `sheet.json` 却选中了那张 png，
    得到的是"整张图集当成一帧"——屏幕上一条横着的马赛克，全程零警告。
    文件夹里躺着两个同名文件，凭什么用户知道要选 json？
    """
    candidate = os.path.splitext(str(path))[0] + ".json"
    return candidate if os.path.isfile(candidate) else None


def _static_probe_hold(frame_count, hold_seconds=None):
    """单帧素材的定格时长；多帧素材恒为 0。"""
    from kill_icon_overlay import DEFAULT_STATIC_HOLD_SECONDS, clamp_hold

    if int(frame_count) > 1:
        return 0.0
    return clamp_hold(DEFAULT_STATIC_HOLD_SECONDS if hold_seconds is None else hold_seconds)


def probe_source(path, grid=None, analyze=False):
    """看一眼这个素材是什么、有多少帧、多大——导入前给用户过目用。

    不写任何文件。UI 靠它在"选完文件、还没确认导入"那一步就把警告
    （GIF 硬边、尺寸不一、帧数超限、单帧定格）摆出来。

    `analyze=True` 才会去读像素做"要不要抠背景/裁边"的判断——那要整套解码，
    **不该跑在 UI 线程上**，调用方自己安排到后台去。
    """
    path = str(path)
    if os.path.isdir(path):
        return _probe_sequence(path, analyze=analyze)

    if not os.path.isfile(path):
        raise KillIconImportError(f"找不到这个素材：{path}")

    lower = path.lower()
    if lower.endswith(".json"):
        return _probe_spritesheet(path, analyze=analyze)

    sibling = _sibling_metadata_path(path) if lower.endswith(".png") else None
    if sibling:
        return _probe_spritesheet(sibling, analyze=analyze)

    if not lower.endswith(SINGLE_FILE_EXTENSIONS):
        raise KillIconImportError(_unsupported_message(path))

    if grid:
        return _probe_grid_sheet(path, grid, analyze=analyze)

    return _probe_animation(path, analyze=analyze)


def _probe_animation(path, analyze=False):
    """单文件动图/静态图的探测。

    只 seek 前 `RATE_SAMPLE_FRAMES` 帧估节奏，不把整套解出来——探测是
    "选完文件立刻要出信息"的交互，把 600 帧解一遍会当场卡住界面。
    """
    Image, _ImageSequence = _pil()
    try:
        source = Image.open(path)
    except (OSError, ValueError) as exc:
        raise KillIconImportError(f"这个文件读不出来：{os.path.basename(path)}（{exc}）") from exc

    warnings = []
    with source:
        image_format = (source.format or "").upper()
        frame_count = int(getattr(source, "n_frames", 1) or 1)
        width, height = source.size
        durations = []
        for index in range(min(frame_count, RATE_SAMPLE_FRAMES)):
            try:
                source.seek(index)
            except (EOFError, ValueError):
                break
            durations.append(source.info.get("duration", 0))
        fps = _fps_from_durations(durations)

    if frame_count > MAX_FRAMES:
        warnings.append(f"帧数超过 {MAX_FRAMES}，只取前 {MAX_FRAMES} 帧。")
        frame_count = MAX_FRAMES

    target_w, target_h = _fit(width, height)
    if (target_w, target_h) != (width, height):
        warnings.append(
            f"单帧尺寸 {width}x{height} 超过 {MAX_FRAME_EDGE}px，"
            f"已等比缩小到 {target_w}x{target_h}。"
        )

    if image_format == "GIF":
        warnings.append(
            "GIF 的透明度是 1-bit 的（像素只能全透明或全不透明），"
            "叠在游戏画面上时边缘会有硬白边。想要干净的半透明边缘，"
            "建议改用 WebP 动图、APNG 或 PNG 帧序列。"
        )

    hold = _static_probe_hold(frame_count)
    if hold:
        warnings.append(
            f"这是一张静态图片，会作为单帧图标定格显示 {hold:.1f} 秒。"
            f"（不给定格时长的话，1 帧按 {DEFAULT_FPS} FPS 只有 0.03 秒，肉眼看不见。）"
        )

    probe = SourceProbe("animation", path, frame_count, target_w, target_h, fps,
                        warnings, hold_seconds=hold)
    if analyze:
        frames, _fps, _warn = _read_animation_frames(path)
        _apply_analysis(probe, frames)
    return probe


def _probe_sequence(directory, analyze=False):
    """帧序列目录的探测：只读文件头拿尺寸，不解像素。"""
    Image, _ImageSequence = _pil()
    paths = _sorted_sequence_files(directory)
    if not paths:
        raise KillIconImportError(
            f"这个文件夹里没有可用的图片：{directory}\n"
            f"帧序列请放 PNG / WebP / JPG / BMP，文件名里带序号（1.png、2.png…）。"
        )

    warnings = []
    if len(paths) > MAX_FRAMES:
        warnings.append(f"帧数超过 {MAX_FRAMES}，只取前 {MAX_FRAMES} 张。")
        paths = paths[:MAX_FRAMES]

    sizes = []
    for path in paths:
        try:
            with Image.open(path) as image:
                sizes.append(image.size)   # PIL 是懒解码的，.size 只读文件头
        except (OSError, ValueError):
            continue
    if not sizes:
        raise KillIconImportError(f"目录里的图片一张都读不出来：{directory}")

    width = max(size[0] for size in sizes)
    height = max(size[1] for size in sizes)
    if len(set(sizes)) > 1:
        warnings.append(f"各帧尺寸不一致，已统一按最大画格 {width}x{height} 居中对齐。")

    target_w, target_h = _fit(width, height)
    if (target_w, target_h) != (width, height):
        warnings.append(
            f"单帧尺寸 {width}x{height} 超过 {MAX_FRAME_EDGE}px，"
            f"已等比缩小到 {target_w}x{target_h}。"
        )

    hold = _static_probe_hold(len(sizes))
    if hold:
        warnings.append(f"这个文件夹里只有一张图，会作为单帧图标定格显示 {hold:.1f} 秒。")

    probe = SourceProbe("sequence", directory, len(sizes), target_w, target_h,
                        DEFAULT_FPS, warnings, hold_seconds=hold)
    if analyze:
        frames, _fps, _warn = _read_sequence_frames(directory)
        _apply_analysis(probe, frames)
    return probe


def _probe_grid_sheet(sprite_path, grid, analyze=False):
    """没有元数据的网格图集：行列由调用方给（用户填的，或 `guess_grid` 猜的）。"""
    Image, _ImageSequence = _pil()
    cols, rows = (max(1, int(grid[0])), max(1, int(grid[1])))
    with Image.open(sprite_path) as sheet:
        width, height = sheet.size
    frame_width = width // cols
    frame_height = height // rows
    if frame_width <= 0 or frame_height <= 0:
        raise KillIconImportError(
            f"按 {cols} 列 {rows} 行切不出有效画格（图集是 {width}x{height}）。"
        )

    frame_count = min(cols * rows, MAX_FRAMES)
    warnings = []
    if width % cols or height % rows:
        warnings.append(
            f"图集尺寸 {width}x{height} 不能被 {cols}x{rows} 整除，"
            f"边缘会有几像素被切掉。"
        )
    target_w, target_h = _fit(frame_width, frame_height)
    probe = SourceProbe("spritesheet", sprite_path, frame_count, target_w, target_h,
                        DEFAULT_FPS, warnings, grid=(cols, rows))
    if analyze:
        frames = _read_spritesheet_frames(sprite_path, cols, rows, frame_count)
        _apply_analysis(probe, frames)
    return probe


def _probe_spritesheet(json_path, analyze=False):
    """现成的图集 + JSON。认两种 schema：我们自己的，和 Aseprite 导出的。"""
    try:
        with open(json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
    except (OSError, ValueError) as exc:
        raise KillIconImportError(f"配置文件读不出来：{exc}") from exc
    if not isinstance(data, dict):
        raise KillIconImportError(f"这份配置不是一个 JSON 对象：{os.path.basename(json_path)}")

    sprite_path = _resolve_sheet_image(json_path, data)

    # ⚠ 这里必须用 `_as_int`：Aseprite 的 `frames` 是一个**字典/数组**，
    # 直接 `int(...)` 会抛 TypeError，用户看到的是一句 Python 报错。
    frame_width = _as_int(data.get("frame_width"))
    frame_height = _as_int(data.get("frame_height"))
    frames = _as_int(data.get("frames"))
    if frame_width > 0 and frame_height > 0 and frames > 0:
        from kill_icon_overlay import clamp_hold

        cols = _as_int(data.get("cols")) or 1
        rows = _as_int(data.get("rows")) or 1
        probe = SourceProbe("spritesheet", json_path, frames, frame_width, frame_height,
                            _as_int(data.get("fps")) or DEFAULT_FPS, [],
                            hold_seconds=clamp_hold(data.get("hold_seconds", 0.0)),
                            grid=(cols, rows))
        if analyze:
            _apply_analysis(probe, _read_spritesheet_frames(sprite_path, cols, rows, frames))
        return probe

    rects = _aseprite_rects(data)
    if rects:
        widths = {rect[2] for rect in rects}
        heights = {rect[3] for rect in rects}
        warnings = ["这是 Aseprite 导出的分帧信息，已按它重新打包成图集。"]
        if len(widths) > 1 or len(heights) > 1:
            warnings.append(
                f"各帧尺寸不一致，已统一按最大画格 {max(widths)}x{max(heights)} 居中对齐。"
            )
        probe = SourceProbe(
            "spritesheet", json_path, min(len(rects), MAX_FRAMES),
            max(widths), max(heights),
            _fps_from_durations([rect[4] for rect in rects]), warnings,
        )
        if analyze:
            _apply_analysis(probe, _read_spritesheet_frames(sprite_path, 0, 0, 0, rects=rects))
        return probe

    raise KillIconImportError(
        f"{os.path.basename(json_path)} 里既没有 frame_width/frames，"
        f"也不是 Aseprite 的导出格式，没法当图集用。"
    )


def _resolve_sheet_image(json_path, data):
    """图集 JSON 对应的那张图。Aseprite 会把文件名写在 `meta.image` 里。"""
    meta = data.get("meta")
    if isinstance(meta, dict) and meta.get("image"):
        candidate = os.path.join(os.path.dirname(json_path), str(meta["image"]))
        if os.path.isfile(candidate):
            return candidate
    candidate = os.path.splitext(json_path)[0] + ".png"
    if os.path.isfile(candidate):
        return candidate
    raise KillIconImportError(
        f"找到了 {os.path.basename(json_path)} 但没找到配套的 .png 图集。"
    )


def _apply_analysis(probe, frames):
    analysis = analyze_frames(frames)
    probe.opaque_background = bool(analysis.get("opaque_background"))
    probe.suggested_key_color = tuple(analysis.get("suggested_key_color") or ())
    probe.trim_box = tuple(analysis.get("trim_box") or ())
    if probe.opaque_background:
        probe.warnings.append(
            "这个素材没有透明背景，叠在游戏画面上会是一个方块。"
            "可以在导入时勾「抠掉背景色」。"
        )
    if int(analysis.get("transparent_margin") or 0) >= 8:
        probe.warnings.append(
            f"四周有约 {analysis['transparent_margin']}px 的全透明边，"
            f"图标看起来会偏小。可以在导入时勾「裁掉透明边」。"
        )
    return probe


# ==================================================== 落库


def _pack_sheet(frames, frame_width, frame_height):
    Image, _ImageSequence = _pil()
    cols = max(1, min(len(frames), MAX_SHEET_WIDTH // max(1, frame_width)))
    rows = (len(frames) + cols - 1) // cols
    sheet = Image.new("RGBA", (frame_width * cols, frame_height * rows), (0, 0, 0, 0))
    for index, frame in enumerate(frames):
        sheet.paste(frame, ((index % cols) * frame_width, (index // cols) * frame_height))
    return sheet, cols, rows


def _atomic_write(path, writer):
    """先写临时文件再改名。

    导入是**覆盖既有风格条目**的操作。中途失败（磁盘满、被杀进程）如果留下
    半张图集，用户下次进游戏看到的是花屏或者干脆没图标，而且看不出发生过什么。
    """
    directory = os.path.dirname(path)
    os.makedirs(directory, exist_ok=True)
    handle, temp_path = tempfile.mkstemp(dir=directory, suffix=".tmp")
    os.close(handle)
    try:
        writer(temp_path)
        os.replace(temp_path, path)
    finally:
        if os.path.exists(temp_path):
            try:
                os.remove(temp_path)
            except OSError:
                pass


def _read_source_frames(source, probe, progress=None, cancel=None):
    """按探测出来的形态把帧读进来。返回 `(帧列表, 素材自带 fps, 警告)`。"""
    if probe.kind == "sequence":
        return _read_sequence_frames(str(source), progress, cancel)
    if probe.kind == "animation":
        return _read_animation_frames(str(source), progress, cancel)

    # 图集：要么按行列切，要么按 Aseprite 的 rect 切
    json_path = probe.path if str(probe.path).lower().endswith(".json") else None
    if json_path:
        with open(json_path, "r", encoding="utf-8") as handle:
            data = json.load(handle)
        sprite_path = _resolve_sheet_image(json_path, data)
        rects = _aseprite_rects(data) if not _as_int(data.get("frame_width")) else None
        cols = _as_int(data.get("cols")) or 1
        rows = _as_int(data.get("rows")) or 1
        frames = _read_spritesheet_frames(sprite_path, cols, rows,
                                          probe.frame_count, rects=rects)
        return frames, probe.fps, []

    cols, rows = probe.grid or (1, 1)
    frames = _read_spritesheet_frames(str(source), cols, rows, probe.frame_count)
    return frames, probe.fps, []


def convert_to_style(source, style_name, kills, *, fps=None, duration=None,
                     hold_seconds=None, variant="", resource_manager=None,
                     output_paths=None, grid=None, trim=False, chroma_key=None,
                     chroma_tolerance=DEFAULT_CHROMA_TOLERANCE,
                     progress=None, cancel=None):
    """把素材转成风格库里的标准条目，返回一份结果字典。

    `fps` 与 `duration` 二选一（都给时 `duration` 优先）：设置页给用户看的是
    "这个图标在屏幕上待多久"，落盘的仍是帧率。

    `hold_seconds` 是播完之后定格的秒数；单帧素材不给的话会自动带上默认值，
    否则它在屏幕上只会闪 0.03 秒（KI-4 之前就是这个表现，而且零提示）。

    `trim` / `chroma_key` 是导入向导里的两个可选修正，默认都不动素材。

    `output_paths=(png, json)` 时不进风格库，直接写到指定位置——制作工具的
    「另存为图集」走这条路。校验（风格名、等级）仍然照做：另存出来的文件
    多半还是要搬回库里的，格式约定不该因为出口不同而松掉。
    """
    from kill_icon_overlay import clamp_fps, clamp_hold, fps_for_duration

    if resource_manager is None:
        from resource_manager import ResourceManager as resource_manager

    style_name = str(style_name or "").strip()
    if not style_name:
        raise KillIconImportError("风格名不能是空的。")
    if any(sep in style_name for sep in ("/", "\\", "..")):
        raise KillIconImportError(f"风格名里不能有路径分隔符：{style_name}")
    if int(kills) not in range(1, 6):
        raise KillIconImportError(f"击杀等级只能是 1~5，收到 {kills}。")

    probe = probe_source(source, grid=grid)
    if output_paths:
        sprite_path, json_path = (str(output_paths[0]), str(output_paths[1]))
    else:
        sprite_path, json_path = resource_manager.get_kill_icon_sprite_sheet_paths(
            style_name, int(kills), variant=variant
        )

    verbatim = (
        probe.kind == "spritesheet"
        and str(probe.path).lower().endswith(".json")
        and not trim and not chroma_key
        and _is_native_schema(probe.path)
    )

    if verbatim:
        # 我们自己格式的图集原样搬进来，不重新编码——重编码只会掉画质。
        source_sheet = _resolve_sheet_image(probe.path, _load_json(probe.path))
        _atomic_write(sprite_path, lambda tmp: shutil.copyfile(source_sheet, tmp))
        metadata = _load_json(probe.path)
        frame_count = int(metadata.get("frames") or probe.frame_count)
        target_fps = clamp_fps(
            fps_for_duration(frame_count, duration) if duration else
            (fps if fps else metadata.get("fps", DEFAULT_FPS))
        )
        metadata["fps"] = target_fps
        metadata["hold_seconds"] = clamp_hold(
            metadata.get("hold_seconds", 0.0) if hold_seconds is None else hold_seconds
        )
        metadata.setdefault("version", 1)
        warnings = list(probe.warnings)
    else:
        frames, source_fps, warnings = _read_source_frames(source, probe, progress, cancel)
        _check_cancelled(cancel)
        frames, frame_width, frame_height, extra = _normalize_frames(
            frames, trim=trim, chroma_key=chroma_key, chroma_tolerance=chroma_tolerance
        )
        warnings = list(warnings) + list(extra)

        frame_count = len(frames)
        target_fps = clamp_fps(
            fps_for_duration(frame_count, duration) if duration else (fps or source_fps)
        )
        target_hold = clamp_hold(
            _static_probe_hold(frame_count) if hold_seconds is None else hold_seconds
        )

        _report(progress, len(frames), len(frames), "处理帧")
        sheet, cols, rows = _pack_sheet(frames, frame_width, frame_height)
        _check_cancelled(cancel)
        _atomic_write(sprite_path, lambda tmp: sheet.save(tmp, "PNG", optimize=True))
        _report(progress, 1, 1, "打包图集")
        metadata = {
            "frame_width": frame_width,
            "frame_height": frame_height,
            "frames": frame_count,
            "cols": cols,
            "rows": rows,
            "fps": target_fps,
            "hold_seconds": target_hold,
            "loop": False,
            "version": 1,
        }

    _atomic_write(
        json_path,
        lambda tmp: _write_json(tmp, metadata),
    )

    # 老格式的逐帧目录会**优先**被 has_kill_icon_level_assets 之外的路径认出来吗？
    # 不会——装载顺序是「图集优先、逐帧目录兜底」。但同一等级同时存在两种格式
    # 会让用户困惑（改了图集却看到老动画的错觉），所以这里显式提示一句。
    legacy_dir = (
        None if output_paths
        else resource_manager.get_kill_icon_legacy_frames_dir(style_name, int(kills))
    )
    if legacy_dir and not variant:
        warnings.append(
            f"这个等级下还留着老的逐帧目录（{legacy_dir}）。播放会优先用刚导入的图集，"
            f"老目录可以删掉。"
        )

    result = {
        "style": style_name,
        "kills": int(kills),
        "variant": variant,
        "kind": probe.kind,
        "frames": int(metadata.get("frames", 0)),
        "fps": int(metadata.get("fps", DEFAULT_FPS)),
        "hold_seconds": float(metadata.get("hold_seconds", 0.0) or 0.0),
        "frame_width": int(metadata.get("frame_width", 0)),
        "frame_height": int(metadata.get("frame_height", 0)),
        "sprite_path": sprite_path,
        "json_path": json_path,
        "warnings": warnings,
    }
    hold_note = f"，定格 {result['hold_seconds']:.1f}s" if result["hold_seconds"] else ""
    logger.info(
        f"导入击杀图标: {style_name}/{kills}{variant} ← {os.path.basename(str(source))} "
        f"({result['frames']} 帧 @ {result['fps']}fps{hold_note})"
    )
    return result


def _as_int(value, default=0):
    """JSON 里的值不一定是数字。Aseprite 的 `frames` 就是个字典。"""
    if isinstance(value, bool) or not isinstance(value, (int, float, str)):
        return default
    try:
        return int(float(value))
    except (TypeError, ValueError):
        return default


def _is_native_schema(json_path):
    data = _load_json(json_path)
    return bool(_as_int(data.get("frame_width")) and _as_int(data.get("frame_height"))
                and _as_int(data.get("frames")))


def _load_json(path):
    with open(path, "r", encoding="utf-8") as handle:
        data = json.load(handle)
    return data if isinstance(data, dict) else {}


def _write_json(path, payload):
    with open(path, "w", encoding="utf-8") as handle:
        json.dump(payload, handle, indent=2, ensure_ascii=False)

"""Audio subsystem exports（惰性）。

UP-055：这里原本是**饥饿式**导入——顶层 `from core.audio.audio_manager import ...`
会把 pygame + numpy + pkg_resources 拉进任何"只是碰了一下 core.audio 里某个
模块"的调用方。

实测（`python -X importtime -c "import gui_widget"`）：整个 1345.7ms 里有
**611.9ms** 是这么来的——gui_widget 只 import 了 `core.audio.audio_resource_health`
（那个模块自己压根不用 pygame，只要 config / resource_manager），但 Python 导入
子模块前必先执行包的 `__init__`，于是 pygame(596.9ms，其中 pkg_resources 314.8 +
numpy 204.6) 被整个拖进"窗口显示前"的关键路径。
讽刺的是 gui_widget 那行 import 上面正写着"重量级组件延迟导入，加速启动"。

改为 PEP 562 惰性导出：名字仍在 `__all__` 里、`from core.audio import AudioManager`
照常可用，只有**真的取用**时才导入对应子模块。

打包安全性：release spec 用 `collect_submodules("core")` 按**文件系统**递归收集
子模块，不依赖本文件的静态 import，因此懒加载不会让子模块从产物里消失。
（红线第四节"hiddenimports 只扫一层 AST"说的是根目录种子文件，不是 core 包。）
"""

from typing import TYPE_CHECKING

# 名字 -> 提供它的子模块。取用时才真正 import。
_EXPORTS = {
    "AudioEvent": "core.audio.audio_event_timeline",
    "AudioEventTimeline": "core.audio.audio_event_timeline",
    "get_audio_event_timeline": "core.audio.audio_event_timeline",
    "DEFAULT_AUDIO_EXTENSIONS": "core.audio.audio_file_utils",
    "AudioManager": "core.audio.audio_manager",
    "get_audio_manager": "core.audio.audio_manager",
    "PlaybackDecision": "core.audio.audio_playback_policy",
    "PlaybackRequest": "core.audio.audio_playback_policy",
    "decide_channel_action": "core.audio.audio_playback_policy",
    "resolve_priority": "core.audio.audio_playback_policy",
    "AudioTaskRunner": "core.audio.audio_task_runner",
    "get_audio_task_runner": "core.audio.audio_task_runner",
    "submit_import_refresh_task": "core.audio.audio_task_runner",
    "submit_reload_audio_task": "core.audio.audio_task_runner",
    "get_legacy_audio_manager": "core.audio.runtime_audio",
    "get_runtime_audio_manager": "core.audio.runtime_audio",
}

if TYPE_CHECKING:  # 只为静态检查 / IDE 补全，运行时不执行
    from core.audio.audio_event_timeline import (
        AudioEvent,
        AudioEventTimeline,
        get_audio_event_timeline,
    )
    from core.audio.audio_file_utils import DEFAULT_AUDIO_EXTENSIONS
    from core.audio.audio_manager import AudioManager, get_audio_manager
    from core.audio.audio_playback_policy import (
        PlaybackDecision,
        PlaybackRequest,
        decide_channel_action,
        resolve_priority,
    )
    from core.audio.audio_task_runner import (
        AudioTaskRunner,
        get_audio_task_runner,
        submit_import_refresh_task,
        submit_reload_audio_task,
    )
    from core.audio.runtime_audio import (
        get_legacy_audio_manager,
        get_runtime_audio_manager,
    )


def __getattr__(name: str):
    """PEP 562：属性缺失时才去导入对应子模块。"""
    module_path = _EXPORTS.get(name)
    if module_path is None:
        raise AttributeError(f"module {__name__!r} has no attribute {name!r}")

    import importlib

    value = getattr(importlib.import_module(module_path), name)
    globals()[name] = value  # 缓存：之后走正常属性查找，不再进这里
    return value


def __dir__():
    return sorted(set(globals()) | set(_EXPORTS))


__all__ = [
    "AudioManager",
    "AudioTaskRunner",
    "AudioEvent",
    "AudioEventTimeline",
    "PlaybackRequest",
    "PlaybackDecision",
    "get_audio_manager",
    "get_runtime_audio_manager",
    "get_legacy_audio_manager",
    "get_audio_task_runner",
    "submit_reload_audio_task",
    "submit_import_refresh_task",
    "get_audio_event_timeline",
    "resolve_priority",
    "decide_channel_action",
    "DEFAULT_AUDIO_EXTENSIONS",
]

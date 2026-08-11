import os

from core.audio.audio_file_utils import (
    DEFAULT_AUDIO_EXTENSIONS,
    find_audio_by_stem,
    find_first_audio_file,
    list_style_dirs_with_audio,
    list_unique_audio_stems,
)


def _touch(path):
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "wb") as f:
        f.write(b"")


def test_list_style_dirs_with_audio_detects_supported_extensions(tmp_path):
    base = tmp_path / "styles"
    _touch(str(base / "A" / "a.wav"))
    _touch(str(base / "b" / "b.ogg"))
    _touch(str(base / "c" / "note.txt"))

    styles = list_style_dirs_with_audio(str(base), extensions=DEFAULT_AUDIO_EXTENSIONS)
    assert styles == ["A", "b"]


def test_find_first_audio_file_prefers_keyword(tmp_path):
    base = tmp_path / "c4"
    _touch(str(base / "1.wav"))
    _touch(str(base / "planted.ogg"))

    picked = find_first_audio_file(
        str(base),
        extensions=DEFAULT_AUDIO_EXTENSIONS,
        preferred_tokens=("planted",),
    )
    assert picked is not None
    assert picked.endswith("planted.ogg")


def test_find_audio_by_stem_follows_extension_priority(tmp_path):
    base = tmp_path / "death"
    _touch(str(base / "demo.ogg"))
    _touch(str(base / "demo.wav"))

    # default priority: mp3 > wav > ogg
    picked = find_audio_by_stem(str(base), "demo")
    assert picked is not None
    assert picked.endswith("demo.wav")


def test_list_unique_audio_stems_deduplicates(tmp_path):
    base = tmp_path / "death"
    _touch(str(base / "same.mp3"))
    _touch(str(base / "same.wav"))
    _touch(str(base / "other.ogg"))

    stems = list_unique_audio_stems(str(base))
    assert stems == ["other", "same"]


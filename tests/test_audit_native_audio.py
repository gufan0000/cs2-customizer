# SPDX-License-Identifier: GPL-3.0-or-later
"""Native decode boundaries; synthetic files only, no devices or hooks."""
from io import BytesIO
import struct
from types import SimpleNamespace
from unittest.mock import Mock

import numpy as np
import pytest
import soundfile

import core.audio.safe_soundfile as safe


def wav(codec=1, frames=16):
    fmt = struct.pack("<HHIIHH", codec, 1, 48000, 96000, 2, 16)
    body = b"WAVEfmt " + struct.pack("<I", len(fmt)) + fmt
    body += b"data" + struct.pack("<I", frames * 2) + bytes(frames * 2)
    return b"RIFF" + struct.pack("<I", len(body)) + body


@pytest.mark.parametrize("payload", [
    b"\x64\xa3\x01\x00" + bytes(64),  # IRCAM, irrespective of .wav suffix
    bytes(80),  # MAT4 / unknown
    wav(0x11), wav(0x55),  # vulnerable native WAV codec paths
    wav()[:-1],  # truncated RIFF
    b"ID3\x04\x00\x00\x00\x00\x00\x00" + bytes(80),
    b"ID3\x04\x00\x00\xff\x00\x00\x00" + bytes(80),
])
@pytest.mark.parametrize("operation", [safe.info, safe.read])
def test_unsafe_container_never_reaches_native_parser(tmp_path, monkeypatch, payload, operation):
    path = tmp_path / "disguised.wav"
    path.write_bytes(payload)
    monkeypatch.setattr(safe.soundfile, "SoundFile", lambda *_: pytest.fail("native parser entered"))
    with pytest.raises(safe.AudioFileError):
        operation(path)


@pytest.mark.parametrize("kind,subtype", [("WAV", "PCM_16"), ("WAV", "FLOAT"),
                                         ("FLAC", "PCM_16"), ("OGG", "VORBIS"),
                                         ("MP3", "MPEG_LAYER_III")])
@pytest.mark.parametrize("channels", [1, 2])
def test_real_common_formats_still_decode(tmp_path, kind, subtype, channels):
    path = tmp_path / ("clip." + kind.lower())
    samples = np.zeros((2400, channels), dtype="float32")
    soundfile.write(path, samples, 48000, format=kind, subtype=subtype)
    result, rate = safe.read(path)
    assert rate == 48000 and len(result) == 2400
    assert safe.info(path).duration == pytest.approx(0.05)
    assert np.isfinite(result).all()


def test_snapshot_cannot_change_under_native_reader(tmp_path, monkeypatch):
    path = tmp_path / "clip.wav"
    original = wav()
    path.write_bytes(original)
    native = safe.soundfile.SoundFile

    def replace_then_open(snapshot):
        path.write_bytes(bytes(80))
        assert snapshot.getvalue() == original
        return native(snapshot)

    monkeypatch.setattr(safe.soundfile, "SoundFile", replace_then_open)
    assert len(safe.read(path)[0]) == 16


def test_limits_precede_native_open_and_array_allocation(tmp_path, monkeypatch):
    path = tmp_path / "clip.wav"
    path.write_bytes(wav())
    with monkeypatch.context() as patch:
        patch.setattr(safe, "MAX_FILE_BYTES", 8)
        patch.setattr(safe.soundfile, "SoundFile", lambda *_: pytest.fail("oversized native input"))
        with pytest.raises(safe.AudioFileError, match="128 MB"):
            safe.read(path)
    native = Mock(channels=2, samplerate=48000, frames=2**40)
    opened = Mock()
    opened.__enter__ = Mock(return_value=native)
    opened.__exit__ = Mock(return_value=False)
    monkeypatch.setattr(safe.soundfile, "SoundFile", lambda *_: opened)
    with pytest.raises(safe.AudioFileError, match="解码长度"):
        safe.read(path)
    native.read.assert_not_called()


def test_float_nan_is_not_sent_to_audio_device(tmp_path):
    path = tmp_path / "float.wav"
    soundfile.write(path, np.array([np.nan, np.inf, -np.inf], dtype="float32"), 48000,
                    subtype="FLOAT")
    data, _ = safe.read(path)
    assert data.tolist() == [0.0, 1.0, -1.0]


def test_unsafe_file_is_reported_before_slot_claims_playback(tmp_path):
    from voice_output_manager import VoiceOutputManager
    from pages.voice_output_page import VoiceOutputPage

    path = tmp_path / "unsafe.wav"
    path.write_bytes(wav(0x11))
    manager = VoiceOutputManager.__new__(VoiceOutputManager)
    manager.play_audio_with_ptt_protocol = Mock()
    page = SimpleNamespace(
        soundboard_slots={0: {"audio": str(path), "name": "clip", "volume": 1}},
        logger=Mock(), voice_manager=manager, ptt_key="v", ptt_enabled=True, ptt_delay=0,
        _status_signal=Mock(), _status_clear_signal=Mock(), _toast_error_signal=Mock(),
    )
    VoiceOutputPage._trigger_slot(page, 0)
    manager.play_audio_with_ptt_protocol.assert_not_called()
    message = page._toast_error_signal.emit.call_args.args[0]
    assert "PCM WAV" in message
    assert all("▶ 播放" not in call.args[0] for call in page._status_signal.emit.call_args_list)


def test_id3_cannot_enable_a_different_container():
    # A valid ID3 tag may precede MP3, but not another native container.
    safe._check_container(b"ID3\x04\x00\x00\x00\x00\x00\x02xx\xff\xfb\x90\x00")
    with pytest.raises(safe.AudioFileError):
        safe._check_container(b"ID3\x04\x00\x00\x00\x00\x00\x00" + wav())


def test_wav_extensible_pcm_is_supported(tmp_path):
    path = tmp_path / "clip.wav"
    buffer = BytesIO()
    soundfile.write(buffer, np.zeros((16, 2)), 48000, format="WAVEX", subtype="PCM_24")
    path.write_bytes(buffer.getvalue())
    assert safe.read(path)[0].shape == (16, 2)

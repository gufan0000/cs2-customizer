# SPDX-License-Identifier: GPL-3.0-or-later
"""Bound voice-file decoding before entering libsndfile's native parsers.

libsndfile 1.2.2 still ships in SoundFile 0.14. Restrict its input formats
and WAV codecs until upstream wheels contain the native security fixes.
"""
from contextlib import contextmanager
from io import BytesIO
from pathlib import Path
import struct
import os
from types import SimpleNamespace

import numpy as np
import soundfile

MAX_FILE_BYTES = 128 * 1024 * 1024
MAX_DECODED_BYTES = 256 * 1024 * 1024


class AudioFileError(ValueError):
    """A file cannot safely enter the voice playback pipeline."""


def _check_wav(data):
    end = struct.unpack_from("<I", data, 4)[0] + 8
    if end != len(data):
        raise AudioFileError("WAV 文件长度错误，请重新导出音频。")
    pos, fmt, has_data, chunks = 12, None, False, 0
    while pos + 8 <= end:
        kind, size = struct.unpack_from("<4sI", data, pos)
        pos += 8
        chunks += 1
        if pos + size > end or chunks > 4096:
            raise AudioFileError("WAV 数据块损坏或过多，请重新导出音频。")
        if kind == b"fmt ":
            if fmt is not None or size < 16 or size > 40:
                raise AudioFileError("WAV 格式信息无效，请转换为 PCM WAV。")
            fmt = data[pos:pos + size]
        elif kind == b"data":
            has_data = True
        pos += size + (size & 1)
    if pos != end or fmt is None or not has_data:
        raise AudioFileError("WAV 数据不完整，请重新导出音频。")
    codec, channels, rate, byte_rate, align, bits = struct.unpack_from("<HHIIHH", fmt)
    if codec == 0xFFFE:
        # WAVE_FORMAT_EXTENSIBLE: only PCM / IEEE float subformats.
        if len(fmt) != 40 or fmt[24:40] not in (
            bytes.fromhex("0100000000001000800000aa00389b71"),
            bytes.fromhex("0300000000001000800000aa00389b71"),
        ):
            raise AudioFileError("暂不支持这个 WAV 编码，请转换为 PCM WAV。")
        codec = fmt[24]
    # In particular, keep IMA ADPCM (CVE-2026-37555) and MPEG-in-WAV
    # (CVE-2026-88386) out of libsndfile, including disguised extensions.
    if codec not in (1, 3, 6, 7):
        raise AudioFileError("暂不支持这个 WAV 编码，请转换为 PCM WAV 或 FLAC。")
    valid_bits = {1: (8, 16, 24, 32), 3: (32, 64), 6: (8,), 7: (8,)}
    if (channels not in (1, 2) or not 8000 <= rate <= 192000
            or bits not in valid_bits[codec] or align != channels * (bits // 8)
            or byte_rate != rate * align):
        raise AudioFileError("音频需为单声道或双声道、8–192 kHz，且 WAV 格式信息完整。")


def _check_container(data):
    if len(data) >= 12 and data[:4] == b"RIFF" and data[8:12] == b"WAVE":
        _check_wav(data)
        return
    if data[:4] in (b"fLaC", b"OggS"):
        return
    offset = 0
    # libsndfile skips ID3 before dispatch. Check the real payload too, so an
    # ID3 tag cannot smuggle a MAT4 / IRCAM / other native parser through.
    if data[:3] == b"ID3":
        if len(data) < 10 or data[3] not in (2, 3, 4) or any(b & 128 for b in data[6:10]):
            raise AudioFileError("MP3 标签损坏，请重新导出音频。")
        size = 0
        for value in data[6:10]:
            size = (size << 7) | value
        offset = 10 + size
        if data[3] == 4 and data[5] & 0x10:
            offset += 10
    head = data[offset:offset + 4]
    if (len(head) == 4 and head[0] == 0xFF and head[1] & 0xE0 == 0xE0
            and head[1] & 0x18 != 0x08 and head[1] & 0x06
            and head[2] & 0xF0 != 0xF0 and head[2] & 0x0C != 0x0C):
        return
    raise AudioFileError("音频格式无法识别，请使用 PCM WAV、MP3、OGG 或 FLAC。")


@contextmanager
def _open(path):
    with Path(path).open("rb") as source:
        size = os.fstat(source.fileno()).st_size
        if size > MAX_FILE_BYTES:
            raise AudioFileError("音频文件超过 128 MB，请截短后重试。")
        data = source.read(size + 1)
    if len(data) != size:
        raise AudioFileError("音频文件在读取时发生变化，请重试。")
    _check_container(data)
    # Decode the checked snapshot, never reopen a mutable path after validation.
    try:
        with BytesIO(data) as snapshot, soundfile.SoundFile(snapshot) as audio:
            if (audio.channels not in (1, 2) or not 8000 <= audio.samplerate <= 192000
                    or not 0 < audio.frames <= MAX_DECODED_BYTES // 8):
                raise AudioFileError("音频声道、采样率或解码长度超限，请转为双声道或截短后重试。")
            yield audio
    except soundfile.LibsndfileError as exc:
        raise AudioFileError("音频文件损坏或无法解码，请重新导出音频。") from exc


def read(path, dtype="float32"):
    if dtype != "float32":
        raise ValueError("Voice decoding only supports float32")
    with _open(path) as audio:
        data = audio.read(frames=audio.frames, dtype="float32")
        np.nan_to_num(data, copy=False, nan=0.0, posinf=1.0, neginf=-1.0)
        return data, audio.samplerate


def info(path):
    with _open(path) as audio:
        return SimpleNamespace(duration=audio.frames / audio.samplerate)

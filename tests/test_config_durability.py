# -*- coding: utf-8 -*-
"""配置耐久性单测：损坏隔离 + 原子保存(P3⑤)。"""
import json

import config as config_mod
from config import Config


def _isolate(monkeypatch, tmp_path):
    cfgfile = tmp_path / "config.json"
    monkeypatch.setattr(config_mod, "get_config_path", lambda: str(cfgfile))
    return cfgfile


def test_corrupt_config_is_quarantined(monkeypatch, tmp_path):
    cfgfile = _isolate(monkeypatch, tmp_path)
    cfgfile.write_text("{ this is not valid json :::", encoding="utf-8")
    cfg = Config()
    cfg.load_config()
    # 损坏文件应被隔离为 .corrupt-*，并重写出有效默认配置
    corrupt = list(tmp_path.glob("config.json.corrupt-*"))
    assert corrupt, "损坏配置未被隔离备份"
    assert cfgfile.exists(), "未重写默认配置"
    json.loads(cfgfile.read_text(encoding="utf-8"))  # 新文件必须是有效 JSON
    assert getattr(cfg, "_load_error", ""), "未记录加载错误状态"


def test_missing_config_not_quarantined(monkeypatch, tmp_path):
    cfgfile = _isolate(monkeypatch, tmp_path)  # 文件不存在
    cfg = Config()
    cfg.load_config()
    # 缺失(非损坏)不应产生 .corrupt 备份，但应写出默认
    assert not list(tmp_path.glob("config.json.corrupt-*"))
    assert cfgfile.exists()


def test_save_is_atomic_and_valid(monkeypatch, tmp_path):
    cfgfile = _isolate(monkeypatch, tmp_path)
    cfg = Config()
    cfg.volume = 0.42
    cfg.save_config_now()
    assert cfgfile.exists()
    data = json.loads(cfgfile.read_text(encoding="utf-8"))
    assert abs(float(data.get("volume", 0)) - 0.42) < 1e-6
    assert not list(tmp_path.glob("config.json.tmp")), "残留 .tmp 临时文件"

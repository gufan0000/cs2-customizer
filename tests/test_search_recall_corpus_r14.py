# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""R14 召回语料：一张「用户真会怎么说」的清单，当回归基线用（2026-08-11）。

**为什么单独一份**：R13 那轮 70 条判据全绿、跨通道对拉也过了，用户装上第一次
打字就打出三个洞。**判据量的是"我想到的那些查询"**——而我想到的和玩家嘴里说的
不是一回事。所以这里不是再写几条精巧的判据，是把一批**真实说法**钉成基线，
覆盖全部页面。（开源裁剪后是 122 条 / 26 个页面：账号页整页移除，
「网易云」这类在线平台说法也没了被测对象——开源版音乐只播本地文件。）

改动匹配算法、加减词表、调任何一个阈值，都要过这张表。
它逮不住"排序好不好"，只逮"能不能搜到"——但那恰恰是用户第一时间会遇到的事。

⚠ 这张表是**量出来的**，不是编的：第一次跑 124 条时 **20 条召回不全**
（17 条完全搜不到 + 3 条搜到别的页），补完词表和「的」字剥离后才全绿。
往里加新说法时**先跑一遍看它红不红**——直接加一条本来就绿的，等于没加。
"""
from __future__ import annotations

import pytest

from core.settings_search import search_detailed

# (查询, 期望出现在结果里的页)。按页面分组，方便看覆盖面。
CORPUS = [
    # 基础设置
    ("全部静音", "basic"), ("关掉声音", "basic"), ("一键关闭", "basic"),
    ("玩家id", "basic"), ("看别人视角", "basic"), ("观战", "basic"),
    # 击杀音效 / 击杀语音
    ("杀人声", "kill_sound"), ("爆头声", "kill_sound"), ("连杀音", "kill_sound"),
    ("双杀", "kill_sound"), ("ace", "kill_sound"),
    ("语音包", "kill_voice"), ("妹子音", "kill_voice"), ("萝莉音", "kill_voice"),
    ("报点", "kill_voice"),
    # 被击杀音效
    ("死了的声音", "death_sound"), ("阵亡", "death_sound"), ("被爆头", "death_sound"),
    # 枪声
    ("大狙", "gun_sound"), ("狙击枪", "gun_sound"), ("步枪声", "gun_sound"),
    ("沙鹰", "gun_sound"), ("压低游戏声音", "gun_sound"), ("原声", "gun_sound"),
    # 切枪 / 换弹
    ("切刀", "switch_weapon"), ("掏枪", "switch_weapon"), ("拔枪", "switch_weapon"),
    ("上膛", "reload_sound"), ("压子弹", "reload_sound"), ("弹夹", "reload_sound"),
    # 特殊音效
    ("燃烧瓶", "special_sound"), ("火瓶", "special_sound"), ("molly", "special_sound"),
    ("烟雾弹", "special_sound"), ("下包", "special_sound"), ("拆包", "special_sound"),
    ("残血", "special_sound"), ("血少", "special_sound"), ("快死了", "special_sound"),
    # 准心
    ("描边", "crosshair"), ("粗细", "crosshair"), ("点准心", "crosshair"),
    ("圆准心", "crosshair"), ("动态准心", "crosshair"), ("分享码", "crosshair"),
    ("导入准心", "crosshair"), ("准星颜色", "crosshair"),
    # 击杀图标
    ("击杀提示", "kill_icon"), ("图案", "kill_icon"), ("击杀动画", "kill_icon"),
    # 局内视角
    ("枪的位置", "viewmodel"), ("手臂位置", "viewmodel"), ("fov", "viewmodel"),
    ("拉近", "viewmodel"), ("第一视角", "viewmodel"), ("快速回正", "viewmodel"),
    ("持枪", "viewmodel"), ("循环按键", "viewmodel"),
    # 开镜放大
    ("假镜", "magnifier"), ("模拟开镜", "magnifier"), ("放大倍率", "magnifier"),
    ("dpi", "magnifier"), ("开镜灵敏度", "magnifier"), ("右键放大", "magnifier"),
    # 自定闪光
    ("被闪", "flash"), ("闪瞎", "flash"), ("防闪", "flash"), ("挡闪", "flash"),
    ("白屏", "flash"),
    # HUD / 屏幕特效
    ("血条颜色", "hud_color"), ("残血变红", "hud_color"), ("界面颜色", "hud_color"),
    ("击杀特效", "screen_effects"), ("屏幕边框", "screen_effects"),
    # 音乐播放
    ("歌单", "music"), ("听歌", "music"), ("bgm", "music"),
    ("边玩边听", "music"), ("播放列表", "music"),
    # 语音输出
    ("音板", "voice_output"), ("开麦", "voice_output"), ("变声", "voice_output"),
    ("队友能听到", "voice_output"), ("虚拟麦", "voice_output"),
    ("放歌给队友", "voice_output"), ("按键说话", "voice_output"),
    # 道具瞄点
    ("扔烟", "utility"), ("烟雾点位", "utility"), ("闪光点位", "utility"),
    ("点位", "utility"), ("投掷教学", "utility"), ("道具引导", "utility"),
    # 高级设置
    ("游戏目录", "advanced"), ("找不到游戏", "advanced"), ("换主题", "advanced"),
    ("深色模式", "advanced"), ("夜间模式", "advanced"), ("开机启动", "advanced"),
    ("最小化到托盘", "advanced"), ("改键", "advanced"), ("恢复默认", "advanced"),
    ("重置设置", "advanced"),
    # 体检 / 导入 / 回放 / 快照 / 预设 / 关于
    ("没声音", "audio_health"), ("修复音频", "audio_health"), ("检查资源", "audio_health"),
    ("加音效", "audio_import_wizard"), ("添加音效", "audio_import_wizard"),
    ("批量导入", "audio_import_wizard"),
    ("后台任务", "audio_task_panel"), ("导入进度", "audio_task_panel"),
    ("刚才响了吗", "audio_replay"), ("音效历史", "audio_replay"),
    ("还原配置", "config_snapshot"), ("回滚", "config_snapshot"), ("存档", "config_snapshot"),
    ("一键配置", "preset_center"), ("配置包", "preset_center"), ("按地图切换", "preset_center"),
    ("版本号", "about"), ("检查更新", "about"), ("官网", "about"), ("反馈", "about"),
]


@pytest.mark.parametrize("query,page_id", CORPUS)
def test_corpus_recall(query, page_id):
    rows = search_detailed(query)
    pages = [r["page_id"] for r in rows]
    assert rows, f"「{query}」一条结果都没有"
    assert page_id in pages, (
        f"「{query}」召回不到 {page_id}，前 3 条是 "
        f"{[(r['page_id'], r['text']) for r in rows[:3]]}"
    )


def test_corpus_covers_every_page():
    """语料要覆盖全部 26 个页面。漏掉的页等于没人替它盯着。"""
    from core.settings_search import SEARCH_INDEX

    covered = {p for _q, p in CORPUS}
    all_pages = {pid for pid, _n, _w in SEARCH_INDEX}
    assert not (all_pages - covered), f"这些页在语料里没有任何说法：{all_pages - covered}"


def test_corpus_is_not_trivially_green():
    """语料不能全是"页面名原样打一遍"这种必然绿的条目。

    ⚠ 这条守的是这张表**本身**的价值：往里加一条本来就绿的说法，
    表会变长但一点信息量都没增加。至少八成条目必须是"不等于页面名"的口语说法。
    """
    from core.settings_search import SEARCH_INDEX

    names = {name for _pid, name, _w in SEARCH_INDEX}
    colloquial = [q for q, _p in CORPUS if q not in names]
    assert len(colloquial) >= len(CORPUS) * 0.8, (
        f"语料里只有 {len(colloquial)}/{len(CORPUS)} 条是口语说法，其余是页面名原样")


def test_no_query_floods_the_panel():
    """召回上去了，精度不能塌。整张语料里没有一条能糊满整个面板。"""
    worst = max(CORPUS, key=lambda c: len({r["page_id"] for r in search_detailed(c[0])}))
    pages = len({r["page_id"] for r in search_detailed(worst[0])})
    assert pages <= 12, f"「{worst[0]}」糊到 {pages} 个页面上了"

# -*- coding: utf-8 -*-
# SPDX-License-Identifier: GPL-3.0-or-later
"""设置搜索（2026-06-10 建，2026-08-10 加项级索引）。

27 个功能页、几百项配置，没有搜索全靠记忆翻页。本模块是搜索的**唯一引擎**——
顶栏下拉和回车跳转都走这里（2026-08-10 之前不是：下拉走的是 QCompleter 自带的
纯子串过滤，拼音/容错/口语全都看不见，详见 `widgets/search_popup` 的说明）。

两层索引：

- **页级**：`SEARCH_INDEX` 手工精选（功能词 + 口语词 + 症状式说法 + 英文别名）。
  「太吵了」「看不见准星」「为什么没声音」这类只能靠手写，自动收割永远收不到。
- **项级**：`core/search_index.json`，由 `scripts/build_search_index.py` 离线生成
  （离屏真建 27 个页面遍历控件树 + AST 扫源码字面量，两条通道互补）。
  这一层让**词表里没写过的具体开关**也能搜到并直接定位到那一行。

对外：
- `search_detailed(q)` → 项级+页级合并排序的结果行（结果面板用这个）
- `search(q)`          → 旧签名，按页去重的 [(page_id, 页面名, 命中词)]
- `text_matches(q, t)` → 通用匹配器，页面内就地定位卡片/控件行时用
"""
from __future__ import annotations

from functools import lru_cache
from typing import List, Set, Tuple

# ---------------- 拼音层(R1-2,2026-06-12) ----------------
# 国内用户习惯打 "zx"/"zhunxin" 找"准心"。pypinyin 缺失时静默降级为纯中文匹配,
# 不让搜索框因为一个可选依赖挂掉。


@lru_cache(maxsize=1)
def _pinyin_engine():
    try:
        from pypinyin import Style, lazy_pinyin

        return lazy_pinyin, Style
    except Exception:
        return None, None


@lru_cache(maxsize=2048)
def pinyin_aliases(text: str) -> Tuple[str, ...]:
    """返回 (全拼, 首字母) 两个别名;无中文/无引擎时返回空元组。"""
    lazy_pinyin, Style = _pinyin_engine()
    if lazy_pinyin is None or not text:
        return ()
    try:
        full = "".join(lazy_pinyin(text))
        initials = "".join(s[0] for s in lazy_pinyin(text) if s)
    except Exception:
        return ()
    out: Set[str] = set()
    if full and full != text:
        out.add(full.lower())
    if initials and initials != text and len(initials) >= 2:
        out.add(initials.lower())
    return tuple(sorted(out))


def _is_ascii_query(q: str) -> bool:
    return bool(q) and all(ord(ch) < 128 for ch in q)


def _long_enough(q: str) -> bool:
    """单个 ASCII 字母只许精确命中，不许走前缀/子串档。

    S1 给 27 个页面各加了英文别名之后实测：查一个字母 `a`，
    about / account / advanced / aim / autostart… **22 个页面**全部以
    "关键词前缀命中" 70 分并列涌出来，结果面板等于没用。
    中文单字不受此限——「音」前缀命中「音量」「音效」是用户真想要的。
    """
    return len(q) >= 2 or not _is_ascii_query(q)


# ---------------- 片段覆盖层(S7,2026-08-11) ----------------
#
# 中文用户不打空格。`_tokenize` 只按空格切词，于是「准心回正」整串是**一个** token，
# 而页面上那一项叫「启用准心快速回正」——不是子串，一分都拿不到，
# 结果第一位是基础设置页里那个孤零零的「准心」。实测 22 条常见说法里
# 有 9 条召回不全，一半栽在这里。
#
# 不引分词库（多一个可选依赖、多一片"装没装上"的静默降级），
# 改成**贪心最长片段覆盖**：把查询切成"能在这条文案里原样找到"的若干片段，
# 看它们合起来解释了查询的多少个字。
#   「准心回正」vs「启用准心快速回正」→ 准心 + 回正 = 4/4 字 → 满覆盖
#   「准心回正」vs「准心」            → 准心      = 2/4 字 → 半覆盖
# 这把尺子和页级原有的 `_span_union_len` 是同一把（见 `_score_token` 里那段教训），
# 现在两层共用，顺带把原来的"反向子串档"也一并吸收了：
# 文案整体是查询的子串时，它自己就是一个片段。

_COVER_MIN_FRAGMENT = 2     # 单字片段满天飞，不算证据
_COVER_MIN_QUERY = 3        # 2 字查询的片段就是它自己，普通子串档已经覆盖
# 覆盖率门槛。**0.75 是量出来的，不是拍的**——先试的 0.5 让三条既有判据同时翻车：
#   「锁血提示」被「启用游戏内提示」勾走（只对上「提示」，2/4）
#   「准心描边」被「准心大小」勾走（只对上「准心」，2/4）
# 半个查询对得上就算命中，等于把查询里最没信息量的那半个字当成了证据。
_COVER_MIN_RATIO = 0.75


@lru_cache(maxsize=4096)
def _grams(q: str) -> Tuple[str, ...]:
    """查询的 2-gram。缓存住是因为快筛每次搜索要跑三千多遍，
    而一次搜索里只有几个不同的查询串——不缓存的话光切片就占 17% 的时间（实测）。"""
    return tuple(q[i:i + 2] for i in range(len(q) - 1))


def _cover_spans(q: str, text: str) -> List[Tuple[int, int]]:
    """q 中能在 text 里原样找到的片段(长度≥2)，贪心最长优先，返回在 q 上的区间。"""
    n = len(q)
    if n < _COVER_MIN_QUERY or not text:
        return []
    # 快筛：k 个命中的 2-gram 最多能覆盖 2k 个字，而下面要求覆盖过半，
    # 所以命中数不到 ceil(n/4) 时连贪心都不用进。项级索引 369 条 × 若干变体，
    # 这道筛子挡掉其中绝大多数。
    need = (n + 3) // 4
    hits = 0
    for gram in _grams(q):
        if gram in text:
            hits += 1
            if hits >= need:
                break
    if hits < need:
        return []
    spans: List[Tuple[int, int]] = []
    i = 0
    while i < n:
        hit = 0
        for j in range(n, i + _COVER_MIN_FRAGMENT - 1, -1):
            if q[i:j] in text:
                hit = j
                break
        if hit:
            spans.append((i, hit))
            i = hit
        else:
            i += 1
    return spans


def _cover_len(q: str, text: str) -> int:
    """片段覆盖了查询的多少个字。"""
    return _span_union_len(_cover_spans(q, text))


def _cover_score(q: str, text: str) -> int:
    """片段覆盖档得分；覆盖不到查询的一半就不算命中(否则"设置"能命中一切)。

    按**覆盖比例**而不是覆盖字数给分。这是实测定下来的：
    查「准心回正」时基础设置页有个项就叫「准心」(覆盖 2/4)，局内视角页那个
    「启用准心快速回正」覆盖 4/4。按字数算两者只差 2 分，按比例算差 7 分——
    差距要大到不会被别的因子(主属页加权、多词覆盖率)抹平才算真的排对了。
    """
    covered = _cover_len(q, text)
    if covered < _COVER_MIN_FRAGMENT or covered < len(q) * _COVER_MIN_RATIO:
        return 0
    # 44 起步(与页级反向子串档同一起点)，满覆盖时追平正向子串的 58 分：
    # "把查询完整解释了" 和 "查询原样出现在里面" 是同一强度的证据。
    return 44 + round(14 * covered / len(q))


# ---------------- 同义词层(S8,2026-08-11) ----------------
#
# 用户嘴里的词和界面上的词经常不是一个。实测：搜「准星」搜不到局内视角页的
# 「启用准心快速回正」(界面写"准心")，搜「鼠标速度」「话筒」「生命值」直接是空。
#
# 做法是**查询变体**而不是给每条文案挂别名：变体天然贯穿所有档位
# (精确/前缀/子串/片段覆盖/拼音/容错)，而给文案挂别名只能在匹配那一步生效，
# 而且会把别名混进"命中词"显示给用户。
#
# 组内两两互通。词只登记**实测有人这么说**的，不做同义词词典——
# 组越大越容易互相污染(把"声音"和"音效"划等号，搜「声音」会糊一屏音效项)。
SYNONYM_GROUPS: Tuple[Tuple[str, ...], ...] = (
    ("准心", "准星", "瞄准点", "crosshair"),
    ("灵敏度", "鼠标速度", "鼠标灵敏度", "sensitivity"),
    ("麦克风", "话筒", "咪头", "microphone"),
    ("血量", "生命值", "血条", "hp"),
    ("热键", "快捷键", "键位", "hotkey"),
    ("音量", "声音大小", "响度", "volume"),
    ("视角", "手模", "viewmodel"),
    ("开镜", "倍镜", "狙击镜", "瞄准镜", "scope"),
    ("回正", "复位", "归位"),
    ("主题", "皮肤", "配色", "theme"),
    ("预设", "方案", "配置包", "preset"),
    ("开机自启", "自启动", "开机启动", "autostart"),
    ("图标", "图案", "icon"),
    ("目录", "路径", "文件夹", "folder"),
    ("更新", "升级", "update"),
    ("静音", "闭麦", "mute"),
    ("投掷物", "道具", "手雷", "grenade"),
)

# 同义词命中比原词低一档，保证"用户打的原词"永远排在同义命中前面。
#
# 0.88 不是拍的：变体的**精确命中**(100 分)乘完必须低于原词对页面的
# **关键词精确命中**(90 分)，否则查「crosshair」时基础设置页那个恰好叫「准心」的
# 开关(变体精确 100)会把准心设置页(原词精确 90)顶掉——用户打页面的英文名，
# 期望的是那一页，不是别处一个同名开关。100×0.88=88 < 90，这条边界就是它的来历。
SYNONYM_PENALTY = 0.88
# 变体上限。每多一个变体就多跑一遍全部档位，而收益递减。
MAX_QUERY_VARIANTS = 6


@lru_cache(maxsize=1)
def _synonym_map() -> dict:
    out: dict = {}
    for group in SYNONYM_GROUPS:
        for term in group:
            out.setdefault(term.lower(), []).extend(
                t for t in group if t.lower() != term.lower()
            )
    return out


@lru_cache(maxsize=2048)
def _query_variants(token: str) -> Tuple[str, ...]:
    """原词 + 同义词替换后的变体。原词永远在 [0]。"""
    mapping = _synonym_map()
    out = [token]
    seen = {token}
    # 结构助词「的」：用户打「死了的声音」，词表里写的是「死了声音」，
    # 一个字之差整条对不上（页级只认整词，差一个字就不是子串了）。
    # ⚠ 只剥「的」。「了」不能剥 ——「死了」「关了」里它是词的一部分，
    #   剥了会把「死了声音」变成「死声音」，反而更对不上。
    stripped = token.replace("的", "")
    if stripped != token and len(stripped) >= 2:
        seen.add(stripped)
        out.append(stripped)
    # 长词优先替换：「鼠标灵敏度」要整体换掉，而不是先被「灵敏度」拆了
    for term in sorted(mapping, key=len, reverse=True):
        if term not in token:
            continue
        for alt in mapping[term]:
            variant = token.replace(term, alt.lower())
            if variant not in seen:
                seen.add(variant)
                out.append(variant)
        if len(out) >= MAX_QUERY_VARIANTS:
            break
    return tuple(out[:MAX_QUERY_VARIANTS])


def _levenshtein_bounded(a: str, b: str, max_dist: int) -> int:
    """有界编辑距离：距离一旦确定超过 max_dist 立即返回 max_dist+1(早退)。
    无第三方依赖，给拼音/英文查询做拼写容错(zunxin→zhunxin, dukcing→ducking)。"""
    if a == b:
        return 0
    la, lb = len(a), len(b)
    if abs(la - lb) > max_dist:
        return max_dist + 1
    if la == 0:
        return lb
    if lb == 0:
        return la
    prev = list(range(lb + 1))
    for i in range(1, la + 1):
        cur = [i] + [0] * lb
        row_min = cur[0]
        ca = a[i - 1]
        for j in range(1, lb + 1):
            cost = 0 if ca == b[j - 1] else 1
            cur[j] = min(prev[j] + 1, cur[j - 1] + 1, prev[j - 1] + cost)
            if cur[j] < row_min:
                row_min = cur[j]
        if row_min > max_dist:
            return max_dist + 1
        prev = cur
    return prev[lb]


def _fuzzy_budget(q: str) -> int:
    """按查询长度给拼写容错预算：太短的查询不容错(噪音大)。"""
    n = len(q)
    if n >= 7:
        return 2
    if n >= 4:
        return 1
    return 0


def _ascii_fuzzy_hit(q: str, target: str) -> bool:
    """ASCII 查询对目标(直接英文/或其拼音别名)做拼写容错命中。"""
    budget = _fuzzy_budget(q)
    if budget <= 0:
        return False
    candidates = [target.lower()]
    candidates.extend(pinyin_aliases(target))
    for cand in candidates:
        if not cand or abs(len(cand) - len(q)) > budget:
            continue
        if _levenshtein_bounded(q, cand, budget) <= budget:
            return True
    return False


def text_matches(query: str, text: str) -> bool:
    """通用匹配:子串(不分大小写)、同义词、片段覆盖、拼音别名、或拼写容错。

    跳转后在页面上就地定位卡片/控件行用的也是这个。**必须和下拉里那套同源**：
    否则会出现"下拉里搜到了、跳过去却高亮不到"——搜「准星」下拉给出
    「启用准心快速回正」，跳过去却因为这里只认原词而找不到那一行。
    """
    q = str(query or "").strip().lower()
    t = str(text or "")
    if not q or not t:
        return False
    tl = t.lower()
    for variant in _query_variants(q):
        if variant in tl:
            return True
        if _cover_score(variant, tl):
            return True
        if _is_ascii_query(variant):
            for alias in pinyin_aliases(t):
                if alias.startswith(variant) or variant in alias:
                    return True
            # 拼写容错兜底（打错一两个字母仍能定位到卡片）
            if _ascii_fuzzy_hit(variant, t):
                return True
    return False

# (page_id, 页面显示名, 关键词列表)
# 关键词包含：功能词 + 口语/俗称 + 常见问法(甚至"症状"式的模糊说法)，
# 让"声音太大""看不见准星""变声""太吵了"这类模糊查询也能命中对应页。
SEARCH_INDEX: List[Tuple[str, str, List[str]]] = [
    ("basic", "基础设置", [
        "总开关", "功能开关", "全部开关", "关闭功能", "音量", "主音量", "总音量", "声音", "声音大小",
        "音量调节", "太吵", "太响", "声音大", "声音小", "游戏模式", "死斗", "竞技", "娱乐", "玩家ID",
        "steamid", "身份", "观战静音", "观战不响", "别人视角", "刷新状态", "载入音频", "重载音频",
        "没声音重载", "日志", "关掉所有声音", "全部静音", "一键关闭", "一键全关",
        # 英文别名（S1）
        "basic", "general", "volume", "master volume", "mute", "settings",
    ]),
    ("kill_sound", "击杀音效", [
        "击杀", "击杀音效", "杀敌音效", "杀人音效", "干掉敌人声音", "击杀声音", "连杀", "1杀", "五杀",
        "音效包", "杀敌反馈", "打死人声音", "击杀提示音", "爆头", "爆头音效", "爆头声音", "headshot",
        "kill", "杀人声", "双杀", "三杀", "四杀", "ace", "残局",
    ]),
    ("kill_voice", "击杀语音", [
        "击杀语音", "语音包", "连杀语音", "报点", "播报", "击杀播报", "连杀播报", "喊话", "妹音", "御姐", "妹子音", "萝莉音", "少女音", "萌妹音",
        "double kill", "三杀语音", "杀人报数", "语音播报", "kill voice", "voice pack",
    ]),
    ("death_sound", "被击杀音效", [
        "被击杀音效", "死亡音效", "被杀", "阵亡", "死了声音", "被爆头", "死亡声音", "阵亡提示", "挂了声音",
        "death", "死了的声音", "死亡的声音",
    ]),
    ("gun_sound", "枪声设置", [
        "枪声", "枪声替换", "换枪声", "开枪音效", "开火声", "枪响", "枪声音", "AWP", "大狙", "沙鹰", "USP",
        "原声保留", "原声音量", "静音覆盖", "ducking", "压低游戏音量", "压低游戏声音", "游戏声音变小", "游戏枪声变小", "枪声太吵",
        "狙击枪声音", "狙击枪", "步枪声音", "gun", "gun sound", "weapon sound", "fire",
    ]),
    ("switch_weapon", "切枪音效", [
        "切枪", "切枪音效", "换武器", "拔枪", "掏枪", "换枪音效", "切枪声音", "switch weapon", "draw", "切刀", "掏刀", "拿刀", "换刀",
    ]),
    ("reload_sound", "换弹音效", [
        "换弹", "换弹音效", "装弹", "上弹", "压弹", "换子弹", "reload", "换弹夹", "弹夹",
        "上膛", "压子弹", "推弹",
    ]),
    ("special_sound", "特殊音效", [
        "特殊音效", "手雷", "雷", "投掷物", "闪光弹", "烟雾弹", "烟雾", "燃烧弹", "molotov", "燃烧瓶", "火瓶", "molly", "纵火", "C4", "炸弹",
        "下包", "拆包", "低血量", "残血", "快死了", "血少", "血量警告", "锁血", "血量提示", "血量提醒",
        "回合", "回合开始", "回合结束", "回合胜利", "回合失败", "MVP", "胜利音效",
        "grenade", "smoke", "bomb", "low hp", "health",
    ]),
    ("crosshair", "准心设置", [
        "准心", "准星", "十字准心", "十字", "瞄准点", "看不见准星", "准星不见", "准心不见了", "没准心",
        "准心颜色", "准星颜色", "准心大小", "准心粗细", "描边", "动态准心", "击杀联动", "击杀变色",
        "导入准心", "分享准心", "准心样式", "自定义准星", "分享码", "准心代码", "准心分享码",
        "crosshair", "crosshairs", "reticle", "aim",
    ]),
    ("kill_icon", "击杀图标", [
        "击杀图标", "连杀图标", "图标", "图案", "击杀提示", "图标动画", "sprite", "精灵图", "FPS",
        "图标位置", "图标大小", "图标缩放", "击杀动画", "kill icon", "icon",
    ]),
    ("viewmodel", "局内视角", [
        "视角", "局内视角", "viewmodel", "手模", "持枪视角", "枪的位置", "手臂位置", "FOV", "视野",
        "自动切换", "循环视角", "视角预设", "手模位置", "第一视角", "view model", "field of view", "拉近", "拉远", "枪往前", "枪往后",
    ]),
    ("magnifier", "开镜放大", [
        "放大", "开镜", "狙击镜", "倍镜", "假镜", "模拟开镜", "放大倍率", "右键放大", "灵敏度",
        "灵敏度联动", "开镜灵敏度", "热键", "放大镜", "鼠标灵敏度",
        "magnifier", "zoom", "scope", "sensitivity", "sens", "dpi", "鼠标dpi",
    ]),
    ("flash", "自定闪光", [
        "闪光", "自定闪光", "被闪", "闪了", "闪瞎", "白屏", "白屏替换", "换闪光图", "闪光图片",
        "闪光音效", "不透明度", "被闪效果", "闪光遮挡", "flash", "flashbang", "blind", "防闪", "挡闪", "抗闪",
    ]),
    ("hud_color", "HUD颜色", [
        "HUD", "HUD颜色", "界面颜色", "血条颜色", "血量颜色", "动态HUD", "击杀变色", "残血变红",
        "游戏界面颜色", "hud color", "interface color",
    ]),
    ("screen_effects", "屏幕特效", [
        "屏幕特效", "特效", "击杀特效", "边框特效", "屏幕边框", "火花", "击杀反馈", "爆头特效",
        "screen effect", "effects", "vfx",
    ]),
    ("music", "音乐播放", [
        "音乐", "音乐播放", "播放器", "歌单", "播放列表", "听歌", "bgm", "背景音乐", "网易云", "QQ音乐",
        "B站音乐", "在线音乐", "死亡音量", "存活音量", "音乐联动", "边玩边听",
        "music", "player", "playlist",
    ]),
    ("voice_output", "语音输出", [
        "音板", "语音输出", "变声", "喊话", "开麦", "说话", "按键说话", "PTT", "VB-Cable", "虚拟麦克风",
        "虚拟麦", "音效转发", "队友", "转发给队友", "放音乐给队友", "队友能听到", "整活", "快捷键播放", "音板快捷键",
        "soundboard", "voice output", "microphone", "mic", "push to talk",
    ]),
    ("fun_afterlife", "死亡刷短视频", [
        "抖音", "刷抖音", "短视频", "死亡刷视频", "阵亡刷视频", "死了刷抖音", "贴屏", "贴边浏览器",
        "小窗", "竖屏", "整活", "摸鱼", "死亡摸鱼", "复活暂停", "刷视频", "看视频",
        "douyin", "tiktok", "short video", "afterlife",
    ]),
    ("utility", "道具瞄点", [
        "道具", "道具瞄点", "瞄点", "投掷物", "扔雷", "扔烟", "烟怎么扔", "烟雾点位", "闪光点位", "点位",
        "点位图", "教学图", "投掷教学", "引导键", "道具引导",
        "utility", "nade", "lineup", "smoke lineup",
    ]),
    ("advanced", "高级设置", [
        "高级设置", "CS2目录", "游戏目录", "游戏路径", "路径", "找不到游戏", "主题", "皮肤", "换肤",
        "换主题", "深色", "浅色", "暗色", "夜间", "更新公告", "托盘", "最小化到托盘", "后台运行",
        "开机自启", "自启动", "开机启动", "窗口记忆", "窗口大小", "管理员", "提权", "热键总览", "快捷键冲突",
        "调试", "调试模式", "重置设置", "恢复默认", "备份设置", "游戏内提示", "OSD",
        "快捷键", "键位", "改键", "绑定快捷键", "怎么绑定快捷键", "按键设置", "热键设置",
        "advanced", "theme", "dark mode", "hotkey", "hotkeys", "shortcut", "keybind",
        "autostart", "startup", "tray", "debug", "reset",
    ]),
    ("audio_health", "音频体检", [
        "音频体检", "资源体检", "体检", "音频检查", "资源检查", "检查资源", "查一下资源", "修复", "缺失目录", "为什么没声音",
        "声音不对", "音效不响", "检查音频", "audio health", "diagnose", "repair",
    ]),
    ("audio_import_wizard", "资源导入向导", [
        "导入", "导入音频", "音频包", "资源包", "批量导入", "拖拽", "加音效", "添加音效", "导入素材",
        "import", "import wizard",
    ]),
    ("audio_task_panel", "音频任务面板", [
        "任务", "后台任务", "导入进度", "任务面板", "tasks", "task panel",
    ]),
    ("audio_replay", "音频事件回放", [
        "回放", "音频回放", "事件记录", "播放历史", "为什么没声音", "刚才响了吗", "音效历史",
        "replay", "event log",
    ]),
    ("config_snapshot", "配置快照", [
        "快照", "配置快照", "配置备份", "回滚", "恢复配置", "还原", "存档", "备份配置", "撤销更改",
        "snapshot", "backup", "restore", "rollback",
    ]),
    ("preset_center", "预设中心", [
        "预设", "预设中心", "预设包", "一键配置", "方案", "配置包", "分享配置", "整套配置", "按地图切换",
        "自动切预设", "配置分享", "导入配置", "preset", "profile", "config pack",
    ]),
    ("about", "关于软件", [
        "关于", "关于软件", "版本", "版本号", "检查更新", "更新日志", "作者", "官网", "反馈", "群号",
        "about", "version", "update", "changelog", "feedback",
    ]),
]

# 跨页重复的关键词：同一个词写在多页词表里，会让排序在几页之间抖。
# 这里声明它的**主属页**，命中主属页时加权、命中其它页时降权。
# 只登记实测重复的那几个（`scripts/` 的探针会报），不做全量对照表。
PRIMARY_OWNER = {
    "喊话": "voice_output",        # kill_voice 也有，但用户说"喊话"九成是想开麦
    "投掷物": "utility",           # special_sound 也有，但"投掷物"更常指点位
    "击杀变色": "hud_color",       # crosshair 也有
    "为什么没声音": "audio_health",  # audio_replay 也有，体检才是出路
}


def _score_token(token: str, name: str, words: List[str]) -> Tuple[int, str]:
    """单个查询词对一个页面的最佳匹配分与命中词（含同义词变体）。"""
    best_score, best_hit = _score_token_one(token, name, words)
    if best_score >= 90:
        return best_score, best_hit          # 精确档，变体不可能更好，省 5 遍
    for variant in _query_variants(token)[1:]:
        s, h = _score_token_one(variant, name, words, allow_phonetic=False)
        s = int(s * SYNONYM_PENALTY)
        if s > best_score:
            best_score, best_hit = s, h
    return best_score, best_hit


def _score_token_one(token: str, name: str, words: List[str],
                     allow_phonetic: bool = True) -> Tuple[int, str]:
    """单个查询词对一个页面(名+关键词)的最佳匹配分与命中词。

    `allow_phonetic=False` 用于同义词变体：拼音/拼写容错是为了兜"用户打的是拼音
    或者打错了"，而变体本身已经是一层猜测，再叠一层就是拿猜测去猜测——
    实测这条路径还是耗时大头（对每条文案算 pinyin_aliases + 编辑距离），
    关掉之后单次查询从 4.2ms 降回 1ms 出头。
    """
    q = token
    ascii_q = allow_phonetic and _is_ascii_query(q) and len(q) >= 2
    score = 0
    best = ""

    # 页面名
    if q in name.lower():
        score = 100 + (50 if name.lower().startswith(q) else 0)
        best = name
    if ascii_q and score < 95:
        for alias in pinyin_aliases(name):
            if alias == q or alias.startswith(q):
                score, best = 95, name
                break
            if q in alias and score < 60:
                score, best = 60, name

    # 关键词
    rev_spans: List[Tuple[int, int]] = []   # 关键词整体落在查询里时，它覆盖的区间
    rev_best = ""
    for w in words:
        wl = w.lower()
        if q == wl:
            if score < 90:
                score, best = 90, w
        elif wl.startswith(q) and _long_enough(q):
            if score < 70:
                score, best = 70, w
        elif q in wl and _long_enough(q):
            if score < 50:
                score, best = 50, w
        elif len(wl) >= 2 and wl in q:
            # 反向子串：用户长句里包含**整个**关键词（"声音太大"含"声音"）。
            #
            # ⚠ 页级这一档**只认整词**，不用项级那套片段覆盖（S7）。
            #    试过放开：把一页 40 个关键词拼成一条算片段覆盖，结果查「声音太大」
            #    时凡是词表里有任何含「声音」的词的页面全部 46 分并列涌出来
            #    ——「打死人声音」的「声音」也算命中，音频体检还反超了基础设置。
            #    页级词表是**手写别名**，一个词要么整体相关要么不相关；
            #    项级文案是界面标签，查询本来就该匹配它的一部分。
            #    两层用不同尺子不是不一致，是因为被测的东西不是一种东西。
            i = q.find(wl)
            rev_spans.append((i, i + len(wl)))
            if len(wl) > len(rev_best):
                rev_best = w
        elif ascii_q:
            hit_alias = False
            for alias in pinyin_aliases(w):
                if alias == q:
                    if score < 88:
                        score, best = 88, w
                    hit_alias = True
                    break
                if alias.startswith(q):
                    if score < 68:
                        score, best = 68, w
                    hit_alias = True
                    break
                if len(q) >= 3 and q in alias:
                    if score < 48:
                        score, best = 48, w
                    hit_alias = True
                    break
            if not hit_alias and score < 40 and _ascii_fuzzy_hit(q, w):
                # 拼写容错档：精确/前缀/子串/拼音全落空后才启用，分数最低
                score, best = 40, w

    # 反向子串档统一结算：按**跨关键词合并后**覆盖的查询字数给分（44 起，最高 50）。
    # 覆盖面才是"这条结果能不能解释用户在问什么"的度量——查「准心描边」时
    # 基础设置页只有「准心」（2 字），准心设置页有「准心」+「描边」（4 字，整个查询）。
    if rev_spans:
        rev_score = 44 + min(6, _span_union_len(rev_spans))
        if rev_score > score:
            score, best = rev_score, rev_best

    # 页面名拼写容错兜底（英文页名/拼音打错）
    if ascii_q and score < 40 and _ascii_fuzzy_hit(q, name):
        score, best = 38, name

    return score, (best or name)


def _span_union_len(spans: List[Tuple[int, int]]) -> int:
    """若干区间合并后的总长度（重叠只算一次）。"""
    if not spans:
        return 0
    merged: List[List[int]] = []
    for start, end in sorted(spans):
        if merged and start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return sum(end - start for start, end in merged)


def _tokenize(query: str) -> List[str]:
    raw = str(query or "").strip().lower()
    return [t for t in raw.split() if t] if raw else []


def _owner_weight(hit_word: str, page_id: str) -> float:
    """跨页重复关键词的主属页加权（见 PRIMARY_OWNER）。"""
    owner = PRIMARY_OWNER.get(hit_word)
    if owner is None:
        return 1.0
    return 1.15 if owner == page_id else 0.75


def search_pages(query: str) -> List[Tuple[str, str, str]]:
    """页级搜索：返回 [(page_id, 页面名, 命中词)]，按相关度排序。"""
    tokens = _tokenize(query)
    if not tokens:
        return []

    scored = []
    for pid, name, words in SEARCH_INDEX:
        total = 0.0
        best = ""
        hit_count = 0
        best_token_score = 0
        for tok in tokens:
            s, b = _score_token(tok, name, words)
            if s > 0:
                hit_count += 1
                total += s * _owner_weight(b, pid)
                if s > best_token_score:
                    best_token_score, best = s, b
        if hit_count == 0:
            continue
        # 多词时要求覆盖度：命中的词越多越靠前；漏词按比例打折
        coverage = hit_count / len(tokens)
        page_score = total * coverage
        scored.append((page_score, pid, name, best or name))

    scored.sort(key=lambda t: -t[0])
    return [(pid, name, hit) for _s, pid, name, hit in scored]


# ---------------- 项级索引层（S2/S3，2026-08-10） ----------------
#
# 页级索引只能把用户送到"某一页",389 个具体开关本身是搜不到的 ——
# 词表里没写的项(「保存FPS设置」「按地图切换预设」)连跳都跳不过去。
# `core/search_index.json` 由 `scripts/build_search_index.py` 离线生成:
# 离屏真建 27 个页面遍历控件树(通道 A) + AST 扫 pages/*.py 字面量(通道 B),
# 两条通道互补(各有一片盲区,实测正好错开)。运行时只读这一个 JSON,零构建开销。

_ITEM_FIELDS = ("page", "text", "card", "tab", "kind")


def _index_path():
    """索引文件路径。打包后在 `_MEIPASS/core/`，源码运行时在本模块同目录。"""
    import os
    import sys

    base = getattr(sys, "_MEIPASS", None)
    if base:
        return os.path.join(base, "core", "search_index.json")
    return os.path.join(os.path.dirname(os.path.abspath(__file__)), "search_index.json")


@lru_cache(maxsize=1)
def _load_item_index() -> Tuple[Tuple[dict, ...], dict]:
    """读项级索引。返回 (items, page_names)。

    ⚠ 缺文件时**降级**成只有页级搜索，而不是抛异常 —— 搜索框绝不能因为一个
    数据文件把主界面拖垮。但降级必须**留痕**：静默降级正是"发布包里少了个文件、
    开发机一切正常"这类假绿的温床，所以这里写一条 warning。
    产物侧另有一道硬门禁（`build_release.verify_onedir_tree` 的正向清单）。
    """
    import json

    path = _index_path()
    try:
        with open(path, "r", encoding="utf-8") as fh:
            data = json.load(fh)
        items = tuple(
            {k: str(it.get(k, "")) for k in _ITEM_FIELDS}
            for it in data.get("items", [])
            if it.get("page") and it.get("text")
        )
        pages = {str(k): str(v) for k, v in (data.get("pages") or {}).items()}
        return items, pages
    except Exception as exc:
        try:
            from core.utils.logger import get_logger

            get_logger("SettingsSearch").warning(
                f"项级搜索索引不可用，已降级为页级搜索: {path} ({exc})"
            )
        except Exception:
            pass
        return (), {}


def item_index_available() -> bool:
    """给判据和冒烟用：项级索引到底装上了没有。"""
    return bool(_load_item_index()[0])


def _score_text(token: str, text: str) -> int:
    """单个查询词对一条**项级文案**的匹配分（含同义词变体）。"""
    best = _score_text_one(token, text)
    if best >= 100:
        return best
    for variant in _query_variants(token)[1:]:
        s = int(_score_text_one(variant, text, allow_phonetic=False) * SYNONYM_PENALTY)
        if s > best:
            best = s
    return best


def _score_text_one(token: str, text: str, allow_phonetic: bool = True) -> int:
    """单个查询词对一条**项级文案**的匹配分。

    分档刻意压在页级之上一点点：项级命中比页级命中更精确，
    同强度下应该排在页面前面（精确命中 100 > 页级关键词精确 90）。
    """
    q = token
    tl = text.lower()
    if q == tl:
        return 100
    if not _long_enough(q):
        return 0        # 单个字母只认精确命中，理由同 _long_enough
    if tl.startswith(q):
        return 78
    if q in tl:
        return 58
    if len(tl) >= 2 and tl in q:
        # 反向子串：用户长句里含这一项的**完整**名字。与页级同一把尺子。
        # 这一档要留在片段覆盖**前面**：它是整词证据，比碎片强，
        # 且不受 _COVER_MIN_RATIO 的门槛约束（「观战静音功能」含「观战静音」，
        # 覆盖只有 4/6，但那是实打实的整项名字）。
        return 44 + min(6, len(tl))
    # 片段覆盖档（S7）：把查询切成能在这条文案里原样找到的片段，
    # 看它们合起来解释了查询的多少。「准心回正」→「启用准心快速回正」靠的就是这里。
    cover = _cover_score(q, tl)
    if cover:
        return cover
    if allow_phonetic and _is_ascii_query(q) and len(q) >= 2:
        for alias in pinyin_aliases(text):
            if alias == q:
                return 76
            if alias.startswith(q):
                return 64
            if len(q) >= 3 and q in alias:
                return 44
        if _ascii_fuzzy_hit(q, text):
            return 36
    return 0


# 单页最多贡献几条项级结果。不设上限的话，搜"音量"会被某一页的十几个
# 同族开关整屏刷掉，别的页一条都露不出来——那比没有项级索引还难用。
MAX_ITEMS_PER_PAGE = 3


def search_items(query: str) -> List[dict]:
    """项级搜索：返回 [{page, text, card, tab, kind, score, hit}]，按相关度排序。"""
    tokens = _tokenize(query)
    items, _pages = _load_item_index()
    if not tokens or not items:
        return []

    scored = []
    for it in items:
        total = 0.0
        hit_count = 0
        best = 0
        for tok in tokens:
            s = _score_text(tok, it["text"])
            if s == 0 and it["card"]:
                # 卡片名只作弱证据：搜"分类音量"时该卡里的项也应该露头，
                # 但不能让卡片名把整卡的项都顶到项名精确命中的前面。
                s = int(_score_text(tok, it["card"]) * 0.45)
            if s > 0:
                hit_count += 1
                total += s
                best = max(best, s)
        if hit_count == 0:
            continue
        coverage = hit_count / len(tokens)
        scored.append((total * coverage, best, it))

    scored.sort(key=lambda t: (-t[0], t[2]["text"]))

    out: List[dict] = []
    per_page: dict = {}
    for score, best, it in scored:
        pid = it["page"]
        if per_page.get(pid, 0) >= MAX_ITEMS_PER_PAGE:
            continue
        per_page[pid] = per_page.get(pid, 0) + 1
        row = dict(it)
        row["score"] = score
        row["hit"] = it["text"] if best >= 36 else it["card"]
        out.append(row)
    return out


def page_name_of(page_id: str) -> str:
    for pid, name, _w in SEARCH_INDEX:
        if pid == page_id:
            return name
    return _load_item_index()[1].get(page_id, page_id)


# 结果面板最多显示多少条。超出部分用户翻不动，也没意义。
MAX_RESULTS = 24


def search_detailed(query: str) -> List[dict]:
    """统一搜索：项级 + 页级合并排序，顶栏下拉直接用这个。

    每条结果:
        kind      "item" | "page"
        page_id   跳转目标页
        page_name 页面显示名
        text      这一条显示的主标题（项名 / 页面名）
        card      项所在卡片（页级结果为空）
        tab       项所在页签（页级结果为空，跳转时要先切到它）
        hit       命中的词（用来告诉用户"为什么搜到它"）
        score     相关度
    """
    tokens = _tokenize(query)
    if not tokens:
        return []

    rows: List[dict] = []
    for it in search_items(query):
        rows.append({
            "kind": "item",
            "page_id": it["page"],
            "page_name": page_name_of(it["page"]),
            "text": it["text"],
            "card": it["card"],
            "tab": it["tab"],
            "hit": it["hit"] or it["text"],
            "score": it["score"],
        })
    seen_item_texts = {(r["page_id"], r["text"]) for r in rows}

    for pid, name, hit in search_pages(query):
        if (pid, name) in seen_item_texts:
            continue  # 项名恰好等于页名时不重复出两条
        rows.append({
            "kind": "page",
            "page_id": pid,
            "page_name": name,
            "text": name,
            "card": "",
            "tab": "",
            "hit": hit,
            "score": _page_score_of(pid, tokens),
        })

    # 同分时项级在前（更精确）
    rows.sort(key=lambda r: (-r["score"], 0 if r["kind"] == "item" else 1, r["text"]))
    return rows[:MAX_RESULTS]


def _page_score_of(page_id: str, tokens: List[str]) -> float:
    for pid, name, words in SEARCH_INDEX:
        if pid != page_id:
            continue
        total = 0.0
        hit_count = 0
        for tok in tokens:
            s, b = _score_token(tok, name, words)
            if s > 0:
                hit_count += 1
                total += s * _owner_weight(b, pid)
        if hit_count == 0:
            return 0.0
        return total * (hit_count / len(tokens))
    return 0.0


def search(query: str) -> List[Tuple[str, str, str]]:
    """兼容旧签名：返回按相关度排序、**按页去重**的 [(page_id, 页面名, 命中词)]。

    2.2.3 起底层换成 `search_detailed()`（项级 + 页级合并），所以现在
    「搜一个词表里没有、但页面上确实存在的开关」也能返回结果 —— 这正是
    这一轮要解决的事。回车跳转仍旧取 `[0]`，行为不变。
    """
    out: List[Tuple[str, str, str]] = []
    seen = set()
    for row in search_detailed(query):
        if row["page_id"] in seen:
            continue
        seen.add(row["page_id"])
        out.append((row["page_id"], row["page_name"], row["hit"]))
    return out

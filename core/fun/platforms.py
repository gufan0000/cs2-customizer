# SPDX-License-Identifier: GPL-3.0-or-later
"""贴屏浏览器的平台预设。

只提供**抖音**和**自定义网址**两项。

2026-08-14 在移动 UA + 9:16 竖窗下逐个实测过其它平台，结论是：各家 App 里
都有沉浸式竖屏流，但**移动网页版**被平台自己阉割，只有抖音在网页端完整开放。
留档如下，省得以后再试一遍：

  抖音        沉浸式竖屏流，自动播放，上滑换下一条          ← 唯一完整可用
  西瓜视频    m.ixigua.com 竖屏信息流，形态接近但要点一下才播
  小红书      /explore 是图文瀑布流；首页会变成 App 下载引导页
  哔哩哔哩    m.bilibili.com 是横屏卡片列表；单视频页是「打开App」引导。
              /story 与 /story/<BV号> 均为 **HTTP 404**，网页端没有沉浸流路由
  快手        m.kuaishou.com 与 kuaishou.com/new-reco 都拿不到内容

所以做成平台下拉没有意义（选了只会失望），不如一个抖音 + 一个自定义。
自定义网址想填上面任何一个都可以，只是别指望有抖音那种效果。
"""

CUSTOM_KEY = "custom"
DEFAULT_PLATFORM = "douyin"

# 抖音登录后，www.douyin.com 会被固定重定向到 /jingxuan（精选网格页），
# 而「推荐」才是竖屏沉浸流。实测（2026-08-14）：
#   · 直接访问 ?recommend=1 或 ?is_from_mobile_home=1&recommend=1 都会被重定向回 /jingxuan
#   · 点一次「推荐」后优雅关闭再重启，照样跳回 /jingxuan —— 它不记这个偏好
#   · 合成鼠标消息（PostMessage）点不动，Chromium 不吃
# 唯一可行的是走调试端点注入 JS 点击，而且窗口隐藏时照样生效，
# 所以可以在预热阶段做掉，用户看到的第一眼就是视频流。
# 按**可见文字**匹配而不是类名/坐标：抖音改版时类名一定会变，文字活得久些。
DOUYIN_FEED_JS = r"""
(() => {
  const wanted = '推荐';
  const nodes = Array.from(document.querySelectorAll('a, div, span, li, p'));
  const hits = nodes.filter(el => {
    if (!el.offsetParent) return false;
    if ((el.textContent || '').trim() !== wanted) return false;
    const r = el.getBoundingClientRect();
    return r.width > 0 && r.height > 0 && r.left < 200;
  });
  if (!hits.length) return 'not-found';
  hits[hits.length - 1].click();
  return 'clicked';
})()
"""

PLATFORM_PRESETS = [
    {
        "key": DEFAULT_PLATFORM,
        "name": "抖音",
        "url": "https://www.douyin.com/",
        "mobile_ua": True,
        "form": "沉浸式竖屏流，自动播放，上滑换下一条",
        # 落地页 URL 里出现这个片段，说明被重定向到了精选网格页，需要切回推荐流
        "wrong_landing": "jingxuan",
        "feed_js": DOUYIN_FEED_JS,
    },
    {
        "key": CUSTOM_KEY,
        "name": "自定义网址",
        "url": "",
        "mobile_ua": True,
        "form": "填什么都行，竖屏短视频类效果最好",
        "wrong_landing": "",
        "feed_js": "",
    },
]

_BY_KEY = {item["key"]: item for item in PLATFORM_PRESETS}
DEFAULT_URL = _BY_KEY[DEFAULT_PLATFORM]["url"]


def get_platform(key):
    """按 key 取预设；认不出的 key 一律回落抖音。"""
    return _BY_KEY.get(str(key or "").strip().lower()) or _BY_KEY[DEFAULT_PLATFORM]


def resolve(key, custom_url="", custom_mobile_ua=True):
    """把 (平台 key, 自定义网址) 解析成实际要用的 (url, mobile_ua)。

    自定义但网址为空时回落抖音 —— 空网址会让浏览器停在空白页，
    死亡时弹出来一片白比不弹更糟。
    """
    preset = get_platform(key)
    if preset["key"] == CUSTOM_KEY:
        url = str(custom_url or "").strip()
        if not url:
            return DEFAULT_URL, True
        return url, bool(custom_mobile_ua)
    return preset["url"], bool(preset["mobile_ua"])

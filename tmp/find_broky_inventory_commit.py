from __future__ import annotations

import html
import json
import re
from pathlib import Path
from urllib.parse import parse_qs, quote, unquote, urlparse

import requests
from bs4 import BeautifulSoup
from PIL import Image

OUT = Path("inventory_source")
IMG = OUT / "search_images"
OUT.mkdir(parents=True, exist_ok=True)
IMG.mkdir(parents=True, exist_ok=True)
UA = "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 Chrome/131 Safari/537.36"
S = requests.Session()
S.headers.update({"User-Agent": UA, "Accept-Language": "en-US,en;q=0.9,zh-CN;q=0.8"})
REPORT: list[str] = []


def log(msg: str) -> None:
    print(msg, flush=True)
    REPORT.append(msg)


def get(url: str, referer: str | None = None) -> requests.Response | None:
    try:
        headers = {"Referer": referer} if referer else None
        r = S.get(url, headers=headers, timeout=25, allow_redirects=True)
        log(f"GET {r.status_code} {len(r.content)} {r.url}")
        return r
    except Exception as exc:
        log(f"GET_ERR {url} {exc!r}")
        return None


queries = [
    "broky Helvijs Saukants Steam profile",
    "broky sold all skins kept signed AK inventory",
    "broky inventory only AK signed teammates",
    "broky Steam inventory AK-47 teammate signatures",
    "broky 库存 卖光 只剩 AK 队友签名",
    "broky 清空库存 队友签名 AK",
]
found: list[str] = []
for i, q in enumerate(queries):
    for engine, url in (
        ("bing", f"https://www.bing.com/search?q={quote(q)}&count=50"),
        ("ddg", f"https://html.duckduckgo.com/html/?q={quote(q)}"),
    ):
        r = get(url)
        if not r:
            continue
        (OUT / f"{engine}_{i}.html").write_bytes(r.content)
        for raw in re.findall(r"https?://[^\"'<> ]+", r.text):
            u = html.unescape(raw).replace("\\/", "/").rstrip("\\")
            try:
                qs = parse_qs(urlparse(u).query)
                if "uddg" in qs:
                    u = unquote(qs["uddg"][0])
            except Exception:
                pass
            if any(host in u for host in ("steamcommunity.com/", "reddit.com/", "hltv.org/", "x.com/", "twitter.com/", "bilibili.com/", "weibo.com/")):
                found.append(u)
found = list(dict.fromkeys(found))
(OUT / "found_urls.txt").write_text("\n".join(found), encoding="utf-8")

candidates = [
    "https://steamcommunity.com/id/broky/",
    "https://steamcommunity.com/id/brokycs/",
    "https://steamcommunity.com/id/brokycsgo/",
    "https://steamcommunity.com/id/brokyfps/",
    "https://steamcommunity.com/id/brokyfaze/",
    "https://steamcommunity.com/id/helvijs/",
    "https://steamcommunity.com/id/helvijssaukants/",
]
for u in found:
    m = re.search(r"https?://steamcommunity\.com/(?:id|profiles)/[^/?#&\" ]+", u)
    if m:
        candidates.append(m.group(0) + "/")
candidates = list(dict.fromkeys(candidates))

best: tuple[int, dict] | None = None
for url in candidates:
    r = get(url)
    if not r or r.status_code >= 400:
        continue
    soup = BeautifulSoup(r.text, "html.parser")
    title = soup.title.get_text(" ", strip=True) if soup.title else ""
    sid = None
    for pat in (
        r'"steamid"\s*:\s*"(\d{17})"',
        r'g_steamID\s*=\s*"(\d{17})"',
        r'/profiles/(\d{17})',
        r'"steamID64"\s*:\s*"(\d{17})"',
    ):
        m = re.search(pat, r.text)
        if m:
            sid = m.group(1)
            break
    log(f"PROFILE {url} sid={sid} title={title!r}")
    if not sid:
        continue
    inv = get(f"https://steamcommunity.com/inventory/{sid}/730/2?l=english&count=5000")
    if not inv or inv.status_code != 200:
        continue
    try:
        data = inv.json()
    except Exception:
        continue
    if not data.get("success"):
        continue
    assets = data.get("assets") or []
    descriptions = data.get("descriptions") or []
    aks = []
    for d in descriptions:
        name = " ".join(str(d.get(k, "")) for k in ("market_hash_name", "name", "type"))
        details = " ".join(x.get("value", "") for x in d.get("descriptions", []) if isinstance(x, dict))
        if "AK-47" in name.upper() or "AK-47" in details.upper():
            aks.append({
                "name": d.get("market_hash_name") or d.get("name"),
                "details": details,
                "icon_url": d.get("icon_url"),
                "classid": d.get("classid"),
                "instanceid": d.get("instanceid"),
            })
    summary = {
        "profile_url": f"https://steamcommunity.com/profiles/{sid}/inventory/",
        "source_profile_url": url,
        "steamid": sid,
        "title": title,
        "asset_count": len(assets),
        "description_count": len(descriptions),
        "ak_items": aks,
    }
    (OUT / f"inventory_{sid}.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    score = (100 if "broky" in (title + url).lower() else 0) + (50 if 0 < len(assets) <= 20 else 0) + (25 if aks else 0)
    if best is None or score > best[0]:
        best = (score, summary)

if best:
    summary = best[1]
    (OUT / "selected_inventory_summary.json").write_text(json.dumps(summary, ensure_ascii=False, indent=2), encoding="utf-8")
    (OUT / "selected_profile_url.txt").write_text(summary["profile_url"], encoding="utf-8")
    for i, ak in enumerate(summary["ak_items"][:5]):
        icon = ak.get("icon_url")
        if not icon:
            continue
        r = get("https://community.cloudflare.steamstatic.com/economy/image/" + icon + "/512fx512f")
        if r and r.status_code == 200:
            (OUT / f"ak_real_{i}.png").write_bytes(r.content)
    log("SELECTED " + summary["profile_url"])
else:
    log("NO_PUBLIC_STEAM_INVENTORY")

# Preserve already-published search images with their original page URLs.
image_queries = [
    "broky Steam inventory signed AK teammates",
    "broky sold inventory AK-47 signatures",
    "broky inventory only one AK",
    "broky 库存 只剩 一把 AK 签名",
    "broky 清空库存 队友签名 AK",
]
records: list[dict] = []
for qi, q in enumerate(image_queries):
    r = get(f"https://www.bing.com/images/search?q={quote(q)}&form=HDRSC2&first=1&count=50")
    if not r:
        continue
    soup = BeautifulSoup(r.text, "html.parser")
    for a in soup.select("a.iusc"):
        raw = a.get("m")
        if not raw:
            continue
        try:
            meta = json.loads(raw)
        except Exception:
            continue
        image_url = meta.get("murl")
        page_url = meta.get("purl")
        title = meta.get("t") or ""
        if not image_url:
            continue
        rr = get(image_url, page_url or "https://www.bing.com/")
        if not rr or rr.status_code != 200 or len(rr.content) < 5000:
            continue
        tmp = IMG / f"{len(records):03d}.bin"
        tmp.write_bytes(rr.content)
        try:
            with Image.open(tmp) as im:
                im = im.convert("RGB")
                if im.width < 320 or im.height < 180:
                    tmp.unlink(missing_ok=True)
                    continue
                im.thumbnail((1920, 1200), Image.Resampling.LANCZOS)
                fn = IMG / f"{len(records):03d}_q{qi}.jpg"
                im.save(fn, quality=90, optimize=True)
            tmp.unlink(missing_ok=True)
        except Exception:
            tmp.unlink(missing_ok=True)
            continue
        records.append({"file": str(fn), "query": q, "image_url": image_url, "page_url": page_url, "title": title})
        if len(records) >= 24:
            break
    if len(records) >= 24:
        break
(OUT / "image_sources.json").write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
REPORT.append(f"SEARCH_IMAGES={len(records)}")
(OUT / "report.txt").write_text("\n".join(REPORT), encoding="utf-8")

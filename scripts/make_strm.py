#!/usr/bin/env python3
"""按 plan.json 生成 strm + nfo，写进 /srv/media

决策（2026-10-19）：
- 认不出集号的 2 个文件（仙逆 SHIXIAN.mkv / 诡秘之主 SPE01）→ 跳过
- 物语系列（14 部合集，需逐部匹配）→ 本轮跳过，第二批处理
- 我真没想重生啊：TMDB 只有 S1=70 → E1-70 归 S01，E71-122 归 S02
- strm 里写 nginx 免认证注入路径，播放时 OpenList 回 302 直连夸克
"""
import html, json, os, urllib.parse
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

PLAN = json.load(open(os.path.join(SCRATCH_DIR, "plan.json")))
OUT = os.environ.get("STRM_OUT", MEDIA_DIR)
BASE = PUBLIC_BASE   # nginx 注入认证的免登录路径（对外域名 + 私有路径前缀）
SKIP_DIRS = {"物语系列"}

def decide(meta, ep, season_raw):
    if season_raw:
        return season_raw, ep
    if meta["kind"] == "movie":
        return 0, ep
    s = {d["n"]: d["eps"] for d in meta["seasons"] if d["eps"]}
    if len(s) <= 1:
        return (list(s)[0] if s else 1), ep
    acc = 0
    for n in sorted(s):
        if ep <= acc + s[n]:
            return n, ep - acc
        acc += s[n]
    return max(s), ep - acc + s[max(s)]

def url_for(src_rel):
    # src_rel 形如 遮天/ZHET/171 4K.mkv
    return BASE + "/" + urllib.parse.quote(URL_PREFIX_AUTOSAVE + "/" + src_rel)

made, skipped = [], []
for r in PLAN:
    meta = r["meta"]
    if r["dir"] in SKIP_DIRS:
        skipped.append((r["dir"], f"{len(r['items'])} 集（整目录跳过）"))
        continue
    if meta["kind"] == "movie":
        title = meta["title"].replace("/", "-")
        d = os.path.join(OUT, MEDIA_MOVIE_DIRNAME, f"{title} ({meta['year']})")
        os.makedirs(d, exist_ok=True)
        src = None
        # 电影只有一个文件，从 items 里找（plan 对电影未存 items，回退扫描）
        for cand in r.get("items") or []:
            src = cand
        if not src:
            skipped.append((r["dir"], "电影：plan 里没记源文件"))
            continue
        base = os.path.join(d, f"{title} ({meta['year']})")
        with open(base + ".strm", "w") as f:
            f.write(url_for(src["src"]) + "\n")
        with open(base + ".nfo", "w") as f:
            f.write(f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<movie>\n  <title>{html.escape(title)}</title>\n  <year>{meta['year']}</year>\n  <tmdbid>{meta['id']}</tmdbid>\n</movie>\n")
        made.append(("电影", title, 1))
        continue
    for it in r["items"]:
        sn, en = decide(meta, it["ep"], it["season_raw"])
        title = meta["title"].replace("/", "-")
        d = os.path.join(OUT, MEDIA_TV_DIRNAME, f"{title} ({meta['year']})", f"Season {sn:02d}")
        os.makedirs(d, exist_ok=True)
        fname = f"{title} S{sn:02d}E{en:02d}"
        with open(os.path.join(d, fname + ".strm"), "w") as f:
            f.write(url_for(it["src"]) + "\n")
        with open(os.path.join(d, fname + ".nfo"), "w") as f:
            f.write(f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<episodedetails>\n  <season>{sn}</season>\n  <episode>{en}</episode>\n  <showtitle>{html.escape(title)}</showtitle>\n  <uniqueid type=\"tmdb\" default=\"true\">{meta['id']}</uniqueid>\n</episodedetails>\n")
    made.append(("剧集", meta["title"], len(r["items"])))

# 剧集级 tvshow.nfo（让 Emby/Jellyfin 直接锁到条目）
for r in PLAN:
    meta = r["meta"]
    if meta["kind"] != "tv" or r["dir"] in SKIP_DIRS:
        continue
    title = meta["title"].replace("/", "-")
    d = os.path.join(OUT, MEDIA_TV_DIRNAME, f"{title} ({meta['year']})")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, "tvshow.nfo"), "w") as f:
        f.write(f"<?xml version=\"1.0\" encoding=\"UTF-8\"?>\n<tvshow>\n  <title>{html.escape(title)}</title>\n  <year>{meta['year']}</year>\n  <uniqueid type=\"tmdb\" default=\"true\">{meta['id']}</uniqueid>\n</tvshow>\n")

total = sum(n for _, _, n in made)
print(f"生成完成：{len(made)} 个条目 / {total} 集")
for kind, title, n in made:
    print(f"  {kind} {title}: {n} 集")
print("\n跳过：")
for d, why in skipped:
    print(f"  {d}: {why}")

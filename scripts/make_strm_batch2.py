#!/usr/bin/env python3
"""第二批：物语系列（TMDB 单一剧 + 分部→季映射）+ 仙逆剧场版"""
import html, json, os, re, urllib.parse, urllib.request
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

OL = OL_URL
OUT = os.environ.get("STRM_OUT", MEDIA_DIR)
BASE = PUBLIC_BASE
VID = (".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".rmvb", ".flv", ".wmv", ".mov", ".mpg")

def login():
    b = json.dumps({"username": OL_USER, "password": OL_PASS}).encode()
    r = urllib.request.Request(OL + "/api/auth/login", data=b,
        headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=20))["data"]["token"]

TOK = login()
def ls(path):
    b = json.dumps({"path": path, "password": "", "page": 1, "per_page": 500,
                    "refresh": False}).encode()
    r = urllib.request.Request(OL + "/api/fs/list", data=b, method="POST",
        headers={"Content-Type": "application/json", "Authorization": TOK})
    return (json.load(urllib.request.urlopen(r, timeout=40)).get("data") or {}).get("content") or []

def url_for(rel):
    return BASE + "/" + urllib.parse.quote(URL_PREFIX_AUTOSAVE + "/" + rel)

# TMDB「物语系列」= tv/46195，5 季：S1 化物語(12) S2 偽物語(11) S3 猫黑+猫白+囮+鬼+恋(23) S4 終物語(12) S5 傾+花+憑(15)
# 本地多出来的部，按顺序放到 S6/S7/S8（TMDB 无数据，能播、无剧集元数据）
SHOW = ("物语系列", 2009, 46195)
PLAN = [
    ("1.化物语",   1, 0,  "化物語"),
    ("2.伪物语",   2, 0,  "偽物語"),
    ("3.猫物语 黑", 3, 0,  "猫物語 黑"),
    ("4.猫物语 白", 3, 4,  "猫物語 白"),
    ("5.囮物語",   3, 9,  "囮物語"),
    ("6.鬼物语",   3, 14, "鬼物語"),
    ("7.恋物语",   3, 18, "恋物語"),
    ("11.终物语",  4, 0,  "終物語"),
    ("8.倾物语",   5, 0,  "傾物語"),
    ("9.花物语",   5, 5,  "花物語"),
    ("10.凭物语",  5, 10, "憑物語"),
    ("12.厉物语",  6, 0,  "暦物語"),
    ("14.终物语 下", 7, 0, "終物語 下"),
    ("15.续 终物语", 8, 0, "続・終物語"),
]
PREFIX = "物语系列/物语系列14部合集·4K高画质版/"
root = SRC_AUTOSAVE + "/" + PREFIX.rstrip("/")
name, year, tid = SHOW
made = 0
for sub, season, offset, jp in PLAN:
    eps = [it for it in ls(root + "/" + sub) if not it.get("is_dir") and it["name"].lower().endswith(VID)]
    def num(fn):
        m = re.findall(r"(\d{1,3})(?=\D*$)", fn)
        return int(m[0]) if m else None
    eps = [(num(e["name"]) or 0, e) for e in eps]
    eps.sort()
    d = os.path.join(OUT, MEDIA_TV_DIRNAME, f"{name} ({year})", f"Season {season:02d}")
    os.makedirs(d, exist_ok=True)
    for ep, e in eps:
        n = ep + offset if ep else offset + 1
        fn = f"{name} S{season:02d}E{n:02d}"
        rel = PREFIX + sub + "/" + e["name"]
        with open(os.path.join(d, fn + ".strm"), "w") as f:
            f.write(url_for(rel) + "\n")
        with open(os.path.join(d, fn + ".nfo"), "w") as f:
            f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<episodedetails>\n  <title>{html.escape(jp)} {ep:02d}</title>\n'
                    f'  <season>{season}</season>\n  <episode>{n}</episode>\n  <showtitle>{html.escape(name)}</showtitle>\n'
                    f'  <uniqueid type="tmdb" default="true">{tid}</uniqueid>\n</episodedetails>\n')
        made += 1
    print(f"  {sub:>12} → S{season:02d} {len(eps)} 集 (E{offset+1:02d}起)")

# 剧集级 nfo
d = os.path.join(OUT, MEDIA_TV_DIRNAME, f"{name} ({year})")
with open(os.path.join(d, "tvshow.nfo"), "w") as f:
    f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<tvshow>\n  <title>{html.escape(name)}</title>\n'
            f'  <year>{year}</year>\n  <uniqueid type="tmdb" default="true">{tid}</uniqueid>\n</tvshow>\n')

# 伤物语三部 → 电影库
MOVIES = [("13.【4K_Super】伤物语 I 铁血篇.mkv", "伤物语1：铁血篇", 2016, 357786),
          ("13.【4K_Super】伤物语 II 热血篇.mkv", "伤物语2：热血篇", 2016, 362584),
          ("13.【4K_Super】伤物语 III 冷血篇.mkv", "伤物语3：冷血篇", 2017, 362585)]
sub = "13.伤物语"
for fn, title, yr, mid in MOVIES:
    t = title.replace("/", "-")
    d = os.path.join(OUT, MEDIA_MOVIE_DIRNAME, f"{t} ({yr})")
    os.makedirs(d, exist_ok=True)
    with open(os.path.join(d, f"{t} ({yr}).strm"), "w") as f:
        f.write(url_for(PREFIX + sub + "/" + fn) + "\n")
    with open(os.path.join(d, f"{t} ({yr}).nfo"), "w") as f:
        f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<movie>\n  <title>{html.escape(t)}</title>\n'
                f'  <year>{yr}</year>\n  <tmdbid>{mid}</tmdbid>\n</movie>\n')
print("  13.伤物语 → 电影库 3 部")

# 仙逆剧场版：弑仙之战
t = "仙逆剧场版：弑仙之战"
d = os.path.join(OUT, MEDIA_MOVIE_DIRNAME, f"{t} (2026)")
os.makedirs(d, exist_ok=True)
with open(os.path.join(d, f"{t} (2026).strm"), "w") as f:
    f.write(url_for("仙逆/xiann/弑仙之战/SHIXIAN.mkv") + "\n")
with open(os.path.join(d, f"{t} (2026).nfo"), "w") as f:
    f.write(f'<?xml version="1.0" encoding="UTF-8"?>\n<movie>\n  <title>{html.escape(t)}</title>\n'
            f'  <year>2026</year>\n  <tmdbid>1599191</tmdbid>\n</movie>\n')
print("  仙逆/xiann/弑仙之战 → 电影库 1 部")
print(f"\n物语系列共生成 {made} 集")

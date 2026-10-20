#!/usr/bin/env python3
"""第三来源：/夸克/来自：Hermes/自动转存 —— 官方 skill 的 saveas 落盘位置
（夸克官方 CLI 的 --to-pdir-path 是相对它自己的「来自：Hermes」沙箱，不是网盘根）

当前映射（人工确认，2026-10-19）：生化危机六部 4K
  1 生化危机 2002 -> movie/1576
  2 生化危机2：启示录 2004 -> movie/1577
  3 生化危机3：灭绝 2007 -> movie/7737
  4 生化危机4：战神再生 2010 -> movie/35791
  5 生化危机5：惩罚 2012 -> movie/71679
  6 生化危机6：终章 2016 -> movie/173897
"""
import html, json, os, urllib.parse, urllib.request
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

OL = OL_URL
OUT = os.environ.get("STRM_OUT", MEDIA_DIR)
BASE = PUBLIC_BASE
SRC = SRC_AUTOSAVE
PREFIX = URL_PREFIX_AUTOSAVE
VID = (".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".rmvb", ".flv", ".wmv", ".mov", ".mpg")

RULES = [
    {"match": "生化危机6部4K", "movies": [
        ("生化危机", 2002, 1576, ("resident.evil.2002",)),
        ("生化危机2：启示录", 2004, 1577, ("apocalypse",)),
        ("生化危机3：灭绝", 2007, 7737, ("extinction",)),
        ("生化危机4：战神再生", 2010, 35791, ("afterlife",)),
        ("生化危机5：惩罚", 2012, 71679, ("retribution",)),
        ("生化危机6：终章", 2016, 173897, ("final.chapter", "final chapter")),
    ]},
    # 食贫道「人间喜剧」系列 7 部（2026-10-20 加入，TMDB 条目按片名+上映日核对）
    {"match": "食贫道人间喜剧", "movies": [
        ("迷失东京", 2023, 1212407, ("迷失东京",)),
        ("迦南孤儿", 2024, 1259822, ("迦南孤儿",)),
        ("何以当归", 2024, 1263063, ("何以当归",)),
        ("神鬼传奇（上）", 2024, 1312697, ("【上】",)),
        ("神鬼传奇（下）", 2024, 1323380, ("【下】",)),
        ("神佑之地", 2024, 1357814, ("神佑之地",)),
        ("不愈之殇", 2024, 1378694, ("不愈之殇",)),
    ]},
]

# tmdb_auto_map.py 自动配好的电影映射（人工 RULES 优先，同目录不重复）
AUTO_RULES = os.path.join(STATE_DIR, "movie_rules_auto.json")
if os.path.exists(AUTO_RULES):
    try:
        for _d, _movies in json.load(open(AUTO_RULES)).items():
            if not any(r["match"] in _d for r in RULES):
                RULES.append({"match": _d,
                              "movies": [(m[0], m[1], m[2], tuple(m[3])) for m in _movies]})
    except Exception:
        pass


def login():
    b = json.dumps({"username": OL_USER, "password": OL_PASS}).encode()
    r = urllib.request.Request(OL + "/api/auth/login", data=b,
        headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r))["data"]["token"]


TOK = login()


def ls(p):
    b = json.dumps({"path": p, "password": "", "page": 1, "per_page": 400, "refresh": False}).encode()
    r = urllib.request.Request(OL + "/api/fs/list", data=b, method="POST",
        headers={"Content-Type": "application/json", "Authorization": TOK})
    return (json.load(urllib.request.urlopen(r, timeout=40)).get("data") or {}).get("content") or []


def walk(path, depth=0, out=None):
    if out is None:
        out = []
    for it in ls(path):
        p = path.rstrip("/") + "/" + it["name"]
        if it.get("is_dir") and depth < 3:
            walk(p, depth + 1, out)
        elif not it.get("is_dir"):
            out.append({"rel": p[len(SRC) + 1:], "name": it["name"], "size": it.get("size") or 0})
    return out


def url_for(rel):
    return BASE + "/" + urllib.parse.quote(PREFIX + "/" + rel)


made = {}
for d in [it["name"] for it in ls(SRC) if it.get("is_dir")]:
    rule = next((r for r in RULES if r["match"] in d), None)
    if not rule:
        continue
    files = [f for f in walk(SRC + "/" + d) if f["name"].lower().endswith(VID)]
    kept = 0
    for title, year, mid, keys in rule["movies"]:
        cands = [f for f in files if any(k in f["name"].lower() for k in keys)]
        if not cands:
            print(f"  ⚠ 未找到: {title}")
            continue
        best = max(cands, key=lambda x: x["size"])
        t = title.replace("/", "-")
        sub = os.path.join(OUT, MEDIA_MOVIE_DIRNAME, f"{t} ({year})")
        os.makedirs(sub, exist_ok=True)
        open(os.path.join(sub, f"{t} ({year}).strm"), "w").write(url_for(best["rel"]) + "\n")
        open(os.path.join(sub, f"{t} ({year}).nfo"), "w").write(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<movie>\n  <title>{html.escape(t)}</title>\n'
            f'  <year>{year}</year>\n  <tmdbid>{mid}</tmdbid>\n</movie>\n')
        kept += 1
    made[d] = kept

if made:
    print("来自：Hermes 生成完成")
    for d, n in made.items():
        print(f"  {d[:40]}: {n} 条")

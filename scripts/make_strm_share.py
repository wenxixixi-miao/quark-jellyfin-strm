#!/usr/bin/env python3
"""把「来自：分享」目录也纳入媒体库（第二来源）

映射规则（人工确认过，2026-10-19）：
  火影忍者 (2002) 4K      -> E1-220 属「火影忍者」46260（52/52/54/62），E221-720 属「疾风传」31910（20 季累计 500）
  L-老Y记                 -> 老友记 1668（10 季累计 228）
  H-好想告诉你【完结】2024  -> 好想告诉你 68854（25/12/5）
  爱、死亡和机器人 4季全     -> 86831（18/8/9/10）
  命运石之门 2季全 + 剧场    -> 42509(24) + 78102(23)，剧场版另挂 movie/225745
  大明王朝1566             -> 68034（46）
  终末的女武神              -> 114868
  新世纪福音战士EVA合集      -> 890（26 集），其余按关键词认电影
  《EVA 新剧场版》四部       -> 电影 序15137 / 破22843 / Q75629 / 终283566
  寂静岭 Silent Hill       -> 电影 588
"""
import html, json, os, re, urllib.parse, urllib.request
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

OL = OL_URL
OUT = os.environ.get("STRM_OUT", MEDIA_DIR)
BASE = PUBLIC_BASE
SRC = SRC_SHARE
VID = (".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".rmvb", ".flv", ".wmv", ".mov", ".mpg")
JUNK = ("sample", "预告", "花絮", "海报", "fanart", "poster", "trailer", "teaser", "截图", "和谐", "补")

# dir 片段 -> 规则
RULES = [
    {"match": "火影忍者", "mode": "cumulative",
     "shows": [("火影忍者", 2002, 46260, [52, 52, 54, 62]),
               ("火影忍者：疾风传", 2007, 31910, [32, 21, 18, 17, 24, 31, 8, 24, 21, 25, 21, 33, 20, 25, 28, 13, 11, 21, 20, 87])]},
    {"match": "老Y记", "mode": "cumulative",
     "shows": [("老友记", 1994, 1668, [24, 24, 25, 23, 23, 23, 23, 23, 23, 17])]},
    {"match": "好想告诉你", "mode": "cumulative",
     "shows": [("好想告诉你", 2009, 68854, [25, 12, 5])]},
    {"match": "爱、死亡和机器人", "mode": "cumulative",
     "shows": [("爱，死亡和机器人", 2019, 86831, [18, 8, 9, 10])]},
    {"match": "命运石之门", "mode": "subs",
     "subs": [("S1(2011", "tv", "命运石之门", 2011, 42509, 1),
              ("0 S2(2018", "tv", "命运石之门 0", 2018, 78102, 1),
              ("剧场版", "movie", "剧场版 命运石之门：负荷领域的既视感", 2013, 225745, 0)],
     "skip_subs": ("认知计算", "23β", "23B")},
    {"match": "大明王朝", "mode": "cumulative",
     "shows": [("大明王朝1566", 2007, 68034, [46])]},
    {"match": "终末的女武神", "mode": "cumulative",
     "shows": [("终末的女武神", 2021, 114868, [12, 15, 15])]},
    {"match": "新世纪福音战士EVA合集", "mode": "cumulative",
     "shows": [("新世纪福音战士", 1995, 890, [26])]},
    {"match": "EVA 新剧场版", "mode": "movies_only",
     "movies": [("福音战士新剧场版：序", 2007, 15137, ("序",)),
                ("福音战士新剧场版：破", 2009, 22843, ("破",)),
                ("福音战士新剧场版：Q", 2012, 75629, ("Q", "Ｑ", "急")),
                ("福音战士新剧场版：终", 2021, 283566, ("终", "終"))]},
    {"match": "寂静岭", "mode": "movies_only",
     "movies": [("寂静岭", 2006, 588, ("寂静岭", "Silent"))]},
]

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
    if out is None: out = []
    for it in ls(path):
        p = path.rstrip("/") + "/" + it["name"]
        if it.get("is_dir") and depth < 3:
            walk(p, depth + 1, out)
        elif not it.get("is_dir"):
            out.append({"rel": p.split("/" + SHARE_DIR + "/", 1)[-1], "name": it["name"], "size": it.get("size") or 0})
    return out

def season_of(rel, fname):
    """从相对路径（第X季 / S2 / Season 2）或文件名里的 SxxExx 识别季号"""
    m = re.search(r"(?i)s(\d{1,2})[._ ]?e(?:p)?\s*0*(\d{1,3})", fname)
    if m:
        return int(m.group(1)), int(m.group(2))
    for seg in rel.split("/")[:-1]:
        for pat in (r"第\s*(\d{1,2})\s*季", r"(?i)season\s*(\d{1,2})", r"^[Ss](\d{1,2})$", r"^(\d{1,2})\s*季"):
            mm = re.search(pat, seg)
            if mm:
                sn = int(mm.group(1))
                if 0 < sn <= 30:
                    return sn, None
    return None, None


def ep_of(name):
    m = re.search(r"(?i)s(\d{1,2})\s*[._ ]?e(?:p)?\s*0*(\d{1,3})", name)
    if m: return int(m.group(1)), int(m.group(2))
    base = re.sub(r"(?:\.(?:mp4|mkv|avi|ts|rmvb|flv|wmv|mov|m2ts))+$", "", name, flags=re.I)
    base = re.sub(r"(?i)(?:4k\w*|8k\w*|\d{3,4}p\w*|hdr\w*|web-?dl|bluray|hevc|h26[45]|x26[45]|\d+bit|ma10p|hi10p|aac|dts|flac)", " ", base)
    base = re.sub(r"\d{3,4}\s*[x×]\s*\d{3,4}", " ", base)     # 1920x1080
    base = re.sub(r"\d+(\.\d+)?\s*fps", " ", base)            # 23.976fps
    m = re.search(r"(?i)\bEP?\.?\s*0*(\d{1,4})(?!\d)", base)
    if m: return None, int(m.group(1))
    base = re.sub(r"(?<![\d])(?:19|20)\d{2}(?![\d])", " ", base)
    m = re.search(r"第\s*0*(\d{1,4})\s*[集话話]", base)
    if m: return None, int(m.group(1))
    nums = re.findall(r"\d{1,4}", base)
    for n in reversed(nums):
        v = int(n)
        if 0 < v < 3000:
            return None, v
    return None, None

def url_for(rel):
    return BASE + "/" + urllib.parse.quote(URL_PREFIX_SHARE + "/" + rel)

def split_seasons(ep, structure):
    """绝对集号 -> (季序号, 该季内集号)"""
    acc = 0
    for i, cnt in enumerate(structure, start=1):
        if ep <= acc + cnt:
            return i, ep - acc
        acc += cnt
    return len(structure), ep - acc

made = {}
_unknown_share = []
for d in [it["name"] for it in ls(SRC) if it.get("is_dir")]:
    rule = next((r for r in RULES if r["match"] in d), None)
    if not rule:
        print(f"  ⚠ 无规则，跳过: {d}")
        _unknown_share.append(d)
        continue
    files = [f for f in walk(SRC + "/" + d)
             if f["name"].lower().endswith(VID) and not any(k in f["name"].lower() for k in JUNK)]
    kept = 0
    if rule["mode"] == "subs":
        best = {}
        for f in files:
            if any(k in f["rel"] for k in rule.get("skip_subs", ())):
                continue
            hit = next((x for x in rule["subs"] if x[0] in f["rel"]), None)
            if not hit:
                continue
            _, kind, title, year, tid, season = hit
            if kind == "movie":
                key = ("movie", tid)
                if key not in best or f["size"] > best[key]["size"]:
                    best[key] = dict(f, kind="movie", title=title, year=year, tid=tid)
            else:
                s2, ep = season_of(f["rel"], f["name"])
                _, ep2 = ep_of(f["name"])
                ep = ep2 or ep
                if not ep:
                    continue
                key = ("tv", tid, season, ep)
                if key not in best or f["size"] > best[key]["size"]:
                    best[key] = dict(f, kind="tv", title=title, year=year, tid=tid, sn=season, en=ep)
        for k, v in best.items():
            if v["kind"] == "movie":
                t = v["title"].replace("/", "-")
                sub = os.path.join(OUT, MEDIA_MOVIE_DIRNAME, f"{t} ({v['year']})")
                os.makedirs(sub, exist_ok=True)
                open(os.path.join(sub, f"{t} ({v['year']}).strm"), "w").write(url_for(v["rel"]) + "\n")
                open(os.path.join(sub, f"{t} ({v['year']}).nfo"), "w").write(
                    f'<?xml version="1.0" encoding="UTF-8"?>\n<movie>\n  <title>{html.escape(t)}</title>\n'
                    f'  <year>{v["year"]}</year>\n  <tmdbid>{v["tid"]}</tmdbid>\n</movie>\n')
            else:
                t = v["title"].replace("/", "-")
                sub = os.path.join(OUT, MEDIA_TV_DIRNAME, f"{t} ({v['year']})", f"Season {v['sn']:02d}")
                os.makedirs(sub, exist_ok=True)
                fn = f"{t} S{v['sn']:02d}E{v['en']:02d}"
                open(os.path.join(sub, fn + ".strm"), "w").write(url_for(v["rel"]) + "\n")
                open(os.path.join(sub, fn + ".nfo"), "w").write(
                    f'<?xml version="1.0" encoding="UTF-8"?>\n<episodedetails>\n  <season>{v["sn"]}</season>\n'
                    f'  <episode>{v["en"]}</episode>\n  <showtitle>{html.escape(t)}</showtitle>\n'
                    f'  <uniqueid type="tmdb" default="true">{v["tid"]}</uniqueid>\n</episodedetails>\n')
            kept += 1
        made[d] = kept
        continue
    if rule["mode"] == "movies_only":
        for title, year, mid, keys in rule.get("movies", []):
            cands = [f for f in files if any(k.lower() in f["name"].lower() for k in keys)]
            if not cands:
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
        continue
    # cumulative：按绝对集号在多部剧/多季之间分配
    shows = rule["shows"]
    ranges, acc = [], 0
    for name, year, tid, structure in shows:
        total = sum(structure)
        ranges.append((name, year, tid, structure, acc + 1, acc + total))
        acc += total
    best = {}
    for f in files:
        det_sn, det_ep = season_of(f["rel"], f["name"])
        _, ep = ep_of(f["name"])
        if det_ep:
            ep = det_ep
        if not ep:
            continue
        if det_sn and len(shows) > 1:
            # 多部剧：季号 = 第几部（如 命运石之门 S1/S2）
            if det_sn > len(shows):
                continue
            name, year, tid, structure = shows[det_sn - 1]
            tgt = (name, year, tid, structure, 0, 0)
            sn, en = (1 if len(structure) == 1 else det_sn), ep
            if len(structure) > 1 and det_sn > 1:
                sn, en = 1, ep
        elif det_sn and len(shows) == 1:
            # 单部剧：季号直接对应 TMDB 季
            name, year, tid, structure = shows[0]
            tgt = (name, year, tid, structure, 0, 0)
            sn, en = det_sn, ep
        else:
            tgt = next((r for r in ranges if r[4] <= ep <= r[5]), None)
            if not tgt:
                continue
            offset = ep - tgt[4]
            sn, en = split_seasons(offset + 1, tgt[3])
        key = (tgt[2], sn, en)
        if key not in best or f["size"] > best[key]["size"]:
            best[key] = dict(f, sn=sn, en=en, title=tgt[0], year=tgt[1], tid=tgt[2])
    for (tid, sn, en), v in best.items():
        t = v["title"].replace("/", "-")
        sub = os.path.join(OUT, MEDIA_TV_DIRNAME, f"{t} ({v['year']})", f"Season {sn:02d}")
        os.makedirs(sub, exist_ok=True)
        fn = f"{t} S{sn:02d}E{en:02d}"
        open(os.path.join(sub, fn + ".strm"), "w").write(url_for(v["rel"]) + "\n")
        open(os.path.join(sub, fn + ".nfo"), "w").write(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<episodedetails>\n  <season>{sn}</season>\n'
            f'  <episode>{en}</episode>\n  <showtitle>{html.escape(t)}</showtitle>\n'
            f'  <uniqueid type="tmdb" default="true">{tid}</uniqueid>\n</episodedetails>\n')
        kept += 1
    # 剧场版
    for title, year, mid, keys in rule.get("movies", []):
        cands = [f for f in files if any(k.lower() in f["name"].lower() for k in keys)]
        if not cands:
            continue
        b2 = max(cands, key=lambda x: x["size"])
        t = title.replace("/", "-")
        sub = os.path.join(OUT, MEDIA_MOVIE_DIRNAME, f"{t} ({year})")
        os.makedirs(sub, exist_ok=True)
        open(os.path.join(sub, f"{t} ({year}).strm"), "w").write(url_for(b2["rel"]) + "\n")
        open(os.path.join(sub, f"{t} ({year}).nfo"), "w").write(
            f'<?xml version="1.0" encoding="UTF-8"?>\n<movie>\n  <title>{html.escape(t)}</title>\n'
            f'  <year>{year}</year>\n  <tmdbid>{mid}</tmdbid>\n</movie>\n')
        kept += 1
    made[d] = kept

# 剧集级 nfo
seen = set()
for d, n in made.items():
    pass
for root, dirs, fs in os.walk(os.path.join(OUT, MEDIA_TV_DIRNAME)):
    if os.path.basename(os.path.dirname(root)) != "剧集":
        continue
    # root 是剧目录
for name in sorted(os.listdir(os.path.join(OUT, MEDIA_TV_DIRNAME))):
    p = os.path.join(OUT, MEDIA_TV_DIRNAME, name)
    if not os.path.isdir(p) or name in seen:
        continue
    seen.add(name)
    m = re.search(r"\((\d{4})\)$", name)
    year = m.group(1) if m else ""
    nfo = os.path.join(p, "tvshow.nfo")
    if not os.path.exists(nfo):
        # 从任一集 nfo 里取 tmdbid
        tid = ""
        for r2, _, fs2 in os.walk(p):
            for f in fs2:
                if f.endswith(".nfo") and f != "tvshow.nfo":
                    mm = re.search(r"<uniqueid[^>]*>(\d+)<", open(os.path.join(r2, f)).read())
                    if mm: tid = mm.group(1)
                    break
            if tid: break
        if tid:
            open(nfo, "w").write(f'<?xml version="1.0" encoding="UTF-8"?>\n<tvshow>\n'
                f'  <title>{html.escape(name[:name.rfind("(")].strip())}</title>\n  <year>{year}</year>\n'
                f'  <uniqueid type="tmdb" default="true">{tid}</uniqueid>\n</tvshow>\n')

try:
    json.dump({"unknown": _unknown_share}, open("/tmp/unknown_share_dirs.json", "w"), ensure_ascii=False)
except Exception:
    pass

print("来自：分享 生成完成")
for d, n in made.items():
    print(f"  {d[:40]}: {n} 条")
print(f"合计 {sum(made.values())} 条")

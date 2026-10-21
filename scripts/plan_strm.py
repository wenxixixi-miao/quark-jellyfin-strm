#!/usr/bin/env python3
"""生成计划：扫转存目录 -> 规范化命名清单（dry-run，不写文件）"""
import json, os, re, time, urllib.request
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

REFRESH = os.environ.get("STRM_REFRESH", "") == "1"   # 1=让 OpenList 直接找夸克要最新列表
SLEEP = float(os.environ.get("STRM_SLEEP", "0.25"))   # 每次列目录之间停一下，防风控
MIN_MB = float(os.environ.get("STRM_MIN_MB", "3"))   # 绝对下限：小于这个当垃圾
DROP_RATIO = float(os.environ.get("STRM_DROP_RATIO", "0.08"))  # 比该剧中位数小到这个比例，当样片
JUNK = ("sample", "预告", "花絮", "花絮", "海报", "fanart", "poster", "trailer", "teaser", "截图", "字幕组招募")

OL = OL_URL
VID = (".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".rmvb", ".flv", ".wmv", ".mov", ".mpg")
MULTI_WORK = {"物语系列"}
_FINAL = os.path.join(STATE_DIR, "tmdb_final.json")
if not os.path.exists(_FINAL):
    raise SystemExit(f"找不到 TMDB 映射表 {_FINAL}")
FINAL = json.load(open(_FINAL))

def login():
    b = json.dumps({"username": OL_USER, "password": OL_PASS}).encode()
    r = urllib.request.Request(OL + "/api/auth/login", data=b,
        headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=20))["data"]["token"]

TOK = login()
def ls(path):
    time.sleep(SLEEP)                 # 每次列目录之间停一下，降低夸克风控概率
    b = json.dumps({"path": path, "password": "", "page": 1, "per_page": 300,
                    "refresh": REFRESH}).encode()
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
            out.append({"path": p, "rel": p.split("/" + AUTOSAVE_DIR + "/", 1)[-1],
                        "name": it["name"], "size": it.get("size") or 0})
    return out

def season_ep(name):
    """优先读文件自带的 SxxExx / S5E215"""
    m = re.search(r"(?i)s(\d{1,2})\s*[._ ]?e(?:p)?\s*0*(\d{1,3})", name)
    if m: return int(m.group(1)), int(m.group(2))
    return None, None

def ep_of(name):
    base = re.sub(r"(?:\.(?:mp4|mkv|avi|ts|rmvb|flv|wmv|mov|m2ts))+$", "", name, flags=re.I)
    base = re.sub(r"(?i)(?:4k\w*|8k\w*|\d{3,4}p\w*|hdr\w*|web-?dl|bluray|hevc|h26[45]|10bit|aac|dts|x26[45])", " ", base)
    base = re.sub(r"\(\s*\d+\s*\)|（\s*\d+\s*）", " ", base)
    base = re.sub(r"(?<![\d])(?:19|20)\d{2}(?![\d])", " ", base)
    base2 = base.replace("久", "9").replace("〇", "0").replace("零", "0")
    m = re.match(r"^\s*(\d)((?:[！!@#&％%＊*·、。．.\-_~¥￥§●★→×+\s][\d])+)\s*$", base2)
    if m:
        j = re.sub(r"\D", "", base2)
        if len(j) <= 4 and 0 < int(j) < 3000: return int(j)
    base = re.sub(r"[！!@#\$&％%＊*·、,，\s_\.\-—~¥￥§●★→×（）()\[\]【】]+", " ", base2)
    # 形如 "1 6 3" 的散数字（发布者用符号把集号拆开）→ 拼成 163
    if re.fullmatch(r"\s*(?:\d\s+){1,3}\d\s*", base):
        j = re.sub(r"\D", "", base)
        if 0 < int(j) < 3000:
            return int(j)
    # 名字里有多个数字且没有 EP/第N集 标记时，集号通常在最后
    toks = re.findall(r"\d{1,4}", base)
    if len(toks) >= 2 and not re.search(r"(?i)e(?:p|pisode)?\s*\d|第\s*\d+\s*[集话話]", base):
        if 0 < int(toks[-1]) < 3000:
            return int(toks[-1])
    for p in [r"(?i)(?:^|[^a-z])e(?:p|pisode)?\.?\s*0*(\d{1,4})(?!\d)",
              r"第\s*0*(\d{1,4})\s*[集话話]", r"\[0*(\d{1,4})(?:v\d)?\]",
              r"^\s*0*(\d{1,4})(?=[\s._\-]|$)", r"[\s._\-]0*(\d{1,4})(?=[\s._\-]|$)"]:
        mm = re.search(p, base)
        if mm and 0 < int(mm.group(1)) < 3000: return int(mm.group(1))
    return None

def decide(meta, ep, season_raw):
    """定最终 (季, 集)

    1) 文件自带季号且该季集数容得下这个集号 → 直接用
    2) 否则若最大季容得下这个集号（发布组常用连续编号） → 归最大季
    3) 否则按各季集数累计挡位映射
    """
    s = {d["n"]: d["eps"] for d in meta["seasons"] if d["eps"]}
    if not s:
        return (season_raw or 1), ep
    if len(s) == 1:
        n = list(s)[0]
        return n, ep
    if season_raw and season_raw in s and ep <= s[season_raw]:
        return season_raw, ep
    mx = max(s)
    if ep <= s[mx]:
        return mx, ep
    acc = 0
    for n in sorted(s):
        if ep <= acc + s[n]:
            return n, ep - acc
        acc += s[n]
    return mx, ep - acc + s[mx]


# 每部的处理策略：优先子目录（画质最好）、分季方式
def plan_dir(dirname, meta):
    files = []
    for f in walk(SRC_AUTOSAVE + "/" + dirname):
        n = f["name"].lower()
        if not n.endswith(VID):
            continue
        if any(k in n for k in JUNK):          # 预告/花絮/样片之类
            continue
        if f["size"] and f["size"] < MIN_MB * 1048576:
            continue
        files.append(f)
    # 自适应去样片：跟该剧自己的中位体积比，太小的才丢（短剧不会被整部干掉）
    sizes = sorted(x["size"] for x in files if x["size"])
    if len(sizes) >= 5:
        median = sizes[len(sizes) // 2]
        floor = max(MIN_MB * 1048576, median * DROP_RATIO)
        files = [x for x in files if not x["size"] or x["size"] >= floor]
    items, unresolved = [], []
    for f in files:
        s, e = season_ep(f["name"])
        ep = e if e else ep_of(f["name"])
        if not ep:
            unresolved.append(f)
            continue
        items.append({"src": f["rel"], "size": f["size"], "season_raw": s, "ep": ep,
                      "subdir": f["rel"].rsplit("/", 1)[0] if "/" in f["rel"] else ""})
    # 若目录里带季号的文件都指向同一季，则没季号的也归到那一季（如诛仙全是 S04、斗破是 S05）
    raws = {it["season_raw"] for it in items if it["season_raw"]}
    default_season = raws.pop() if len(raws) == 1 else None
    # 去重：先定最终(季,集)，同一集只留体积最大的版本
    best = {}
    multi = dirname in MULTI_WORK
    for it in items:
        sn, en = decide(meta, it["ep"], it["season_raw"] or default_season)
        it["sn"], it["en"] = sn, en
        k = (it["subdir"], sn, en) if multi else (sn, en)
        if k not in best or it["size"] > best[k]["size"]:
            best[k] = it
    dups = len(items) - len(best)
    return files, sorted(best.values(), key=lambda x: (x.get("sn") or 0, x.get("en") or 0)), unresolved, dups

# 记录未纳入映射表的目录（新转存进来的剧），供同步器提示
_all_dirs = [it["name"] for it in ls(SRC_AUTOSAVE) if it.get("is_dir")]
_unknown = [d for d in _all_dirs if d not in FINAL]
try:
    json.dump({"unknown": _unknown}, open("/tmp/unknown_dirs.json", "w"), ensure_ascii=False)
except Exception:
    pass

rows = []
for dirname, meta in FINAL.items():
    files, items, unresolved, dups = plan_dir(dirname, meta)
    if meta["kind"] == "movie":
        print(f"【{dirname}】电影 {meta['title']} ({meta['year']}) — {len(files)} 个文件")
        rows.append({"dir": dirname, "meta": meta,
                     "items": [{"src": f["rel"], "size": f["size"], "season_raw": None, "ep": 0, "subdir": ""} for f in files],
                     "unresolved": [], "dups": 0})
        continue
    seasons = {s["n"]: s["eps"] for s in meta["seasons"] if s["eps"]}
    over = [i for i in items if i["ep"] > max(seasons.values())]
    print(f"【{dirname}】{meta['title']} — 本地 {len(files)} 文件 / 唯一集 {len(items)} / 重复丢弃 {dups} / 认不出 {len(unresolved)}")
    if seasons: print(f"   TMDB 季: {seasons}")
    if over:
        print(f"   ⚠ 超界 {len(over)} 个（本地集号 > TMDB 最大季集数）：{[i['ep'] for i in over[:6]]}")
    for u in unresolved[:3]:
        print(f"   ？认不出: {u['rel']}")
    if items[:2]:
        i0 = items[0]
        print(f"   例: {i0['src']}  →  季{i0['season_raw'] or '?'} 集{i0['ep']}")
    rows.append({"dir": dirname, "meta": meta, "items": items,
                 "unresolved": [u["rel"] for u in unresolved], "dups": dups})

json.dump(rows, open(os.path.join(SCRATCH_DIR, "plan.json"), "w"), ensure_ascii=False, indent=2)
print("\n计划已存 plan.json")

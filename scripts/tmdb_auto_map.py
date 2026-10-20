#!/usr/bin/env python3
"""自动 TMDB 映射：把「新转存进来、还没配映射」的目录自动对到 TMDB 条目

只在置信度足够时自动建映射，否则原样留给人工确认（保持 🆕 提示行为）。

判定：
  1) 目录里视频文件 ≥6 成带集号特征（SxxExx / EPxx / 第N集 / 纯数字）→ 当剧集
     需要：TMDB 标题（中文名或原名）与目录名清理后**完全一致**
           且 本地最大集号 ≤ TMDB 总集数（skill 里的硬判据）
     通过 → 写入 state/scratch 目录的 tmdb_final.json（plan_strm.py 下一轮自动接上）
  2) 否则当电影（每个视频一个条目）
     需要：标题完全一致；同名多部时靠年份消歧，消不了就算拿不准交给人工
     通过 → 写入 state 目录下的 movie_rules_auto.json（make_strm_hermes.py 合并使用）

拿不准的一律不写，留给 /tmp/unknown_dirs.json 的提示走人工。

用法：python3 tmdb_auto_map.py [--dry] [--force]
"""
import json, os, re, sys, urllib.parse, urllib.request
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

OL = OL_URL
SRC = SRC_AUTOSAVE
FINAL_PATH = os.path.join(SCRATCH_DIR, "tmdb_final.json")
MOVIE_RULES_PATH = os.path.join(STATE_DIR, "movie_rules_auto.json")
SKIP_PATH = os.path.join(STATE_DIR, "tmdb_auto_skip.json")

SCRIPTS = SCRIPT_DIR
VID = (".mp4", ".mkv", ".avi", ".ts", ".m2ts", ".rmvb", ".flv", ".wmv", ".mov", ".mpg")
DRY = "--dry" in sys.argv
FORCE = "--force" in sys.argv

# 明显不是片名的目录：永远不自动配
JUNK_DIR = re.compile(r"(?i)^(新建文件夹|未命名|临时|待整理|其他|其它|杂物|电影|剧集|下载|待看|test|new folder)\d*$")

QUALITY = re.compile(
    r"(?i)(?:4k\w*|8k\w*|2160p\w*|1080p\w*|720p\w*|hdr\d*\w*|sdr|10bit|8bit|x26[45]|h\.?26[45]|hevc|avc|av01|"
    r"web[-\s]?dl|webrip|bluray|blu-ray|remux|bdrip|hdtv|aac|dts|ddp?\d?(?:\.\d)?|flac|hq|高码率|超清|"
    r"官方中字|中字|内封字幕|简繁英字幕|杜比|立体环绕声)")
NOISE_DIR = re.compile(
    r"(?i)(合集|全集|系列|部合集|\d+\s*部|全\d+季|更新至\s*\d+\s*集|S\d{1,2}E\d{1,4}(\s*-\s*E?\d{1,4})?|"
    r"\d+\s*集全|臻彩|纯净版|典藏版|收藏版)")
# 频道/栏目前缀，出现在片名前面时优先剥掉
CHANNEL = re.compile(r"(?i)^(食贫道|b站|哔哩哔哩|东瀛大宝荐|南洋大宝荐|北极大宝荐)\s*[-_\s]*")


def tmdb_key():
    if not TMDB_KEY:
        raise SystemExit("config.json 里没配 tmdb_api_key")
    return TMDB_KEY


KEY = tmdb_key()


def tmdb(path, **params):
    params["api_key"] = KEY
    params.setdefault("language", "zh-CN")
    url = "https://api.themoviedb.org/3" + path + "?" + urllib.parse.urlencode(params)
    try:
        return json.load(urllib.request.urlopen(url, timeout=25))
    except Exception:
        return {}


def norm(s):
    s = (s or "").lower()
    s = re.sub(r"[\[\]【】()（）〈〉《》·・,，、。:：!！?？'\"“”‘’\s_\-—~|/\\]+", "", s)
    return s


def clean_title(raw):
    s = os.path.splitext(raw)[0]
    s = QUALITY.sub(" ", s)
    s = NOISE_DIR.sub(" ", s)
    s = re.sub(r"[\[\]【】()（）]", " ", s)
    s = re.sub(r"(?<!\d)(?:19|20)\d{2}(?!\d)", " ", s)
    s = re.sub(r"\s+", " ", s).strip(" -_.·")
    return s.strip()


def title_variants(raw):
    """一个文件名/目录名可能带频道前缀、栏目名、副标题 —— 从长到短给出候选片名"""
    base = clean_title(raw)
    out = []
    cur = base
    for _ in range(3):
        m = CHANNEL.match(cur)
        if not m:
            break
        cur = cur[m.end():].strip(" -_.·")
    for s in (base, cur):
        if s and s not in out:
            out.append(s)
    # 按空白/短横切段，从最长的整段到单段
    segs = [x for x in re.split(r"[\s\-_·]+", cur) if x]
    if len(segs) > 1:
        for i in range(len(segs)):
            for j in range(len(segs), i, -1):
                cand = "".join(segs[i:j]) if j - i == 1 else " ".join(segs[i:j])
                cand = cand.strip()
                if len(cand) >= 2 and cand not in out:
                    out.append(cand)
    return out


def year_of(raw):
    m = re.search(r"(?<!\d)((?:19|20)\d{2})(?!\d)", raw)
    return int(m.group(1)) if m else None


def ep_markers(names):
    hit, mx = 0, 0
    for n in names:
        base = os.path.splitext(n)[0]
        b = QUALITY.sub(" ", base)
        e = None
        for pat in (r"(?i)s\d{1,2}\s*[._ ]?e(?:p)?\s*0*(\d{1,4})",
                    r"(?i)(?:^|[^a-z])e(?:p|pisode)?\.?\s*0*(\d{1,4})(?!\d)",
                    r"第\s*0*(\d{1,4})\s*[集话話]",
                    r"^\s*0*(\d{1,4})(?=[\s._\-]|$)",
                    r"[\s._\-]0*(\d{1,4})(?=[\s._\-]|$)"):
            m = re.search(pat, b)
            if m:
                e = int(m.group(1))
                break
        if e and 0 < e < 3000:
            hit += 1
            mx = max(mx, e)
    return hit, mx


def login_ol():
    b = json.dumps({"username": OL_USER, "password": OL_PASS}).encode()
    r = urllib.request.Request(OL + "/api/auth/login", data=b,
                               headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(r, timeout=20))["data"]["token"]


def ls(tok, path, refresh=False):
    b = json.dumps({"path": path, "password": "", "page": 1, "per_page": 300,
                    "refresh": refresh}).encode()
    r = urllib.request.Request(OL + "/api/fs/list", data=b,
                               headers={"Content-Type": "application/json",
                                        "Authorization": tok})
    return (json.load(urllib.request.urlopen(r, timeout=60)).get("data") or {}).get("content") or []


def walk(tok, path, depth=0, out=None):
    if out is None:
        out = []
    for it in ls(tok, path):
        p = path.rstrip("/") + "/" + it["name"]
        if it.get("is_dir") and depth < 3:
            walk(tok, p, depth + 1, out)
        elif not it.get("is_dir"):
            out.append({"name": it["name"], "rel": p.split("/" + AUTOSAVE_DIR + "/", 1)[-1],
                        "size": it.get("size") or 0})
    return out


def covered_dirs():
    cov = set()
    try:
        cov |= set(json.load(open(FINAL_PATH)))
    except Exception:
        pass
    for script in ("make_strm_hermes.py", "make_strm_share.py"):
        try:
            cov |= set(re.findall(r'"match":\s*"([^"]+)"', open(os.path.join(SCRIPTS, script)).read()))
        except Exception:
            pass
    return cov


def match_tv(title, max_ep):
    d = tmdb("/search/tv", query=title)
    cands = [r for r in (d.get("results") or [])[:12]
             if norm(r.get("name")) == norm(title) or norm(r.get("original_name")) == norm(title)]
    for r in cands:
        det = tmdb(f"/tv/{r['id']}")
        seasons = [{"n": s.get("season_number"), "eps": s.get("episode_count") or 0}
                   for s in (det.get("seasons") or [])
                   if (s.get("season_number") or 0) > 0 and (s.get("episode_count") or 0) > 0]
        total = sum(s["eps"] for s in seasons)
        if seasons and max_ep and max_ep <= total:
            return {"kind": "tv", "id": r["id"], "title": r.get("name") or title,
                    "year": (r.get("first_air_date") or "")[:4], "seasons": seasons,
                    "total_eps": total}
    return None


def _pick_exact(results, title, year):
    exact = [r for r in results
             if norm(r.get("title")) == norm(title) or norm(r.get("original_title")) == norm(title)]
    if not exact:
        return None
    if year:
        near = [r for r in exact
                if year_of(r.get("release_date") or "") and
                abs(year_of(r.get("release_date") or "") - year) <= 1]
        if len(near) == 1:
            return near[0]
        if len(near) > 1:
            return None
        return exact[0] if len(exact) == 1 else None
    return exact[0] if len(exact) == 1 else None


def match_movie(raw, dir_year=None):
    """返回 (result, 尝试过的候选, 是否因同名撞车而放弃)"""
    year = year_of(raw) or dir_year
    tried = []
    ambiguous = False
    for t in title_variants(raw):
        tried.append(t)
        res = (tmdb("/search/movie", query=t).get("results") or [])[:12]
        exact = [r for r in res
                 if norm(r.get("title")) == norm(t) or norm(r.get("original_title")) == norm(t)]
        if len(exact) > 1 and not year:
            ambiguous = True
        r = _pick_exact(res, t, year)
        if r:
            return r, tried, False
    return None, tried, ambiguous


def main():
    tok = login_ol()
    final = json.load(open(FINAL_PATH))
    movie_rules = json.load(open(MOVIE_RULES_PATH)) if os.path.exists(MOVIE_RULES_PATH) else {}
    skip = json.load(open(SKIP_PATH)) if os.path.exists(SKIP_PATH) else {}
    cov = covered_dirs()

    dirs = [it["name"] for it in ls(tok, SRC, refresh=FORCE) if it.get("is_dir")]
    todo = [d for d in dirs
            if d not in final and d not in movie_rules
            and not any(c in d for c in cov)
            and not JUNK_DIR.match(d.strip())]

    mapped, unsure, clashes = [], {}, []
    for d in todo:
        files = [f for f in walk(tok, SRC + "/" + d) if f["name"].lower().endswith(VID)]
        if not files:
            continue
        sig = f"{len(files)}:{sum(f['size'] for f in files)}"
        if not FORCE and skip.get(d) == sig:
            continue
        names = [f["name"] for f in files]
        hit, max_ep = ep_markers(names)
        is_tv = len(files) >= 2 and hit >= max(2, int(len(files) * 0.6))

        if is_tv:
            meta = match_tv(clean_title(d), max_ep)
            if meta:
                final[d] = meta
                mapped.append(f"{d} → 剧集《{meta['title']}》TMDB {meta['id']}"
                              f"（本地最大集 {max_ep} ≤ 总集数 {meta['total_eps']}）")
            else:
                unsure[d] = sig
            continue

        picked, bad = [], []
        for f in files:
            r, tried, amb = match_movie(f["name"], year_of(d))
            if not r:
                bad.append((f["name"], amb))
                continue
            t = r.get("title") or clean_title(f["name"])
            if any(norm(t) == norm(x[0]) for x in picked):
                continue
            y = year_of(r.get("release_date") or "") or ""
            picked.append([t, y, r["id"], [tried[-1] if tried else clean_title(f["name"])]])
        if picked:
            movie_rules[d] = picked
            mapped.append(f"{d} → 电影 " + "、".join(f"《{p[0]}》({p[1]}) TMDB {p[2]}" for p in picked))
            if bad:
                unsure[d] = sig
                clashes.append(f"{d}：还有 {len(bad)} 个没配上（同名多部或认不出），需要人工选 → "
                               + "；".join(x[0][:28] for x in bad[:3]))
        else:
            unsure[d] = sig
            if any(b for _, b in bad):
                clashes.append(f"{d}：同名多部，需人工选 → {clean_title(bad[0][0])}")

    if mapped:
        print("🧩 自动配好 TMDB 映射（不用人工）：")
        for line in mapped:
            print("   " + line)
    if clashes:
        for c in clashes:
            print("❓ " + c)
    elif unsure:
        print("❓ 拿不准、等你确认：" + "、".join(sorted(unsure)))

    if not DRY:
        os.makedirs(os.path.dirname(SKIP_PATH), exist_ok=True)
        if mapped:
            json.dump(final, open(FINAL_PATH, "w"), ensure_ascii=False, indent=1)
            json.dump(movie_rules, open(MOVIE_RULES_PATH, "w"), ensure_ascii=False, indent=1)
        json.dump(unsure, open(SKIP_PATH, "w"), ensure_ascii=False, indent=1)


if __name__ == "__main__":
    main()

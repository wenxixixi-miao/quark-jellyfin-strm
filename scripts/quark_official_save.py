#!/usr/bin/env python3
"""用夸克官方 skill 自动追更新：只看「存进过 /自动转存 的分享」，有新增就存回原目录

设计：
- 分享目录映射缓存在 state 里，只对没见过的分享调一次 get-share-saved-dir，省时间
- 只在真存了东西时输出（cron 才会发微信）；否则静默
- 全程 no_agent 运行：不经过大模型，零 token

用法: python3 quark_official_save.py [--dry]
"""
import json, os, subprocess, sys, time
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

SKILL = QUARK_CLI_DIR
CLI = os.path.join(SKILL, "scripts", "quark-drive.cjs")
STATE = os.path.join(STATE_DIR, "quark_official.json")
OL = OL_URL
SID = time.strftime("%s") + "-auto01"
SESS_IN = "自动追更：检查转存过的分享有没有新增"
DRY = "--dry" in sys.argv

def cli(*args, timeout=120):
    cmd = ["node", CLI] + list(args) + ["--session-input", SESS_IN, "--session-id", SID]
    r = subprocess.run(cmd, cwd=SKILL, capture_output=True, text=True, timeout=timeout)
    out = []
    for line in (r.stdout or "").splitlines():
        line = line.strip()
        if line.startswith("{"):
            try:
                out.append(json.loads(line))
            except Exception:
                pass
    return out

def ol_login():
    import urllib.request
    body = json.dumps({"username": OL_USER, "password": OL_PASS}).encode()
    req = urllib.request.Request(OL + "/api/auth/login", data=body,
          headers={"Content-Type": "application/json"}, method="POST")
    return json.load(urllib.request.urlopen(req, timeout=20))["data"]["token"]

def media_dir_names():
    """/夸克/自动转存 下的剧名 + 一级子目录名，作为白名单"""
    import urllib.request
    tok = ol_login()
    def ls(p):
        body = json.dumps({"path": p, "password": "", "page": 1, "per_page": 200, "refresh": False}).encode()
        req = urllib.request.Request(OL + "/api/fs/list", data=body, method="POST",
              headers={"Content-Type": "application/json", "Authorization": tok})
        d = json.load(urllib.request.urlopen(req, timeout=30))
        return (d.get("data") or {}).get("content") or []
    names = set()
    for it in ls(SRC_AUTOSAVE):
        if not it.get("is_dir"):
            continue
        names.add(it["name"])
        for sub in ls(SRC_AUTOSAVE + "/" + it["name"]):
            if sub.get("is_dir"):
                names.add(sub["name"])
    return names

def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    return {"dirs": {}, "seen": []}

def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)

def main():
    white = media_dir_names()
    st = load_state()

    # 1) 拉有更新的分享（自动翻页）
    shares, page = [], 1
    while True:
        rows = cli("get-share-update-list", "--page", str(page), "--size", "50")
        lst = [r for r in rows if r.get("type") == "list"]
        shares += [r["data"] for r in lst]
        tail = [r for r in rows if r.get("type") == "result"]
        if not lst or not (tail and (tail[-1].get("data") or {}).get("has_next_page")):
            break
        page += 1
        if page > 6:
            break

    saved, skipped = [], 0
    for s in shares:
        url = s.get("share_url") or ""
        title = s.get("title") or ""
        if not url:
            continue
        # 2) 查这个分享上次存进的目录（缓存）
        pdir = st["dirs"].get(url)
        if pdir is None:
            rows = cli("get-share-saved-dir", "--url", url)
            res = [r for r in rows if r.get("type") == "result"]
            pdir = ((res[0].get("data") or {}).get("pdir_name") or "") if res else ""
            st["dirs"][url] = pdir
        if not pdir or pdir not in white:
            skipped += 1
            continue
        # 先取这次更新了哪些文件，用于报告
        fnames, fmsg = [], ""
        frows = cli("get-share-update-files", "--url", url, timeout=180)
        for r in frows:
            if r.get("type") == "result":
                d = r.get("data") or {}
                fnames = [f.get("title", "") for f in (d.get("files") or [])]
                fmsg = r.get("msg") or ""
        if DRY:
            saved.append((title, pdir, fnames or ["(dry)"]))
            continue
        # 3) 存新增文件到原目录
        rows = cli("saveas-update", "--url", url, timeout=180)
        ok = any(r.get("code") == 0 for r in rows)
        if ok:
            saved.append((title, pdir, fnames or ["(已存入)"], fmsg))

    st["dirs"] = {k: v for k, v in st["dirs"].items() if v in white or v == ""}
    save_state(st)

    if DRY:
        print(f"[dry] 有更新的分享 {len(shares)} 个，白名单命中 {len(saved)} 个，跳过 {skipped}")
        for item in saved[:15]:
            t, d, names = item[0], item[1], item[2]
            print(f"   {t[:24]:26} → {d}：{'、'.join(n for n in names[:3] if n)}")
        return
    if saved:
        print(f"✅ 夸克转存成功：{len(saved)} 个分享有新集入库")
        for item in saved[:12]:
            t, d, names = item[0], item[1], item[2]
            msg = item[3] if len(item) > 3 else ""
            shown = "、".join(n for n in names[:4] if n)
            if len(names) > 4:
                shown += f" 等 {len(names)} 个文件"
            print(f"  {t[:22]:24} → {d}：{shown or '已存入'}")
        if msg:
            print()
            print(msg)

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"⚠️ 官方接口追更失败: {e}")
        sys.exit(1)

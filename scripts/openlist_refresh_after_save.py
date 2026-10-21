#!/usr/bin/env python3
"""监听器转存成功后，刷新 OpenList 对应目录的缓存

原理：OpenList 每个目录有独立缓存（默认 30 分钟）。监听器转存成功后在
monitor.log 写 "✅ 转存完成"，本脚本读取新增的成功记录，配对上最近的
"🎯 命中关键字: [xx]"，然后对该关键词目录（递归到 3 层）调用 /api/fs/list
并带 refresh=true，强制 OpenList 重新向夸克要列表。

成功时静默（不输出），出错才输出（cron 会把它发到微信）。
"""
import json, os, re, sys, urllib.request, urllib.error
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

OPENLIST = OL_URL
USER, PWD = OL_USER, OL_PASS
LOG = "/root/quark-auto-save/monitor.log"
STATE = "/root/.openlist_refresh_state.json"

BASE_DIR = SRC_AUTOSAVE
MAX_DEPTH = 3
MAX_CALLS = 60

def login():
    body = json.dumps({"username": USER, "password": PWD}).encode()
    r = urllib.request.Request(OPENLIST + "/api/auth/login", data=body,
                               headers={"Content-Type": "application/json"}, method="POST")
    with urllib.request.urlopen(r, timeout=20) as resp:
        d = json.load(resp)
    tok = (d.get("data") or {}).get("token")
    if not tok:
        raise RuntimeError("OpenList 登录失败")
    return tok

def fs_list(token, path, refresh):
    body = json.dumps({"path": path, "password": "", "page": 1, "per_page": 200,
                       "refresh": refresh}).encode()
    r = urllib.request.Request(OPENLIST + "/api/fs/list", data=body, method="POST",
                               headers={"Content-Type": "application/json",
                                        "Authorization": token})
    with urllib.request.urlopen(r, timeout=30) as resp:
        return json.load(resp)

def refresh_tree(token, root, depth=0, budget=None):
    if budget is None:
        budget = {"n": 0}
    if budget["n"] >= MAX_CALLS or depth > MAX_DEPTH:
        return 0
    try:
        d = fs_list(token, root, True)
        budget["n"] += 1
    except Exception:
        return 0
    items = (d.get("data") or {}).get("content") or []
    n = 1
    for it in items:
        if it.get("is_dir") and depth < MAX_DEPTH:
            n += refresh_tree(token, root.rstrip("/") + "/" + it["name"], depth + 1, budget)
    return n

def new_successes():
    """返回自上次以来新增的、转存成功的关键词列表"""
    if not os.path.exists(LOG):
        return []
    size = os.path.getsize(LOG)
    st = {"offset": 0}
    if os.path.exists(STATE):
        try:
            st = json.load(open(STATE))
        except Exception:
            st = {"offset": 0}
    off = st.get("offset", 0)
    if size < off:            # 日志被截断/轮转
        off = 0
    with open(LOG, "rb") as f:
        f.seek(off)
        chunk = f.read().decode("utf-8", "ignore")
        newoff = f.tell()
    if not chunk.strip():
        return []
    kws = []
    last_kw = None
    for line in chunk.splitlines():
        if "命中关键字" in line:
            found = re.findall(r"['\"]([^'\"]+)['\"]", line)
            if found:
                last_kw = found[0].strip()
            continue
        if "转存完成" in line and last_kw:
            kws.append(last_kw)
            last_kw = None
        elif "检测到资源" in line:
            m2 = re.search(r'\[([^\]]+)\]', line)
            if m2:
                last_kw = m2.group(1).strip()
    json.dump({"offset": newoff, "ts": int(__import__("time").time())}, open(STATE, "w"))
    return kws

def main():
    kws = new_successes()
    if not kws:
        return
    token = login()
    total = 0
    for kw in set(kws):
        path = BASE_DIR + "/" + kw
        n = refresh_tree(token, path)
        if n == 0:                      # 该关键词目录不在 自动转存 下，退回刷根目录
            n = refresh_tree(token, BASE_DIR, 0, {"n": 0})
        total += n
    if total == 0:
        print("⚠️ 转存成功后刷新 OpenList 缓存失败（0 个目录刷新成功）")
        sys.exit(1)

if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""生成 nginx map：Jellyfin 条目 Id -> .strm 里的夸克直链

用途：让 /Videos/{id}/stream 直接 302 到夸克 CDN，杜绝 Jellyfin 服务端代理视频流。
由 strm_sync.py 在有变化后调用，也可手动跑。
"""
import json, os, subprocess, sys, urllib.request
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

JF = JF_URL

OUT = NGINX_MAP_PATH

def api_key():
    return JF_KEY

def fetch_items():
    key = api_key()
    if not key:
        raise SystemExit("缺少 Jellyfin API Key")
    items, start = [], 0
    while True:
        url = f"{JF}/Items?Recursive=true&IncludeItemTypes=Movie,Episode&Fields=Path&Limit=500&StartIndex={start}"
        req = urllib.request.Request(url, headers={"Authorization": "MediaBrowser Token=" + key})
        d = json.load(urllib.request.urlopen(req, timeout=60))
        batch = d.get("Items") or []
        items += batch
        total = d.get("TotalRecordCount") or 0
        start += len(batch)
        if not batch or start >= total:
            break
    return items

def main():
    items = fetch_items()
    lines = ["# 自动生成，勿手改（strm_sync.py 维护）", "map $uri $strm_target {", '    default "";']
    n = 0
    for it in items:
        iid = (it.get("Id") or "").lower()
        path = it.get("Path") or ""
        # Jellyfin 里 strm 条目的 Path 是本地 .strm 文件；真实 URL 在 MediaSources 里
        if not iid:
            continue
        url = it.get("RemoteUrl") or ""
        if not url:
            # 退回：读 .strm 文件首行
            if path.endswith(".strm") and os.path.exists(path):
                try:
                    url = open(path).read().strip()
                except Exception:
                    url = ""
        if not url.startswith("http"):
            continue
        lines.append(f'    ~*^/videos/{iid}/stream "{url}";')
        n += 1
    lines.append("}")
    os.makedirs(os.path.dirname(OUT), exist_ok=True)
    open(OUT, "w").write("\n".join(lines) + "\n")
    r = subprocess.run(["nginx", "-t"], capture_output=True, text=True)
    if r.returncode == 0:
        subprocess.run(["systemctl", "reload", "nginx"], capture_output=True)
        print(f"已写入 {n} 条映射并 reload nginx")
    else:
        print("⚠️ nginx 配置校验失败，未 reload：\n" + (r.stderr or "")[-400:])
        sys.exit(1)

if __name__ == "__main__":
    main()

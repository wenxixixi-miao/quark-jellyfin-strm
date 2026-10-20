#!/usr/bin/env python3
"""夸克 → OpenList → Jellyfin 全自动媒体库：集中配置

所有私有信息（域名、路径前缀、账号、密钥）都从 config.json 读，
代码里不写死任何一条。复制 config.example.json 成 config.json 再填。
"""
import json, os

HERE = os.path.dirname(os.path.abspath(__file__))
CONFIG_PATH = os.path.abspath(os.path.expanduser(
    os.environ.get("STRM_CONFIG", os.path.join(HERE, "config.json"))))

DEFAULTS = {
    "openlist": {"url": "http://127.0.0.1:5244", "username": "admin", "password": ""},
    # 播放地址 = 对外域名 + nginx 里那个免认证私有路径前缀
    "public_base": "https://quark.example.com/CHANGE_ME_PATH",
    "jellyfin": {"url": "http://127.0.0.1:8096", "api_key": ""},
    "tmdb_api_key": "",
    "quark": {"cli_dir": "~/.hermes/skills/quarkclouddrive"},
    "paths": {
        "mount": "/夸克",                 # OpenList 里夸克存储的挂载点名
        "autosave_dir": "自动转存",        # 追更落点（相对挂载点）
        "share_dir": "来自：分享",         # 存量转存落点
        "media": "/srv/media",            # Jellyfin 媒体库根（只放文本 strm/nfo）
        "scratch": "~/.cache/strm/scratch",  # 中间产物（plan.json / tmdb_final.json）
        "state": "~/.cache/strm/state",      # 运行状态
        "nginx_map": "/etc/nginx/conf.d/jellyfin_strm_302.conf",
        "tv_dirname": "剧集",
        "movie_dirname": "电影",
    },
    "sync": {"refresh": False, "sleep": 0.25},
}


def _deep_merge(base, over):
    out = dict(base)
    for k, v in (over or {}).items():
        if isinstance(v, dict) and isinstance(out.get(k), dict):
            out[k] = _deep_merge(out[k], v)
        else:
            out[k] = v
    return out


def load():
    data = {}
    if os.path.exists(CONFIG_PATH):
        with open(CONFIG_PATH, encoding="utf-8") as f:
            data = json.load(f)
    return _deep_merge(DEFAULTS, data)


CFG = load()
P = CFG["paths"]

# —— OpenList ——
OL_URL = CFG["openlist"]["url"].rstrip("/")
OL_USER = CFG["openlist"]["username"]
OL_PASS = CFG["openlist"]["password"]

# —— 播放地址（nginx 302 入口）——
PUBLIC_BASE = CFG["public_base"].rstrip("/")

# —— 挂载点与来源目录 ——
MOUNT = P["mount"].rstrip("/")
AUTOSAVE_DIR = P["autosave_dir"].strip("/")
SHARE_DIR = P["share_dir"].strip("/")
SRC_AUTOSAVE = MOUNT + "/" + AUTOSAVE_DIR
SRC_SHARE = MOUNT + "/" + SHARE_DIR
URL_PREFIX_AUTOSAVE = MOUNT.lstrip("/") + "/" + AUTOSAVE_DIR
URL_PREFIX_SHARE = MOUNT.lstrip("/") + "/" + SHARE_DIR

# —— 媒体库 ——
MEDIA_DIR = os.path.expanduser(P["media"])
MEDIA_TV_DIRNAME = P["tv_dirname"]
MEDIA_MOVIE_DIRNAME = P["movie_dirname"]
SCRATCH_DIR = os.path.expanduser(P["scratch"])
STATE_DIR = os.path.expanduser(P["state"])
SCRIPT_DIR = HERE
NGINX_MAP_PATH = P["nginx_map"]

# —— Jellyfin / TMDB / 夸克官方 CLI ——
JF_URL = CFG["jellyfin"]["url"].rstrip("/")
JF_KEY = CFG["jellyfin"]["api_key"]
TMDB_KEY = CFG["tmdb_api_key"]
QUARK_CLI_DIR = os.path.expanduser(CFG["quark"]["cli_dir"])

for d in (SCRATCH_DIR, STATE_DIR):
    os.makedirs(d, exist_ok=True)

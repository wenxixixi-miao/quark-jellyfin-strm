#!/usr/bin/env python3
"""strm 同步器：全量重算到临时目录 -> 只应用真实变化

借鉴 SmartStrm 的四点：
1) 内容级 diff：URL 没变的 strm 一个字节都不动（不动 mtime，Jellyfin 就不会重刮）
2) 保护式删除：某集连续两轮都不存在才删 strm，防 OpenList 抽风返回空目录把库清空
3) 播放会话闸门：Jellyfin 里有活跃播放的剧，这一轮整个跳过
4) 请求间隔：由 plan_strm 里的 STRM_SLEEP 控制（默认 0.25s）

静默运行：正常无输出；有问题才打印（cron 会把 stdout 发到微信）。
用法：python3 strm_sync.py [--force] [--dry]
"""
import json, os, shutil, subprocess, sys, time, urllib.request
from cfg import (OL_URL, OL_USER, OL_PASS, PUBLIC_BASE, MOUNT, SRC_AUTOSAVE, SRC_SHARE,
                 AUTOSAVE_DIR, SHARE_DIR, URL_PREFIX_AUTOSAVE, URL_PREFIX_SHARE,
                 MEDIA_DIR, SCRATCH_DIR, STATE_DIR, SCRIPT_DIR, NGINX_MAP_PATH,
                 JF_URL, JF_KEY, TMDB_KEY, QUARK_CLI_DIR,
                 MEDIA_TV_DIRNAME, MEDIA_MOVIE_DIRNAME)

MEDIA = MEDIA_DIR
TMP = "/tmp/strm_build"
STATE = os.path.join(STATE_DIR, "strm_sync.json")

SCRIPTS = SCRIPT_DIR
ROUNDS_BEFORE_DELETE = 2
NO_DELETE = os.environ.get("STRM_NO_DELETE", "1") == "1"   # 默认不自动删除，避免误删媒体库条目

def jf_conf():
    """Jellyfin 地址与 API Key 都来自 config.json"""
    return JF_URL, JF_KEY

def playing_shows():
    """返回正在播放的剧名集合；拿不到就返回 None（表示不跳过任何东西）"""
    url, key = jf_conf()
    if not (url and key):
        return None
    try:
        req = urllib.request.Request(url + "/Sessions",
              headers={"Authorization": "MediaBrowser Token=" + key})
        data = json.load(urllib.request.urlopen(req, timeout=15))
    except Exception:
        return None
    names = set()
    for s in data:
        item = s.get("NowPlayingItem")
        if not item:
            continue
        names.add(item.get("SeriesName") or item.get("Name") or "")
    return names

def refresh_jellyfin():
    url, key = jf_conf()
    if not (url and key):
        return
    try:
        req = urllib.request.Request(url + "/Library/Refresh", method="POST",
              headers={"Authorization": "MediaBrowser Token=" + key})
        urllib.request.urlopen(req, timeout=20)
    except Exception as e:
        print(f"⚠️ 通知 Jellyfin 扫库失败: {e}")

def build_temp():
    env = dict(os.environ, STRM_OUT=TMP)
    if os.path.isdir(TMP):
        shutil.rmtree(TMP, ignore_errors=True)
    for script in ("tmdb_auto_map.py", "plan_strm.py", "make_strm.py", "make_strm_batch2.py", "make_strm_share.py", "make_strm_hermes.py"):
        r = subprocess.run([sys.executable, os.path.join(SCRIPTS, script)],
                           capture_output=True, text=True, env=env, timeout=1800)
        if r.returncode != 0:
            raise RuntimeError(f"{script} 失败: {r.stderr[-500:]}")
    # batch2 走的是媒体库常量，确认它读环境变量
    n = sum(1 for _, _, fs in os.walk(TMP) for f in fs if f.endswith(".strm"))
    if n == 0:
        raise RuntimeError("临时目录没有生成任何 strm，中止")

def load_state():
    if os.path.exists(STATE):
        try:
            return json.load(open(STATE))
        except Exception:
            pass
    return {"missing": {}}

def save_state(st):
    os.makedirs(os.path.dirname(STATE), exist_ok=True)
    json.dump(st, open(STATE, "w"), ensure_ascii=False, indent=1)

def rel(p, root):
    return os.path.relpath(p, root)

def show_of(relpath):
    parts = relpath.split(os.sep)
    return parts[1] if len(parts) > 1 and parts[0] in ("剧集", "电影") else parts[0]

def main():
    force = "--force" in sys.argv
    dry = "--dry" in sys.argv
    st = load_state()
    busy = playing_shows() or set()

    build_temp()
    new_files = {rel(os.path.join(r, f), TMP) for r, _, fs in os.walk(TMP) for f in fs}
    old_files = {rel(os.path.join(r, f), MEDIA) for r, _, fs in os.walk(MEDIA) for f in fs}

    added = changed = kept = skipped_busy = 0
    for rp in sorted(new_files):
        src, dst = os.path.join(TMP, rp), os.path.join(MEDIA, rp)
        show = show_of(rp)
        if any(show in b or b in show for b in busy if b):
            skipped_busy += 1
            continue
        try:
            newc = open(src, "rb").read()
        except Exception:
            continue
        if os.path.exists(dst):
            try:
                if open(dst, "rb").read() == newc:
                    kept += 1
                    continue
            except Exception:
                pass
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(newc)
            changed += 1
        else:
            os.makedirs(os.path.dirname(dst), exist_ok=True)
            open(dst, "wb").write(newc)
            added += 1

    # 保护式删除：连续 N 轮不存在才真正删
    gone = old_files - new_files
    deleted = 0
    if NO_DELETE:
        gone = set()          # 自动删除已停用：失效条目只统计、不删除
    for rp in gone:
        if not rp.endswith((".strm", ".nfo")):
            continue
        show = show_of(rp)
        if any(show in b or b in show for b in busy if b):
            continue
        cnt = st["missing"].get(rp, 0) + 1
        if cnt >= ROUNDS_BEFORE_DELETE:
            try:
                os.remove(os.path.join(MEDIA, rp))
                deleted += 1
            except Exception:
                pass
            st["missing"].pop(rp, None)
        else:
            st["missing"][rp] = cnt
    # 恢复存在的文件计数
    for rp in new_files:
        st["missing"].pop(rp, None)
    save_state(st)

    if dry:
        print(f"[dry] 新增 {added} / 变化 {changed} / 未动 {kept} / 待删计数 {len(st['missing'])} / 播放跳过 {skipped_busy}")
        return

    # 新转存进来、但还没配 TMDB 映射的剧：提示一次
    new_unknown = []
    try:
        unknown = set(json.load(open("/tmp/unknown_dirs.json")).get("unknown") or [])
        try:
            unknown |= set(json.load(open("/tmp/unknown_share_dirs.json")).get("unknown") or [])
        except Exception:
            pass
        known = set(st.get("known_unknown") or [])
        new_unknown = sorted(unknown - known)
        st["known_unknown"] = sorted(unknown)
        save_state(st)
    except Exception:
        pass

    if new_unknown:
        print("🆕 发现新目录（还没配 TMDB 条目，暂未入库）：" + "、".join(new_unknown))
        print("   要我加进媒体库就说一声，我查好条目跑一次同步就行。")

    if added or changed or deleted:
        refresh_jellyfin()
        try:
            subprocess.run([sys.executable, os.path.join(SCRIPTS, "gen_strm_map.py")],
                           capture_output=True, timeout=180)
        except Exception:
            pass
        print(f"strm 同步：新增 {added}，更新 {changed}，删除 {deleted}，未动 {kept}"
              + (f"，播放中跳过 {skipped_busy}" if skipped_busy else ""))
    # 无变化则完全静默

if __name__ == "__main__":
    try:
        main()
    except Exception as e:
        print(f"⚠️ strm 同步失败: {e}")
        sys.exit(1)

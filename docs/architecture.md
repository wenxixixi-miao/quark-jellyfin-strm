# 四层联动：夸克 / OpenList / nginx / Jellyfin 各干什么

这套东西最容易搞混的一点是：**谁负责内容、谁负责门面、谁负责元数据、谁负责把字节送到播放器**。
四者职责一旦分清，出问题就能一眼定位到层。

```
                       ┌──────────────────────────── 入库方向（每小时级）────────────────────────────┐

  夸克网盘                    OpenList (127.0.0.1:5244)              strm 生成器系列               Jellyfin (127.0.0.1:8096)
 /夸克/自动转存  ──WebDAV──▶  QuarkTV 驱动 + 302_redirect  ──列目录──▶  plan/make/tmdb_auto_map  ──扫库──▶  剧集/电影 库
 /夸克/来自：分享             只做门面，不搬字节                    生成 .strm + .nfo 文本        自动刮 TMDB 元数据
       ▲                                                              （每个条目几十字节）            会话/进度/海报
       │                                                                     │
       │ 官方 CLI saveas-update（每 10 分钟）                                  │ gen_strm_map.py
       │                                                                     ▼
   分享链接 ────────────────────────────────────────────────▶  nginx map: Jellyfin item id → 夸克直链

                       └──────────────────────────── 播放方向（每次点播）──────────────────────────────┘

  播放器(爆米花/Infuse) ──GET /Videos/{id}/stream──▶ nginx ──302──▶ 夸克 CDN ──直接发字节给播放器
                                                        │
                                                        └── 命中 map 才 302；没命中才回落到 Jellyfin（会经服务器中转，属于故障态）
```

## 1. 夸克：唯一的内容与字节提供方

- 内容存在 `挂载点/自动转存/<剧或片>/`（追更落点）和 `挂载点/来自：分享/<剧>/`（存量落点）。
- 追更走官方开放接口（`scripts/quark_official_save.py`）：`get-share-update-list` 找出「有新增的分享」→
  `get-share-saved-dir` 判断这条分享上次是不是存进了我们的目录（白名单）→ `saveas-update` **增量**存回原目录。
  增量语义很关键：不删旧、只加新，所以路径稳定，strm 不需要每轮全量重建。
- 播放直链由夸克按文件签发，有效期很短（约 3 小时），所以**不能在 strm 里写死**，必须每次播放现取。

## 2. OpenList：只是一个「能 302 的门面」

- 用 `QuarkTV` 驱动把网盘挂成 WebDAV，关键参数 `webdav_policy=302_redirect`：
  客户端来要文件时，OpenList 不给字节，而是回一个 302 指向夸克 CDN。
- `link_method` 二选一，都 302、都不占服务器带宽：
  - `streaming`：夸克转码流，起播快、画质被压（4K 片源也常只给 1080P 档）；
  - `download`：源文件直链，原画，但单线程会被限速（实测 ~700KB/s 量级，4K 起播会卡）。
- **别用普通 `Quark` 驱动开转码地址**：那条路实测全线 `plf_invalid`，且驱动初始化会把策略改成
  `native_proxy` —— 一旦变成代理，字节就从这台服务器过了，这正是我们要避免的。

## 3. nginx：两个职责，别混为一谈

**(a) 给 strm 一个免认证的播放前缀**

strm 里写的是 `https://quark.example.com/<私有路径>/<挂载点>/自动转存/…`。
这个 `<私有路径>` 在 nginx 里 `proxy_pass` 到 OpenList 的 `/dav/`，并注入 Basic 认证头，
只放行 `GET/HEAD`（封掉 PROPFIND 遍历与写操作）。
播放器拿到的 URL 不需要账号密码，也不会泄露 OpenList 管理员凭据。

**(b) 把 Jellyfin 的播放请求强行改成 302**

Jellyfin 收到 `/Videos/{id}/stream` 时，默认会**自己去读文件再转发**——strm 场景下等于让服务器
替客户端下载整个视频。所以 nginx 用一张 map 表（`conf.d/jellyfin_strm_302.conf`）：

```nginx
map $uri $strm_target {
    default "";
    ~*^/videos/<jellyfin item id>/stream "https://quark.example.com/<私有路径>/…/<文件>";
}
```

命中就 `return 302`，客户端直接去夸克 CDN；没命中才回落到 Jellyfin。
这张表由 `scripts/gen_strm_map.py` 生成：它从 Jellyfin 的 `/Items` 拿 item id + 本地 `.strm` 路径，
再用 `.strm` 内容补齐真实 URL。**Jellyfin 重建条目后 item id 会变，所以每次新增/变更多条目后必须重跑。**

## 4. Jellyfin：只做元数据、库、会话，不做流量

- 媒体库里**只有文本**：每个条目一个 `.strm`（一行 URL）加一个 `.nfo`（季/集/tmdbid）。
  1583 集也才十几 MB，磁盘和内存都无压力。
- `.nfo` 里**故意不写 `<title>`**：写了 Jellyfin 就锁死本地标题、不去 TMDB 取真实集名。
  只写 `season/episode/showtitle/uniqueid(type=tmdb)`。
- 视频解码全关（`EnableVideoPlaybackTranscoding=False`）：客户端要吃转码就直接报错，
  而不是悄悄让服务器转——这是有意为之，不是故障。
- 扫库触发：`strm_sync.py` 发现变化后 `POST /Library/Refresh`；首次扫库很慢（要远端 ffprobe），
  海报也可能要单独 `ImageRefreshMode=FullRefresh` 才下来。

## 入库一条链：谁在什么时候动

| 时机 | 谁 | 做什么 |
|---|---|---|
| 每 10 分钟 | `quark_official_pipeline.sh` | 官方接口追更；**有新增才**继续 |
| 有新增时 | `quark_official_pipeline.sh` | `STRM_REFRESH=1 strm_sync.py` |
| 每 2 小时 | `strm_sync_fallback.sh` | 不看事件、只扫目录（手动塞文件也能发现） |
| 每轮同步 | `tmdb_auto_map.py` | 新目录自动对 TMDB（剧集要求标题一致＋集号不越界；电影要求标题一致＋年份吻合），拿不准就报给人 |
| 每轮同步 | `plan_strm.py` | 扫两个来源目录 → 解析集号 → 定季/集 → 写 `plan.json`（dry-run，不落盘） |
| 每轮同步 | `make_strm.py` / `make_strm_batch2.py` / `make_strm_share.py` / `make_strm_hermes.py` | 按映射生成 `.strm` + `.nfo` 到临时目录 |
| 每轮同步 | `strm_sync.py` | 内容级 diff，只把真正变化的文件写进媒体库；有变化才通知 Jellyfin 扫库 |
| 有变化时 | `gen_strm_map.py` | 重写 nginx map 并 reload |
| 播放时 | nginx + OpenList + 夸克 | 302 直连，服务器不过字节 |

## `strm_sync.py` 的四条自保设计

1. **内容级 diff**：URL 没变的 strm 一个字节都不动，mtime 不变 → Jellyfin 不会重新刮。
2. **保护式删除**：某集连续两轮不存在才删（默认还关掉自动删除），防 OpenList 抽风返回空目录把库清空。
3. **播放会话闸门**：正在播放的剧这一轮整个跳过，避免播到一半文件被改。
4. **请求间隔**：列目录之间 `sleep 0.25s`，降低被夸克风控的概率。

## 必须成立的不变量（排障就从这几条查）

1. 每个 `.strm` 里只有一行 `https://…`；URL 指向 nginx 私有前缀，不是 `/d/` 直链。
2. 每个 Jellyfin 条目都能在 nginx map 里找到对应行（`grep <item id>` 应为 1）。
3. 带 `Range` 请求 `/Videos/{id}/stream` 应返回 **302**，跳转域名是夸克 CDN；返回 200/206 就是有人在替客户端搬字节。
4. OpenList 的存储 `webdav_policy` 必须是 `302_redirect`；驱动是 `QuarkTV`。
5. 媒体库目录里不该出现视频文件本体。

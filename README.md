# data.gov.my 全量镜像与监控方案（调研版）

> 调研日期：2026 年（主站页脚显示 ©2026）。对象：马来西亚政府开放数据门户 https://data.gov.my 及其官方 Open API。
> **本仓库同时是该门户的全量镜像**（爬取快照日 2026-09-09），数据情况见下节与 §9。

## 镜像速览（本仓库内容）

| 项目 | 数值 |
|---|---|
| 数据源 | https://data.gov.my （马来西亚政府开放数据门户）+ S3 文件主机 storage.data.gov.my / storage.dosm.gov.my |
| 爬取快照日 | 2026-09-09（工具与清单中的时间戳均为当日） |
| 数据集 | **290 个 / 18 大类 / 45 机构**，其中 279 个有 S3 直链文件，11 个为「日期模板 + edition 档案」型 |
| 当前快照文件 | 557 个（278 CSV + 279 Parquet），**166 MB** |
| 历史档案（edition） | 352 个（176 CSV + 176 Parquet），**8.53 GB**；车辆注册 2000–2026、pricecatcher 2022-01 起逐月、轨道交通 OD 按年 |
| 元数据 | `registry/registry.json` + `registry.csv`（290 条）+ `registry/details/<id>.json`（290 个详情页：frequency / next_update / 字段 schema / methodology / caveat） |
| 本地合计 | **8.70 GB / 911 文件**，全部通过完整性校验（大小 + ETag-MD5 + Parquet 魔数，0 问题） |
| 本仓库收录 | 除 **5 个 >100 MB 的 CSV**（GitHub 单文件硬限制，清单见 §9.2）外的全部文件；已推送完成：**1211 文件 / 7.54 GB**，`main @ b379b9d` |
| 数据清单 | `DATA_INVENTORY.csv`（932 行：数据集/类型/版本/字节/md5/来源 URL/本地路径） |

复现与校验：
```bash
python tools/verify.py            # 校验已下载文件完整性（离线）
python tools/make_inventory.py    # 重建 DATA_INVENTORY.csv
python tools/monitor.py --refresh-registry --head   # 之后每日监控变化
```

数据版权属马来西亚政府各机构，以 data.gov.my 的 Terms of Use / Open Data Guiding Principles 为准；
本仓库仅为研究用途的镜像与工具，署名与许可说明见 §7、§9。

## 0. 一句话结论

data.gov.my **不是传统 CKAN**，而是马来西亚政府自研平台（Next.js 前端 + Django 后端，代码全部开源）。
数据主体是一个 **约 290 个数据集的「数据目录」**，每个数据集都有：
(1) 托管在 S3 上的**整表 CSV / Parquet 直链**（支持 Range 断点续传，带 ETag / Last-Modified，无认证、无速率限制）；
(2) 可编程查询的 **Open API**（官方文档 https://developer.data.gov.my ，无需 token，但限流 4 次/分钟）。
「完全爬取 + 监控」**不需要也不应该去爬页面 HTML**——应以「**注册表驱动 + S3 文件直链为主、API 为辅、多层元数据比对监控**」为架构。
实测规模：当前快照 CSV 合计约 140 MB、Parquet 约 18 MB（290 数据集 × 2 文件）；再加上 11 个日期模板数据集的
**历史 edition 档案**（车辆注册 2000–2026、pricecatcher 2022-01 起逐月、轨道交通 OD 按年，352 文件合计约 8.5 GB），
全量镜像约 **8.7 GB**，一台普通服务器即可常驻镜像并保留多版本。

## 1. 平台事实清单（2026 实证）

| 项目 | 事实 |
|---|---|
| 主站 | https://data.gov.my （Next.js SSR；robots.txt 允许全爬；有 sitemap） |
| 目录页 | https://data.gov.my/data-catalogue —— 页面内嵌 __NEXT_DATA__ JSON，含**完整注册表**（id/标题/描述/data_as_of/机构/CSV 与 Parquet 直链） |
| 数据集详情页 | https://data.gov.my/data-catalogue/<id> —— 含 frequency、last_updated、**next_update**、字段 schema、methodology、caveat、exclude_openapi 等 |
| 官方 Open API | 基址 https://api.data.gov.my ，无需 token；端点：/data-catalogue?id=<id>（通用）、/opendosm?id=<id>（DOSM 专用）、GTFS 静态/实时、天气 |
| API 限流 | **4 次/分钟**（Data Catalogue / OpenDOSM / Weather / GTFS 均如此），超出返回 429 |
| API 参数 | filter / ifilter / contains / icontains / range / sort / date_start / date_end / timestamp_start / timestamp_end / limit / include / exclude；?meta=true 返回 {meta,data}；错误格式 {status,errors} |
| 文件主机 | storage.dosm.gov.my（DOSM）与 storage.data.gov.my（其余机构），标准 S3，支持 Range、ETag、Last-Modified，无速率限制 |
| 规模 | 290 数据集 / 18 大类 / 45 机构（registry 见本目录） |
| 开源 | github.com/data-gov-my/{datagovmy-front, datagovmy-back, datagovmy-meta, datagovmy-ai} |
| 其他 | 约 38 个可视化 dashboard；开发者文档有 changelog；有 helpdesk 与 data-request 官方通道 |

**日期模板直链（重要修正）**：11 个数据集（ridership_od_*、registration_transactions_*、pricecatcher）的
注册表直链是**日期模板**（含字面量 `YYYY-MM-DD`，如 `komuter_YYYY-MM-DD.csv`），直接请求当然 404。
这些数据集 `exclude_openapi=true`（Open API 查询同样 404，属正常），真实数据按**版本档案（edition）**存放：
把 edition 标签（年份，或 pricecatcher 的 年月）替换进模板即得档案直链（如 `komuter_2026.csv`、
`pricecatcher_2026-09.csv`）。实测不存在按日命名的滚动文件（HEAD 了 data_as_of/last_updated/次日等多组候选
日期均 404），edition 档案即全部数据体（车辆注册 2000–2026 年、pricecatcher 2022-01 起逐月、轨道交通
OD 按年），CSV 档案合计约数 GB。`download_editions.py` 负责展开并下载全部 edition 文件。
currency_codes 的 CSV 在 storage.dosm.gov.my 上缺失（3 个候选路径均 404），但其 Parquet 在
storage.data.gov.my 正常——以 Parquet/API 为准即可。

## 2. 推荐架构（三层）

调度层（cron / Windows 任务计划 / Airflow）
  └─► monitor.py（注册表 diff + HEAD 扫描）──发现变化──► download.py（只重下变化的文件）
        │
        ├─ ① 注册表 registry.json（290 条元数据，单一真相源）
        ├─ ② S3 文件直链（CSV + Parquet，数据主体；ETag 变化才重下）
        └─ ③ Open API（4 次/分钟；仅用于 API-only 数据集 / 增量行拉取）

产物：
  data/<id>/<id>.csv 与 <id>.parquet （当前版，必要时按 ETag 归档旧版）
  data/<id>/<basename>（日期模板数据集的 edition 档案，如 komuter_2026.csv）
  data/manifest.json （快照指针：ETag/大小/时间，监控依据）
  data/editions_manifest.json （edition/滚动档案清单）
  registry/details/<id>.json （每个数据集的详情页元数据：frequency/next_update/fields/methodology/caveat 等）

要点：
- 全量下载 = 580 个文件（290 x CSV+Parquet）的 S3 拉取 + 352 个 edition 档案（约 8.5 GB），并发 8~16、
  断点续传、ETag/MD5 校验，数小时内完成（首次按带宽而定；之后只重下变化的文件）。
- 之后每天监控 = 1 次目录页请求（注册表 diff）+ 580 次 HEAD（S3，无配额），成本趋近于零。
- edition 档案的监控：注册表 link_editions 变化即新档案出现；下载工具按 edition 标签展开 URL。
- API 全局限速：串行 + 每请求间隔 ≥15 秒，遇 429 指数退避；先 ?limit=1&meta=true 看总量再分页。
- 每个数据集旁保存字段 schema 与方法论（详情页 JSON），分析时解释口径必备（注意 caveat，如人口数据普查年与抽样年粒度不同）。

## 3. 目录结构

- registry/  注册表（本次实测生成 290 条，含直链、文件大小、ETag、Last-Modified）
  - registry.json（机器用） registry.csv（Excel 可读）
  - details/<id>.json（290 个数据集的详情页元数据）details_index.json（速查表）
- tools/     stdlib-only Python（3.10+，零第三方依赖）
  - common.py         共享工具（HTTP/解析/校验）
  - fetch_registry.py 重抓目录页、重建注册表、输出与上次差异
  - download.py       并发/断点续传下载全部 CSV+Parquet，写 manifest.json
  - download_editions.py 展开并下载日期模板数据集的全部 edition 档案（写 editions_manifest.json）
  - fetch_details.py  逐数据集抓详情页元数据（fields/frequency/methodology/caveat 等，写 registry/details/）
  - monitor.py        注册表 diff + HEAD 扫描；可自动重下 / 通知 webhook
  - verify.py         本地完整性校验：文件存在/大小/MD5/Parquet 魔数，对照 registry 与 manifest
  - make_inventory.py 生成 DATA_INVENTORY.csv（本仓库收录内容的单一清单）
- registry/details/ 数据集详情元数据
- data/      下载产物（已随本仓库发布，仅 5 个 >100 MB 文件除外，见 §9）
- DATA_INVENTORY.csv  全部 932 条文件记录（数据集/类型/版本/字节/md5/来源 URL/本地路径）

## 4. 使用

首次（全量镜像）：
  python tools/fetch_registry.py
  python tools/download.py --jobs 12
  python tools/download_editions.py --jobs 8     # 日期模板数据集的全部 edition 档案
  python tools/fetch_details.py --jobs 6         # 可选：抓 290 个详情页元数据（研究方法论/caveat 必需）

日常（建议每天一次，可用 --download 让变化自动落地）：
  python tools/monitor.py --refresh-registry --head
  python tools/monitor.py --refresh-registry --head --download
  python tools/monitor.py --head --webhook https://your.alert.endpoint

调试：
  python tools/download.py --ids fuelprice,population_malaysia   # 只下几个
  python tools/download.py --parquet-only                        # 只要 parquet
  python tools/download_editions.py --ids ridership_od_komuter,pricecatcher  # 只下某几个档案数据集
  python tools/monitor.py --head                                 # 只做 HEAD 扫描
  python tools/verify.py                                         # 校验已下载文件完整性

注意：注册表直链含字面 `YYYY-MM-DD` 的数据集（ridership_od_*、registration_transactions_*、pricecatcher）
不能直接用 download.py 拉取——它们按 edition 存档（link_editions），需用 download_editions.py；
这些数据集在 Open API 中亦不存在（exclude_openapi=true），无需在 API 增量层寻找。

## 5. API 增量拉取（4 次/分钟限流下的用法，官方格式）

  # 基本查询：取 fuelprice 前 3 条（id 见 registry 或详情页 "Sample OpenAPI query"）
  curl "https://api.data.gov.my/data-catalogue?id=fuelprice&limit=3"
  # 带 meta（查看记录总数与所用过滤条件）
  curl "https://api.data.gov.my/data-catalogue?id=fuelprice&meta=true&limit=10"
  # 时间窗口增量（适合高频数据集，监控“新增行”）
  curl "https://api.data.gov.my/data-catalogue?id=fuelprice&date_start=2026-09-01@date"

说明：全量历史请优先用 S3 直链文件（同一份数据的整表快照、不限流）；
API 用于①直链 404 的 API-only 数据集、②定制过滤/增量。请自报 User-Agent 并遵守限流。

## 6. 监控设计（三层信号）

| 监控目标 | 信号源 | 频率 | 成本 |
|---|---|---|---|
| 新增/下线/改名数据集 | 目录页注册表 diff | 每日 | 1 次页面请求 |
| 目录结构 / 机构清单 | S3 上 /metadata/metadata_category_en.json、/metadata/metadata_agencies.json | 每周 | 无 |
| 某数据集数据更新 | S3 文件 ETag / Last-Modified HEAD | 每日 | 580 次 HEAD，无配额 |
| 下次更新时间预测 | 详情页 next_update / frequency（可选抓 290 个详情页） | 每周 | 290 次页面请求 |
| API-only 数据集更新 | data_as_of / 时间戳增量拉取 | 按频率 | 4 次/分钟配额内 |
| 平台级变更 | developer.data.gov.my/changelog；GitHub data-gov-my/* | 每周 | 无 |

变化落地动作：重下变更文件 → 更新 manifest → 记 changelog（旧/新 ETag、时间）→ 通知（webhook/邮件）。

## 7. 合规与注意

- robots.txt 允许全爬；官方提供无 token API 并鼓励程序化使用。请使用可识别 User-Agent 并留联系方式。
- **务必遵守 4 次/分钟的 API 限流**；S3 直链虽不限流，仍建议并发 ≤16、避开高峰。
- 许可：页脚有 Terms of Use / Open Data Guiding Principles；各数据集元数据含口径与许可说明，
  对外发布成果前请核对具体条款（本调研未逐条核验）。
- 批量/高优先级需求可走官方通道：developer.data.gov.my（文档）、helpdesk、data-request 页。
- 本工具仅做抓取与镜像；研究口径以各数据集 methodology 为准（如人口 1970-2020 普查调整值 + 年中间隔估计，
  粒度随时间加深，跨年对比需谨慎）。

## 9. GitHub 发布与本仓库收录范围

仓库：**https://github.com/changwu/data-gov-my**（public）｜镜像快照日 **2026-09-09**

### 9.1 收录内容

| 内容 | 收录 |
|---|---|
| `tools/`（8 个纯标准库 Python 工具） | ✅ 全部 |
| `registry/`（290 条注册表 + 290 个详情页元数据） | ✅ 全部 |
| `DATA_INVENTORY.csv`（932 条文件清单） | ✅ |
| `data/manifest.json`、`data/editions_manifest.json`（ETag/大小/来源 URL） | ✅ |
| 当前快照 CSV + Parquet（557 文件，166 MB） | ✅ 全部 |
| edition 历史档案 Parquet（176 文件，257 MB） | ✅ 全部 |
| edition 历史档案 CSV（176 文件，8.28 GB） | ⚠️ 除 5 个 >100 MB 外全部收录（7115 MB） |

### 9.2 因 GitHub 单文件 100 MB 硬限制而未收录的 5 个文件

这些文件**并非缺失数据**：每个都有一份 Parquet 孪生文件已在本仓库中（列式格式，字段完全相同，仅编码不同）。
需要原始 CSV 时按 `source_url` 直接下载即可（S3 直链无需认证、无速率限制）。

| # | 文件 | 大小 | 本仓库中的 Parquet 孪生 | 下载地址 |
|---|---|---|---|---|
| 1 | `ridership_od_rapidrail_daily/rapidrail_2024_daily.csv` | 310.2 MB | `rapidrail_2024_daily.parquet` (5.3 MB) | https://storage.data.gov.my/transportation/rail/rapidrail_2024_daily.csv |
| 2 | `ridership_od_rapidrail_daily/rapidrail_2025_daily.csv` | 309.6 MB | `rapidrail_2025_daily.parquet` (5.5 MB) | https://storage.data.gov.my/transportation/rail/rapidrail_2025_daily.csv |
| 3 | `ridership_od_rapidrail_daily/rapidrail_2023_daily.csv` | 232.8 MB | `rapidrail_2023_daily.parquet` (3.7 MB) | https://storage.data.gov.my/transportation/rail/rapidrail_2023_daily.csv |
| 4 | `ridership_od_rapidrail_daily/rapidrail_2026_daily.csv` | 197.7 MB | `rapidrail_2026_daily.parquet` (3.5 MB) | https://storage.data.gov.my/transportation/rail/rapidrail_2026_daily.csv |
| 5 | `ridership_od_komuter/komuter_2024.csv` | 110.9 MB | `komuter_2024.parquet` (5.3 MB) | https://storage.data.gov.my/transportation/ktmb/komuter_2024.csv |

合计未收录 CSV 1.16 GB；`data/` 本地全量为 8.70 GB，本仓库收录约 7.54 GB。
（另有 `currency_codes` 的 CSV 在上游 storage.dosm.gov.my 本身就缺失，其 Parquet 已收录。）

### 9.3 分批推送与校验（已完成）

GitHub 单次 push 约 2 GB 上限，因此按「元数据 → 当前快照 → edition Parquet → edition CSV 分卷」共 **9 批**提交推送，
**2026-09-09 完成，用时 28 分钟，最终提交 `b379b9d`**（`main`）：

| 批次 | 内容 | 文件数 | 大小 |
|---|---|---|---|
| 1 | README / tools / registry / 清单 / 元数据 | 307 | 1.7 MB |
| 2 | 当前快照 CSV+Parquet | 557 | 166 MB |
| 3 | edition 档案 Parquet | 176 | 257 MB |
| 4–9 | edition 档案 CSV（分 6 卷） | 171 | 7.12 GB |
| | **合计** | **1211** | **7.54 GB** |

- commit 信息形如 `mirror: edition archives: CSV batch 3 (27 files)`；超限文件 GitHub 会拒绝整次 push，
  5 个 >100 MB 文件已由 `.gitignore` 排除（§9.2）。
- **传输方式**：SSH（`git@github.com:changwu/data-gov-my.git`）。本机 git 只带 schannel TLS 后端且不可用
  （`SEC_E_NO_CREDENTIALS`），HTTPS 推送失败，故改用系统 OpenSSH——见 `core.sshCommand` 指向的包装脚本
  `~/.ssh_dgm/ssh_github.cmd`，以及 `github.com` 在部分网络下需固定可用边缘 IP（`http.curloptResolve`）。
- **校验**：克隆远端仓库后逐条比对 blob SHA，**1211 条全部一致**（内容寻址 ⇒ 字节级一致）；
  抽样文件按 MD5 复核（`fuelprice.csv`、`komuter_utara_2020.csv`、`pricecatcher_2026-09.parquet`）全部 MATCH；
  5 个 >100 MB 文件确认不在远端树中。
- GitHub 对 50–100 MB 的文件会给出 "larger than recommended maximum" 警告（本仓库共有数十个），属提示而非错误，推送正常接受。
- 注意：仓库体积已远超 GitHub 建议的 1 GB，克隆较慢；日常研究建议只取所需子目录
  （`git clone --filter=blob:none --sparse` 或按需下载单个数据集目录）。

### 9.4 署名与许可

- 数据来源：**data.gov.my**（马来西亚政府开放数据门户），各数据集版权归相应机构（DOSM、JPJ、KPDN、KTMB、MOF 等）。
- 使用时请遵守该站 **Terms of Use** 与 **Open Data Guiding Principles**；转载/发布研究成果请注明原始来源与数据集名称。
- 本仓库中的工具脚本（`tools/`）为镜像与监控用途，可自由使用；镜像数据本身不主张任何新版权。

## 10. 建议下一步

1. 立即：跑通本目录工具，建立全量本地镜像，registry 即国别研究索引。
2. 一周内：每日监控任务 + 通知上线；向研究同事发布首版数据清单（`DATA_INVENTORY.csv`）。
3. 季度：按需补充实时通道（GTFS/天气/OpenDOSM 全部时间序列）；把镜像接入机构数据湖
   （Parquet → DuckDB / 湖格式），按国别政策研究专题建视图。
4. 长期：关注官方 changelog 与 GitHub；若目录页结构改版导致 fetch_registry 解析失败，按新结构更新解析器即可
   （注册表数据同时可在 S3 /metadata/ 下找到部分静态 JSON 作为对照）。

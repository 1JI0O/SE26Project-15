# TraceLab 压力测试方案

## 1. 目标与范围

本方案针对 `server/`（多用户云端同步服务，PostgreSQL）与 `backend/`（本地优先 FastAPI，SQLite）分别设计压力测试，目的不是给出漂亮的 TPS 数字，而是**定位并量化源码中已存在的容量边界**，为发布前的容量结论和后续调优提供证据。

范围内：

- server：认证、Workspace/项目、同步 `bootstrap/pull/push/ack`、Blob 分片上传与下载、`/admin-console` 只读页与维护任务。
- backend：项目/论文/仓库 CRUD、代码分析异步任务、张量流与工作区读接口、静态追溯、RAG 检索、Agent SSE 流。

范围外（明确不做，避免结论被误读）：

- 不测 MinerU 官方 API 与真实 LLM 服务的吞吐（外部依赖，且 `backend/tests/conftest.py` 约定测试不得访问网络）。LLM 相关路径用本地 stub 或 mock 上游替代。
- 不做前端渲染性能（Vue/Tauri）压测，只在稳态下抽样验证接口时延对交互的影响。
- 不在生产环境执行。所有破坏性阶段仅在隔离的 staging/本机环境执行。

压力测试纳入正式测试范围。本轮结果按第 8 节三类结论产出，作为容量与性能验收证据；对应用例与报告在 `FinalRelease/` 下同步更新（原“性能测试按要求不执行”的口径作废）。

## 2. 被测系统的真实约束（已按源码核对）

压测场景直接围绕这些数字设计，而不是凭经验猜测。

### 2.1 server 侧

| 约束 | 位置 | 值 |
|---|---|---|
| API 进程数 / 资源 | `server/compose.yaml` | `uvicorn --workers 2`，`cpus: 1.5`，`mem_limit: 3g` |
| DB 连接池 | `server/tracelab_server/db/session.py` | `create_engine(..., pool_pre_ping=True)`，未指定 `pool_size`/`max_overflow`，即 SQLAlchemy 默认 5+10=15 连接/进程，2 进程共 30 |
| 请求执行模型 | `server/tracelab_server/api/routes/*.py` | 除 `blobs.upload_chunk` 外全部为同步 `def`，由 AnyIO 线程池承载（默认 40 线程/进程） |
| 认证限流 | `auth/service.py:79`、`api/routes/auth.py` | register 5、login 10、refresh 30、forgot 5；bucket 行用 `with_for_update()` 加锁 |
| 同步批量上限 | `schemas/cloud.py:190`、`api/routes/sync.py:119` | push 每请求 1–100 个 operation；pull `limit ≤ 500` |
| 分片上传 | `core/config.py`、`storage/blob_store.py:33` | chunk 默认 8 MiB（1–32 MiB）；`await request.body()` 整片入内存；每片 `os.fsync`；分片必须严格顺序追加，偏移不符返回 409 |
| 体积与配额 | `core/config.py` | PDF ≤100 MiB、ZIP ≤500 MiB、账号配额 5 GiB、项目配额 2 GiB；磁盘 80% 告警 / 90% 停写 |
| 维护 Worker | `worker.py:34` | 轮询间隔 2 s |
| **workspace 写锁** | `services/cloud_sync.py:230,388` | `apply_operation` 每个 operation 都 `SELECT ... FROM workspace ... FOR UPDATE` |
| 口令哈希 | `auth/password.py` | Argon2id，`memory_cost=64 MiB`、`time_cost=3`、`parallelism=2` |
| 单事件 payload | `services/cloud_sync.py` | 超过 `MAX_EVENT_PAYLOAD_BYTES` 返回 413，要求改用 blob 引用 |

由此得到三个按优先级排列的待验证假设，压测就是为了证实或推翻它们。

**H1：同一 workspace 的写入是串行的。** `apply_operation` 在处理每个 operation 时都对该 workspace 行取 `FOR UPDATE`，且逐 operation 提交。这意味着一个 100 ops 的 push 会反复抢同一把锁，而同 workspace 的所有设备写入完全串行。push 吞吐的上限由单 operation 的锁持有时间决定，与并发设备数基本无关；并发只会转化为等待。这比连接池更早成为瓶颈，所以 S2 的优先级提到与 S1 同级。

**H2：线程池宽于连接池。** 40 线程/进程对 15 连接/进程（2 进程共 80 对 30）。同步读写压力下预期出现 `QueuePool limit ... timed out`（默认等待 30 s）而非平滑降级。叠加 H1 的锁等待会更早触发：线程持锁等待时连接不释放。

**H3：登录是 CPU 与内存密集操作。** Argon2id 每次校验约占 64 MiB 内存、跑 3 轮、用 2 线程，而 api 容器只有 `cpus: 1.5` / `mem_limit: 3g`。少量并发登录即可打满 CPU 并挤压其他请求。同时 `enforce_rate_limit` 对同一 bucket 行 `FOR UPDATE`，同 IP 并发登录再叠一层串行化。

因此除 S5 外，所有场景必须**预签发 token 并复用**：否则先撞 429 与 Argon2 的 CPU 墙，根本测不到目标接口。

### 2.2 backend 侧

| 约束 | 位置 | 值 |
|---|---|---|
| 数据库 | `app/db/session.py` | SQLite，`journal_mode=WAL`，`timeout=30`，`check_same_thread=False`；WAL 仍是单写者 |
| 代码分析线程池 | `app/services/analysis_jobs.py:17` | `TRACELAB_ANALYSIS_WORKERS` 默认 2（1–8） |
| Agent 会话线程池 | `app/services/agent/conversations.py:72` | `max_workers=4` |
| Agent 分析线程池 | `app/services/agent/analysis_jobs.py:59` | `max_workers=2` |
| 论文解析线程池 | `app/services/document_parsers/jobs.py:66` | `max_workers=1` |
| 追溯子 Agent 并行度 | `app/core/config.py` | `tracelab_trace_subagent_parallelism` 默认 3（0–8） |
| 归档导入上限 | `app/services/code_analysis/constants.py` | 20 000 文件 / 512 MiB 解压后；单源文件 512 KB |
| 同步分析阈值 | `app/core/config.py` | `tracelab_analysis_inline_max_bytes=512_000`，超过则转异步任务 |
| SSE 流 | `app/api/routes/agent.py:580,794` | 分析任务与 run 事件流，长连接 |
| 云端代理超时 | `app/core/config.py` | `tracelab_cloud_proxy_timeout_seconds=120` |

backend 是单用户本地服务，压测目标不是并发用户数，而是**队列深度与长任务下的可用性**：小池子（1–4 worker）被长任务占满时，交互式读接口是否仍然可用；SQLite 单写者在写密集场景下是否触发 30 s 锁等待。

## 3. 环境与基线

- server：Docker Compose 起 `postgres + migrator + api + worker`，保持 `compose.yaml` 默认资源限制（这是发布配置，压测必须测发布配置）。`APP_ENV=staging`，`CLOUD_SYNC_FEATURE_ENABLED=true`，`CLOUD_REQUIRE_EMAIL_VERIFICATION=false`（仅压测环境，用于批量制备已验证账号），SMTP 留空。
- backend：`uv run uvicorn app.main:app --host 127.0.0.1 --port 8000`（不加 `--reload`），`TRACELAB_LLM_ENABLED=false`；需要测 Agent 路径时指向本机 mock OpenAI-compatible 服务。数据目录指向隔离路径，参照系统测试用的 `D:/tmp/tracelab-*`。
- 压测客户端与被测服务分离进程；server 场景建议客户端独立于 Docker 主机 CPU 配额之外，避免客户端与服务抢 CPU 造成误判。
- 每个场景执行前重建数据集，记录数据规模（账号数、workspace 数、实体数、事件数、blob 总字节）。结论必须绑定数据规模，否则不可复现。

数据制备用独立脚本（建议 `server/scripts/seed_stress_data.py`、`backend/scripts/seed_stress_data.py`），直连数据库批量写入，不走限流接口。制备内容至少覆盖：

- server：50 账号 / 10 workspace / 每 workspace 20 项目 / 每项目 2 000 条 `sync_event`（用于 pull 分页与 `workspace_seq` 递增竞争）。
- backend：1 个项目含 1 篇已解析论文、1 个 5 000 文件规模仓库快照、2 000 条追溯链接、RAG 索引已建。

## 4. 工具选型

主工具 **Locust**（Python，贴合仓库 `uv` 工具链，可直接复用 `httpx` 与既有 schema 生成请求体，且能用自定义 `User` 处理 SSE 长连接）。放在 `stress/` 目录，用独立 `pyproject.toml` 管理，**不写入 backend/server 的依赖**，避免影响 CI 的 `uv sync --frozen`。

辅助：

- `pg_stat_statements` + `pg_stat_activity` 抓 server 慢查询与连接数；
- `docker stats` / `cAdvisor` 抓容器 CPU、内存、IO；
- backend 侧用 `py-spy` 抽样火焰图定位 GIL 与线程池阻塞。

不选 k6 的原因：SSE 与分片上传的顺序约束用 Python 表达更直接，且团队栈已是 Python。

## 5. 场景矩阵

每个场景给出并发模型、负载参数、观测重点和判定线。判定线是**本轮待验证的目标值**，若实测不达标，结论是记录容量上限与瓶颈定位，而不是自动判失败。

### S1 同步读写混合（server，最高优先级）

- 模型：N 个虚拟设备，循环 `GET /sync/pull` → `POST /sync/push`（每次 20 ops）→ `POST /sync/ack`，读写比 3:1。token 预签发。
- 阶梯：N = 10 → 30 → 60 → 120 → 240，每级稳态 5 min。
- 观测：p50/p95/p99 时延、错误率与错误分类（499/500/503 与 `QueuePool timed out`）、`pg_stat_activity` 活跃连接、`workspace_seq` 冲突比例、AnyIO 线程池排队。
- 判定：N=60 时 p95 < 800 ms、错误率 < 0.5%；出现连接池超时即记录为容量上限，并确认是否需要显式配置 `pool_size/max_overflow` 与 `anyio` 线程上限。

### S2 同一 workspace 写热点（server，与 S1 同级，验证 H1）

- 模型：设备全部 push 到**同一** workspace，制造 `workspace_seq` 与实体版本竞争。分两组对照：
  - A 组：并发 10 / 20 / 40 / 80，每 push 固定 20 ops，写同一 workspace；
  - B 组：同样并发，但每设备写**各自独立**的 workspace。
- 关键观测：A/B 两组的 push 吞吐比。若 H1 成立，A 组吞吐随并发上升迅速趋平（受单 operation 锁持有时间约束），B 组则接近线性扩展。
- 同时观测：`pg_locks` 上 `workspace` 行锁的等待链、`conflict` 占比、`pg_stat_activity` 中 `Lock` 等待事件占比、push p99 随并发的增长曲线。
- 另测 ops 批量大小对锁的影响：并发固定 20，每 push 分别 1 / 20 / 100 ops，比较单 operation 有效吞吐。
- 判定：无未捕获 500，冲突全部以 `conflict` 语义返回，`workspace_seq` 单调递增且无空洞或重复。吞吐结论以 A/B 对照比值形式记录，作为是否需要下沉锁粒度（改为实体级锁或序列号原子自增）的依据。

### S3 大分页 pull 与冷启动 bootstrap（server）

- 模型：20 设备并发 `limit=500` 连续翻页拉完 2 000 事件；另 20 设备并发 `GET /sync/bootstrap`。
- 观测：单页时延随 `after` 增大的漂移（索引有效性）、响应体大小、内存峰值。
- 判定：翻页时延不随偏移线性增长；api 容器内存不触及 3 g 上限。

### S4 分片上传并发（server）

- 模型：单 blob 内分片必须顺序，所以并发维度是 blob 数。12 / 24 / 48 个并发上传，每个 60 MiB（约 8 片 × 8 MiB），穿透 `upload-init → chunks → complete → download`。
- 观测：吞吐（MiB/s）、api 容器内存（并发 × 8 MiB 整片入内存）、`fsync` 导致的磁盘 await、409 偏移错误率、配额与磁盘水位（80%/90%）行为。
- 判定：48 并发下不 OOM、不 502；触达配额/水位时返回明确业务错误而非 5xx。

### S5 认证成本与限流（server，验证 H3）

- 模型三组：
  - 限流内合法登录：多个不同 IP/账号并发登录，控制在每 bucket 上限内，测 Argon2 校验的真实吞吐与 CPU 占用；
  - 超限压测：故意超 `login`(10)/`refresh`(30)/`register`(5) 上限，验证限流稳定性与 bucket 行 `FOR UPDATE` 竞争；
  - 叠加：S1 稳态运行中注入登录流量，观测 Argon2 对同步链路的挤压。
- 观测：登录 p95/p99、api 容器 CPU 与内存峰值（64 MiB × 并发）、429 命中准确性、锁等待、同步链路时延劣化幅度。
- 判定：429 不退化为 5xx；限流请求自身 p99 < 500 ms；记录单实例可持续登录 QPS 作为容量结论。若登录流量能显著劣化同步链路，产出隔离建议（独立 worker 或降低 Argon2 参数的权衡分析）。

### S6 管理台与维护任务并发（server）

- 模型：S1 稳态 60 并发运行中，叠加 `/admin/metrics`、`/admin/audit`、`/admin/jobs` 轮询，并触发 `maintenance/gc` 与 `compact-events`。
- 观测：维护任务对同步链路时延的影响、Worker 2 s 轮询下的任务堆积。
- 判定：同步 p95 劣化 < 30%；维护任务不阻塞写入。

### S7 代码分析队列饱和（backend）

- 模型：连续提交 12 个仓库导入（含接近 20 000 文件 / 512 MiB 上限的一个），队列深度远超 2 worker；同时以 1 rps 轮询 `GET /workspace/code-tree`、`/workspace/code-files/*`、`/workspace/tensor-flow`。
- 观测：任务排队时延、读接口 p95、SQLite `database is locked` 次数、进程 RSS。
- 判定：读接口 p95 < 1 s 且无 5xx；任务不丢失、状态机可恢复。

### S8 Agent SSE 长连接与并发运行（backend）

- 模型：8 条会话并发触发 run（mock LLM，每 run 约 60 s），全程订阅 `/runs/{id}/events` 与 `/analysis-jobs/{id}/events`；期间随机断开 30% 连接再重连。
- 观测：SSE 连接存活、事件不重不漏、`max_workers=4` 会话池与 `=2` 分析池的排队、断连后服务端资源是否回收。
- 判定：无事件丢失或重复投递；断连不产生泄漏的线程或任务；重启后 lifespan 能恢复中断任务。

### S9 写密集混合（backend）

- 模型：追溯链接批量增删改 + 代码文件保存（`PUT /workspace/code-files/*`，接近 512 KB）+ RAG 检索并发，持续 10 min。
- 观测：SQLite 写锁等待、30 s timeout 触发次数、WAL 文件增长与 checkpoint 行为。
- 判定：无请求因锁等待超时失败；WAL 不无界增长。

### S10 浸泡与尖峰（两侧）

- 浸泡：server 以 S1 的 40 并发运行 4 h；backend 以 S9 的一半强度运行 4 h。观测内存与句柄单调增长、连接泄漏、磁盘增长。
- 尖峰：10 → 200 并发在 10 s 内拉升，维持 2 min 后回落。观测恢复时间与是否出现雪崩式失败。
- 判定：浸泡期内 RSS 与句柄数无持续上升趋势；尖峰回落后 60 s 内恢复稳态时延。

## 6. 观测指标与采集

统一采集，全部落盘为可复算的原始数据，不只保留汇总图。

- 客户端侧：每请求的 name、状态码、时延，导出 Locust CSV（`_stats.csv`、`_failures.csv`、`_stats_history.csv`）。
- 服务侧：容器 CPU/内存/IO 时序；PostgreSQL 连接数、等待事件、慢查询 Top 20；backend 进程 RSS、线程数、`py-spy` 采样。
- 应用侧：错误分类计数（限流 429、冲突 409、配额 413、连接池超时、锁超时），这类分类比总错误率更能定位瓶颈。
- 环境快照：提交号、镜像 tag、compose 配置、数据规模、客户端机器规格。

## 7. 执行阶梯

每个场景统一按五段执行：预热 1 min → 爬坡（按 5 节给定阶梯）→ 稳态 5 min → 尖峰 2 min → 回落观察 2 min。浸泡场景单独排期。任一级出现错误率 > 5% 或 p99 > 10 s 即停止升压，记录该级为上限。

排期建议：S1/S2/S4 优先（云端多用户主路径），S7/S8 次之（本地长任务可用性），其余随后；S10 放在参数确定后执行。

## 8. 判定标准

一次压测轮次的产出必须包含以下三类结论，缺一不算完成：

1. **容量结论**：每个场景在给定资源下的最大稳定并发与对应 p95/p99。
2. **瓶颈定位**：瓶颈在 CPU、连接池、线程池、磁盘 IO 还是锁，附证据（连接数曲线、等待事件、火焰图）。
3. **正确性结论**：压力下语义是否仍然正确——同步序列单调、冲突可判定、上传字节一致（sha256 校验）、SSE 事件不重不漏、配额与限流准确。

正确性失败的严重级高于时延不达标。压力下出现数据错乱按缺陷处理并登记到 `FinalRelease/缺陷清单_TraceLab.md`。

## 9. 风险与注意事项

- 压测账号与数据必须在隔离环境创建；不得对生产或共享 staging 执行 S4/S6/S10。
- `maintenance/gc` 会删除 blob，只能在压测专用环境触发。
- 客户端成为瓶颈是常见误判来源：每轮记录客户端 CPU，若客户端饱和则结论无效。
- 限流会掩盖真实瓶颈，除 S5 外一律预签发 token 并复用。
- 大体积上传会快速逼近磁盘水位，执行前确认可用空间 ≥ 场景总字节的 2 倍。

## 10. 产出物

- `stress/`：Locust 场景脚本、数据制备脚本、运行入口（独立依赖，不进 CI 的 frozen 安装）。
- `docs/stress-test-report.md`：按第 8 节三类结论组织，附原始 CSV 与监控快照路径。
- 若压测确认了第 2 节的连接池/线程池假设，产出对应的配置调整提案（显式 `pool_size`/`max_overflow`、AnyIO 线程上限、worker 数与资源配额），并同步更新 `docs/architecture.md` 中的部署描述。

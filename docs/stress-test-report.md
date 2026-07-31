# TraceLab 压力测试报告

对应方案：[`stress-test-plan.md`](stress-test-plan.md)。面向汇报的概要见 [`stress-test-summary.md`](stress-test-summary.md)；本文为完整执行记录与原始证据。

执行环境为一次性隔离环境，全部端口仅绑定 127.0.0.1，未接触生产或共享环境。

## 1. 执行范围

| 场景 | 目标 | 状态 |
|---|---|---|
| S1 | 同步推拉阶梯加压（H2 连接池） | 已执行 |
| S2 | 同一 Workspace 写热点（H1 行锁） | 已执行 |
| S3 | 大 Workspace 分页拉取 | 已执行 |
| S4 | Blob 分块上传/下载一致性 | 已执行 |
| S5 | 登录鉴权（H3 Argon2 成本） | 已执行 |
| S6 | 管理端 + 维护任务叠加同步稳态 | 已执行 |
| S7 | 本地后端解析/分析队列饱和 | 已执行 |
| S8 | Agent SSE 并发会话 | **未执行**（需 mock LLM 服务，本轮不具备） |
| S9 | SQLite WAL 并发写 | 已执行 |
| S10 | 尖峰（10→200） | 已执行 |
| S10 | 4 小时耐久 soak | **未执行**（时间预算不足） |

偏差记录：

- S1 各档稳态时长取 3 分钟而非方案中的 5 分钟，用于在单机时间预算内覆盖更多档位；结论为吞吐平台期，缩短稳态不影响判定方向。
- `monitoring/collect_server.sh` 的 `PG_CONTAINER` 默认值原为 `tracelab-postgres`，与隔离环境实际容器名 `tlstress-postgres-1` 不符，且所有 psql 探针都重定向了 stderr，导致本轮 PostgreSQL 采样 CSV 全程为空而未报错。**本报告中的锁等待与连接数证据均来自临时 psql 直查，而非该采样脚本。** 已修正默认值并加入容器可达性前置检查（不可达即退出而非静默产出空文件）。

## 2. 容量结论

**云端同步服务（api 限 cpus 1.5 / mem 3g，`--workers 2`）**

| 场景 | 并发 | 吞吐 | p50 | p95 | 错误率 |
|---|---|---|---|---|---|
| S1 | 10 → 240 | 26–29 rps（全程持平） | — | — | N≥120 起 5xx |
| S1 | 60 | 25.77 rps | push 6100 ms | push 9200 ms | 0% |
| S3 | 分页拉取 | — | 25–68 ms | — | 0% |
| S4 | 4 / 8 并发 blob | ~54 MiB/s 双向 | — | — | 0% |
| S6 | 60 + 管理端叠加 | 35.16 rps | push 4700 ms | push 6400 ms | 0% |
| S10 尖峰 | 200（保持 2 min） | 18.3 rps | 63 ms | 40 s | 3.9% |

**最大稳定并发结论：远低于方案预设档位。** 吞吐从 N=10 到 N=240 稳定在 26–29 rps，说明饱和点落在 N=10 与 N=30 之间。N=60 时错误率仍为 0%，但 push p95 已达 9200 ms，不满足方案 p95 < 800 ms 的判定，因此**可接受的稳定并发上限低于 60**。

写入吞吐上限约 130 ops/s，与批大小无关：单 op 12.4 ops/s、20 op 批 140.8 ops/s、100 op 批 117.7 ops/s。加大批只是把吞吐换成时延（100 op 批 p50 13.75 s）。

**本地后端（SQLite WAL）**：S9 在 24 并发写入下零 `database is locked`，错误率 0.09%。

## 3. 瓶颈定位

### H2 确认成立：SQLAlchemy 连接池，而非线程池

直接证据来自 api 容器日志：

```
QueuePool limit of size 5 overflow 10 reached, connection timed out, timeout 30.00
```

N=120 首次出现，S1 全程 187+ 次，尖峰场景 274 次。AnyIO 线程池每进程 40，而连接池每进程 5 + 10 溢出 = 15，两 worker 合计 30 —— 线程拿到执行权却拿不到连接，在 30 s 后超时。

**这是缺陷而非单纯容量问题**：池耗尽以未捕获 ASGI 异常冒泡为 500，而不是优雅的 503 + Retry-After。客户端无法区分"过载请重试"与"服务出错"。

### H1 需要修正，不是简单确认

锁本身真实存在且被直接观测到：`pg_stat_activity` 显示 22–28 个后端同时阻塞在 `workspace` 行的 tuple lock 上，阻塞语句正是 `_lock_workspace` 的 `SELECT ... FOR UPDATE`，峰值 28 逼近 30 连接上限。

但**隔离 workspace 的对照组反而更慢**：

| 分组 | push p50 | 吞吐 |
|---|---|---|
| 共享热点 | 3742 ms | 7.07 rps |
| 隔离 workspace | 4578 ms | 5.55 rps |

行锁在此并发下起到了准入控制作用。移除热点后更多请求真正并行，直接把 CPU 打满（api 峰值 153.6%，预算 150%）。**该并发下的天花板是 CPU，不是锁。** 内存不是约束（248 MiB / 3 GiB）。

结论：H1 的机制描述正确，但"消除热点锁即可提升吞吐"的推论不成立；先扩 CPU 再谈锁优化。

### H3 部分成立，但被限流遮蔽

Argon2id 单次校验实测 59.8 ms / 64 MiB，对应约 25 logins/s 的 CPU 上限。但登录限流为 10/min（IP 与邮箱双维度），比 Argon2 上限早约 150 倍触发。**单 IP 压力源无法触达 Argon2 瓶颈**，方案中的 `within_limit` 模式在单生成器下不可复现。

附带发现（安全相关）：`server/tracelab_server/api/routes/auth.py:57` 的 `_client_ip` 直接取 `X-Forwarded-For` 第一个值，无可信代理白名单，而 nginx 是 append 而非 replace —— 应用层 per-IP 桶可被伪造。部署配置中由 nginx 自身的 `limit_req_zone $binary_remote_addr rate=10r/m` 兜底，因此线上风险有限，但应用层不应单独依赖该字段。

### S6：管理端与维护任务不构成额外瓶颈

同状态对照（同一次 seed 后连续执行，避免数据量漂移）：

| 分组 | push p50 | push p95 | 聚合吞吐 | 错误率 |
|---|---|---|---|---|
| 对照（无叠加） | 4700 ms | 6700 ms | 34.39 rps | 0% |
| S6（管理端 + gc + compact） | 4700 ms | 6400 ms | 35.16 rps | 0% |

同步 p95 劣化 ≈ 0（落在轮次噪声内），满足 < 30% 判定。管理端 491 次请求零失败，p95 1900 ms。

维护任务确实执行而非仅入队：`background_job` 表确认 45 个 `gc_tombstones` + 49 个 `compact_sync_events` 全部 `completed`，且期间写入速率未下降 —— "维护不阻塞写入"结论有效，非空判定。

### S7：读可用但显著退化

分析队列饱和时读请求零失败，但聚合 p50 从 46 ms 升至 610 ms（约 13×），p95 从 72 ms 升至 4100 ms（约 57×）。

### S10 尖峰：可恢复，但积压需约 2 分钟排空

10 → 200（10 s 内）保持 2 分钟：p95 40 s、p99 85 s、最大 124 s，错误率 3.9%（187 次 5xx，根因同为连接池超时）。

回落到 10 并发后的恢复轨迹：

| 回落后时间 | 吞吐 | p50 | 失败/s |
|---|---|---|---|
| +0–15 s | 9.5 rps | 180 ms | 2.90 |
| +45–60 s | 8.5 rps | 117 ms | 0.03 |
| +75–90 s | 26.5 rps | 45 ms | 0 |
| +105–120 s | 26.3 rps | 27 ms | 0 |

吞吐与 p50 在约 75 s 内完全恢复到尖峰前水平（26 rps / 20 ms），失败在 60 s 内归零。尖峰期间发出的请求耗时 60–124 s 才完成，其回填使恢复窗口的 p95 仍显示 60 s 量级 —— 即**服务本身自愈，但请求积压需要完整 2 分钟排空**。压测结束后 `/api/v1/health` 正常，无需人工干预。

## 4. 正确性结论

正确性整体通过，无数据错乱：

- **字节一致性**：S4 完成 203 次带 sha256 校验的下载，0 处不匹配。
- **同步序列**：S1/S6/S10 全程未出现游标回退或事件丢失；ack 与 pull 语义在饱和下保持。
- **SQLite WAL**：24 并发写入零 `database is locked`。注意 WAL 增长到 124 MB（DB 146 MB）而未触发 checkpoint，长期运行需关注。
- **限流准确性**：10/min 双维度限流按预期生效，未观察到漏放。
- **SSE 不重不漏**：未验证（S8 未执行）。

但压力下暴露 4 个功能缺陷，其中 1 个为可用性阻断级。

## 5. 缺陷清单

### D1（严重）`recover_repository_analysis` 使后端永久无法启动

`backend/app/services/analysis_jobs.py:203-229`：`session.commit()` 使属性过期，session 关闭后再读 `job.job_id`，抛 `DetachedInstanceError`，lifespan 失败 → `Application startup failed. Exiting.`

**任何非正常关机只要遗留 `queued`/`running` 的 `RepositoryAnalysisJob`，后端就再也起不来。** 本轮已确定性复现（重启后遇到，隔离验证），只能手工清理 8 条卡住的记录才恢复。这是数据依赖的启动死锁，用户无自助恢复路径。

### D2（高）`upload_init` 留下不可恢复的中毒状态

`server/tracelab_server/api/routes/blobs.py:139-200`：删除 `failed` 状态的 `BlobObject` 时未清理其子 `upload_session`，外键为 `NO ACTION`，导致该 sha256 的**每一次后续重试都永久 500**。

### D3（中）`trace_links` 去重存在 TOCTOU 竞态

`backend/app/api/routes/traces.py:149` 的预检查与 `:166` 的插入非原子。并发提交相同 pair 时触发 `UNIQUE constraint failed: trace_link.fingerprint` → 500，而串行下同样的重复请求返回 409。应改为依赖唯一约束并捕获 `IntegrityError` 转 409。

### D4（低）畸形 PDF 返回 500 而非 400

`backend/app/api/routes/papers.py:161` / `app/services/paper_parser.py:52`：pypdf 解析异常直接冒泡为 500，应作为客户端输入错误返回 400。

### D5（中）连接池耗尽返回 500 而非 503

见 3.1。属容量退化路径的错误语义问题，影响客户端重试策略。

## 6. 建议优先级

1. 修 D1 —— 阻断级，影响所有本地用户的正常启动。
2. 提高 api 连接池上限至与线程池匹配，或反向收窄线程池；同时把池超时映射为 503 + Retry-After（D5）。
3. 扩 api CPU 预算 —— 当前 1.5 core 是同步写入的实际天花板，先于任何锁优化。
4. 修 D2、D3 的重试与竞态语义。
5. 为 `_client_ip` 增加可信代理白名单，不单独依赖 `X-Forwarded-For` 首值。
6. 补 S8（Agent SSE）与 4 小时 soak，二者是本轮唯一未覆盖的判定项。

## 7. 修复记录

D1–D5 已全部修复，每项附回归测试。本节记录改动位置与验证方式；第 5 节的缺陷描述保留为压测发现的原始记录。

| 缺陷 | 改动 | 回归测试 |
| --- | --- | --- |
| D1 | `backend/app/services/analysis_jobs.py` —— 在 `commit()` 前取出 `job_id`，不再依赖过期属性 | `backend/tests/repositories/test_repository_analysis_recovery.py` |
| D2 | `server/tracelab_server/api/routes/blobs.py` —— 删除 `failed` blob 前先删子 `upload_session`，并在两次 delete 之间 `flush()` 强制顺序 | `server/tests/integration/test_blob_failed_retry.py` |
| D3 | `backend/app/api/routes/traces.py` —— 预检查降级为快路径，`flush()` 捕获 `IntegrityError` 转 409 | `backend/tests/tracing/test_trace_duplicate_race.py` |
| D4 | `backend/app/api/routes/papers.py`、`app/services/paper_parser.py` —— pypdf 解析异常转 400 | `backend/tests/papers/test_upload_validation.py` |
| D5 | `server/tracelab_server/core/config.py`、`db/session.py`、`main.py`、`compose.yaml` —— 池宽度可配置、超时映射为 503 + `Retry-After` | `server/tests/unit/test_pool_config.py` |

两处需要说明的细节：

- **D2 的顺序问题**：这些 SQLModel 表未声明 ORM `relationship()`，工作单元没有依赖可排序，同一次 flush 内父行 DELETE 可能先于子行发出，因此显式 `flush()` 是修复的必要部分而非冗余。原有 server 套件看不到这个缺陷，是因为 SQLite 默认 `PRAGMA foreign_keys=OFF`；新测试显式打开，并单独断言约束确实生效。
- **D5 不是把池开到最大**：`compose.yaml` 中 api 取 12+8（× 2 workers = 峰值 40），postgres 同步上调 `max_connections=200`。没有开得更宽，因为 postgres 被限在 `cpus: 1.0`，更多并发连接只会在 CPU 上排队。连接预算表见 `server/README.md`。

验证：backend `336 passed` + ruff 通过；server `tests/unit` 与 D2 测试共 `6 passed`，ruff 通过。server 完整套件另有 4 项失败，位于 `tests/integration/test_cloud_auth_sync.py`，原因是 `blob_store.disk_percent()` 读宿主真实磁盘（本机 C: 92% > `cloud_disk_stop_percent` 90）导致 upload-init 返回 507。已通过在干净 HEAD 上复现确认为既有测试的环境脆弱性，与本次改动无关；该套件未打 `disk_percent` 补丁，本次也未改动它。

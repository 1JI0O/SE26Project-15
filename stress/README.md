# TraceLab 压力测试工程

独立依赖，不进 `backend/` 或 `server/` 的 lockfile，因此不影响 CI 的 `uv sync --frozen`。

方案与判定标准见 [`../docs/stress-test-plan.md`](../docs/stress-test-plan.md)。

## 安装

```bash
cd stress
uv sync --extra seed          # 需要制备数据时；纯压力机可省略 --extra seed
```

## 一、制备数据（server 场景）

制备脚本直连 PostgreSQL 批量写入，**绕过限流与 Argon2 登录成本**，并直接签发 access token
写入 `identities.json` 供 Locust 复用。这是方案 H3 要求的前提。

```bash
cd stress
export TRACELAB_STRESS_DB="postgresql+psycopg://tracelab:tracelab@127.0.0.1:5432/tracelab"
export CLOUD_JWT_SECRET="<与被测 server 完全一致的密钥>"

uv run python -m seed.seed_server \
  --users 50 --workspaces 10 --projects-per-workspace 20 \
  --events-per-project 100 --out identities.json
```

`CLOUD_JWT_SECRET` 必须与被测实例一致，否则签出的 token 会被 401。

access token 默认有效期 15 分钟（`cloud_access_token_minutes`）。超过 15 分钟的场景（S10 浸泡）
用 `--token-minutes` 签发长效 token，或让 Locust 走 `--refresh-tokens` 模式。

清理：

```bash
uv run python -m seed.seed_server --cleanup
```

只删除本工具创建的、带 `stress-` 前缀的账号与其级联数据。

## 一之二、制备数据（backend 场景）

backend 场景**必须**用一个已上传论文与代码仓库的项目，否则测不到目标路径：

- `POST /projects/{id}/trace-links` 在缺少任一侧时直接返回 409
  （`backend/app/api/routes/traces.py:122`），写场景会退化成纯错误流量；
- `GET /workspace/code-tree`、`/workspace/code-files/{path}` 在没有代码归档时返回 404。

因此执行 S7/S9 前先手工或用脚本完成：新建项目 → 上传并解析一篇论文 → 导入一个仓库
（建议接近 `MAX_ARCHIVE_FILES=20000` / 512 MiB 上限的一个，用于制造队列深度）→ 建好 RAG 索引。
`STRESS_CODE_PATH` 取该仓库中一个真实存在的可编辑文本文件路径。

准备完成后用 health 与一次手工请求确认前置成立，再开始压测：

```bash
curl -s "http://127.0.0.1:8000/api/v1/projects/<id>/workspace/code-tree" -o /dev/null -w '%{http_code}\n'
# 期望 200；404 表示代码归档尚未导入，此时 S7/S9 结论无效
```

## 二、执行场景

```bash
# S1 同步读写混合
uv run locust -f locustfiles/server_sync.py --host http://127.0.0.1:8000 \
  -u 60 -r 10 -t 5m --csv results/s1_60 --headless

# S2 写热点 A/B 对照（验证 H1：workspace 行锁是否串行化写入）
STRESS_HOTSPOT=shared uv run locust -f locustfiles/server_sync.py \
  --host http://127.0.0.1:8000 -u 40 -r 10 -t 5m --csv results/s2a_40 --headless
STRESS_HOTSPOT=isolated uv run locust -f locustfiles/server_sync.py \
  --host http://127.0.0.1:8000 -u 40 -r 10 -t 5m --csv results/s2b_40 --headless

# S4 分片上传并发
uv run locust -f locustfiles/server_blobs.py --host http://127.0.0.1:8000 \
  -u 24 -r 4 -t 5m --csv results/s4_24 --headless

# S5 认证成本与限流
STRESS_AUTH_MODE=within_limit uv run locust -f locustfiles/server_auth.py \
  --host http://127.0.0.1:8000 -u 10 -r 2 -t 3m --csv results/s5_within --headless

# S7 backend 读可用性（队列饱和期间）
STRESS_PROJECT_ID=1 uv run locust -f locustfiles/backend_workspace.py \
  --host http://127.0.0.1:8000 -u 8 -r 2 -t 10m --csv results/s7_8 --headless

# S9 backend 写密集（SQLite 单写者）
STRESS_PROJECT_ID=1 STRESS_WRITE=1 STRESS_CODE_PATH=src/model.py \
  uv run locust -f locustfiles/backend_workspace.py \
  --host http://127.0.0.1:8000 -u 8 -r 2 -t 10m --csv results/s9_8 --headless
```

S7 的语义是「后台分析队列被占满时读接口是否仍可用」，所以执行 S7 期间要**另外**并行提交
仓库导入以压满 `TRACELAB_ANALYSIS_WORKERS`（默认 2）的队列，locust 只负责产生读流量并测量其时延。

环境变量汇总见各 locustfile 顶部注释。

## 三、监控采集

压测期间另开终端：

```bash
bash monitoring/collect_server.sh results/s1_60      # docker stats + pg 快照
bash monitoring/collect_backend.sh results/s7_8      # RSS/线程数 + py-spy 采样
```

`monitoring/pg_probes.sql` 是连接数、等待事件、行锁等待链与慢查询 Top 20 的取样查询，
`collect_server.sh` 按 5 s 间隔落盘为时序 CSV。H1/H2 的证据主要来自这里。

## 四、结论归档

原始 CSV 与监控快照留在 `results/<场景>_<并发>/`，结论写入 `../docs/stress-test-report.md`，
按方案第 8 节的容量、瓶颈、正确性三类组织。压力下的正确性缺陷登记到
`../FinalRelease/缺陷清单_TraceLab.md`。

## 注意

- 仅在隔离环境执行。`S4`/`S6`/`S10` 会写入大量 blob 并可能触发 `maintenance/gc` 删除数据。
- 每轮记录压力机自身 CPU；压力机饱和则该轮结论无效。
- 执行 S4 前确认磁盘可用空间 ≥ 场景总字节的 2 倍。

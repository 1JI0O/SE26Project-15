# 论文解析接口契约

## 接入方式

TraceLab 通过独立的本地 `mineru-api` 解析论文。后端默认地址为
`http://127.0.0.1:8001`，避免与 TraceLab FastAPI 的默认 8000 端口冲突。

```bash
mineru-api --host 127.0.0.1 --port 8001 --enable-vlm-preload true
```

可配置环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TRACELAB_MINERU_URL` | `http://127.0.0.1:8001` | MinerU FastAPI 地址 |
| `TRACELAB_MINERU_BACKEND` | `hybrid-auto-engine` | MinerU 解析后端 |
| `TRACELAB_MINERU_LANGUAGE` | `ch` | OCR 语言提示 |
| `TRACELAB_MINERU_PARSE_METHOD` | `auto` | 文本/OCR 自动选择 |
| `TRACELAB_MINERU_REQUEST_TIMEOUT` | `20` | 单次 HTTP 请求超时（秒） |
| `TRACELAB_MINERU_TASK_TIMEOUT` | `600` | 完整解析任务超时（秒） |
| `TRACELAB_MINERU_POLL_INTERVAL` | `1` | MinerU 状态轮询间隔（秒） |
| `TRACELAB_PAPER_JOB_ROOT` | `./data/paper-jobs` | 任务和解析缓存目录 |

## 异步解析

`POST /api/v1/projects/{project_id}/paper-jobs`

上传表单字段 `file`，成功返回 `202 Accepted`。调用方轮询：

`GET /api/v1/projects/{project_id}/paper-jobs/{job_id}`

状态为 `queued`、`running`、`succeeded` 或 `failed`。完成后读取：

`GET /api/v1/projects/{project_id}/paper-jobs/{job_id}/result`

结果包含持久化后的论文记录、解析器版本和统一页块结构。块坐标归一化到
`0..1`，页码从 1 开始，块 ID 格式为 `p{page}-b{order}`。

## 缓存与降级

缓存键由 PDF 内容 SHA-256 和解析器名称组成。相同论文重复提交时复用已完成结果；
MinerU 原始 JSON/ZIP 和统一结构分别保存。MinerU 不可用或超时时任务进入 `failed`，
不会导致 TraceLab 进程退出。第一迭代的 `POST /paper` 暂时保留兼容，新的前端应使用
`paper-jobs` 接口。

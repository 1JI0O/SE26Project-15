# 论文解析接口契约

## 接入方式

TraceLab 使用统一的 `MinerUParser`，支持本地 `mineru-api` 和 MinerU 官方 API。
业务接口、解析任务状态和标准化结果不随提供方变化。默认使用本地服务：

```bash
mineru-api --host 127.0.0.1 --port 8001 --enable-vlm-preload true
```

可配置环境变量：

| 变量 | 默认值 | 说明 |
|---|---|---|
| `TRACELAB_MINERU_PROVIDER` | `local` | `local` 或 `official` |
| `TRACELAB_MINERU_URL` | `http://127.0.0.1:8001` | MinerU FastAPI 地址 |
| `TRACELAB_MINERU_BACKEND` | `pipeline` | 本地 MinerU 解析后端 |
| `TRACELAB_MINERU_LANGUAGE` | `ch` | OCR 语言提示 |
| `TRACELAB_MINERU_PARSE_METHOD` | `auto` | 文本/OCR 自动选择 |
| `TRACELAB_MINERU_API_URL` | `https://mineru.net/api/v4` | 官方 API 地址 |
| `TRACELAB_MINERU_API_TOKEN` | 空 | 官方 API 令牌，仅在 `official` 模式必填 |
| `TRACELAB_MINERU_API_MODEL` | `vlm` | 官方 API 模型，可设为 `pipeline` 或 `vlm` |
| `TRACELAB_MINERU_API_OCR` | `true` | 官方 API 是否启用 OCR |
| `TRACELAB_MINERU_FORMULA_ENABLE` | `true` | 是否识别公式 |
| `TRACELAB_MINERU_TABLE_ENABLE` | `true` | 是否识别表格 |
| `TRACELAB_MINERU_REQUEST_TIMEOUT` | 本地 `20`，官方 `60` | 单次 HTTP 请求超时（秒） |
| `TRACELAB_MINERU_REQUEST_RETRIES` | `3` | 官方 API 瞬时网络错误的最大尝试次数 |
| `TRACELAB_MINERU_TASK_TIMEOUT` | `600` | 完整解析任务超时（秒） |
| `TRACELAB_MINERU_POLL_INTERVAL` | `1` | MinerU 状态轮询间隔（秒） |
| `TRACELAB_PAPER_JOB_ROOT` | `./data/paper-jobs` | 任务和解析缓存目录 |
| `TRACELAB_MINERU_OUTPUT_ROOT` | 自动探测仓库 `output/` | 兼容读取旧版本地 MinerU 未打包进 ZIP 的图片 |

使用官方 API 时只需在后端进程环境中配置：

```bash
export TRACELAB_MINERU_PROVIDER=official
export TRACELAB_MINERU_API_TOKEN='<从 MinerU 控制台获取>'
```

令牌不得提交到仓库。官方 API 上传使用预签名地址，认证头只发送给 MinerU API，
不会透传到对象存储。按照官方文档，上传预签名地址时不附加 `Content-Type`。

## 异步解析

`POST /api/v1/projects/{project_id}/paper-jobs`

上传表单字段 `file`，成功返回 `202 Accepted`。调用方轮询：

`GET /api/v1/projects/{project_id}/paper-jobs/{job_id}`

状态为 `queued`、`running`、`succeeded` 或 `failed`。这两个轮询接口对非数字的
`project_id`（例如客户端离开工作台后路由 id 变为 `NaN` 的在飞轮询）返回 `404` 而非 `422`，
避免导航过程中出现请求校验错误。完成后读取：

`GET /api/v1/projects/{project_id}/paper-jobs/{job_id}/result`

结果包含持久化后的论文记录、解析器版本和统一页块结构。块坐标归一化到
`0..1`，页码从 1 开始，块 ID 格式为 `p{page}-b{order}`。

工作台按章节读取 MinerU 原始 Markdown：

`GET /api/v1/projects/{project_id}/workspace/paper-document`

响应包含 `markdown`、带层级和页码的 `sections`、`asset_base_url`、解析来源，以及带
`render_anchor`/`anchor_resolved` 的稳定 `blocks`。阅读器使用 `p{page}-b{order}` 精确
滚动并高亮追溯证据；原始 Markdown 无法精确对齐时显式回退到 quote/section，不静默
跳到错误位置。
Markdown 中的图片通过 `GET /api/v1/projects/{project_id}/paper/assets/{asset_path}`
按需读取；表格、行内/块级公式由前端 Markdown 阅读器渲染。旧的分页接口继续保留给
追溯兼容逻辑，但不再作为论文阅读器的数据源。

## 缓存与降级

缓存键由 PDF 内容 SHA-256、提供方和解析参数组成。相同论文重复提交时复用已完成结果；
MinerU 原始 JSON/ZIP 和统一结构分别保存。MinerU 不可用或超时时任务进入 `failed`，
不会导致 TraceLab 进程退出。第一迭代的 `POST /paper` 暂时保留兼容，新的前端应使用
`paper-jobs` 接口。

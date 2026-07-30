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

响应还包含 `pdf_url`：指向原始 PDF 的接口地址，仅在磁盘上仍存在原件时返回，否则为 `null`。阅读器据此启用/禁用 PDF 视图开关——原件缺失时保持沉默而非报错。

`blocks` 中每个块除文本与 `render_anchor` 外，还携带用于在原始 PDF 上作画的几何信息：

| 字段 | 说明 |
|---|---|
| `bbox` | 块级包围盒，`[x0, y0, x1, y1]`，归一化到页面 `0..1`，左上原点。来自 MinerU `content_list` 的 0-1000 空间重缩放。 |
| `lines` | 行级盒子数组 `{text, bbox}`，同一 `0..1` 空间。来自 `middle.json`，用于句子级高亮；旧文档或无法与行对齐时为空，阅读器回退到整块 `bbox`。 |
| `page_size` | 该块所在页的尺寸 `[width, height]`（PDF 点）。阅读器据此校验实际渲染页面的尺寸/朝向；不一致（旋转页、渲染器分歧）时抑制高亮而非画错位置。 |

Markdown 中的图片通过 `GET /api/v1/projects/{project_id}/paper/assets/{asset_path}`
按需读取；表格、行内/块级公式由前端 Markdown 阅读器渲染。旧的分页接口继续保留给
追溯兼容逻辑，但不再作为论文阅读器的数据源。

阅读器在原始 PDF 上叠加高亮而非在渲染后的 Markdown 上，因此需要原件字节：

`GET /api/v1/projects/{project_id}/paper/file`

以 `application/pdf` 内联返回最近一次上传的原始 PDF（`Content-Disposition: inline`，私有缓存 1 小时）。`storage_path` 在返回前会重新解析并限定在上传根目录内，拒绝数据库恢复或旧安装遗留的越界绝对路径。原件缺失时返回 `404`，与 `pdf_url` 为 `null` 一致。前端 PDF 视图用 pdf.js 渲染页面，其 cmaps/标准字体在构建期由 `frontend/scripts/copy-pdfjs-assets.mjs` 打包进 `public/pdfjs/`，以同源路径加载，桌面壳无需联网。

## 缓存与降级

缓存键由 PDF 内容 SHA-256、提供方和解析参数组成。相同论文重复提交时复用已完成结果；
MinerU 原始 JSON/ZIP 和统一结构分别保存。MinerU 不可用或超时时任务进入 `failed`，
不会导致 TraceLab 进程退出。第一迭代的 `POST /paper` 暂时保留兼容，新的前端应使用
`paper-jobs` 接口。

`PaperDocument.content_hash` 保存的就是这个缓存键，`workspace/paper-document` 依赖它定位
MinerU markdown 与图片归档；为空时只能返回合成 markdown（`source="normalized-fallback"`）。

## 云端同步导入的论文

解析缓存是**设备本地**的：缓存键含 PDF 内容哈希与本机解析参数，缓存文件本身不进同步协议。
因此从云端下载的论文必须在本机重新解析，不能沿用来源设备的解析结果。

导入流程（`services/cloud_import.py`）：写入 PDF 后先用兼容解析器生成占位文本，标记
`parse_status="running"`、`parser="pending-import"`、`content_hash=""`，随后按本机
`TRACELAB_MINERU_*` 配置提交解析任务；完成后写入真实 `content_hash`、章节/段落/页块结构，
并刷新 RAG paper 索引。相同 PDF 若本机已解析过，缓存命中会立即完成。

本机未配置解析器或解析失败时保留占位文本，但 `parse_status="failed"` 且 `parser_version`
追加失败原因——占位结果不会被当作解析成功，避免"同步下来的论文永远是回退解析"这类静默降级。

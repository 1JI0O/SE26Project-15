# Cloud API 与同步契约

Server API 固定前缀为 `/api/v1`，只接受 public UUID 作为租户和领域边界。运行入口是
`server/tracelab_server/main.py`，版本化快照见
[`cloud-sync.openapi.json`](cloud-sync.openapi.json)；Local API 不装配账号或管理员路由。

## 身份与权限矩阵

| 操作 | 未验证用户 | viewer | editor | owner | platform_admin |
|---|---:|---:|---:|---:|---:|
| 登录、账号状态、设备管理 | 是 | 是 | 是 | 是 | 是 |
| 读取 workspace 项目、事件和 Blob | 否 | 是 | 是 | 是 | 仅作为成员 |
| 创建/修改项目、push、上传 Blob | 否 | 否 | 是 | 是 | 仅作为成员 |
| 成员与角色管理 | 否 | 否 | 否 | 是 | 否 |
| 用户启停、配额、指标、审计、维护 | 否 | 否 | 否 | 否 | 是 |
| 项目正文、PDF、代码、Agent 内容 | 否 | 按成员权限 | 按成员权限 | 按成员权限 | 无默认接口 |

所有领域请求依次验证 access token、有效 session、账号状态、邮箱验证、workspace membership
和最低角色。管理员身份不能绕过 workspace membership。

## API

- 认证：`POST /auth/register|login|refresh|logout|logout-all`，`GET /auth/me|devices`，
  `DELETE /auth/devices/{device_id}`，`POST /auth/verify-email|password/forgot|password/reset`。
- Workspace：`GET|POST /workspaces`，`GET /workspaces/{workspace_id}`，以及
  `GET|POST|PATCH|DELETE /workspaces/{workspace_id}/members...`。
- 项目：`GET|POST /projects`，`GET|PATCH|DELETE /projects/{public_id}`。
- 设备项目状态：`GET|PATCH /projects/{public_id}/device-sync`；暂停/解绑只作用于当前设备。
- 云端领域：`GET /projects/{public_id}/entities`，`POST|PATCH|DELETE
  /projects/{public_id}/entities/{entity_type}...`，以及 Artifact 版本历史与当前版本选择接口。
- 同步：`GET /sync/bootstrap`、`GET /sync/pull`、`POST /sync/push|ack`。
- Blob：`POST /blobs/upload-init`、`PUT /blobs/{blob_id}/chunks/{index}`、
  `POST /blobs/{blob_id}/complete`、`GET /blobs/{blob_id}/download`。
- 管理：`GET /admin/users|metrics|audit`、`PATCH /admin/users/{user_id}`、
  `PATCH /admin/workspaces/{workspace_id}/quota`、`POST /admin/maintenance/gc|compact-events`。

Browser 的 refresh token 是 Secure/HttpOnly/SameSite=Lax Cookie；Cookie 刷新请求必须同时
携带可信 Origin、可读 CSRF Cookie 与同值 `X-CSRF-Token`。Desktop 在 JSON body 发送由系统
凭据库读取的 refresh token。access token 只存在进程内存。

## Push DTO 与结果

每个 `operations[]` 元素包含：

```json
{
  "workspace_id": "uuid",
  "device_id": "uuid",
  "client_operation_id": "uuid",
  "supersedes_operation_id": null,
  "entity_type": "project|paper_document|code_repository|code_edit|paper_target|code_target|trace_link|agent_*",
  "entity_public_id": "public-id",
  "operation": "upsert|delete|select_version",
  "base_version": 1,
  "payload": {}
}
```

单个操作在独立事务中完成实体修改、版本递增、workspace sequence、sync event 和 receipt。
响应状态为 `applied`、`duplicate` 或 `conflict`；冲突携带远端版本和快照，服务端不会静默覆盖。
Project、TraceLink 决定采用乐观锁；文件以 ArtifactVersion 保留多个不可变版本；Agent Message 和
Run Event 只追加。`pull.limit` 范围为 1–500，客户端持久化成功后才可 `ack`。
冲突解决必须创建新的 `client_operation_id`，并通过 `supersedes_operation_id` 指向原冲突 receipt。

## 禁用字段（forbidden keys）

服务端 `cloud_sync._find_forbidden_key` 会**递归**扫描 push payload，只要任意层级出现以下键
（大小写不敏感）或以 `_api_key` 结尾的键，整个 `/sync/push` 请求直接 `422 "Payload contains a
forbidden field"`：

```text
storage_path, absolute_path, local_path, api_key, llm_api_key,
mineru_api_key, refresh_token, access_token, secret, _upload_content
```

这是防止本地路径 / 密钥泄露到云端的安全护栏，**不可放宽**。由于客户端把同一工作区的所有子操作
打包进一条 push 请求、且服务端一条失败即整批失败，Agent 运行数据（run event payload、message
metadata、memory source 等任意运行时字段）若含上述键，会**阻塞整个工作区的同步**。

因此 Desktop 本地后端必须在写入和读取 outbox 时**剥离这些键**：`local_sync.scrub_forbidden_keys`
在 `record_local_operation`（入队时）与 `read_outbox`（序列化给客户端时，可自愈修复前已入库的
历史脏行）两处应用。`local_sync.FORBIDDEN_SYNC_KEYS` 是服务端集合的**镜像**，两端必须保持一致，
`backend/tests/sync/test_forbidden_key_scrub.py` 有漂移守卫测试。服务端命中时记 WARNING（仅键名、
不记键值）便于定位。

## 领域字段校验（bounded envelope）

`sync_validation.validate_domain_operation` 对每条非 project upsert 校验必填字段与受限取值，命中即
`422` 并记 WARNING（仅原因、不记取值）。取值词表必须与客户端 canonical 枚举一致，否则整批 push 失败：

- TraceLink `status` ∈ `{proposed, accepted, rejected, stale}`（`proposed` 是新生成链接的初始态，
  见 `frontend`/`backend/app/schemas/traces.py` 的 `TraceStatus`；`pending` 仅为历史兼容保留）。
- AgentMessage `role` ∈ `{user, assistant, system, tool}`。
- 必填字段见 `REQUIRED_UPSERT_FIELDS`（如 trace_link 需 `paper_ref/code_ref/status`，
  agent_message 需 `conversation_public_id/role`）。
- PaperTarget 需 `quote/quote_hash/fingerprint`，CodeTarget 需 `path/quote/code_quote_hash/fingerprint`：
  锚点的本地主键（`ptarget-<hex>`/`ctarget-<hex>`）不进入协议，接收端靠这些字段重新锚定。

### 本地主键不上行（public id 翻译）

`trace_link` 的 `paper_target_id`/`code_target_id`/`paper_document_id`/`code_repository_id` 都是
设备本地主键，在另一台机器上无意义。payload 只携带对应的 `*_public_id`，由
`local_sync._target_public_id` / `_row_public_id` 在出站时翻译，导入侧
`_resolve_local_id` 反向映射。因此 **锚点必须先于关系导入**（前端 `IMPORT_PRIORITY`：
paper_document/code_repository → paper_target/code_target → trace_link），未解析的引用会被丢弃
而不是重试。

### 旧项目修复（backfill）

`POST /local-sync/backfill?workspace_id=<uuid>`

协议扩展后，**已启用同步的旧项目不会自愈**：没有任何逻辑会重新触碰未变更的实体，所以旧项目的
云端副本会永久缺少锚点，且 `trace_link` 只有早期的 8 个字段。该接口按当前 payload builder 重新
入队：锚点以 `base_version=0` 入队（云端尚无该实体），`trace_link` 以本地当前 version 入队
（成功推送过的项目其本地 version 即云端 version，乐观锁成立）。返回各类型入队计数；workspace
无本地同步状态时 404。

前端在 `synchronizeWorkspace` 中按 workspace 自动执行一次（`tracelab_sync_backfill_targets_v1`
标记，失败不写标记以便下次重试）。后续再扩展协议时应提升该标记版本号，而不是新增第二个标记。

### 机器派生实体的冲突语义

`paper_target`/`code_target` 由分析流水线从同一 artifact 确定性重算（`MACHINE_DERIVED_TYPES`）。
push 冲突不进冲突中心，本地 outbox 置为 `superseded`，改由下一次 pull 取服务端副本——否则重算
产生的噪声会淹没真正需要人工决定的冲突（追溯决定、文件版本）。

## 同步数据分类

| 分类 | 进入 outbox/event | 存储方式 |
|---|---|---|
| Project/Paper/Repository/TraceLink 源数据 | 是 | 小字段或 Blob UUID |
| 代码编辑版本 | 是 | 内容 Blob；事件不含完整源码 |
| Agent 会话消息、Run Event、Memory | 默认是，可按项目关闭 | 小消息字段；大结果使用 Blob |
| PDF、ZIP、派生分析 JSON | 不内嵌 | SHA-256 Blob 引用 |
| 论文解析结构、MinerU markdown/图片 | 否 | 设备本地缓存，导入后由本机解析器重建 |
| 分析缓存、UI 布局、临时任务 | 否 | 仅本地或可重建 |
| MinerU、LLM、集成 API key | 永不 | 本地凭据或部署环境 |
| SQLite 文件、服务器绝对路径 | 永不 | 不属于协议 |

### 导入后的本地重建（派生数据不同步）

解析结构与分析结果不进协议，接收端必须用**自己的**配置重新派生，否则同一份 PDF 在两台机器上
呈现不同（这是"同学同步下来是 pypdf 而不是 MinerU"的根因）：

- `paper_document` 导入后 `parse_status="running"`、`parser="pending-import"`、`content_hash=""`，
  由 `cloud_import.schedule_paper_reparse` 用本机配置的解析器（MinerU local/official）重跑，成功后
  写入真实 `content_hash` 并刷新 RAG paper 索引。`content_hash` 是解析缓存键，缺失会让
  `markdown_for_cache` 未命中并退回合成 markdown。
- `code_repository` 导入时只做 `scan_code_archive`（文件树），随后
  `cloud_import.schedule_repository_analysis` 跑完整分析补齐 symbols/imports 与代码检索索引；
  已同步的 diagram blob 仍会覆盖派生图。
- 本机未配置解析器或解析失败时保留占位文本，但 `parse_status="failed"` 并在 `parser_version`
  追加原因，不伪装成解析成功。

`local_only` 不写 outbox；`cloud_enabled` push/pull；`cloud_paused` 仅影响当前 Desktop、只 pull；
“解除本机绑定”把当前 Desktop 恢复为 `local_only`，不删除云端项目；owner 的独立“删除云端项目”
操作才会影响所有设备并生成至少保留 30 天的 tombstone。

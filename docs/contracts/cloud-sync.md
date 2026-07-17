# Cloud API 与同步契约

Cloud API 固定前缀为 `/api/v1`，只接受 public UUID 作为租户和领域边界。生产 OpenAPI
由 `app.cloud:app` 的 `/openapi.json` 提供；Local API 不装配本文件中的账号或管理员路由。

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
  "entity_type": "project|paper_document|code_repository|code_edit|trace_link|agent_*",
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

## 同步数据分类

| 分类 | 进入 outbox/event | 存储方式 |
|---|---|---|
| Project/Paper/Repository/TraceLink 源数据 | 是 | 小字段或 Blob UUID |
| 代码编辑版本 | 是 | 内容 Blob；事件不含完整源码 |
| Agent 会话消息、Run Event、Memory | 默认是，可按项目关闭 | 小消息字段；大结果使用 Blob |
| PDF、ZIP、派生分析 JSON | 不内嵌 | SHA-256 Blob 引用 |
| 分析缓存、UI 布局、临时任务 | 否 | 仅本地或可重建 |
| MinerU、LLM、集成 API key | 永不 | 本地凭据或部署环境 |
| SQLite 文件、服务器绝对路径 | 永不 | 不属于协议 |

`local_only` 不写 outbox；`cloud_enabled` push/pull；`cloud_paused` 仅影响当前 Desktop、只 pull；
“解除本机绑定”把当前 Desktop 恢复为 `local_only`，不删除云端项目；owner 的独立“删除云端项目”
操作才会影响所有设备并生成至少保留 30 天的 tombstone。

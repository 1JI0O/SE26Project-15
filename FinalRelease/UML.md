# TraceLab UML 模型（对照当前实现）

**版本：2.0**  
**日期：2026-07-31**  
**说明：** 用例 / 分析 / 设计模型与仓库源码一致；云端只含账号与同步，不含分析。

---

## 1. 用例模型（Use-Case View）

### 1.1 参与者与用例总图

```mermaid
flowchart LR
  User((复现用户))
  Admin((平台管理员))
  ExtMinerU[[MinerU]]
  ExtLLM[[LLM API]]
  ExtGH[[GitHub]]
  ExtSMTP[[SMTP]]

  User --> UC1[UC1 导入与解析]
  User --> UC2[UC2 Agent 追溯与审阅]
  User --> UC3[UC3 标注模式建链]
  User --> UC4[UC4 编辑代码与图浏览]
  User --> UC5[UC5 Agent 对话]
  User --> UC6[UC6 配置集成]
  User --> UC7[UC7 可选云同步]
  User --> UC8[UC8 VS Code 精简闭环]
  Admin --> UC9[UC9 管理控制台]

  UC1 -.-> ExtMinerU
  UC1 -.-> ExtGH
  UC2 -.-> ExtLLM
  UC5 -.-> ExtLLM
  UC7 -.-> ExtSMTP
```

### 1.2 用例关系

```mermaid
flowchart TB
  UC1[UC1 导入与解析]
  UC1 -->|include| UC1a[上传 PDF]
  UC1 -->|include| UC1b[ZIP / GitHub 导入]
  UC1 -->|include| UC1c[MinerU 异步解析]
  UC1 -->|include| UC1d[AST 分析与张量图]

  UC2[UC2 Agent 追溯与审阅]
  UC2 -->|include| UC2a[协调器触发分析任务]
  UC2 -->|include| UC2b[四阶段取证发布]
  UC2 -->|include| UC2c[证据校验落库]
  UC2 -->|include| UC2d[双向高亮与矩阵审阅]
  UC2 -->|extend| UC2e[深度思考置信度]
  UC2 -->|extend| UC2f[RAG 加速定位]

  UC3[UC3 标注模式]
  UC3 -->|include| UC3a[选论文并可切换]
  UC3 -->|include| UC3b[选代码并可切换]
  UC3 -->|include| UC3c[填表创建 TraceLink]

  UC5[UC5 Agent 对话]
  UC5 -->|include| UC5a[SSE Run]
  UC5 -->|include| UC5b[写工具人工确认]
```

### 1.3 关键用例简述

| 用例 | 目标 | 前置 | 后置 |
|---|---|---|---|
| UC1 | 论文结构与代码工作区可用 | 已建项目 | PaperDocument / CodeRepository 可查 |
| UC2 | 得到可审阅的 Agent 追溯 | 论文+代码就绪；建议已配 Provider | TraceLink proposed/accepted/rejected；无 Provider 则等待 |
| UC3 | 手工追加一条关系 | 标注模式开启 | 新 TraceLink（manual） |
| UC4 | 编辑代码、浏览图 | 仓库已分析 | revision 递增；旧追溯可 stale |
| UC5 | 对话协助理解/修改 | Provider 可用 | Run 审计；写操作经确认 |
| UC6 | 配置 MinerU / LLM / RAG | 应用可写设置库 | 后续解析/Agent/检索可用 |
| UC7 | 登录后按项目同步 | 用户主动启用 | sync_mode 变更；分析仍在本地 |
| UC8 | 在 VS Code 内完成精简闭环 | 已装扩展 | `.tracelab/` 产物 |
| UC9 | 运维账号与配额 | 管理员账号 | 审计日志；不读项目正文 |

---

## 2. 分析模型（Analysis Model）

### 2.1 健壮性分析（导入 → 追溯 → 审阅）

```mermaid
flowchart TB
  Actor((用户))

  subgraph Boundary[边界]
    WL[工作台界面]
    AG[标注引导条]
    AP[Agent 面板]
    SP[设置对话框]
    SC[同步/冲突中心]
  end

  subgraph Control[控制]
    IC[导入解析控制]
    CC[追溯协调器]
    AJ[分析任务控制]
    TC[审阅控制]
    AC[Agent 运行控制]
    RC[RAG 索引控制]
    SY[本地同步控制]
  end

  subgraph Entity[实体]
    Project
    PaperDocument
    CodeRepository
    PaperTarget
    CodeTarget
    TraceLink
    AgentAnalysisJob
    AgentRun
    RagChunk
    SyncOutbox
  end

  Actor --> WL
  Actor --> AG
  Actor --> AP
  Actor --> SP
  Actor --> SC

  WL --> IC
  WL --> TC
  AG --> TC
  AP --> AC
  SP --> IC
  SC --> SY

  IC --> PaperDocument
  IC --> CodeRepository
  IC --> CC
  CC --> AJ
  AJ --> AgentAnalysisJob
  AJ --> AgentRun
  AJ --> PaperTarget
  AJ --> CodeTarget
  AJ --> TraceLink
  TC --> TraceLink
  AC --> AgentRun
  AC --> TraceLink
  RC --> RagChunk
  SY --> SyncOutbox
  SY --> Project
```

### 2.2 分析类图（核心领域）

```mermaid
classDiagram
  direction TB
  class Project {
    +id
    +name
    +syncMode
    +agentDeepThinking
  }
  class PaperDocument {
    +contentHash
    +pages
    +sections
    +markdown
  }
  class CodeRepository {
    +revision
    +fileTree
    +analysisJson
    +tensorGraph
  }
  class PaperTarget {
    +blockId
    +quote
    +occurrence
    +quoteHash
    +salience
    +targetType
  }
  class CodeTarget {
    +path
    +lineRange
    +quote
    +occurrence
    +codeQuoteHash
    +role
  }
  class TraceLink {
    +relationType
    +relevance
    +confidence
    +status
    +evidence
    +source
  }
  class AgentAnalysisJob {
    +kind
    +status
    +fingerprint
  }
  class AgentRun {
    +status
    +events
  }
  class RagIndex {
    +scope
    +status
    +generation
  }

  Project "1" --> "0..*" PaperDocument
  Project "1" --> "0..*" CodeRepository
  Project "1" --> "*" TraceLink
  Project "1" --> "*" AgentAnalysisJob
  TraceLink --> PaperTarget
  TraceLink --> CodeTarget
  TraceLink --> PaperDocument
  TraceLink --> CodeRepository
  AgentAnalysisJob --> AgentRun
  AgentAnalysisJob --> TraceLink : publish
  Project --> RagIndex
```

### 2.3 分析时序：Agent 追溯发布

```mermaid
sequenceDiagram
  actor U as 用户
  participant W as 工作台
  participant C as 协调器
  participant J as 分析任务
  participant A as Agent Runtime
  participant V as 证据校验
  participant DB as TraceLink/Targets

  U->>W: 导入完成 / Provider 就绪
  W->>C: maybe_start_trace
  C->>J: 创建/复用 job（fingerprint 幂等）
  J->>A: 四阶段循环（可派生子代理）
  A->>V: publish_trace_candidates
  alt quote/occurrence 命中
    V->>DB: 写入 proposed
    J-->>W: SSE analysis.published
  else 校验失败
    V-->>A: 拒绝该候选
  end
  U->>W: 接受 / 拒绝
  W->>DB: 更新 status
```

---

## 3. 设计模型

### 3.1 分层包图

```mermaid
flowchart TB
  subgraph FE[frontend]
    Views[views/]
    Features[features/]
    Comp[composables/ + stores/]
    ApiTS[api/]
  end

  subgraph Desktop[Tauri]
    Rust[src-tauri]
    Side[PyInstaller sidecar]
  end

  subgraph BE[backend/app]
    Routes[api/routes]
    Schemas[schemas]
    Svc[services/*]
    Models[models]
    DB[(SQLite)]
  end

  subgraph Ext[外部]
    MinerU
    LLM
    GitHub
  end

  subgraph Cloud[server 可选]
    CloudAPI[Auth/Sync/Blob/Admin]
    PG[(PostgreSQL)]
    Blob[Blob]
  end

  Views --> Features --> Comp --> ApiTS
  ApiTS -->|/api/v1| Routes
  Rust --> Side --> Routes
  Routes --> Schemas
  Routes --> Svc
  Svc --> Models --> DB
  Svc --> MinerU
  Svc --> LLM
  Svc --> GitHub
  ApiTS -.->|cloud-api / sync| CloudAPI
  CloudAPI --> PG
  CloudAPI --> Blob
```

### 3.2 设计类图（后端核心服务）

```mermaid
classDiagram
  direction LR
  class PaperRoutes
  class RepositoryRoutes
  class TraceRoutes
  class AgentRoutes
  class RagRoutes
  class LocalSyncRoutes

  class PaperParsingService
  class CodeAnalysisService
  class TraceCoordinator
  class AnalysisJobRunner
  class AnalysisTools
  class AgentRuntime
  class RagService
  class LocalSyncService
  class DocumentParserFactory

  PaperRoutes --> PaperParsingService
  PaperParsingService --> DocumentParserFactory
  RepositoryRoutes --> CodeAnalysisService
  TraceRoutes --> TraceCoordinator
  AgentRoutes --> AgentRuntime
  AgentRoutes --> AnalysisJobRunner
  AnalysisJobRunner --> AnalysisTools
  AnalysisJobRunner --> AgentRuntime
  RagRoutes --> RagService
  LocalSyncRoutes --> LocalSyncService
  TraceCoordinator --> AnalysisJobRunner
```

### 3.3 设计时序：PDF 解析

```mermaid
sequenceDiagram
  participant UI as usePaper
  participant API as papers route
  participant Job as PaperParsingService
  participant F as parser factory
  participant MU as MinerU
  participant DB as SQLite

  UI->>API: POST paper-jobs
  API->>Job: enqueue
  API-->>UI: job_id
  Job->>F: create_mineru_parser
  F->>MU: submit / poll
  MU-->>F: payload
  Job->>Job: normalize + cache
  Job->>DB: PaperDocument
  Job->>Job: 触发 maybe_start_trace / RAG 重建
  UI->>API: 轮询 job / 拉 document
```

### 3.4 设计时序：Agent 写工具确认

```mermaid
sequenceDiagram
  participant UI as AgentPanel
  participant API as agent route
  participant RT as conversations/runtime
  participant Tool as tools

  UI->>API: POST run（SSE）
  API->>RT: 多步规划
  RT->>Tool: 写工具请求
  Tool-->>API: AgentToolRequest pending
  API-->>UI: confirmation_required
  UI->>API: accept / reject
  alt 确认
    API->>Tool: execute
    Tool-->>UI: 成功并刷新
  else 拒绝
    API-->>UI: 不落库
  end
```

### 3.5 部署 / 运行视图

```mermaid
flowchart TB
  subgraph Device[用户设备]
    Browser[浏览器]
    Tauri[Tauri Desktop]
    VSCode[VS Code 扩展]
    LocalAPI[Local FastAPI\n:8000 或 :8765]
    SQLite[(SQLite)]
    Files[(uploads / data)]
  end

  subgraph OptionalExt[可选外部]
    MinerUSvc[MinerU]
    LLMSvc[LLM / Embeddings]
  end

  subgraph OptionalCloud[可选云端 Compose]
    Proxy[反向代理]
    CloudAPI[server FastAPI]
    Worker[维护 Worker]
    PG[(PostgreSQL)]
    Blob[(Blob)]
  end

  Browser --> LocalAPI
  Tauri --> LocalAPI
  VSCode --> LocalAPI
  LocalAPI --> SQLite
  LocalAPI --> Files
  LocalAPI --> MinerUSvc
  LocalAPI --> LLMSvc
  Browser -.-> Proxy
  Tauri -.-> Proxy
  Proxy --> CloudAPI
  CloudAPI --> PG
  CloudAPI --> Blob
  Worker --> PG
  Worker --> Blob
```

**边界硬约束：** `Worker` / `CloudAPI` 不做 MinerU、AST、LLM、Agent；这些只发生在 `LocalAPI`（或扩展捆绑运行时）。

---

## 4. 状态机摘录

### 4.1 TraceLink 状态

```mermaid
stateDiagram-v2
  [*] --> proposed: Agent/手动创建
  proposed --> accepted: 用户接受
  proposed --> rejected: 用户拒绝
  accepted --> proposed: 撤回
  rejected --> proposed: 撤回
  proposed --> stale: 论文/代码版本变化
  accepted --> stale: 版本变化且无法继续有效
```

### 4.2 标注模式步骤

```mermaid
stateDiagram-v2
  [*] --> select_paper: 开始标注
  select_paper --> confirm_paper: 选中论文
  confirm_paper --> select_paper: 重选/清空
  confirm_paper --> confirm_paper: 切换其他论文条目
  confirm_paper --> select_code: 确认
  select_code --> confirm_code: 选中代码
  confirm_code --> select_code: 重选/清空
  confirm_code --> confirm_code: 切换其他代码范围
  confirm_code --> form: 确认
  form --> select_code: 上一步
  form --> [*]: 创建成功/取消
```

---

## 5. 与源码映射（便于验收抽查）

| 模型元素 | 主要源码 |
|---|---|
| 用例 UC2 | `services/tracing/coordinator.py`、`services/agent/analysis_jobs.py` |
| 证据校验 | `services/agent/analysis_tools.py` |
| 子代理 | `services/agent/subagents.py` |
| 标注模式 | `frontend/src/stores/annotation.ts`、`AnnotationGuide.vue` |
| RAG | `services/rag/*`、`routes/rag.py` |
| 云同步 | `server/tracelab_server/*`、`services/local_sync.py` |
| Desktop | `frontend/src-tauri`、`scripts/build-backend-sidecar.mjs` |

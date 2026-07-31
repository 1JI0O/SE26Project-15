# TraceLab 技术原型 UML 模型

## 1. 用例模型（用例视图 / Use-Case View）

**视图说明：** 用例视图描述系统对外提供的业务能力与参与者交互边界，对应本迭代三条典型用例及支撑用例。

### 1.1 参与者与用例总图

```mermaid
flowchart LR
  User((复现用户))
  ExtMinerU[[MinerU 解析服务]]
  ExtLLM[[LLM API]]
  ExtGH[[GitHub]]

  User --> UC1[UC1 导入与解析项目]
  User --> UC2[UC2 论文—代码追溯浏览]
  User --> UC3[UC3 编辑分析与 Agent 协作]
  User --> UC4[UC4 配置集成密钥]
  User --> UC5[UC5 可选云端登录与同步]

  UC1 -.-> ExtMinerU
  UC1 -.-> ExtGH
  UC2 -.-> ExtLLM
  UC3 -.-> ExtLLM
```

### 1.2 用例关系（包含 / 扩展）

```mermaid
flowchart TB
  UC1[UC1 导入与解析项目]
  UC1 -->|include| UC1a[上传或选择 PDF]
  UC1 -->|include| UC1b[上传 ZIP / GitHub / 本地目录]
  UC1 -->|include| UC1c[过滤无关文件]
  UC1 -->|include| UC1d[触发 MinerU 解析]
  UC1 -->|include| UC1e[解析代码树与符号]

  UC2[UC2 论文—代码追溯浏览]
  UC2 -->|include| UC2a[分栏阅读论文与代码]
  UC2 -->|include| UC2b[Agent 生成追溯候选]
  UC2 -->|include| UC2c[查看证据与置信度]
  UC2 -->|include| UC2d[确认或驳回追溯]
  UC2 -->|extend| UC2e[从图节点跳转代码]

  UC3[UC3 编辑分析与 Agent 协作]
  UC3 -->|include| UC3a[编辑并保存代码]
  UC3 -->|include| UC3b[触发代码/张量流分析]
  UC3 -->|include| UC3c[Agent 对话]
  UC3 -->|include| UC3d[写工具人工确认]
  UC3 -->|extend| UC3e[发布或更新架构图]
```

### 1.3 关键用例简述

| 用例 | 目标 | 前置 | 后置 |
|---|---|---|---|
| UC1 | 获得可浏览的论文结构与代码工作区 | 已创建项目 | PaperDocument / CodeRepository 可查 |
| UC2 | 得到可定位、可审阅的追溯候选 | 论文与代码已导入 | TraceLink 进入 proposed/accepted/rejected |
| UC3 | 在受控条件下修改代码并刷新分析/图 | 工作区可打开文件 | 新 revision；图/追溯可更新 |
| UC4 | 配置 MinerU / Agent API | 本地应用可写设置库 | 后续解析/Agent 可用 |
| UC5 | （可选）登录后按项目同步 | 用户主动启用 | sync_mode 变更；本地仍可离线 |

---

## 2. 分析模型（分析视图 / Analysis Model）

**视图说明：** 分析模型用边界—控制—实体（BCE / 健壮性风格）表达问题域对象与职责，不绑定具体框架类名。

### 2.1 健壮性分析（导入—追溯—Agent 主路径）

```mermaid
flowchart TB
  Actor((用户))

  subgraph Boundary[边界类 Boundary]
    WL[工作台界面]
    PL[项目列表界面]
    AP[Agent 面板]
    SP[设置对话框]
  end

  subgraph Control[控制类 Control]
    PC[项目管理控制]
    IC[导入与解析控制]
    TC[追溯生成与审阅控制]
    AC[Agent 运行控制]
    WC[工作区聚合控制]
  end

  subgraph Entity[实体类 Entity]
    Project
    PaperDocument
    CodeRepository
    CodeSymbol
    TraceLink
    AnalysisTask
    AgentSession
    IntegrationSettings
  end

  Actor --> WL
  Actor --> PL
  Actor --> AP
  Actor --> SP

  PL --> PC
  WL --> WC
  WL --> IC
  WL --> TC
  AP --> AC
  SP --> PC

  PC --> Project
  IC --> PaperDocument
  IC --> CodeRepository
  IC --> AnalysisTask
  WC --> PaperDocument
  WC --> CodeRepository
  WC --> CodeSymbol
  TC --> TraceLink
  TC --> PaperDocument
  TC --> CodeSymbol
  AC --> AgentSession
  AC --> TraceLink
  AC --> CodeRepository
  PC --> IntegrationSettings
```

### 2.2 分析类图（核心领域）

```mermaid
classDiagram
  direction TB
  class Project {
    +id
    +name
    +createdAt
    +syncMode
  }
  class PaperDocument {
    +status
    +pages
    +sections
    +markdown
  }
  class CodeRepository {
    +revision
    +fileTree
    +sourceType
  }
  class CodeSymbol {
    +qualifiedName
    +path
    +range
  }
  class TraceLink {
    +relationType
    +confidence
    +status
    +evidence
  }
  class AnalysisTask {
    +kind
    +state
    +error
  }
  class TensorGraph {
    +nodes
    +edges
  }
  class AgentSession {
    +messages
    +pendingToolConfirm
  }

  Project "1" --> "0..1" PaperDocument
  Project "1" --> "0..1" CodeRepository
  Project "1" --> "*" TraceLink
  Project "1" --> "*" AnalysisTask
  Project "1" --> "*" AgentSession
  CodeRepository "1" --> "*" CodeSymbol
  CodeRepository "1" --> "0..1" TensorGraph
  TraceLink --> PaperDocument : paper锚点
  TraceLink --> CodeSymbol : code锚点
```

### 2.3 分析层时序（用例 2 摘要）

```mermaid
sequenceDiagram
  actor U as 用户
  participant B as 工作台边界
  participant T as 追溯控制
  participant A as Agent 控制
  participant E as TraceLink 实体

  U->>B: 请求生成/刷新追溯
  B->>A: 启动 Agent Run
  A->>A: 读取论文块与代码符号上下文
  A-->>B: 提出追溯候选（待确认或直接写入 proposed）
  B->>T: 展示矩阵与证据
  U->>B: 接受 / 驳回
  B->>T: 更新状态
  T->>E: status = accepted/rejected
```

---

## 3. 设计模型

### 3.1 分层包图（逻辑 / 开发视图）

```mermaid
flowchart TB
  subgraph FE[frontend 表现层]
    Views[views/]
    Features[features/]
    API[api/ + composables/]
  end

  subgraph Desktop[Tauri 壳]
    Sidecar[PyInstaller FastAPI sidecar]
    Dialog[本地目录选择]
  end

  subgraph BE[backend 应用层]
    Routes[api/routes]
    Services[services/]
    Models[models/]
    Storage[storage/]
  end

  subgraph Ext[外部系统]
    MinerU
    LLM
    GitHub
  end

  subgraph OptionalCloud[server 可选云端]
    CloudAPI[Cloud FastAPI]
    PG[(PostgreSQL)]
    Blob[Blob 卷]
  end

  Views --> Features --> API
  API -->|HTTP| Routes
  Dialog --> API
  Sidecar --> Routes
  Routes --> Services
  Services --> Models
  Services --> Storage
  Services --> MinerU
  Services --> LLM
  Services --> GitHub
  API -.->|可选同步| CloudAPI
  CloudAPI --> PG
  CloudAPI --> Blob
```

### 3.2 设计类图
```mermaid
classDiagram
  direction LR
  class ProjectRoutes
  class PaperRoutes
  class RepositoryRoutes
  class WorkspaceRoutes
  class TraceRoutes
  class AgentRoutes

  class WorkspaceService
  class PaperParsingService
  class CodeAnalysisService
  class TracingService
  class AgentRuntime
  class TensorFlowBuilder
  class LocalSyncService

  class Project
  class PaperDocument
  class CodeRepository
  class TraceLink
  class AgentRun

  ProjectRoutes --> Project
  PaperRoutes --> PaperParsingService
  RepositoryRoutes --> CodeAnalysisService
  WorkspaceRoutes --> WorkspaceService
  TraceRoutes --> TracingService
  AgentRoutes --> AgentRuntime

  PaperParsingService --> PaperDocument
  CodeAnalysisService --> CodeRepository
  CodeAnalysisService --> TensorFlowBuilder
  WorkspaceService --> PaperDocument
  WorkspaceService --> CodeRepository
  WorkspaceService --> TraceLink
  TracingService --> TraceLink
  AgentRuntime --> AgentRun
  AgentRuntime --> TraceLink
  AgentRuntime --> CodeRepository
  LocalSyncService --> Project
```

### 3.3 设计时序图：PDF 上传与 MinerU 解析（用例 1）

```mermaid
sequenceDiagram
  participant UI as ProjectWorkspaceView
  participant API as papers route
  participant Job as ParsingService
  participant MU as MinerU Provider
  participant DB as SQLite

  UI->>API: POST /projects/{id}/paper (PDF)
  API->>DB: 保存文件与 PaperDocument(pending)
  API->>Job: enqueue parse job
  API-->>UI: job_id / status
  Job->>MU: submit / poll
  MU-->>Job: raw parse payload
  Job->>Job: normalize → pages/sections
  Job->>DB: PaperDocument(ready)
  UI->>API: GET workspace / paper
  API-->>UI: 结构化论文页
```

### 3.4 设计时序图：Agent 写操作确认（用例 3）

```mermaid
sequenceDiagram
  participant UI as AgentPanel
  participant API as agent route
  participant RT as AgentRuntime
  participant Tool as tools.execute
  participant WS as workspace_service

  UI->>API: POST run (stream SSE)
  API->>RT: 调用 LLM + 工具规划
  RT->>Tool: 请求写工具 (save_code / create_trace / ...)
  Tool-->>API: pending confirmation
  API-->>UI: 确认卡片事件
  UI->>API: confirm / reject
  alt 用户确认
    API->>Tool: execute
    Tool->>WS: 持久化变更
    API-->>UI: 成功 + 刷新提示
  else 用户拒绝
    API-->>UI: 取消，不落库
  end
```

### 3.5 部署 / 运行视图

```mermaid
flowchart TB
  subgraph DevMachine[开发者 / 演示机]
    Browser[浏览器 Vite 或静态页]
    Tauri[Tauri App]
    LocalAPI[Local FastAPI :8000/:8765]
    SQLite[(SQLite)]
    Uploads[(uploads/)]
  end

  subgraph Optional[可选外部]
    MinerUSvc[MinerU]
    LLMSvc[LLM API]
    Cloud[(server Compose\nPG + Blob)]
  end

  Browser --> LocalAPI
  Tauri --> LocalAPI
  LocalAPI --> SQLite
  LocalAPI --> Uploads
  LocalAPI --> MinerUSvc
  LocalAPI --> LLMSvc
  Browser -.-> Cloud
  Tauri -.-> Cloud
```

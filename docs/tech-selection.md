# 技术选型说明

## 选型结论

本项目采用前后端分离架构：

- 前端：Vue 3 + TypeScript + Vite + Vue Router + Pinia + Element Plus
- 后端：FastAPI + Pydantic v2 + SQLModel + SQLite/PostgreSQL
- 文件与解析：本地文件系统存储上传物，服务层封装 PDF 解析和代码静态分析
- 后续扩展：保留 VS Code 插件通过同一 HTTP API 接入工作台项目、文档结构和追溯关系

## 前端理由

Vue 3 与 TypeScript 适合快速构建低保真工作台，同时保持类型约束。Vite 启动快，适合迭代演示。Element Plus 提供成熟表格、上传、布局和标签组件，能快速形成项目列表、上传区、双栏阅读/浏览工作区和追溯结果面板。

## 后端理由

FastAPI 原生支持 OpenAPI，可将接口契约作为前后端协作依据。Pydantic v2 适合定义请求/响应模型。SQLModel 兼具 SQLAlchemy 能力和 Pydantic 类型体验，第一迭代可用 SQLite 快速落地，后续平滑迁移 PostgreSQL。

## 扩展方向

- 解析任务异步化：后续接入 Celery/RQ 或 FastAPI BackgroundTasks。
- 追溯算法服务化：将 embedding 检索、规则匹配、LLM 辅助解释封装为独立 `trace` service。
- VS Code 插件：插件只需复用项目、代码符号、追溯关系接口，不直接操作数据库。
- 权限与团队协作：后续增加用户、组织、项目成员和操作审计表。


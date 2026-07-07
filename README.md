# 论文代码双向追溯 Web 工作台

本项目是第一次迭代的前后端协作基线：前端使用 Vue 3 + TypeScript 搭建 Web 工作台低保真原型，后端使用 FastAPI 提供统一接口、OpenAPI 文档、SQLite 开发数据库、论文 PDF 解析最小原型和 Python 代码静态分析最小原型。

## 技术栈

- 前端：Vue 3、TypeScript、Vite、Vue Router、Pinia、Element Plus、Axios
- 后端：FastAPI、Pydantic v2、SQLModel/SQLAlchemy、Uvicorn、SQLite
- 解析原型：pypdf 提取 PDF 文本与页码，Python ast 分析代码文件树、类、函数、导入关系与 PyTorch 模型候选
- 接口契约：FastAPI 自动生成 OpenAPI，手写契约文档见 `docs/api-contract.md`

## 目录

```text
paper-code-trace-workbench/
  backend/        FastAPI 后端
  frontend/       Vue 3 前端
  database/       数据库初版 SQL 草稿
  docs/           需求拆分、技术选型、接口契约、架构说明
```

## 快速启动

后端：

```bash
cd backend
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

前端：

```bash
cd frontend
pnpm install
pnpm dev
```

Windows PowerShell：

```powershell
# 后端
Copy-Item .env.example backend\.env -Force
cd backend
python -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install -e '.[dev]'
python -m uvicorn app.main:app --reload

# 前端另开一个 PowerShell
cd <项目根目录>\frontend
$env:COREPACK_ENABLE_AUTO_PIN=0
corepack pnpm install
corepack pnpm dev
```

默认后端地址为 `http://127.0.0.1:8000`，接口文档为 `http://127.0.0.1:8000/docs`。

## 第一迭代交付范围

- 项目、论文、代码仓库、追溯关系的基础接口
- 文件上传接口：论文 PDF、代码 ZIP
- 论文解析最小原型：标题、摘要、章节、段落、页码结构化 JSON
- 代码分析最小原型：文件树、类、函数、导入关系、PyTorch 模型结构候选
- Web 工作台静态原型：项目列表、上传区、论文阅读区、代码浏览区、追溯结果面板

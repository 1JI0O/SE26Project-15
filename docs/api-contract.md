# 接口契约

后端统一前缀为 `/api/v1`。运行后可访问 `/docs` 查看自动生成的 OpenAPI 文档。

## 健康检查

`GET /api/v1/health`

响应：

```json
{
  "status": "ok",
  "service": "Paper Code Trace Workbench"
}
```

## 项目

`GET /api/v1/projects`

返回项目列表。

`POST /api/v1/projects`

请求：

```json
{
  "name": "ResNet 论文复现",
  "description": "追溯论文段落与 PyTorch 实现"
}
```

`GET /api/v1/projects/{project_id}`

返回项目详情。

## 论文

`POST /api/v1/projects/{project_id}/paper`

表单上传字段：`file`，仅第一迭代约定为 PDF。

返回：

```json
{
  "id": 1,
  "project_id": 1,
  "filename": "paper.pdf",
  "title": "Paper Title",
  "abstract": "Abstract text",
  "sections": [],
  "paragraphs": []
}
```

`GET /api/v1/projects/{project_id}/paper`

返回该项目最新论文解析结果。

## 代码仓库

`POST /api/v1/projects/{project_id}/code`

表单上传字段：`file`，第一迭代约定为 ZIP 包。

返回：

```json
{
  "id": 1,
  "project_id": 1,
  "filename": "repo.zip",
  "file_tree": [],
  "symbols": [],
  "imports": [],
  "pytorch_candidates": []
}
```

`GET /api/v1/projects/{project_id}/code`

返回该项目最新代码分析结果。

## 追溯关系

`GET /api/v1/projects/{project_id}/trace-links`

返回已保存的追溯关系。

`POST /api/v1/projects/{project_id}/trace-links`

请求：

```json
{
  "paper_ref": "paragraph:12",
  "code_ref": "models/resnet.py:ResNet",
  "relation_type": "implements",
  "confidence": 0.82,
  "rationale": "该代码类实现了论文中的残差网络结构。"
}
```

`POST /api/v1/projects/{project_id}/trace-links/suggest`

基于当前论文与代码分析结果生成候选追溯关系。第一迭代为启发式示例，后续可替换为 embedding/LLM/规则混合方案。


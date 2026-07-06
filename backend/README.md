# Backend

FastAPI 后端提供项目、论文上传解析、代码上传分析和追溯关系接口。

## Run

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
uvicorn app.main:app --reload
```

OpenAPI 文档：`http://127.0.0.1:8000/docs`。


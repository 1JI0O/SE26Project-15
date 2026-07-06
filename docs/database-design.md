# 数据库初版设计

## 表

- `project`：项目工作空间。
- `paper_document`：论文文件与解析 JSON。
- `code_repository`：代码包与静态分析 JSON。
- `trace_link`：论文片段与代码对象的追溯关系。

## 设计原则

- 第一迭代将章节、段落、符号、文件树等结构化内容存为 JSON，方便快速迭代解析器。
- 对外接口使用稳定字段，内部 JSON 结构后续可逐步规范为独立表。
- `trace_link.paper_ref` 与 `trace_link.code_ref` 先采用可读引用字符串，后续可升级为外键引用到段落表和符号表。


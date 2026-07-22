# CLAUDE.md

本文件为项目级硬约束，Claude Code 及其他 AI 助手在本仓库中工作时必须严格遵守。

## Git 提交与合并政策（硬约束）

- 任何 commit、merge 均不得携带 Claude 或其他 AI 的联合作者信息，即禁止出现 `Co-Authored-By: Claude ...` 或类似的 AI 署名 trailer。
- 所有提交只能使用仓库所有者本人的 git 身份（姓名/邮箱），不得添加、保留或恢复任何 AI 身份信息。
- 生成 commit message 时不得包含任何暗示由 AI 生成/协作的署名或标注。
- 若发现历史提交中已包含 AI 署名，应在获得用户明确确认后修正，且修正过程中不得改变代码内容，仅去除署名部分。

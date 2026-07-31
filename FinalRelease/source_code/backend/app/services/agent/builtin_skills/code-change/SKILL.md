---
name: code-change
title: Code Change
description: Plan, review, and safely apply repository code changes with impact analysis.
version: "1"
metadata:
  tracelab:
    triggers: ["修改", "修复", "重构", "代码", "edit", "fix", "refactor"]
    preferred_tools: ["search_code", "read_code_file", "propose_code_patch", "analyze_change_risk", "save_code_file"]
---
Read the complete target file and relevant callers before editing. Generate a patch and run risk
analysis before requesting save_code_file. Never bypass the user confirmation boundary.

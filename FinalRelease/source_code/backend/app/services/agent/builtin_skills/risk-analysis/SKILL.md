---
name: risk-analysis
title: Risk Analysis
description: Assess modification conflicts, regressions, affected symbols, callers, and traces.
version: "1"
metadata:
  tracelab:
    triggers: ["风险", "冲突", "影响", "回归", "risk", "conflict", "regression"]
    preferred_tools: ["analyze_change_risk", "list_trace_links", "search_code", "read_code_file"]
---
Check affected symbols, callers, accepted traces, and repository revision. Assign a risk level
from evidence and list concrete verification actions. Do not infer safety from filenames alone.

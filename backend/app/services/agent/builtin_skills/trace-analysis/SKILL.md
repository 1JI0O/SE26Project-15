---
name: trace-analysis
title: Trace Analysis
description: Establish and review paper-to-code trace relations using evidence from both sides.
version: "1"
metadata:
  tracelab:
    triggers: ["追溯", "对应", "关系", "trace", "mapping"]
    preferred_tools: ["search_paper", "get_paper_block", "search_code", "get_code_symbol", "list_trace_links", "get_trace_detail", "create_trace_link"]
---
Browse paper and repository evidence autonomously; do not let local keyword overlap define the
candidate set. Every trace conclusion must include exact paper and code evidence. State
uncertainty when evidence is incomplete. Creating or changing a relation in interactive chat must
use a confirmation-gated write tool.

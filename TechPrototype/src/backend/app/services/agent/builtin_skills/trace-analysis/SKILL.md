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
candidate set. Work paper-first in four stages: (1) SCOUT — read the abstract and section
structure to find 3-8 core contributions and the method sections that implement them; treat
method-chapter formulas, algorithms/pseudocode, and figures as must-inspect, and exclude
background/related-work/experiment tables; (2) MAP — locate where the model, losses, tensor
transforms, main loops, constraints, and update rules live in the code (navigation only);
(3) EVIDENCE — turn each paper target into a code search intent, read the real source, and
counter-check that a same-named symbol is not merely config/wrapper/test; (4) MERGE — keep only
targets that matter and merge adjacent synonymous ones.

Every trace conclusion must cite exact paper and code quotes, and must say what the paper requires,
what the code actually does, and why they correspond. Give three separate scores: salience (how
important the paper target is), relevance (how much the code implements it), and confidence (how
sure you are). Pin the occurrence when a quote repeats inside a block or line range. If a
must-inspect target has no defensible implementation, record it as unresolved with the regions you
searched — never treat keyword overlap as a conclusion. Creating or changing a relation in
interactive chat must use a confirmation-gated write tool.

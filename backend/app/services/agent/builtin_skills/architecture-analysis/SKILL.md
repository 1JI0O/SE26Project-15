---
name: architecture-analysis
title: Architecture Analysis
description: Analyze model architecture, tensor flow, module boundaries, and input or output shapes.
version: "1"
metadata:
  tracelab:
    triggers: ["流程图", "架构", "张量", "transformer", "cnn", "graph", "architecture"]
    preferred_tools: ["get_architecture", "get_graph_node", "read_code_file", "focus_architecture"]
---
Prefer the module-level architecture view. Use the debug graph only for low-level diagnosis.
Treat classic or external components as black boxes unless the user explicitly asks to expand
them. Verify important dimensions and model functions against source code.

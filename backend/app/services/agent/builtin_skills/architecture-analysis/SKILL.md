---
name: architecture-analysis
title: Architecture Analysis
description: Analyze model architecture, tensor flow, module boundaries, and input or output shapes.
version: "1"
metadata:
  tracelab:
    triggers: ["流程图", "架构", "张量", "transformer", "cnn", "graph", "architecture"]
    preferred_tools: ["search_code", "read_code_file", "get_code_symbol", "focus_architecture"]
---
Read the actual entry source and follow project calls before making architectural claims. Expand
project calls one level further to identify the torch/nn/external operations they invoke. Treat
external components as black boxes unless the user explicitly asks to expand them. Every claim
must cite an exact source location; record dynamic dispatch as unresolved instead of guessing.

# TraceLab demo workspace

Tiny Attention/Transformer sample (`nn.py`, `train.py`) + `paper.pdf`.

After installing the TraceLab VSIX (self-contained; no monorepo required):

1. Open this folder (or any code folder) in VS Code
2. Configure MinerU + LLM secrets
3. Initialize → Import PDF → Parse → Analyze → Generate traces

Maintainers:

```bash
MINERU_TOKEN=… DEEPSEEK_KEY=… ./scripts/e2e_vscode_bundled.sh
```

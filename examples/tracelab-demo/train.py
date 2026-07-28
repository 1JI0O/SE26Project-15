"""Demo training entry for TraceLab workspace analysis."""

from __future__ import annotations

import torch

from nn import TinyTransformerBlock


def train_step(model: TinyTransformerBlock, batch: torch.Tensor) -> torch.Tensor:
    output = model(batch)
    loss = output.pow(2).mean()
    return loss


def main() -> None:
    model = TinyTransformerBlock(dim=64, heads=4)
    batch = torch.randn(2, 16, 64)
    loss = train_step(model, batch)
    print(f"demo loss={float(loss):.6f}")


if __name__ == "__main__":
    main()

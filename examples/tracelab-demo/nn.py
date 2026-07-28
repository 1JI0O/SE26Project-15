"""Tiny Attention-style module for TraceLab demo tracing."""

from __future__ import annotations

import math

import torch
from torch import nn


class MultiHeadAttention(nn.Module):
    """Scaled dot-product multi-head attention."""

    def __init__(self, dim: int, heads: int = 4) -> None:
        super().__init__()
        if dim % heads != 0:
            raise ValueError("dim must be divisible by heads")
        self.heads = heads
        self.head_dim = dim // heads
        self.qkv = nn.Linear(dim, dim * 3)
        self.proj = nn.Linear(dim, dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        batch, seq, dim = x.shape
        qkv = self.qkv(x).reshape(batch, seq, 3, self.heads, self.head_dim)
        qkv = qkv.permute(2, 0, 3, 1, 4)
        query, key, value = qkv[0], qkv[1], qkv[2]
        scores = (query @ key.transpose(-2, -1)) / math.sqrt(self.head_dim)
        weights = scores.softmax(dim=-1)
        context = weights @ value
        context = context.transpose(1, 2).reshape(batch, seq, dim)
        return self.proj(context)


class TinyTransformerBlock(nn.Module):
    def __init__(self, dim: int, heads: int = 4) -> None:
        super().__init__()
        self.attn = MultiHeadAttention(dim, heads=heads)
        self.ffn = nn.Sequential(
            nn.Linear(dim, dim * 4),
            nn.GELU(),
            nn.Linear(dim * 4, dim),
        )
        self.norm1 = nn.LayerNorm(dim)
        self.norm2 = nn.LayerNorm(dim)

    def forward(self, x: torch.Tensor) -> torch.Tensor:
        x = x + self.attn(self.norm1(x))
        x = x + self.ffn(self.norm2(x))
        return x

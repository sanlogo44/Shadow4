"""
Referenz-Architektur: "shadow-transformer".

Ein schlanker, gut lesbarer Decoder-only Transformer mit:
    - RMSNorm
    - Rotary Position Embeddings (RoPE)
    - Multi-Head Self-Attention mit optionalem KV-Cache
    - SwiGLU Feed-Forward

Dies ist EINE mögliche Architektur unter vielen. Neue Architekturen werden
einfach als weitere Klasse hinzugefügt und im `ARCHITECTURE_REGISTRY`
registriert -- das restliche System (Training, Registry, Benchmark, API)
bleibt unverändert, da es nur gegen `ShadowModel` programmiert ist.

Torch ist eine optionale Abhängigkeit: Ohne installiertes PyTorch bleibt
die gesamte übrige Engine (Tokenizer, Registry, Dataset, Benchmark-Gerüst,
Node-System, API-Schemas) trotzdem benutzbar.
"""

from __future__ import annotations

import math
from typing import Optional

from shadow_engine.config import ModelCoreConfig
from shadow_engine.model_core.base import GenerationConfig

try:
    import torch
    import torch.nn as nn
    import torch.nn.functional as F
    _TORCH_AVAILABLE = True
except ImportError:  # pragma: no cover
    _TORCH_AVAILABLE = False
    torch = None
    nn = object  # type: ignore


def _require_torch():
    if not _TORCH_AVAILABLE:
        raise RuntimeError(
            "PyTorch ist nicht installiert. Installiere `torch`, um "
            "ShadowTransformer zu instanziieren (siehe requirements.txt)."
        )


if _TORCH_AVAILABLE:

    class RMSNorm(nn.Module):
        def __init__(self, dim: int, eps: float = 1e-6):
            super().__init__()
            self.eps = eps
            self.weight = nn.Parameter(torch.ones(dim))

        def forward(self, x):
            norm = x * torch.rsqrt(x.pow(2).mean(-1, keepdim=True) + self.eps)
            return norm * self.weight

    def _rope_cache(seq_len: int, dim: int, theta: float, device, dtype):
        inv_freq = 1.0 / (theta ** (torch.arange(0, dim, 2, device=device).float() / dim))
        t = torch.arange(seq_len, device=device).float()
        freqs = torch.outer(t, inv_freq)
        emb = torch.cat((freqs, freqs), dim=-1)
        return emb.cos().to(dtype), emb.sin().to(dtype)

    def _rotate_half(x):
        x1, x2 = x.chunk(2, dim=-1)
        return torch.cat((-x2, x1), dim=-1)

    def _apply_rope(q, k, cos, sin):
        cos = cos[None, None, :, :]
        sin = sin[None, None, :, :]
        q_ = (q * cos) + (_rotate_half(q) * sin)
        k_ = (k * cos) + (_rotate_half(k) * sin)
        return q_, k_

    class CausalSelfAttention(nn.Module):
        def __init__(self, cfg: ModelCoreConfig):
            super().__init__()
            assert cfg.hidden_size % cfg.num_heads == 0
            self.num_heads = cfg.num_heads
            self.head_dim = cfg.hidden_size // cfg.num_heads
            self.rope_theta = cfg.rope_theta

            self.q_proj = nn.Linear(cfg.hidden_size, cfg.hidden_size, bias=False)
            self.k_proj = nn.Linear(cfg.hidden_size, cfg.hidden_size, bias=False)
            self.v_proj = nn.Linear(cfg.hidden_size, cfg.hidden_size, bias=False)
            self.o_proj = nn.Linear(cfg.hidden_size, cfg.hidden_size, bias=False)
            self.dropout = cfg.dropout

        def forward(self, x, attention_mask=None, kv_cache=None):
            b, t, c = x.shape
            q = self.q_proj(x).view(b, t, self.num_heads, self.head_dim).transpose(1, 2)
            k = self.k_proj(x).view(b, t, self.num_heads, self.head_dim).transpose(1, 2)
            v = self.v_proj(x).view(b, t, self.num_heads, self.head_dim).transpose(1, 2)

            if kv_cache is not None and kv_cache.get("k") is not None:
                past_len = kv_cache["k"].shape[2]
            else:
                past_len = 0

            cos, sin = _rope_cache(
                past_len + t, self.head_dim, self.rope_theta, x.device, x.dtype
            )
            cos, sin = cos[past_len:past_len + t], sin[past_len:past_len + t]
            q, k = _apply_rope(q, k, cos, sin)

            if kv_cache is not None:
                if kv_cache.get("k") is not None:
                    k = torch.cat([kv_cache["k"], k], dim=2)
                    v = torch.cat([kv_cache["v"], v], dim=2)
                kv_cache["k"], kv_cache["v"] = k, v

            attn_mask = None
            if attention_mask is None and kv_cache is None:
                attn_mask = torch.full((t, t), float("-inf"), device=x.device).triu(1)

            out = F.scaled_dot_product_attention(
                q, k, v, attn_mask=attn_mask,
                dropout_p=self.dropout if self.training else 0.0,
                is_causal=attention_mask is None and kv_cache is None,
            )
            out = out.transpose(1, 2).contiguous().view(b, t, c)
            return self.o_proj(out)

    class SwiGLU(nn.Module):
        def __init__(self, cfg: ModelCoreConfig):
            super().__init__()
            hidden = int(cfg.hidden_size * cfg.ffn_multiplier)
            self.gate = nn.Linear(cfg.hidden_size, hidden, bias=False)
            self.up = nn.Linear(cfg.hidden_size, hidden, bias=False)
            self.down = nn.Linear(hidden, cfg.hidden_size, bias=False)

        def forward(self, x):
            return self.down(F.silu(self.gate(x)) * self.up(x))

    class TransformerBlock(nn.Module):
        def __init__(self, cfg: ModelCoreConfig):
            super().__init__()
            self.attn_norm = RMSNorm(cfg.hidden_size)
            self.attn = CausalSelfAttention(cfg)
            self.ffn_norm = RMSNorm(cfg.hidden_size)
            self.ffn = SwiGLU(cfg)

        def forward(self, x, attention_mask=None, kv_cache=None):
            x = x + self.attn(self.attn_norm(x), attention_mask, kv_cache)
            x = x + self.ffn(self.ffn_norm(x))
            return x

    class ShadowTransformer(nn.Module):
        """Referenz-Implementierung von `ShadowModel` fuer das Torch-Backend."""

        architecture = "shadow-transformer"

        def __init__(self, cfg: ModelCoreConfig, name: str = "shadow-model"):
            super().__init__()
            self.cfg = cfg
            self.name = name

            self.token_embed = nn.Embedding(cfg.vocab_size, cfg.hidden_size)
            self.blocks = nn.ModuleList([TransformerBlock(cfg) for _ in range(cfg.num_layers)])
            self.final_norm = RMSNorm(cfg.hidden_size)
            self.lm_head = nn.Linear(cfg.hidden_size, cfg.vocab_size, bias=False)

            if cfg.tie_embeddings:
                self.lm_head.weight = self.token_embed.weight

            self.apply(self._init_weights)

        def _init_weights(self, module):
            if isinstance(module, nn.Linear):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)
            elif isinstance(module, nn.Embedding):
                nn.init.normal_(module.weight, mean=0.0, std=0.02)

        def forward(self, input_ids, attention_mask=None, labels=None, kv_caches=None, **kwargs):
            x = self.token_embed(input_ids)
            caches = kv_caches or [None] * len(self.blocks)
            for block, cache in zip(self.blocks, caches):
                x = block(x, attention_mask, cache)
            x = self.final_norm(x)
            logits = self.lm_head(x)

            loss = None
            if labels is not None:
                loss = F.cross_entropy(
                    logits[:, :-1, :].reshape(-1, logits.size(-1)),
                    labels[:, 1:].reshape(-1),
                    ignore_index=-100,
                )
            return {"logits": logits, "loss": loss}

        @torch.no_grad()
        def generate(self, input_ids, generation_config: GenerationConfig, **kwargs):
            kv_caches = [dict(k=None, v=None) for _ in self.blocks]
            generated = input_ids
            cur = input_ids

            for _ in range(generation_config.max_new_tokens):
                out = self.forward(cur, kv_caches=kv_caches)
                next_logits = out["logits"][:, -1, :] / max(generation_config.temperature, 1e-5)

                if generation_config.repetition_penalty != 1.0:
                    for token_id in set(generated[0].tolist()):
                        next_logits[:, token_id] /= generation_config.repetition_penalty

                if generation_config.top_k:
                    v, _ = torch.topk(next_logits, min(generation_config.top_k, next_logits.size(-1)))
                    next_logits[next_logits < v[:, [-1]]] = float("-inf")

                probs = F.softmax(next_logits, dim=-1)
                if generation_config.top_p < 1.0:
                    sorted_probs, sorted_idx = torch.sort(probs, descending=True)
                    cum_probs = torch.cumsum(sorted_probs, dim=-1)
                    mask = cum_probs - sorted_probs > generation_config.top_p
                    sorted_probs[mask] = 0.0
                    sorted_probs = sorted_probs / sorted_probs.sum(dim=-1, keepdim=True)
                    next_token = sorted_idx.gather(-1, torch.multinomial(sorted_probs, 1))
                else:
                    next_token = torch.multinomial(probs, 1)

                generated = torch.cat([generated, next_token], dim=1)
                cur = next_token

                if next_token.item() in generation_config.stop_token_ids:
                    break

            return generated

        def num_parameters(self) -> int:
            return sum(p.numel() for p in self.parameters())

        def config_dict(self) -> dict:
            return {
                "architecture": self.architecture,
                "name": self.name,
                **self.cfg.__dict__,
            }


# Architektur-Registry: neue Architekturen hier eintragen.
ARCHITECTURE_REGISTRY: dict[str, type] = {}
if _TORCH_AVAILABLE:
    ARCHITECTURE_REGISTRY["shadow-transformer"] = ShadowTransformer


def build_model(cfg: ModelCoreConfig, name: str = "shadow-model"):
    """Factory: baut ein Modell rein anhand des Architektur-Namens in der Config."""
    _require_torch()
    if cfg.architecture not in ARCHITECTURE_REGISTRY:
        raise ValueError(
            f"Unbekannte Architektur '{cfg.architecture}'. "
            f"Verfügbar: {list(ARCHITECTURE_REGISTRY)}"
        )
    return ARCHITECTURE_REGISTRY[cfg.architecture](cfg, name=name)

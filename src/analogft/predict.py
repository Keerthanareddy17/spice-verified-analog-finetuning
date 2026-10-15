"""One prediction interface over different models (Groq API, local Hugging Face model, +LoRA).

Every backend receives exactly the same messages, built by `prompting`:
    [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": format_prompt(state)}]

`Predictor.predict_one(state)` is what the Phase 4 agent calls on a live state (a dict with
spec, design, metrics, regions, available_actions); `predict_batch(records)` is for datasets.
Parsing and scoring live in `prompting.parse_response` and `evaluation`.
"""
from __future__ import annotations

import hashlib
import json
import os
import time
from dataclasses import asdict, dataclass, field
from pathlib import Path

from .prompting import SYSTEM_PROMPT, format_prompt, parse_response

GROQ_URL = "https://api.groq.com/openai/v1/chat/completions"


def build_messages(state: dict) -> list[dict]:
    """The exact system + user messages every backend sees (same for all models)."""
    return [{"role": "system", "content": SYSTEM_PROMPT}, {"role": "user", "content": format_prompt(state)}]


@dataclass
class Prediction:
    """Result for one state. `raw` is the model's final answer text (reasoning excluded)."""
    raw: str
    action: str | None
    error: str | None            # None, no_json, unknown_action, unavailable_action, api_error
    meta: dict = field(default_factory=dict)  # tokens, latency, finish_reason, ...

    def to_dict(self) -> dict:
        return asdict(self)


class Backend:
    """Turns lists of chat messages into (text, meta) pairs."""
    name = "backend"

    def generate(self, batch: list[list[dict]], keys: list[str]) -> list[tuple[str, dict]]:
        raise NotImplementedError


class Predictor:
    """Backend + prompt building + parsing."""

    def __init__(self, backend: Backend):
        self.backend = backend

    def predict_batch(self, records: list[dict], keys: list[str] | None = None) -> list[Prediction]:
        """`keys` identify examples for caching (default: record ids)."""
        keys = keys or [r["id"] for r in records]
        outs = self.backend.generate([build_messages(r) for r in records], keys)
        preds = []
        for r, (text, meta) in zip(records, outs):
            if meta.get("api_error"):
                preds.append(Prediction(text, None, "api_error", meta))
                continue
            action, err = parse_response(text, r["available_actions"])
            preds.append(Prediction(text, action, err, meta))
        return preds

    def predict_one(self, state: dict, key: str | None = None) -> Prediction:
        """Predict for a live state. The key defaults to a hash of the prompt (so identical states share a cache entry)."""
        msgs = build_messages(state)
        key = key or hashlib.sha1(msgs[1]["content"].encode()).hexdigest()[:16]
        return self.predict_batch([state], [key])[0]


# ----- Groq ------------------------------------------------------------------------------

class GroqBackend(Backend):
    """OpenAI-compatible chat completions at Groq, temperature 0, one request at a time.

    Raw responses are cached in `cache_path` (JSONL, keyed by model + example key) so an
    interrupted run resumes without spending tokens twice. Rate limits: sleeps until the
    token window resets when the remaining tokens are too few; retries 429s with backoff.
    """

    def __init__(self, model: str, cache_path: Path | None = None, reasoning_effort: str | None = "medium",
                 max_tokens: int = 2048, api_key: str | None = None, min_tokens_needed: int = 2600,
                 daily_token_budget: int | None = None, log=print):
        self.model, self.name = model, f"groq:{model}"
        self.reasoning_effort, self.max_tokens = reasoning_effort, max_tokens
        self.key = api_key or os.environ.get("GROQ_API_KEY")
        if not self.key:
            raise RuntimeError("GROQ_API_KEY is not set (put it in .env)")
        self.cache_path = Path(cache_path) if cache_path else None
        self.min_tokens_needed = min_tokens_needed
        self.daily_token_budget, self.tokens_spent = daily_token_budget, 0
        self.log = log
        self.rate_limits: dict = {}
        self.cache: dict[str, dict] = {}
        if self.cache_path and self.cache_path.exists():
            for line in self.cache_path.read_text().splitlines():
                if line.strip():
                    row = json.loads(line)
                    if row["model"] == model:
                        self.cache[row["key"]] = row

    # -- one HTTP call --
    def _post(self, messages: list[dict]) -> tuple[dict, dict, float]:
        import requests
        body = {"model": self.model, "messages": messages, "temperature": 0, "max_completion_tokens": self.max_tokens}
        if self.reasoning_effort:
            body["reasoning_effort"] = self.reasoning_effort
        headers = {"Authorization": f"Bearer {self.key}", "Content-Type": "application/json"}
        delay = 5.0
        for attempt in range(8):
            t0 = time.time()
            r = requests.post(GROQ_URL, headers=headers, json=body, timeout=120)
            dt = time.time() - t0
            self.rate_limits = {k.lower(): v for k, v in r.headers.items() if "ratelimit" in k.lower()}
            if r.status_code == 200:
                return r.json(), dict(r.headers), dt
            if r.status_code in (429, 500, 502, 503):
                wait = float(r.headers.get("retry-after", delay))
                if r.status_code == 429 and "per day" in r.text.lower():
                    raise DailyLimitReached(r.text[:300])
                self.log(f"  HTTP {r.status_code}, retrying in {wait:.0f}s (attempt {attempt + 1})")
                time.sleep(wait)
                delay = min(delay * 2, 60)
                continue
            raise RuntimeError(f"Groq HTTP {r.status_code}: {r.text[:300]}")
        raise RuntimeError("Groq: too many retries")

    def _pace(self) -> None:
        """If the per-minute token window is nearly used up, wait for it to reset."""
        rem = self.rate_limits.get("x-ratelimit-remaining-tokens")
        reset = self.rate_limits.get("x-ratelimit-reset-tokens")
        if rem is not None and float(rem) < self.min_tokens_needed:
            wait = _parse_duration(reset) if reset else 20.0
            self.log(f"  pacing: {rem} tokens left in window, sleeping {wait + 1:.0f}s")
            time.sleep(wait + 1)

    def generate(self, batch, keys):
        out = []
        for messages, key in zip(batch, keys):
            row = self.cache.get(key)
            if row is None:
                if self.daily_token_budget is not None and self.tokens_spent >= self.daily_token_budget:
                    raise DailyLimitReached(f"token budget {self.daily_token_budget} reached")
                self._pace()
                data, _, dt = self._post(messages)
                msg = data["choices"][0]["message"]
                usage = data.get("usage", {})
                details = usage.get("completion_tokens_details") or {}
                row = {"model": self.model, "key": key, "content": msg.get("content") or "",
                       "reasoning": (msg.get("reasoning") or "")[:1500],
                       "finish_reason": data["choices"][0].get("finish_reason"),
                       "prompt_tokens": usage.get("prompt_tokens"), "completion_tokens": usage.get("completion_tokens"),
                       "reasoning_tokens": details.get("reasoning_tokens"), "total_tokens": usage.get("total_tokens"),
                       "latency_s": round(dt, 2)}
                self.tokens_spent += row["total_tokens"] or 0
                self.cache[key] = row
                if self.cache_path:
                    self.cache_path.parent.mkdir(parents=True, exist_ok=True)
                    with self.cache_path.open("a") as f:
                        f.write(json.dumps(row) + "\n")
            meta = {k: row[k] for k in ("finish_reason", "prompt_tokens", "completion_tokens", "reasoning_tokens",
                                        "total_tokens", "latency_s")}
            meta["truncated"] = row["finish_reason"] == "length"
            out.append((row["content"], meta))
        return out


class DailyLimitReached(RuntimeError):
    """Groq's daily token cap (or our own budget) stopped the run; cached results are kept."""


def _parse_duration(s: str) -> float:
    """Groq reset headers look like '1m30.5s', '7.66s' or '250ms'."""
    total, num = 0.0, ""
    i = 0
    while i < len(s):
        ch = s[i]
        if ch.isdigit() or ch == ".":
            num += ch
        elif s[i:i + 2] == "ms":
            total += float(num) / 1000; num = ""; i += 1
        elif ch == "m":
            total += 60 * float(num); num = ""
        elif ch == "s":
            total += float(num); num = ""
        i += 1
    return total


# ----- Hugging Face -----------------------------------------------------------------------

class HFBackend(Backend):
    """A local causal LM (optionally with a LoRA adapter): batched greedy decoding via the chat template."""

    def __init__(self, model_name: str, adapter_path: str | Path | None = None, max_new_tokens: int = 64,
                 batch_size: int = 16, device: str | None = None, dtype: str | None = None):
        import torch
        from transformers import AutoModelForCausalLM, AutoTokenizer
        self.torch = torch
        self.device = device or ("cuda" if torch.cuda.is_available() else "mps" if torch.backends.mps.is_available() else "cpu")
        # fp16 on GPU (T4 has no bf16); fp32 on CPU/MPS for safety
        dt = {"fp16": torch.float16, "fp32": torch.float32, None: torch.float16 if self.device == "cuda" else torch.float32}[dtype]
        self.tok = AutoTokenizer.from_pretrained(model_name)
        self.tok.padding_side = "left"
        if self.tok.pad_token is None:
            self.tok.pad_token = self.tok.eos_token
        self.model = AutoModelForCausalLM.from_pretrained(model_name, dtype=dt).to(self.device)
        if adapter_path:
            from peft import PeftModel
            self.model = PeftModel.from_pretrained(self.model, str(adapter_path)).to(self.device)
        self.model.eval()
        self.max_new_tokens, self.batch_size = max_new_tokens, batch_size
        self.name = f"hf:{model_name}" + (f"+{Path(adapter_path).name}" if adapter_path else "")

    def generate(self, batch, keys=None):
        torch = self.torch
        texts = [self.tok.apply_chat_template(m, tokenize=False, add_generation_prompt=True) for m in batch]
        out: list[tuple[str, dict]] = []
        for i in range(0, len(texts), self.batch_size):
            enc = self.tok(texts[i:i + self.batch_size], return_tensors="pt", padding=True).to(self.device)
            with torch.no_grad():
                gen = self.model.generate(**enc, max_new_tokens=self.max_new_tokens, do_sample=False,
                                          pad_token_id=self.tok.pad_token_id)
            new = gen[:, enc["input_ids"].shape[1]:]
            for row in new:
                n_tok = int((row != self.tok.pad_token_id).sum())
                out.append((self.tok.decode(row, skip_special_tokens=True).strip(),
                            {"completion_tokens": n_tok, "truncated": n_tok >= self.max_new_tokens}))
        return out

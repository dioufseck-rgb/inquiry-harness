"""Cache-aware cost estimates and a shared, preflighted experiment budget.

The rate card is data, not a model-name allowlist in the LLM implementation.
Costs are API-usage estimates, not invoice reconciliation. Unknown charges
retain their entire reservation so a failed request cannot silently free money.
"""
from __future__ import annotations

from contextlib import contextmanager
import json
import os
from pathlib import Path
import time
import uuid


class BudgetExceeded(RuntimeError):
    pass


def token_counts(usage: dict, inclusive: bool) -> tuple[int, int, int, int]:
    if inclusive:
        read = usage.get("cached_input_tokens", 0)
        write = usage.get("cache_write_input_tokens", 0)
        regular = max(0, usage["input_tokens"] - read - write)
    else:
        regular = usage["input_tokens"]
        read = usage.get("cache_read_input_tokens", 0)
        write = usage.get("cache_creation_input_tokens", 0)
    return regular, read, write, usage["output_tokens"]


def estimate_cost(usage: dict, rate: dict) -> float:
    counts = token_counts(usage, rate.get("input_includes_cache", False))
    tier = rate.get("long", rate) if sum(counts[:3]) > rate.get("long_above_tokens", float("inf")) else rate
    return sum(n * tier[k] for n, k in zip(counts, ("input", "cached_input", "cache_write", "output"))) / 1_000_000


@contextmanager
def _locked(path: Path):
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("a+b") as handle:
        if handle.tell() == 0:
            handle.write(b"0")
            handle.flush()
        if os.name == "nt":
            import msvcrt
            deadline = time.monotonic() + 30
            while True:
                try:
                    handle.seek(0)
                    msvcrt.locking(handle.fileno(), msvcrt.LK_NBLCK, 1)
                    break
                except OSError:
                    if time.monotonic() >= deadline:
                        raise TimeoutError("experiment budget lock timed out")
                    time.sleep(0.05)
        else:
            import fcntl
            fcntl.flock(handle, fcntl.LOCK_EX)
        try:
            yield
        finally:
            if os.name == "nt":
                handle.seek(0)
                msvcrt.locking(handle.fileno(), msvcrt.LK_UNLCK, 1)
            else:
                fcntl.flock(handle, fcntl.LOCK_UN)


class ExperimentBudget:
    def __init__(self, path: Path, limits: dict[str, float], reserved: dict[str, float] | None = None):
        self.path = Path(path)
        self.limits = limits
        self.reserved = reserved or {}

    def _read(self) -> dict:
        return json.loads(self.path.read_text(encoding="utf-8")) if self.path.exists() else {"spent": {}, "pending": {}, "calls": []}

    def _write(self, data: dict) -> None:
        temporary = self.path.with_suffix(f".tmp-{os.getpid()}")
        temporary.write_text(json.dumps(data, indent=2), encoding="utf-8")
        os.replace(temporary, self.path)

    def reserve(self, provider: str, upper_bound: float, *, use_reserved: bool = False) -> str:
        with _locked(self.path.with_suffix(".lock")):
            data = self._read()
            pending = sum(r["usd"] for r in data["pending"].values() if r["provider"] == provider)
            limit = self.limits[provider] - (0 if use_reserved else self.reserved.get(provider, 0))
            if data["spent"].get(provider, 0) + pending + upper_bound > limit + 1e-9:
                raise BudgetExceeded(f"{provider} budget would exceed ${limit:.2f}; no request sent")
            token = uuid.uuid4().hex
            data["pending"][token] = {"provider": provider, "usd": upper_bound}
            self._write(data)
            return token

    def finish(self, token: str, actual: float | None, metadata: dict) -> None:
        with _locked(self.path.with_suffix(".lock")):
            data = self._read()
            reservation = data["pending"].pop(token)
            charge = reservation["usd"] if actual is None else actual
            provider = reservation["provider"]
            data["spent"][provider] = data["spent"].get(provider, 0) + charge
            data["calls"].append({**metadata, "provider": provider, "cost_usd": actual,
                                  "budget_debit_usd": charge, "reserved_usd": reservation["usd"]})
            self._write(data)

    def status(self) -> dict:
        with _locked(self.path.with_suffix(".lock")):
            return self._read()

"""Optional MCP stdio transport for the epistemic inquiry service.

Run one host-configured instance per trust boundary. The transport exposes no
application actions, source-writing operation, shell or caller-selected path.
Network hosting, caller authentication and scheduled watching are separate work.
"""

from __future__ import annotations

import argparse
import asyncio
from functools import partial
import json
from typing import Any

from pathlib import Path

from .runtime import Budget, validate_prices
from .service import InquiryService
from .workers import LLMWorker


def create_server(service: InquiryService):
    try:
        from mcp.server.fastmcp import FastMCP
    except ImportError as error:
        raise RuntimeError("Install inquiry-harness[service] to use the MCP transport") from error
    server = FastMCP(
        "Epistemic Inquiry",
        instructions="Examine propositions under explicit profiles. Findings never authorize an action. "
                     "Use capabilities to inspect supported forms, limits and the request schema.",
    )

    @server.tool()
    def capabilities() -> dict[str, Any]:
        """Describe the generic request contract, implemented methods and host limits."""
        return service.capabilities()

    @server.tool()
    async def inquire(request: dict[str, Any], budget: dict[str, Any] | None = None,
                      mode: str = "documents", include_record: bool = False) -> dict[str, Any]:
        """Examine a scoped question using supplied sources and return standing with warrant."""
        return await asyncio.to_thread(service.inquire, request, budget=budget,
                                       mode=mode, include_record=include_record)

    @server.tool()
    async def check(request: dict[str, Any], budget: dict[str, Any] | None = None,
                    mode: str = "supplied", include_record: bool = False) -> dict[str, Any]:
        """Run a focused inquiry with a smaller budget and the same acceptance requirements."""
        return await asyncio.to_thread(service.check, request, budget=budget,
                                       mode=mode, include_record=include_record)

    @server.tool()
    async def replay(inquiry_id: str) -> dict[str, Any]:
        """Verify and recompute a stored inquiry; no model calls or truth guarantee."""
        return await asyncio.to_thread(service.replay, inquiry_id)

    @server.resource("inquiry://records/{inquiry_id}")
    def inquiry_record(inquiry_id: str) -> str:
        """The complete host-owned argument record and trace for one inquiry."""
        return json.dumps(service.read_record(inquiry_id), ensure_ascii=False, allow_nan=False)

    return server


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Epistemic inquiry service over MCP stdio.")
    parser.add_argument("--model", required=True, help="Explicit provider:model; credentials use provider environment variables.")
    parser.add_argument("--critic-model", help="Optional separate critic provider:model.")
    parser.add_argument("--effort", choices=["none", "low", "medium", "high"], default="low")
    parser.add_argument("--record-root", default="runs/service")
    parser.add_argument("--calls", type=int, default=10)
    parser.add_argument("--tool-calls", type=int, default=8)
    parser.add_argument("--tokens", type=int, default=160000)
    parser.add_argument("--output-tokens", type=int, default=8192)
    parser.add_argument("--timeout", type=float, default=180)
    parser.add_argument("--prices", help="JSON price table keyed by provider:model (input, cached_input, output USD per million tokens).")
    parser.add_argument("--max-cost-usd", type=float, default=None,
                        help="Host dollar cap per inquiry; requires a price entry for every configured worker.")
    return parser.parse_args(argv)


def build_service(args: argparse.Namespace) -> InquiryService:
    """Build the host-configured service; the cap is checked against the price table before any request."""
    effort = None if args.effort == "none" else args.effort
    prices = validate_prices(json.loads(Path(args.prices).read_text(encoding="utf-8"))) if args.prices else {}
    identities = [args.model] + ([args.critic_model] if args.critic_model else [])
    service = InquiryService(
        partial(LLMWorker.from_spec, args.model, effort=effort),
        critic_factory=partial(LLMWorker.from_spec, args.critic_model, effort=effort) if args.critic_model else None,
        max_budget=Budget(max_model_calls=args.calls, max_tool_calls=args.tool_calls,
                          max_total_tokens=args.tokens, max_output_tokens=args.output_tokens,
                          timeout_seconds=args.timeout, max_cost_usd=args.max_cost_usd),
        record_root=args.record_root, prices=prices, worker_identities=identities,
    )
    if args.max_cost_usd is not None:
        service._check_prices_cover_workers()
    return service


def main(argv: list[str] | None = None) -> int:
    service = build_service(parse_args(argv))
    create_server(service).run(transport="stdio")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""Check connectivity and basic structured arithmetic without student data."""

import argparse
import os
import sys
from dataclasses import replace
from pathlib import Path

from homework_ta.application.ports.llm import ChatMessage, LLMRequest
from homework_ta.infrastructure.llm.openai_compatible import ProviderError
from homework_ta.infrastructure.llm.router import LiteLLMRouter, RouterConfig
from homework_ta.interfaces.cli import _default_prompts_dir, _read_prompt
from homework_ta.observability import configure_logging


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--router-config",
        type=Path,
        default=Path(os.environ.get("HOMEWORK_TA_ROUTER_CONFIG", "config/router.jsonc")),
    )
    parser.add_argument("--provider", help="check only this configured provider")
    parser.add_argument("--prompt", help="plain chat connectivity test (no JSON requirement)")
    parser.add_argument("--log-file", type=Path, default=Path("logs/provider-check.jsonl"))
    args = parser.parse_args(argv)
    try:
        configure_logging(args.log_file, console=True)
        config = RouterConfig.load(args.router_config)
        if args.provider:
            routes = tuple(route for route in config.providers if route.name == args.provider)
            if not routes:
                raise ValueError("provider is not present in router configuration")
            config = replace(config, providers=routes)
        request = LLMRequest(
            messages=(
                ChatMessage(
                    "user",
                    args.prompt or _read_prompt(_default_prompts_dir() / "provider_smoke.md"),
                ),
            ),
            response_schema=None
            if args.prompt is not None
            else {
                "type": "object",
                "properties": {"answer": {"const": 14}},
                "required": ["answer"],
                "additionalProperties": False,
            },
            schema_name="plain_chat" if args.prompt is not None else "synthetic_arithmetic",
        )
        result = LiteLLMRouter(config).complete(request)
        if args.prompt is not None:
            print(f"Provider check passed: {result.model}; reply: {result.content}")
        else:
            print(f"Provider check passed: {result.model}; arithmetic and JSON validated.")
        return 0
    except (OSError, ValueError, ProviderError) as exc:
        print(f"Provider check failed: {exc}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

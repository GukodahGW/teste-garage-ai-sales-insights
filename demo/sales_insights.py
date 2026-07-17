"""Demonstra o consumo do endpoint GET /sales-insights."""

from __future__ import annotations

import argparse
import os
from urllib.parse import urlencode

from http_client import get_json

DEFAULT_BASE_URL = "http://127.0.0.1:8000"
DEFAULT_QUESTION = "Qual foi o produto mais vendido em janeiro de 2025?"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Faz uma pergunta ao endpoint GET /sales-insights."
    )
    parser.add_argument(
        "question",
        nargs="?",
        default=DEFAULT_QUESTION,
        help=f"pergunta sobre as vendas (padrão: {DEFAULT_QUESTION!r})",
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("GARAGE_API_URL", DEFAULT_BASE_URL),
        help="URL base da API (padrão: GARAGE_API_URL ou http://127.0.0.1:8000)",
    )
    args = parser.parse_args()

    query = urlencode({"question": args.question})
    url = f"{args.base_url.rstrip('/')}/sales-insights?{query}"
    return get_json(url)


if __name__ == "__main__":
    raise SystemExit(main())

"""Demonstra o consumo do endpoint GET /top-products."""

from __future__ import annotations

import argparse
import os

from http_client import get_json

DEFAULT_BASE_URL = "http://127.0.0.1:8000"


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Consulta o endpoint GET /top-products."
    )
    parser.add_argument(
        "--base-url",
        default=os.getenv("GARAGE_API_URL", DEFAULT_BASE_URL),
        help="URL base da API (padrão: GARAGE_API_URL ou http://127.0.0.1:8000)",
    )
    args = parser.parse_args()

    url = f"{args.base_url.rstrip('/')}/top-products"
    return get_json(url)


if __name__ == "__main__":
    raise SystemExit(main())

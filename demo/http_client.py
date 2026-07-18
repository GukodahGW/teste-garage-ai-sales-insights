"""Pequeno cliente HTTP compartilhado pelos demonstrativos da API."""

from __future__ import annotations

import json
import sys
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen


def get_json(url: str, *, timeout: float = 180.0) -> int:
    """Executa um GET real e imprime o status e o corpo da resposta."""

    request = Request(url, headers={"Accept": "application/json"}, method="GET")
    print(f"Requisicao: GET {url}")

    try:
        with urlopen(request, timeout=timeout) as response:
            status = response.status
            body = response.read().decode("utf-8")
    except HTTPError as error:
        status = error.code
        body = error.read().decode("utf-8", errors="replace")
    except TimeoutError:
        print(
            f"A API nao respondeu em {timeout:g} segundos. "
            "Verifique a disponibilidade do provedor LLM e tente novamente.",
            file=sys.stderr,
        )
        return 1
    except URLError as error:
        print(f"Falha ao conectar com a API: {error.reason}", file=sys.stderr)
        return 1

    print(f"Status: {status}")
    print("Resposta:")
    _print_body(body)
    return 0 if 200 <= status < 300 else 1


def _print_body(body: str) -> None:
    try:
        parsed: Any = json.loads(body)
    except json.JSONDecodeError:
        print(body)
        return

    print(json.dumps(parsed, ensure_ascii=False, indent=2))

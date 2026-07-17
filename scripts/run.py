"""Executa a aplicacao exclusivamente com o Python da .venv local."""

import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_PYTHON = (
    ROOT / ".venv" / "Scripts" / "python.exe"
    if sys.platform == "win32"
    else ROOT / ".venv" / "bin" / "python"
)


def main() -> int:
    if not VENV_PYTHON.exists():
        print("Ambiente ausente. Execute: python scripts/bootstrap.py", file=sys.stderr)
        return 2

    arguments = sys.argv[1:] or ["--help"]
    completed = subprocess.run(
        [str(VENV_PYTHON), "-m", "garage_sales", *arguments],
        cwd=ROOT,
        check=False,
    )
    return completed.returncode


if __name__ == "__main__":
    raise SystemExit(main())


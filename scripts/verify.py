"""Executa a suite de verificacao usando ferramentas instaladas na .venv."""

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
        print("Ambiente ausente. Execute: python scripts/bootstrap.py --dev", file=sys.stderr)
        return 2

    commands = (
        [str(VENV_PYTHON), "-m", "pytest", "-q"],
        [str(VENV_PYTHON), "-m", "ruff", "check", "."],
        [str(VENV_PYTHON), "-m", "mypy"],
    )
    for command in commands:
        print(f"> {' '.join(command)}", flush=True)
        completed = subprocess.run(command, cwd=ROOT, check=False)
        if completed.returncode != 0:
            return completed.returncode
    return 0


if __name__ == "__main__":
    raise SystemExit(main())


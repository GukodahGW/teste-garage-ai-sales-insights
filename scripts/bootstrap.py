"""Sincroniza a .venv local com o pyproject.toml e o uv.lock."""

import argparse
import shutil
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
BACKUP_VENV_DIR = ROOT / ".venv.previous"


def _run(command: list[str]) -> None:
    print(f"> {' '.join(command)}", flush=True)
    subprocess.run(command, cwd=ROOT, check=True)


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Prepara o ambiente local do projeto.")
    parser.add_argument(
        "--dev",
        action="store_true",
        help="instala pytest, ruff e mypy alem das dependencias de runtime",
    )
    parser.add_argument(
        "--database",
        choices=("sqlite", "postgres", "mysql"),
        default="sqlite",
        help="instala o driver do banco escolhido (padrao: sqlite)",
    )
    parser.add_argument(
        "--recreate",
        action="store_true",
        help="remove e recria somente o diretorio .venv deste projeto",
    )
    return parser.parse_args()


def main() -> int:
    if sys.version_info < (3, 11):
        print("Python 3.11 ou superior e obrigatorio.", file=sys.stderr)
        return 2

    args = _parse_args()
    uv_executable = shutil.which("uv")
    if uv_executable is None:
        print("uv nao encontrado. Instale-o e deixe o executavel no PATH.", file=sys.stderr)
        return 2

    if Path(uv_executable).resolve().is_relative_to(VENV_DIR.resolve()):
        print("Execute o bootstrap usando um uv externo a .venv.", file=sys.stderr)
        return 2

    backup_created = False

    if args.recreate and VENV_DIR.exists():
        if Path(sys.prefix).resolve() == VENV_DIR.resolve():
            print("Execute --recreate usando um Python externo a .venv.", file=sys.stderr)
            return 2
        if BACKUP_VENV_DIR.exists():
            try:
                shutil.rmtree(BACKUP_VENV_DIR)
            except PermissionError:
                print(
                    "Nao foi possivel remover .venv.previous. Feche processos que a usam.",
                    file=sys.stderr,
                )
                return 2
        try:
            VENV_DIR.rename(BACKUP_VENV_DIR)
        except OSError as error:
            print(f"Nao foi possivel preparar a recriacao: {error}", file=sys.stderr)
            return 2
        backup_created = True

    try:
        sync_command = [
            uv_executable,
            "sync",
            "--locked",
            "--python",
            sys.executable,
        ]
        if args.dev:
            sync_command.extend(["--extra", "dev"])
        if args.database != "sqlite":
            sync_command.extend(["--extra", args.database])
        _run(sync_command)
    except (OSError, subprocess.CalledProcessError) as error:
        print(f"Falha ao preparar o ambiente: {error}", file=sys.stderr)
        if backup_created and BACKUP_VENV_DIR.exists():
            shutil.rmtree(VENV_DIR, ignore_errors=True)
            if not VENV_DIR.exists():
                BACKUP_VENV_DIR.rename(VENV_DIR)
                print("O ambiente anterior foi restaurado.", file=sys.stderr)
        return 1

    if BACKUP_VENV_DIR.exists():
        try:
            shutil.rmtree(BACKUP_VENV_DIR)
        except PermissionError:
            print(
                "Aviso: .venv.previous ainda esta em uso e pode ser removida depois.",
                file=sys.stderr,
            )

    print("\nAmbiente pronto. Execute: python scripts/run.py --help")
    if args.dev:
        print("Validacao: python scripts/verify.py")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

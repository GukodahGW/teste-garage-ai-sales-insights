"""Cria a .venv local e instala somente dependencias fixadas no repositorio."""

import argparse
import shutil
import subprocess
import sys
import venv
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
VENV_DIR = ROOT / ".venv"
BACKUP_VENV_DIR = ROOT / ".venv.previous"
PIP_VERSION = "26.1.2"


def _venv_python() -> Path:
    if sys.platform == "win32":
        return VENV_DIR / "Scripts" / "python.exe"
    return VENV_DIR / "bin" / "python"


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
    virtual_python = _venv_python()
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
        if not virtual_python.exists():
            print(f"Criando ambiente virtual em {VENV_DIR}", flush=True)
            venv.EnvBuilder(with_pip=True).create(VENV_DIR)

        python = str(virtual_python)
        _run([python, "-m", "pip", "install", "--upgrade", f"pip=={PIP_VERSION}"])

        dependency_file = "dev.lock" if args.dev else "runtime.lock"
        install_command = [
            python,
            "-m",
            "pip",
            "install",
            "--requirement",
            str(ROOT / "requirements" / dependency_file),
        ]
        if args.database != "sqlite":
            install_command.extend(
                ["--requirement", str(ROOT / "requirements" / f"{args.database}.lock")]
            )
        _run(install_command)

        _run(
            [
                python,
                "-m",
                "pip",
                "install",
                "--editable",
                str(ROOT),
                "--no-deps",
                "--no-build-isolation",
            ]
        )
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

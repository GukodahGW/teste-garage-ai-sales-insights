from pathlib import Path

from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from garage_sales.cli import main


def test_runtime_cli_initializes_checks_and_queries_database(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    database_path = (tmp_path / "runtime.db").as_posix()
    monkeypatch.setenv("GARAGE_DATABASE_URL", f"sqlite+pysqlite:///{database_path}")

    assert main(["init-db"]) == 0
    assert main(["migrate-db"]) == 0
    assert main(["check-db"]) == 0
    assert main(["list-sales"]) == 0

    output = capsys.readouterr().out
    assert output.count("Migracoes aplicadas e seed validado: sqlite") == 2
    assert "Conexao OK: sqlite" in output
    assert '"id": 33' in output


def test_runtime_cli_loads_database_configuration_from_dotenv(
    tmp_path: Path,
    monkeypatch: MonkeyPatch,
) -> None:
    database_path = (tmp_path / "from-dotenv.db").as_posix()
    (tmp_path / ".env").write_text(
        f"GARAGE_DATABASE_URL=sqlite+pysqlite:///{database_path}\n",
        encoding="utf-8",
    )
    monkeypatch.setenv("GARAGE_DATABASE_URL", "temporary-value-for-cleanup")
    monkeypatch.delenv("GARAGE_DATABASE_URL")
    monkeypatch.chdir(tmp_path)

    assert main(["init-db"]) == 0

    assert (tmp_path / "from-dotenv.db").is_file()

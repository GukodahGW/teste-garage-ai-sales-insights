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
    assert main(["check-db"]) == 0
    assert main(["list-sales"]) == 0

    output = capsys.readouterr().out
    assert "Schema criado: sqlite" in output
    assert "Conexao OK: sqlite" in output
    assert "[]" in output


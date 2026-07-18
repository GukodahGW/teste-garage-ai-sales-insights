from _pytest.capture import CaptureFixture
from _pytest.monkeypatch import MonkeyPatch

from demo import http_client


def test_get_json_reports_timeout_without_a_traceback(
    monkeypatch: MonkeyPatch,
    capsys: CaptureFixture[str],
) -> None:
    def raise_timeout(*args: object, **kwargs: object) -> None:
        del args, kwargs
        raise TimeoutError

    monkeypatch.setattr(http_client, "urlopen", raise_timeout)

    assert http_client.get_json("http://127.0.0.1:8000/sales-insights", timeout=1) == 1

    captured = capsys.readouterr()
    assert "nao respondeu em 1 segundos" in captured.err
    assert "provedor LLM" in captured.err

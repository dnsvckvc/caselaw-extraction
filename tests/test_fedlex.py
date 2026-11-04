import json

import httpx
import pytest

from caselaw_extraction import fedlex
from caselaw_extraction.fedlex import CORE_CODES, fetch_abbreviations, load_code_map


def test_load_code_map_reads_cache_and_core_codes_win(tmp_path):
    cache = tmp_path / "abbr.json"
    cache.write_text(json.dumps({"ZGB": {"sr": "999"}, "EPÜ 2000": {"sr": "0.232.142.2"}}))
    m = load_code_map(cache)
    assert m["ZGB"] == CORE_CODES["ZGB"]  # the hand-checked list overrides Fedlex
    assert m["EPÜ 2000"] == "0.232.142.2"
    assert m["BGG"] == "173.110"


def test_load_code_map_fetches_and_writes_cache_when_missing(tmp_path, monkeypatch):
    calls = []

    def fake_fetch():
        calls.append(1)
        return {"XYZ": {"sr": "1.2", "act": "a", "title": "t"}}

    monkeypatch.setattr(fedlex, "fetch_abbreviations", fake_fetch)
    cache = tmp_path / "sub" / "abbr.json"
    m = load_code_map(cache)
    assert calls == [1]
    assert m["XYZ"] == "1.2"
    assert json.loads(cache.read_text())["XYZ"]["sr"] == "1.2"
    # a second call reads the cache and does not fetch again; refresh=True fetches
    assert load_code_map(cache)["XYZ"] == "1.2" and calls == [1]
    assert load_code_map(cache, refresh=True)["XYZ"] == "1.2" and calls == [1, 1]


def test_load_code_map_survives_http_error_and_read_only_dir(tmp_path, monkeypatch):
    def failing_fetch():
        raise httpx.ConnectError("offline")

    monkeypatch.setattr(fedlex, "fetch_abbreviations", failing_fetch)

    def no_write(self, *a, **k):
        raise OSError("read-only file system")

    monkeypatch.setattr(type(tmp_path), "write_text", no_write)
    m = load_code_map(tmp_path / "abbr.json")
    assert m["OR"] == "220" and "XYZ" not in m  # core codes still work offline


def test_fetch_abbreviations_parses_bindings_first_hit_wins(monkeypatch):
    payload = {
        "results": {
            "bindings": [
                {
                    "abbr": {"value": " OR "},
                    "sr": {"value": "220"},
                    "act": {"value": "u1"},
                    "title": {"value": "Obligationenrecht"},
                },
                {"abbr": {"value": "OR"}, "sr": {"value": "999"}, "act": {"value": "u2"}},
                {"abbr": {"value": "ZGB"}, "sr": {"value": "210"}, "act": {"value": "u3"}},
            ]
        }
    }

    class FakeResponse:
        def raise_for_status(self):
            pass

        def json(self):
            return payload

    class FakeClient:
        def __init__(self, timeout):
            self.timeout = timeout

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, url, params, headers):
            assert url == fedlex.ENDPOINT and "SELECT" in params["query"]
            return FakeResponse()

    monkeypatch.setattr(fedlex.httpx, "Client", FakeClient)
    out = fetch_abbreviations(timeout=1.0)
    assert out["OR"] == {"sr": "220", "act": "u1", "title": "Obligationenrecht"}
    assert out["ZGB"]["title"] == ""
    assert len(out) == 2


def test_fetch_abbreviations_raises_on_http_status(monkeypatch):
    class FakeResponse:
        def raise_for_status(self):
            raise httpx.HTTPStatusError("503", request=None, response=None)

    class FakeClient:
        def __init__(self, timeout):
            pass

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def get(self, *a, **k):
            return FakeResponse()

    monkeypatch.setattr(fedlex.httpx, "Client", FakeClient)
    with pytest.raises(httpx.HTTPError):
        fetch_abbreviations()

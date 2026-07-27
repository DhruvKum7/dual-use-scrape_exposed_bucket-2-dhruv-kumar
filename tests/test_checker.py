import json
from pathlib import Path
from urllib.error import HTTPError, URLError

import pytest

import checker
from checker import (
    check_endpoint,
    is_allowed_endpoint,
    load_results,
    normalise_bucket_endpoint,
    run_checker,
)


def test_local_endpoints_are_allowed() -> None:
    assert is_allowed_endpoint(
        "http://localhost:4566/creative-studio-assets"
    )
    assert is_allowed_endpoint(
        "http://127.0.0.1:4566/creative-studio-assets"
    )


def test_external_endpoints_are_blocked() -> None:
    assert not is_allowed_endpoint("https://example.com/bucket")
    assert not is_allowed_endpoint("https://google.com")
    assert not is_allowed_endpoint("file:///bucket")
    assert not is_allowed_endpoint("localhost:4566/bucket")


def test_normalise_object_url_to_bucket_root() -> None:
    endpoint = (
        "http://localhost:4566/"
        "creative-studio-assets/images/sample.jpg?version=1"
    )

    result = normalise_bucket_endpoint(
        endpoint=endpoint,
        bucket_name="creative-studio-assets",
    )

    assert result == (
        "http://localhost:4566/creative-studio-assets"
    )


def test_external_endpoint_is_not_requested() -> None:
    result = check_endpoint("https://example.com/test")

    assert result["accessible"] is False
    assert result["status_code"] is None
    assert result["error"] == "Blocked non-local endpoint"


def test_load_results_reads_valid_json(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "results.json"

    file_path.write_text(
        json.dumps(
            {
                "scraper": {
                    "depth": 3,
                    "discovered_buckets": [],
                },
                "checker": {
                    "buckets": [],
                },
            }
        ),
        encoding="utf-8",
    )

    result = load_results(file_path)

    assert result["scraper"]["depth"] == 3
    assert result["scraper"]["discovered_buckets"] == []


def test_load_results_rejects_missing_file(
    tmp_path: Path,
) -> None:
    missing_file = tmp_path / "missing.json"

    with pytest.raises(FileNotFoundError):
        load_results(missing_file)


def test_load_results_rejects_missing_scraper_section(
    tmp_path: Path,
) -> None:
    file_path = tmp_path / "invalid.json"
    file_path.write_text(
        json.dumps({"checker": {"buckets": []}}),
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_results(file_path)


def test_check_endpoint_success(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    class FakeHeaders:
        def get(self, key: str, default: str = "") -> str:
            if key == "Content-Type":
                return "application/xml"

            return default

    class FakeResponse:
        status = 200
        headers = FakeHeaders()

        def __enter__(self) -> "FakeResponse":
            return self

        def __exit__(
            self,
            exc_type: object,
            exc_value: object,
            traceback: object,
        ) -> None:
            return None

    def fake_urlopen(
        request: object,
        timeout: float,
    ) -> FakeResponse:
        return FakeResponse()

    monkeypatch.setattr(checker, "urlopen", fake_urlopen)

    result = check_endpoint(
        "http://localhost:4566/creative-studio-assets"
    )

    assert result["accessible"] is True
    assert result["status_code"] == 200
    assert result["content_type"] == "application/xml"
    assert result["error"] is None


def test_check_endpoint_http_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: object,
        timeout: float,
    ) -> None:
        raise HTTPError(
            url="http://localhost:4566/private",
            code=403,
            msg="Forbidden",
            hdrs=None,
            fp=None,
        )

    monkeypatch.setattr(checker, "urlopen", fake_urlopen)

    result = check_endpoint(
        "http://localhost:4566/private"
    )

    assert result["accessible"] is False
    assert result["status_code"] == 403


def test_check_endpoint_connection_error(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_urlopen(
        request: object,
        timeout: float,
    ) -> None:
        raise URLError("Connection refused")

    monkeypatch.setattr(checker, "urlopen", fake_urlopen)

    result = check_endpoint(
        "http://localhost:4566/test"
    )

    assert result["accessible"] is False
    assert result["status_code"] is None
    assert "Connection refused" in result["error"]


def test_run_checker_merges_results(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def fake_check_endpoint(
        endpoint: str,
        timeout: float = 5.0,
    ) -> dict[str, object]:
        return {
            "endpoint": endpoint,
            "accessible": True,
            "status_code": 200,
            "content_type": "application/xml",
            "error": None,
        }

    monkeypatch.setattr(
        checker,
        "check_endpoint",
        fake_check_endpoint,
    )

    data = {
        "scraper": {
            "depth": 3,
            "discovered_buckets": [
                {
                    "bucket_name": "creative-studio-assets",
                    "endpoints": [
                        (
                            "http://localhost:4566/"
                            "creative-studio-assets/image.jpg"
                        )
                    ],
                    "source_urls": [
                        "http://localhost:8000/gallery.html"
                    ],
                }
            ],
        },
        "checker": {
            "buckets": [],
        },
    }

    result = run_checker(data)

    buckets = result["checker"]["buckets"]

    assert len(buckets) == 1
    assert buckets[0]["bucket_name"] == "creative-studio-assets"
    assert buckets[0]["anonymous_access_detected"] is True
    assert buckets[0]["checks"][0]["status_code"] == 200
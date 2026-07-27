import json
from pathlib import Path

import pytest

from summary import (
    generate_summary,
    load_json,
    write_summary,
)


def test_generate_summary() -> None:
    results = {
        "scraper": {
            "depth": 3,
            "discovered_buckets": [
                {
                    "bucket_name": "creative-studio-assets",
                    "endpoints": [
                        (
                            "http://localhost:4566/"
                            "creative-studio-assets"
                        )
                    ],
                    "source_urls": [
                        "http://localhost:8000/config.html"
                    ],
                }
            ],
        },
        "checker": {
            "buckets": [
                {
                    "bucket_name": "creative-studio-assets",
                    "checks": [
                        {
                            "endpoint": (
                                "http://localhost:4566/"
                                "creative-studio-assets"
                            ),
                            "accessible": True,
                            "status_code": 200,
                        }
                    ],
                    "anonymous_access_detected": True,
                }
            ],
        },
    }

    summary = generate_summary(results)

    assert summary["summary"]["crawl_depth"] == 3
    assert (
        summary["summary"]["discovered_bucket_count"]
        == 1
    )
    assert summary["summary"]["checked_bucket_count"] == 1
    assert (
        summary["summary"]["accessible_bucket_count"]
        == 1
    )

    bucket = summary["buckets"][0]

    assert bucket["bucket_name"] == (
        "creative-studio-assets"
    )
    assert bucket["checked_endpoints"] == 1
    assert bucket["accessible_endpoints"] == 1
    assert bucket["anonymous_access_detected"] is True


def test_generate_summary_handles_empty_results() -> None:
    summary = generate_summary({})

    assert (
        summary["summary"]["discovered_bucket_count"]
        == 0
    )
    assert summary["summary"]["checked_bucket_count"] == 0
    assert (
        summary["summary"]["accessible_bucket_count"]
        == 0
    )
    assert summary["buckets"] == []


def test_load_json(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "results.json"
    input_file.write_text(
        json.dumps(
            {
                "scraper": {
                    "discovered_buckets": [],
                }
            }
        ),
        encoding="utf-8",
    )

    result = load_json(input_file)

    assert "scraper" in result


def test_load_json_rejects_missing_file(
    tmp_path: Path,
) -> None:
    with pytest.raises(FileNotFoundError):
        load_json(tmp_path / "missing.json")


def test_load_json_rejects_invalid_json(
    tmp_path: Path,
) -> None:
    input_file = tmp_path / "invalid.json"
    input_file.write_text(
        "{invalid json",
        encoding="utf-8",
    )

    with pytest.raises(ValueError):
        load_json(input_file)


def test_write_summary(
    tmp_path: Path,
) -> None:
    output_file = tmp_path / "summary.json"

    write_summary(
        {
            "summary": {
                "discovered_bucket_count": 0,
            },
            "buckets": [],
        },
        output_file,
    )

    assert output_file.exists()

    saved_data = json.loads(
        output_file.read_text(encoding="utf-8")
    )

    assert (
        saved_data["summary"]["discovered_bucket_count"]
        == 0
    )
    
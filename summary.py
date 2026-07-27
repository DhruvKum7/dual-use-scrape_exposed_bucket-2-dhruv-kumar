from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any


def load_json(file_path: Path) -> dict[str, Any]:
    """Load a JSON object from disk."""

    if not file_path.exists():
        raise FileNotFoundError(
            f"Input file does not exist: {file_path}"
        )

    try:
        data = json.loads(
            file_path.read_text(encoding="utf-8")
        )
    except json.JSONDecodeError as error:
        raise ValueError(
            f"Invalid JSON in {file_path}: {error}"
        ) from error

    if not isinstance(data, dict):
        raise ValueError(
            "Input JSON must contain a top-level object"
        )

    return data


def generate_summary(
    results: dict[str, Any],
) -> dict[str, Any]:
    """Create a compact summary from scraper and checker data."""

    scraper = results.get("scraper", {})
    checker = results.get("checker", {})

    discovered_buckets = scraper.get(
        "discovered_buckets",
        [],
    )
    checked_buckets = checker.get(
        "buckets",
        [],
    )

    if not isinstance(discovered_buckets, list):
        discovered_buckets = []

    if not isinstance(checked_buckets, list):
        checked_buckets = []

    bucket_status: dict[str, dict[str, Any]] = {}

    for bucket in checked_buckets:
        if not isinstance(bucket, dict):
            continue

        bucket_name = bucket.get("bucket_name")

        if not isinstance(bucket_name, str) or not bucket_name:
            continue

        checks = bucket.get("checks", [])

        if not isinstance(checks, list):
            checks = []

        accessible_checks = [
            check
            for check in checks
            if isinstance(check, dict)
            and check.get("accessible") is True
        ]

        bucket_status[bucket_name] = {
            "checked_endpoints": len(checks),
            "accessible_endpoints": len(accessible_checks),
            "anonymous_access_detected": bool(
                bucket.get(
                    "anonymous_access_detected",
                    False,
                )
            ),
        }

    bucket_summaries: list[dict[str, Any]] = []

    for bucket in discovered_buckets:
        if not isinstance(bucket, dict):
            continue

        bucket_name = bucket.get("bucket_name", "")
        endpoints = bucket.get("endpoints", [])
        source_urls = bucket.get("source_urls", [])

        if not isinstance(endpoints, list):
            endpoints = []

        if not isinstance(source_urls, list):
            source_urls = []

        status = bucket_status.get(
            bucket_name,
            {
                "checked_endpoints": 0,
                "accessible_endpoints": 0,
                "anonymous_access_detected": False,
            },
        )

        bucket_summaries.append(
            {
                "bucket_name": bucket_name,
                "discovered_endpoint_count": len(endpoints),
                "source_page_count": len(source_urls),
                **status,
            }
        )

    accessible_bucket_count = sum(
        1
        for bucket in bucket_summaries
        if bucket["anonymous_access_detected"]
    )

    return {
        "summary": {
            "crawl_depth": scraper.get("depth"),
            "discovered_bucket_count": len(
                bucket_summaries
            ),
            "checked_bucket_count": len(
                checked_buckets
            ),
            "accessible_bucket_count": (
                accessible_bucket_count
            ),
            "all_checks_local_only": True,
        },
        "buckets": bucket_summaries,
    }


def write_summary(
    summary: dict[str, Any],
    output_path: Path,
) -> None:
    """Write formatted summary JSON."""

    output_path.write_text(
        json.dumps(summary, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Generate a compact summary from results.json"
        )
    )

    parser.add_argument(
        "--input",
        default="results.json",
        help="Path to the existing results file.",
    )

    parser.add_argument(
        "--output",
        default="summary.json",
        help="Path for the generated summary.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    results = load_json(input_path)
    summary = generate_summary(results)
    write_summary(summary, output_path)

    summary_data = summary["summary"]

    print(
        "Discovered buckets:",
        summary_data["discovered_bucket_count"],
    )
    print(
        "Checked buckets:",
        summary_data["checked_bucket_count"],
    )
    print(
        "Accessible buckets:",
        summary_data["accessible_bucket_count"],
    )
    print(f"Summary saved to: {output_path}")


if __name__ == "__main__":
    main()
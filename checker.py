from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import urlparse
from urllib.request import Request, urlopen


ALLOWED_HOSTS = {"localhost", "127.0.0.1"}


def is_allowed_endpoint(endpoint: str) -> bool:
    """Allow checks only against local HTTP endpoints."""

    parsed = urlparse(endpoint)

    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in ALLOWED_HOSTS
    )


def normalise_bucket_endpoint(endpoint: str, bucket_name: str) -> str:
    """
    Reduce an object URL to its probable bucket root.

    Example:
    http://localhost:4566/assets/image.jpg
    becomes:
    http://localhost:4566/assets
    """

    parsed = urlparse(endpoint)
    parts = [part for part in parsed.path.split("/") if part]

    if bucket_name in parts:
        bucket_index = parts.index(bucket_name)
        bucket_path = "/" + "/".join(parts[: bucket_index + 1])
    else:
        bucket_path = parsed.path.rstrip("/")

    return parsed._replace(
        path=bucket_path,
        params="",
        query="",
        fragment="",
    ).geturl()


def check_endpoint(
    endpoint: str,
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Perform a basic local HTTP accessibility check."""

    if not is_allowed_endpoint(endpoint):
        return {
            "endpoint": endpoint,
            "accessible": False,
            "status_code": None,
            "error": "Blocked non-local endpoint",
        }

    request = Request(
        endpoint,
        method="GET",
        headers={
            "User-Agent": "LocalResearchChecker/1.0",
        },
    )

    try:
        with urlopen(request, timeout=timeout) as response:
            status_code = response.status

            return {
                "endpoint": endpoint,
                "accessible": 200 <= status_code < 400,
                "status_code": status_code,
                "content_type": response.headers.get(
                    "Content-Type",
                    "",
                ),
                "error": None,
            }

    except HTTPError as error:
        return {
            "endpoint": endpoint,
            "accessible": False,
            "status_code": error.code,
            "content_type": error.headers.get(
                "Content-Type",
                "",
            )
            if error.headers
            else "",
            "error": str(error),
        }

    except (URLError, TimeoutError, ValueError) as error:
        return {
            "endpoint": endpoint,
            "accessible": False,
            "status_code": None,
            "content_type": "",
            "error": str(error),
        }


def load_results(results_path: Path) -> dict[str, Any]:
    """Load and validate the scraper results file."""

    if not results_path.exists():
        raise FileNotFoundError(
            f"Results file does not exist: {results_path}"
        )

    data = json.loads(
        results_path.read_text(encoding="utf-8")
    )

    if "scraper" not in data:
        raise ValueError(
            "Invalid results file: missing scraper section"
        )

    discovered = data["scraper"].get(
        "discovered_buckets",
        [],
    )

    if not isinstance(discovered, list):
        raise ValueError(
            "Invalid results file: discovered_buckets must be a list"
        )

    return data


def run_checker(
    data: dict[str, Any],
    timeout: float = 5.0,
) -> dict[str, Any]:
    """Check every unique local endpoint from scraper findings."""

    checked_buckets: list[dict[str, Any]] = []

    discovered_buckets = data["scraper"].get(
        "discovered_buckets",
        [],
    )

    for bucket in discovered_buckets:
        bucket_name = bucket.get("bucket_name", "")
        raw_endpoints = bucket.get("endpoints", [])

        if not isinstance(raw_endpoints, list):
            raw_endpoints = []

        normalised_endpoints = {
            normalise_bucket_endpoint(
                endpoint=endpoint,
                bucket_name=bucket_name,
            )
            for endpoint in raw_endpoints
            if isinstance(endpoint, str)
            and endpoint
            and is_allowed_endpoint(endpoint)
        }

        checks = [
            check_endpoint(
                endpoint=endpoint,
                timeout=timeout,
            )
            for endpoint in sorted(normalised_endpoints)
        ]

        checked_buckets.append(
            {
                "bucket_name": bucket_name,
                "checks": checks,
                "anonymous_access_detected": any(
                    check["accessible"]
                    for check in checks
                ),
            }
        )

    data["checker"] = {
        "buckets": checked_buckets,
    }

    return data


def write_results(
    data: dict[str, Any],
    output_path: Path,
) -> None:
    """Write checker results to JSON."""

    output_path.write_text(
        json.dumps(data, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Check local endpoints found by the scraper."
        )
    )

    parser.add_argument(
        "--input",
        default="results.json",
        help="Path to the scraper results JSON file.",
    )

    parser.add_argument(
        "--output",
        default="results.json",
        help="Path to save the updated checker results.",
    )

    parser.add_argument(
        "--timeout",
        type=float,
        default=5.0,
        help="Request timeout in seconds.",
    )

    args = parser.parse_args()

    input_path = Path(args.input)
    output_path = Path(args.output)

    data = load_results(input_path)

    updated_data = run_checker(
        data=data,
        timeout=args.timeout,
    )

    write_results(
        data=updated_data,
        output_path=output_path,
    )

    bucket_count = len(
        updated_data["checker"]["buckets"]
    )

    accessible_count = sum(
        1
        for bucket in updated_data["checker"]["buckets"]
        if bucket["anonymous_access_detected"]
    )

    print(f"Buckets checked: {bucket_count}")
    print(f"Accessible buckets: {accessible_count}")
    print(f"Results saved to: {output_path}")


if __name__ == "__main__":
    main()
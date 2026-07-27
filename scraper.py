from __future__ import annotations

import argparse
import json
import re
from collections import deque
from dataclasses import dataclass
from html.parser import HTMLParser
from pathlib import Path
from typing import Iterable
from urllib.error import HTTPError, URLError
from urllib.parse import urljoin, urlparse
from urllib.request import Request, urlopen
import json
from pathlib import Path
from typing import Iterable

ALLOWED_HOSTS = {"localhost", "127.0.0.1"}

URL_PATTERN = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?/"
    r"[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+",
    re.IGNORECASE,
)

LOCAL_ENDPOINT_PATTERN = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?/"
    r"([a-z0-9][a-z0-9.-]{1,62})"
    r"(?:/[^\s\"'<>]*)?",
    re.IGNORECASE,
)

BUCKET_ASSIGNMENT_PATTERN = re.compile(
    r"""
    (?:bucketName|bucket_name|bucket)
    \s*[:=]\s*
    ["']([a-z0-9][a-z0-9.-]{1,62})["']
    """,
    re.IGNORECASE | re.VERBOSE,
)

S3_STYLE_PATTERN = re.compile(
    r"https?://([a-z0-9][a-z0-9.-]{1,62})"
    r"\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BucketFinding:
    bucket_name: str
    endpoint: str
    source_url: str


class LinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.links: set[str] = set()

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        for attribute, value in attrs:
            if attribute.lower() in {"href", "src", "action"} and value:
                self.links.add(value)


def is_allowed_url(url: str) -> bool:
    parsed = urlparse(url)

    return (
        parsed.scheme in {"http", "https"}
        and parsed.hostname in ALLOWED_HOSTS
    )


def fetch_page(url: str, timeout: float = 5.0) -> str:
    if not is_allowed_url(url):
        raise ValueError(f"Blocked non-local URL: {url}")

    request = Request(
        url,
        headers={
            "User-Agent": "LocalResearchCrawler/1.0",
        },
    )

    with urlopen(request, timeout=timeout) as response:
        content_type = response.headers.get("Content-Type", "")

        if (
            "text/html" not in content_type
            and "text/plain" not in content_type
        ):
            return ""

        charset = response.headers.get_content_charset() or "utf-8"

        return response.read().decode(
            charset,
            errors="replace",
        )


def extract_links(html: str, base_url: str) -> set[str]:
    parser = LinkParser()
    parser.feed(html)

    links: set[str] = set()

    for raw_link in parser.links:
        absolute_url = urljoin(base_url, raw_link)
        absolute_url = absolute_url.split("#", maxsplit=1)[0]

        if is_allowed_url(absolute_url):
            links.add(absolute_url)

    return links


def extract_bucket_findings(
    html: str,
    source_url: str,
) -> set[BucketFinding]:
    """Extract probable bucket names and endpoints from HTML."""

    findings: set[BucketFinding] = set()
    endpoint_by_bucket: dict[str, str] = {}

    possible_urls = {
        endpoint.rstrip("'\"),.;]}")
        for endpoint in URL_PATTERN.findall(html)
    }

    for endpoint in possible_urls:
        match = LOCAL_ENDPOINT_PATTERN.match(endpoint)

        if not match:
            continue

        bucket_name = match.group(1)
        endpoint_by_bucket.setdefault(bucket_name, endpoint)

        findings.add(
            BucketFinding(
                bucket_name=bucket_name,
                endpoint=endpoint,
                source_url=source_url,
            )
        )

    for match in LOCAL_ENDPOINT_PATTERN.finditer(html):
        bucket_name = match.group(1)
        endpoint = match.group(0).rstrip("'\"),.;]}")

        endpoint_by_bucket.setdefault(bucket_name, endpoint)

        findings.add(
            BucketFinding(
                bucket_name=bucket_name,
                endpoint=endpoint,
                source_url=source_url,
            )
        )

    for match in BUCKET_ASSIGNMENT_PATTERN.finditer(html):
        bucket_name = match.group(1)

        matching_endpoint = endpoint_by_bucket.get(bucket_name)

        if not matching_endpoint:
            matching_endpoint = next(
                (
                    endpoint
                    for endpoint in possible_urls
                    if bucket_name.lower() in endpoint.lower()
                ),
                "",
            )

        findings.add(
            BucketFinding(
                bucket_name=bucket_name,
                endpoint=matching_endpoint,
                source_url=source_url,
            )
        )

    for match in S3_STYLE_PATTERN.finditer(html):
        findings.add(
            BucketFinding(
                bucket_name=match.group(1),
                endpoint=match.group(0),
                source_url=source_url,
            )
        )

    return findings


def crawl(
    start_url: str,
    max_depth: int = 3,
) -> tuple[set[str], set[BucketFinding]]:
    """Crawl local pages and collect probable bucket references."""

    if not is_allowed_url(start_url):
        raise ValueError(
            "Only localhost or 127.0.0.1 targets are allowed."
        )

    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    visited: set[str] = set()
    findings: set[BucketFinding] = set()

    while queue:
        current_url, depth = queue.popleft()

        if current_url in visited or depth > max_depth:
            continue

        visited.add(current_url)
        print(f"[depth={depth}] Visiting: {current_url}")

        try:
            html = fetch_page(current_url)
        except (
            HTTPError,
            URLError,
            TimeoutError,
            ValueError,
            OSError,
        ) as error:
            print(f"[warning] Failed to fetch {current_url}: {error}")
            continue

        findings.update(
            extract_bucket_findings(
                html=html,
                source_url=current_url,
            )
        )

        if depth >= max_depth:
            continue

        for link in sorted(extract_links(html, current_url)):
            if link not in visited:
                queue.append((link, depth + 1))

    return visited, findings


def write_results(
    findings: Iterable[BucketFinding],
    depth: int,
    output_path: Path,
) -> None:
    """Write findings while merging duplicate bucket names."""

    bucket_map: dict[str, dict[str, set[str]]] = {}

    for finding in findings:
        if finding.bucket_name not in bucket_map:
            bucket_map[finding.bucket_name] = {
                "endpoints": set(),
                "source_urls": set(),
            }

        if finding.endpoint:
            bucket_map[finding.bucket_name]["endpoints"].add(
                finding.endpoint
            )

        if finding.source_url:
            bucket_map[finding.bucket_name]["source_urls"].add(
                finding.source_url
            )

    discovered_buckets = []

    for bucket_name in sorted(bucket_map):
        discovered_buckets.append(
            {
                "bucket_name": bucket_name,
                "endpoints": sorted(
                    bucket_map[bucket_name]["endpoints"]
                ),
                "source_urls": sorted(
                    bucket_map[bucket_name]["source_urls"]
                ),
            }
        )

    output = {
        "scraper": {
            "depth": depth,
            "discovered_buckets": discovered_buckets,
        },
        "checker": {
            "buckets": [],
        },
    }

    output_path.write_text(
        json.dumps(output, indent=2),
        encoding="utf-8",
    )


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Depth-limited crawler for the provided local application."
    )

    parser.add_argument(
        "--url",
        default="http://localhost:8000/home",
        help="Local URL from which crawling starts.",
    )

    parser.add_argument(
        "--depth",
        type=int,
        default=3,
        choices=range(0, 4),
        metavar="{0,1,2,3}",
        help="Maximum crawling depth.",
    )

    parser.add_argument(
        "--output",
        default="results.json",
        help="Output JSON path.",
    )

    args = parser.parse_args()

    visited, findings = crawl(
        start_url=args.url,
        max_depth=args.depth,
    )

    write_results(
        findings=findings,
        depth=args.depth,
        output_path=Path(args.output),
    )

    print(f"Total pages visited: {len(visited)}")
    print(f"Bucket findings: {len(findings)}")
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
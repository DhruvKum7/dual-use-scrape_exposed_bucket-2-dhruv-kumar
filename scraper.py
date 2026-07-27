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


ALLOWED_HOSTS = {"localhost", "127.0.0.1"}

URL_PATTERN = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?/[A-Za-z0-9._~:/?#\[\]@!$&'()*+,;=%-]+"
)

BUCKET_ASSIGNMENT_PATTERN = re.compile(
    r"""(?:bucket(?:Name)?|bucket_name)\s*[:=]\s*["']([a-z0-9][a-z0-9.-]{1,62})["']""",
    re.IGNORECASE,
)

S3_STYLE_PATTERN = re.compile(
    r"https?://([a-z0-9][a-z0-9.-]{1,62})\.s3(?:[.-][a-z0-9-]+)?\.amazonaws\.com",
    re.IGNORECASE,
)

LOCAL_ENDPOINT_PATTERN = re.compile(
    r"https?://(?:localhost|127\.0\.0\.1)(?::\d+)?/([a-z0-9][a-z0-9.-]{1,62})",
    re.IGNORECASE,
)


@dataclass(frozen=True)
class BucketFinding:
    bucket_name: str
    endpoint: str


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

        if "text/html" not in content_type and "text/plain" not in content_type:
            return ""

        charset = response.headers.get_content_charset() or "utf-8"
        return response.read().decode(charset, errors="replace")


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
    findings: set[BucketFinding] = set()

    possible_urls = set(URL_PATTERN.findall(html))

    for endpoint in possible_urls:
        endpoint = endpoint.rstrip('\'");,]}')

        match = LOCAL_ENDPOINT_PATTERN.match(endpoint)
        if match:
            findings.add(
                BucketFinding(
                    bucket_name=match.group(1),
                    endpoint=endpoint,
                )
            )

    for match in LOCAL_ENDPOINT_PATTERN.finditer(html):
        endpoint_match = URL_PATTERN.search(
            html,
            pos=max(0, match.start() - 100),
        )

        endpoint = (
            endpoint_match.group(0).rstrip('\'");,]}')
            if endpoint_match
            else source_url
        )

        findings.add(
            BucketFinding(
                bucket_name=match.group(1),
                endpoint=endpoint,
            )
        )

    for match in BUCKET_ASSIGNMENT_PATTERN.finditer(html):
        bucket_name = match.group(1)

        matching_endpoint = next(
            (
                endpoint
                for endpoint in possible_urls
                if bucket_name in endpoint
            ),
            source_url,
        )

        findings.add(
            BucketFinding(
                bucket_name=bucket_name,
                endpoint=matching_endpoint.rstrip('\'");,]}'),
            )
        )

    for match in S3_STYLE_PATTERN.finditer(html):
        findings.add(
            BucketFinding(
                bucket_name=match.group(1),
                endpoint=match.group(0),
            )
        )

    return findings


def crawl(
    start_url: str,
    max_depth: int = 3,
) -> tuple[set[str], set[BucketFinding]]:
    if not is_allowed_url(start_url):
        raise ValueError(
            "The crawler only accepts localhost or 127.0.0.1 targets."
        )

    queue: deque[tuple[str, int]] = deque([(start_url, 0)])
    visited: set[str] = set()
    findings: set[BucketFinding] = set()

    while queue:
        current_url, depth = queue.popleft()

        if current_url in visited or depth > max_depth:
            continue

        visited.add(current_url)

        try:
            html = fetch_page(current_url)
        except (HTTPError, URLError, TimeoutError, ValueError) as error:
            print(f"[warning] Could not fetch {current_url}: {error}")
            continue

        findings.update(
            extract_bucket_findings(
                html=html,
                source_url=current_url,
            )
        )

        if depth == max_depth:
            continue

        for link in extract_links(html, current_url):
            if link not in visited:
                queue.append((link, depth + 1))

    return visited, findings


def write_results(
    findings: Iterable[BucketFinding],
    depth: int,
    output_path: Path,
) -> None:
    discovered_buckets = [
        {
            "bucket_name": finding.bucket_name,
            "endpoint": finding.endpoint,
        }
        for finding in sorted(
            findings,
            key=lambda item: (item.bucket_name, item.endpoint),
        )
    ]

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

    print(f"Pages visited: {len(visited)}")
    print(f"Bucket findings: {len(findings)}")
    print(f"Results saved to: {args.output}")


if __name__ == "__main__":
    main()
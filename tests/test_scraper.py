from pathlib import Path

import pytest

from scraper import (
    BucketFinding,
    extract_bucket_findings,
    extract_links,
    is_allowed_url,
    write_results,
)


def test_localhost_url_is_allowed() -> None:
    assert is_allowed_url("http://localhost:8000/index.html")
    assert is_allowed_url("http://127.0.0.1:8000/index.html")


def test_external_url_is_blocked() -> None:
    assert not is_allowed_url("https://example.com")
    assert not is_allowed_url("https://google.com")
    assert not is_allowed_url("ftp://localhost/file.txt")


def test_extract_links_converts_relative_links() -> None:
    html = """
    <html>
        <body>
            <a href="/gallery.html">Gallery</a>
            <a href="config.html">Config</a>
            <a href="https://example.com">External</a>
        </body>
    </html>
    """

    links = extract_links(
        html=html,
        base_url="http://localhost:8000/index.html",
    )

    assert "http://localhost:8000/gallery.html" in links
    assert "http://localhost:8000/config.html" in links
    assert "https://example.com" not in links


def test_extract_bucket_assignment() -> None:
    html = """
    <script>
        const bucketName = "creative-studio-assets";
        const bucketEndpoint =
            "http://localhost:4566/creative-studio-assets";
    </script>
    """

    findings = extract_bucket_findings(
        html=html,
        source_url="http://localhost:8000/config.html",
    )

    bucket_names = {
        finding.bucket_name
        for finding in findings
    }

    assert "creative-studio-assets" in bucket_names


def test_extract_local_endpoint() -> None:
    html = """
    <img
        src="http://127.0.0.1:4566/creative-studio-assets/image.jpg"
        alt="Sample image"
    >
    """

    findings = extract_bucket_findings(
        html=html,
        source_url="http://localhost:8000/gallery.html",
    )

    assert any(
        finding.bucket_name == "creative-studio-assets"
        for finding in findings
    )

    assert any(
        finding.endpoint.startswith(
            "http://127.0.0.1:4566/creative-studio-assets"
        )
        for finding in findings
    )


def test_write_results_deduplicates_bucket_names(
    tmp_path: Path,
) -> None:
    findings = {
        BucketFinding(
            bucket_name="creative-studio-assets",
            endpoint=(
                "http://localhost:4566/"
                "creative-studio-assets"
            ),
            source_url="http://localhost:8000/config.html",
        ),
        BucketFinding(
            bucket_name="creative-studio-assets",
            endpoint=(
                "http://127.0.0.1:4566/"
                "creative-studio-assets/image.jpg"
            ),
            source_url="http://localhost:8000/gallery.html",
        ),
    }

    output_file = tmp_path / "results.json"

    write_results(
        findings=findings,
        depth=3,
        output_path=output_file,
    )

    assert output_file.exists()

    content = output_file.read_text(encoding="utf-8")

    assert '"depth": 3' in content
    assert content.count('"bucket_name": "creative-studio-assets"') == 1
    assert '"checker"' in content


@pytest.mark.parametrize(
    "url",
    [
        "",
        "localhost:8000",
        "file:///index.html",
        "javascript:alert(1)",
    ],
)
def test_invalid_urls_are_blocked(url: str) -> None:
    assert not is_allowed_url(url)
# Scrape Exposed Bucket — Local Research Task

## Scope

This project is implemented exclusively against the locally provided Docker
application running on `localhost`. It must not be used against third-party or
live systems.

## Objective

- Crawl the provided local application up to depth 3.
- Identify possible storage bucket names and endpoints.
- Check the discovered local challenge resources for anonymous list/read access.
- Generate `results.json` and `summary.json`.

## Environment

- Python 3.10+
- Docker Desktop
- Local challenge application
- Target URL: `http://localhost:8000/home`

## Time Tracking

- Start time: To be taken from the initial Git commit timestamp
- End time: To be taken from the final Git push timestamp

## Status

Project initialized.
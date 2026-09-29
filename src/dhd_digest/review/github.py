"""Just enough of the GitHub REST API for the daily review issue. Runs inside
Actions, which provides GITHUB_TOKEN and GITHUB_REPOSITORY."""
import os

import httpx

API = "https://api.github.com"
LABEL = "daily-review"


def _client() -> httpx.Client:
    return httpx.Client(base_url=f"{API}/repos/{os.environ['GITHUB_REPOSITORY']}", timeout=30.0,
                        headers={"Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
                                 "Accept": "application/vnd.github+json"})


def open_issue(title: str, body: str) -> int:
    with _client() as c:
        c.post("/labels", json={"name": LABEL, "color": "5319e7",
                                "description": "Daily curation review"})   # 422 if it exists: fine
        r = c.post("/issues", json={"title": title, "body": body, "labels": [LABEL]})
        r.raise_for_status()
        return r.json()["number"]


def issue_body(number: int) -> str:
    with _client() as c:
        r = c.get(f"/issues/{number}")
        r.raise_for_status()
        return r.json()["body"] or ""


def comment(number: int, body: str):
    with _client() as c:
        c.post(f"/issues/{number}/comments", json={"body": body}).raise_for_status()

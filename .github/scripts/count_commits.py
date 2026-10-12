#!/usr/bin/env python3
"""Count every commit authored by LOGIN and write the badges into README.md.

Counts commits on the default branch of each repository, asking the API for a
single commit per repo and reading the page count out of the Link header, so
one request is enough however long the history is.

The token decides what is visible. A personal access token with the `repo`
scope sees private repositories; the GITHUB_TOKEN that Actions provides by
default sees only this one, so the count then covers public repos alone.
"""

import json
import os
import re
import sys
import urllib.error
import urllib.request
from datetime import datetime, timezone

API = "https://api.github.com"
LOGIN = os.environ.get("LOGIN", "amirh3sam")
TOKEN = os.environ.get("GH_TOKEN", "").strip()
README = os.environ.get("README_PATH", "README.md")

START = "<!--COMMIT-COUNT:START-->"
END = "<!--COMMIT-COUNT:END-->"


def get(url):
    """GET a URL, returning (parsed body, headers). (None, {}) on 404/409."""
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{LOGIN}-commit-counter")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        # 409 is an empty repository, 404 a repo this token cannot see
        if e.code in (404, 409):
            return None, {}
        raise


def list_repos():
    """Every repo the token can see for LOGIN, private included when allowed."""
    repos, page = [], 1
    endpoint = "user/repos?affiliation=owner" if TOKEN else f"users/{LOGIN}/repos?"
    while True:
        body, _ = get(f"{API}/{endpoint}&per_page=100&page={page}")
        if not body:
            break
        repos.extend(body)
        if len(body) < 100:
            break
        page += 1
    # a token without visibility into the account still returns this repo only
    if not repos:
        body, _ = get(f"{API}/users/{LOGIN}/repos?per_page=100")
        repos = body or []
    return repos


def commits_in(full_name):
    """Commits authored by LOGIN on this repo's default branch."""
    url = f"{API}/repos/{full_name}/commits?author={LOGIN}&per_page=1"
    body, headers = get(url)
    if body is None:
        return 0
    link = headers.get("Link", "")
    m = re.search(r'[?&]page=(\d+)>;\s*rel="last"', link)
    if m:
        return int(m.group(1))
    # no Link header means a single page: 0 or 1 commits
    return len(body)


def badge(label, value, logo, color):
    """A shields.io badge matching the neon style of this profile."""
    esc = lambda s: str(s).replace("-", "--").replace("_", "__").replace(" ", "_")
    return (
        f'<img alt="{label}" src="https://img.shields.io/badge/'
        f'{esc(label)}-{esc(value)}-000000'
        f'?style=for-the-badge&logo={logo}&logoColor={color}" />'
    )


def main():
    repos = list_repos()
    if not repos:
        print("No repositories visible to this token.", file=sys.stderr)
        return 1

    total = public = private = 0
    for r in repos:
        n = commits_in(r["full_name"])
        total += n
        if r.get("private"):
            private += n
        else:
            public += n

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    block = "\n".join([
        START,
        badge("TOTAL COMMITS", total, "git", "00F7FF"),
        badge("REPOSITORIES", len(repos), "github", "FF00FF"),
        badge("LAST SYNC", today, "githubactions", "00FF41"),
        END,
    ])

    text = open(README, encoding="utf-8").read()
    if START not in text or END not in text:
        print(f"Markers {START} / {END} not found in {README}.", file=sys.stderr)
        return 1

    updated = re.sub(
        re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S
    )
    open(README, "w", encoding="utf-8", newline="\n").write(updated)

    print(f"repos={len(repos)} total={total} public={public} private={private}")
    print("changed" if updated != text else "unchanged")
    return 0


if __name__ == "__main__":
    sys.exit(main())

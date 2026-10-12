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
DASHBOARD = os.environ.get("DASHBOARD_PATH", "assets/ops-dashboard.svg")

START = "<!--COMMIT-COUNT:START-->"
END = "<!--COMMIT-COUNT:END-->"


class RateLimited(Exception):
    """The API refused us for quota reasons, not for permissions."""


def get(url, tolerate=(404, 409)):
    """GET a URL, returning (parsed body, headers). (None, {}) on a tolerated code.

    404 is a repo this token cannot see, 409 an empty one, and 403 is what the
    Actions GITHUB_TOKEN returns for user-level endpoints such as /user/repos,
    since it is scoped to a single repository rather than to an account.
    """
    req = urllib.request.Request(url)
    req.add_header("Accept", "application/vnd.github+json")
    req.add_header("User-Agent", f"{LOGIN}-commit-counter")
    if TOKEN:
        req.add_header("Authorization", f"Bearer {TOKEN}")
    try:
        with urllib.request.urlopen(req, timeout=30) as r:
            return json.loads(r.read().decode()), dict(r.headers)
    except urllib.error.HTTPError as e:
        # a 403 with no quota left is rate limiting, not a permissions problem
        if e.code in (403, 429) and e.headers.get("x-ratelimit-remaining") == "0":
            raise RateLimited(
                f"API quota exhausted (resets at "
                f"{e.headers.get('x-ratelimit-reset', 'unknown')})."
            ) from None
        if e.code in tolerate:
            return None, {}
        raise


def paginate(endpoint, tolerate=(404, 409)):
    """Collect every page of a list endpoint."""
    out, page = [], 1
    sep = "&" if "?" in endpoint else "?"
    while True:
        body, _ = get(f"{API}/{endpoint}{sep}per_page=100&page={page}", tolerate)
        if not body:
            break
        out.extend(body)
        if len(body) < 100:
            break
        page += 1
    return out


def diagnose_token():
    """Say plainly what this token can see, so a bad secret is obvious in the log."""
    if not TOKEN:
        print("No token supplied. Counting public repositories only.")
        return
    try:
        req = urllib.request.Request(f"{API}/user")
        req.add_header("Authorization", f"Bearer {TOKEN}")
        req.add_header("Accept", "application/vnd.github+json")
        req.add_header("User-Agent", f"{LOGIN}-commit-counter")
        with urllib.request.urlopen(req, timeout=30) as r:
            scopes = r.headers.get("x-oauth-scopes", "")
            who = json.loads(r.read().decode()).get("login", "?")
        if scopes.strip():
            print(f"Token acts as '{who}' with scopes: {scopes}")
            if "repo" not in [s.strip() for s in scopes.split(",")]:
                print("WARNING: this token has no `repo` scope, so private "
                      "repositories stay invisible. Regenerate it with `repo` "
                      "ticked.", file=sys.stderr)
        else:
            print(f"Token acts as '{who}' (fine-grained or no scopes listed).")
    except urllib.error.HTTPError as e:
        # the Actions GITHUB_TOKEN cannot call /user at all
        print(f"Token cannot read account-level data (HTTP {e.code}). "
              f"This is expected for the built-in GITHUB_TOKEN; add a "
              f"COMMIT_COUNT_TOKEN secret to include private repositories.")


def list_repos():
    """Repos visible for LOGIN, plus whether private ones were included.

    Tries the account-wide endpoint first, which needs a token with the `repo`
    scope, and falls back to the public listing when that is refused. Returns
    (repos, saw_private) so the badge can say which it actually counted.
    """
    if TOKEN:
        repos = paginate("user/repos?affiliation=owner", tolerate=(403, 404, 409))
        if repos:
            n_priv = sum(1 for r in repos if r.get("private"))
            print(f"Account-wide listing OK: {len(repos)} repos, {n_priv} private.")
            return repos, n_priv > 0
        print("Account-wide listing unavailable; counting public repos only.")
    return paginate(f"users/{LOGIN}/repos"), False


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
    diagnose_token()
    repos, saw_private = list_repos()
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

    # Only claim a grand total when private repos were actually in scope,
    # so the badge never overstates what it counted.
    label = "TOTAL COMMITS" if saw_private else "PUBLIC COMMITS"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    rows = [START, badge(label, f"{total:,}", "git", "00F7FF")]
    if saw_private:
        rows.append(badge("PUBLIC", f"{public:,}", "unlock", "00FF41"))
        rows.append(badge("PRIVATE", f"{private:,}", "lock", "FF00FF"))
    rows.append(badge("REPOS", len(repos), "github", "FF00FF"))
    rows.append(badge("LAST SYNC", today, "githubactions", "00FF41"))
    rows.append(END)
    block = "\n".join(rows)

    text = open(README, encoding="utf-8").read()
    if START not in text or END not in text:
        print(f"Markers {START} / {END} not found in {README}.", file=sys.stderr)
        return 1

    updated = re.sub(
        re.escape(START) + r".*?" + re.escape(END), lambda _: block, text, flags=re.S
    )
    open(README, "w", encoding="utf-8", newline="\n").write(updated)

    svg_changed = update_dashboard(total, public, private, saw_private,
                                   len(repos), label, today)

    print(f"repos={len(repos)} total={total} public={public} private={private}")
    print("changed" if (updated != text or svg_changed) else "unchanged")
    return 0


def update_dashboard(total, public, private, saw_private, repo_count, label, today):
    """Rewrite the counter panel in the OPS CENTER dashboard SVG."""
    if not os.path.exists(DASHBOARD):
        return False

    svg = open(DASHBOARD, encoding="utf-8").read()
    before = svg

    split = (f"{public:,} PUBLIC · {private:,} PRIVATE" if saw_private
             else "PUBLIC REPOS ONLY")
    fields = {
        "oc-count": f"{total:,}",
        "oc-label": label,
        "oc-sub": split,
        "oc-meta": f"{repo_count} REPOS · SYNCED {today}",
    }
    for el_id, value in fields.items():
        # replace only the text content of the element carrying this id
        pattern = rf'(<text id="{el_id}"[^>]*>)(.*?)(</text>)'
        if not re.search(pattern, svg, flags=re.S):
            print(f"Warning: #{el_id} not found in {DASHBOARD}.", file=sys.stderr)
            continue
        svg = re.sub(pattern, lambda m: m.group(1) + esc_xml(value) + m.group(3),
                     svg, flags=re.S)

    if svg != before:
        open(DASHBOARD, "w", encoding="utf-8", newline="\n").write(svg)
        return True
    return False


def esc_xml(s):
    return str(s).replace("&", "&amp;").replace("<", "&lt;").replace(">", "&gt;")


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RateLimited as e:
        # bail out before writing anything, so a half-finished count never
        # lands on the profile as if it were real
        print(f"{e} Leaving the current numbers in place.", file=sys.stderr)
        sys.exit(1)

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

import dashboard

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
            raw = r.read().decode().strip()
            # an empty repo answers some endpoints with 204 No Content, and
            # json.loads("") raises rather than returning nothing useful
            if not raw:
                return None, dict(r.headers)
            return json.loads(raw), dict(r.headers)
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
    bots = automation_commits(repos)

    rows = [START, badge(label, f"{total:,}", "git", "00F7FF")]
    if saw_private:
        rows.append(badge("PUBLIC", f"{public:,}", "unlock", "00FF41"))
        rows.append(badge("PRIVATE", f"{private:,}", "lock", "FF00FF"))
    if bots:
        rows.append(badge("AUTOMATION", f"{bots:,}", "githubactions", "FFF200"))
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

    weeks, months = contribution_history()
    svg_changed = update_dashboard({
        "login": LOGIN,
        "total": total, "public": public, "private": private,
        "saw_private": saw_private, "repo_count": len(repos),
        "label": label, "today": today, "bots": bots,
        "languages": language_mix(repos),
        "months": months,
        "weeks": weeks,
        "recent": recent_commits(),
    })

    print(f"repos={len(repos)} total={total} public={public} private={private} bots={bots}")
    print("changed" if (updated != text or svg_changed) else "unchanged")
    return 0


def update_dashboard(data):
    """Regenerate the whole OPS CENTER dashboard from live data."""
    svg = dashboard.render(data)
    before = open(DASHBOARD, encoding="utf-8").read() if os.path.exists(DASHBOARD) else ""
    if svg != before:
        open(DASHBOARD, "w", encoding="utf-8", newline="\n").write(svg)
        return True
    return False


# --------------------------------------------------------------------------
# extra panels: each returns a falsy value on failure so one dead source
# degrades its own panel instead of taking the whole run down


def graphql(query):
    body = json.dumps({"query": query}).encode()
    req = urllib.request.Request("https://api.github.com/graphql", data=body)
    req.add_header("Authorization", f"Bearer {TOKEN}")
    req.add_header("User-Agent", f"{LOGIN}-commit-counter")
    req.add_header("Content-Type", "application/json")
    with urllib.request.urlopen(req, timeout=30) as r:
        return json.loads(r.read().decode())


def contribution_history():
    """Weekly totals and monthly commit counts for the last year.

    Queried as `viewer`, which folds in private contributions, so the charts
    match the counter rather than showing only the public half.
    """
    if not TOKEN:
        return [], []
    try:
        d = graphql("""{ viewer { contributionsCollection { contributionCalendar {
              weeks { contributionDays { date contributionCount } } } } } }""")
        weeks_raw = (d["data"]["viewer"]["contributionsCollection"]
                      ["contributionCalendar"]["weeks"])
    except Exception as e:
        print(f"Contribution history unavailable: {e}", file=sys.stderr)
        return [], []

    # keep the daily shape: the heatmap needs one cell per day, padded to a
    # full week so partial weeks at either end still line up
    weeks = []
    for w in weeks_raw:
        days = [d["contributionCount"] for d in w["contributionDays"]]
        weeks.append(days + [0] * (7 - len(days)) if len(days) < 7 else days)

    by_month, order = {}, []
    for w in weeks_raw:
        for day in w["contributionDays"]:
            key = day["date"][:7]
            if key not in by_month:
                by_month[key] = 0
                order.append(key)
            by_month[key] += day["contributionCount"]
    names = ["J", "F", "M", "A", "M", "J", "J", "A", "S", "O", "N", "D"]
    months = [(names[int(k[5:7]) - 1], by_month[k]) for k in order][-12:]
    return weeks, months


def automation_commits(repos):
    """Commits made by bots in your own repos, counted separately from yours.

    The commits API cannot filter by a bot author -- `?author=github-actions[bot]`
    returns nothing -- so this reads the contributors endpoint instead, which
    gives an exact per-author count in one request per repo.

    Forks are skipped: their history belongs to the upstream project, not here.
    """
    total = 0
    for r in repos:
        if r.get("fork"):
            continue
        for c in paginate(f"repos/{r['full_name']}/contributors?anon=1"):
            if isinstance(c, dict) and c.get("type") == "Bot":
                total += c.get("contributions", 0)
    return total


def language_mix(repos):
    """Bytes per language across every visible repo."""
    totals = {}
    for r in repos:
        body, _ = get(f"{API}/repos/{r['full_name']}/languages")
        if body:
            for lang, n in body.items():
                totals[lang] = totals.get(lang, 0) + n
    return sorted(totals.items(), key=lambda kv: -kv[1])


def parse_ts(s):
    """Parse a git timestamp. The API mixes 'Z' with real offsets like -04:00."""
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def recent_commits():
    """The newest commits authored by LOGIN, newest first."""
    url = (f"{API}/search/commits?q=author:{LOGIN}"
           f"&sort=author-date&order=desc&per_page=10")
    try:
        body, _ = get(url, tolerate=(403, 404, 422))
    except Exception as e:
        print(f"Recent commits unavailable: {e}", file=sys.stderr)
        return []
    if not body or "items" not in body:
        return []

    now = datetime.now(timezone.utc)
    out = []
    for it in body["items"]:
        when = parse_ts(it["commit"]["author"]["date"])
        if when is None:
            continue
        mins = (now - when).total_seconds() / 60
        ago = (f"{int(mins)}m" if mins < 60 else
               f"{int(mins/60)}h" if mins < 1440 else f"{int(mins/1440)}d")
        out.append((it["repository"]["name"],
                    it["commit"]["message"].split("\n")[0], ago))
    return out


if __name__ == "__main__":
    try:
        sys.exit(main())
    except RateLimited as e:
        # bail out before writing anything, so a half-finished count never
        # lands on the profile as if it were real
        print(f"{e} Leaving the current numbers in place.", file=sys.stderr)
        sys.exit(1)

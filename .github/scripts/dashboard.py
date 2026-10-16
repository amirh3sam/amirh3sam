#!/usr/bin/env python3
"""Render the OPS CENTER dashboard from real account data.

Every panel is drawn from numbers fetched at run time. Nothing here is
decorative stand-in data: if a source cannot be reached the panel says so
rather than showing a plausible-looking figure.
"""

W, H = 1000, 420
MONO = "Courier New, monospace"

CYAN = "#00f7ff"
MAGENTA = "#ff00ff"
GREEN = "#00ff41"
YELLOW = "#fff200"
RED = "#ff2d55"
DIM = "#6b7a8f"


def esc(s):
    return (str(s).replace("&", "&amp;").replace("<", "&lt;")
            .replace(">", "&gt;").replace('"', "&quot;"))


def clip(s, n):
    s = str(s)
    return s if len(s) <= n else s[: n - 1] + "…"


def text(x, y, s, size=10, fill=CYAN, anchor="start", weight="normal",
         opacity=1.0, spacing=None, el_id=None, glow=False):
    a = [f'x="{x}"', f'y="{y}"', f'font-family="{MONO}"', f'font-size="{size}"']
    if weight != "normal":
        a.append(f'font-weight="{weight}"')
    a.append(f'fill="{fill}"')
    if anchor != "start":
        a.append(f'text-anchor="{anchor}"')
    if opacity != 1.0:
        a.append(f'fill-opacity="{opacity}"')
    if spacing:
        a.append(f'letter-spacing="{spacing}"')
    if el_id:
        a.append(f'id="{el_id}"')
    if glow:
        a.append('filter="url(#g)"')
    return f'<text {" ".join(a)}>{esc(s)}</text>'


def panel(x, y, w, h, title, colour):
    """A titled panel frame in the house style."""
    return (
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="#0a0f1f" '
        f'stroke="{colour}" stroke-opacity="0.7"/>'
        f'<rect x="{x}" y="{y}" width="{w}" height="{h}" rx="8" fill="url(#grid)"/>'
        + text(x + 14, y + 22, title, 12, colour, weight="bold")
    )


def unavailable(x, y, w, h, why):
    """Shown instead of a panel's content when its data could not be fetched."""
    return text(x + w / 2, y + h / 2 + 4, why, 10, DIM, anchor="middle")


# --------------------------------------------------------------------------
# panels


def p_languages(x, y, w, h, langs):
    out = [panel(x, y, w, h, "LANGUAGE MIX", MAGENTA)]
    if not langs:
        out.append(unavailable(x, y, w, h, "no language data"))
        return "".join(out)

    total = sum(n for _, n in langs) or 1
    top = langs[:5]
    bar_x, bar_w = x + 14, w - 28
    row_y = y + 48
    for name, n in top:
        pct = n / total * 100
        out.append(text(bar_x, row_y - 5, clip(name, 14), 10, "#cfe6f5"))
        out.append(text(bar_x + bar_w, row_y - 5, f"{pct:.0f}%", 10, MAGENTA,
                        anchor="end"))
        out.append(f'<rect x="{bar_x}" y="{row_y}" width="{bar_w}" height="6" '
                   f'rx="3" fill="#14203a"/>')
        out.append(f'<rect x="{bar_x}" y="{row_y}" width="{max(2, bar_w*n/total):.1f}" '
                   f'height="6" rx="3" fill="{MAGENTA}" filter="url(#g)"/>')
        row_y += 23
    return "".join(out)


def p_months(x, y, w, h, months):
    """months: list of (label, count), oldest first."""
    out = [panel(x, y, w, h, "COMMITS / MONTH", GREEN)]
    if not months:
        out.append(unavailable(x, y, w, h, "no activity data"))
        return "".join(out)

    peak = max(n for _, n in months) or 1
    base, top_y = y + h - 26, y + 42
    span = base - top_y
    slot = (w - 28) / len(months)
    bw = max(5, slot * 0.62)
    for i, (label, n) in enumerate(months):
        bh = max(2, span * n / peak)
        bx = x + 14 + i * slot + (slot - bw) / 2
        out.append(f'<rect x="{bx:.1f}" y="{base-bh:.1f}" width="{bw:.1f}" '
                   f'height="{bh:.1f}" rx="2" fill="{GREEN}" '
                   f'fill-opacity="{0.45 + 0.55*n/peak:.2f}" filter="url(#g)"/>')
        out.append(text(bx + bw / 2, base + 12, label, 8, DIM, anchor="middle"))
    out.append(text(x + w - 14, y + 22, f"PEAK {peak}", 9, GREEN,
                    anchor="end", opacity=0.75))
    return "".join(out)


def p_counter(x, y, w, h, total, public, private, saw_private, repos, today, label, bots=0):
    out = [panel(x, y, w, h, "COMMIT COUNTER", CYAN)]
    out.append(f'<circle cx="{x+w-18}" cy="{y+18}" r="4" fill="{GREEN}" '
               f'filter="url(#g)"><animate attributeName="opacity" '
               f'values="1;0.15;1" dur="2s" repeatCount="indefinite"/></circle>')
    out.append(f'<line x1="{x+14}" y1="{y+34}" x2="{x+w-14}" y2="{y+34}" '
               f'stroke="{CYAN}" stroke-opacity="0.18"/>')
    cx = x + w / 2
    out.append(text(cx, y + 92, f"{total:,}", 52, CYAN, anchor="middle",
                    weight="bold", el_id="oc-count", glow=True))
    out.append(text(cx, y + 115, label, 11, CYAN, anchor="middle", weight="bold",
                    spacing=3, opacity=0.8, el_id="oc-label"))
    split = (f"{public:,} PUBLIC · {private:,} PRIVATE" if saw_private
             else "PUBLIC REPOS ONLY")
    out.append(text(cx, y + 136, split, 10, GREEN, anchor="middle", spacing=1,
                    opacity=0.85, el_id="oc-sub"))
    meta = f"{repos} REPOS · {bots:,} AUTOMATED" if bots else f"{repos} REPOS"
    out.append(text(cx, y + 154, f"{meta} · {today}", 9,
                    MAGENTA, anchor="middle", spacing=1, opacity=0.7,
                    el_id="oc-meta"))
    return "".join(out)


def p_recent(x, y, w, h, commits):
    out = [panel(x, y, w, h, "RECENT COMMITS", YELLOW)]
    if not commits:
        out.append(unavailable(x, y, w, h, "no recent commits"))
        return "".join(out)

    row_y = y + 44
    for repo, msg, ago in commits[:6]:
        out.append(text(x + 14, row_y, clip(repo, 20), 10, YELLOW, opacity=0.95))
        out.append(text(x + 160, row_y, clip(msg, 36), 10, "#cfe6f5", opacity=0.9))
        out.append(text(x + w - 14, row_y, ago, 9, DIM, anchor="end"))
        row_y += 20
    return "".join(out)


def p_activity(x, y, w, h, grid):
    """A contribution heatmap. `grid` is a list of weeks, each 7 daily counts.

    Drawn as a calendar rather than a bar chart: the grid stays legible on a
    quiet year, where bars would collapse into an empty box.
    """
    out = [panel(x, y, w, h, "CONTRIBUTION MAP", MAGENTA)]
    if not grid:
        out.append(unavailable(x, y, w, h, "no contribution data"))
        return "".join(out)

    total = sum(sum(wk) for wk in grid)
    peak = max((max(wk) for wk in grid if wk), default=0) or 1

    pitch, cell = 7.4, 5.6
    gx, gy = x + 26, y + 46
    for ci, wk in enumerate(grid):
        for ri, n in enumerate(wk):
            if n <= 0:
                fill, op = "#16233c", 1.0
            else:
                # four steps, so a single commit still reads as present
                step = min(4, 1 + int(3 * n / peak))
                fill, op = CYAN, 0.28 + 0.24 * step
            out.append(
                f'<rect x="{gx+ci*pitch:.1f}" y="{gy+ri*pitch:.1f}" '
                f'width="{cell}" height="{cell}" rx="1.4" fill="{fill}" '
                f'fill-opacity="{op:.2f}"/>'
            )

    for ri, lab in ((1, "M"), (3, "W"), (5, "F")):
        out.append(text(x + 16, gy + ri * pitch + cell, lab, 7, DIM, anchor="middle"))

    legend_x = x + w - 14 - 5 * pitch
    base_y = gy + 7 * pitch + 14
    out.append(text(legend_x - 8, base_y + cell, "LESS", 7, DIM, anchor="end"))
    for i in range(5):
        fill, op = ("#16233c", 1.0) if i == 0 else (CYAN, 0.28 + 0.24 * i)
        out.append(f'<rect x="{legend_x+i*pitch:.1f}" y="{base_y}" width="{cell}" '
                   f'height="{cell}" rx="1.4" fill="{fill}" fill-opacity="{op:.2f}"/>')
    out.append(text(x + w - 14, base_y + cell, "MORE", 7, DIM))
    out.append(text(x + 26, base_y + cell, f"{total:,} contributions in 12 months",
                    9, MAGENTA, opacity=0.75))
    out.append(text(x + w - 14, y + 22, f"PEAK {peak}/DAY", 9, MAGENTA,
                    anchor="end", opacity=0.75))
    return "".join(out)


# --------------------------------------------------------------------------


def render(d):
    """Build the whole dashboard. `d` carries every panel's data."""
    parts = [
        f'<svg xmlns="http://www.w3.org/2000/svg" viewBox="0 0 {W} {H}" '
        f'width="100%" role="img" aria-label="Live dashboard of GitHub '
        f'activity for {esc(d["login"])}.">',
        '<defs>',
        '<filter id="g" x="-50%" y="-50%" width="200%" height="200%">'
        '<feGaussianBlur stdDeviation="2.5" result="b"/><feMerge>'
        '<feMergeNode in="b"/><feMergeNode in="SourceGraphic"/></feMerge></filter>',
        '<pattern id="grid" width="24" height="24" patternUnits="userSpaceOnUse">'
        '<path d="M24 0H0V24" fill="none" stroke="#00f7ff" stroke-opacity="0.07"/>'
        '</pattern>',
        '</defs>',
        f'<rect width="{W}" height="{H}" rx="12" fill="#05080f"/>',
        text(20, 30, "TECH CITY // OPS CENTER", 18, CYAN, weight="bold", glow=True),
        f'<circle cx="960" cy="24" r="5" fill="{RED}" filter="url(#g)">'
        f'<animate attributeName="opacity" values="1;0.1;1" dur="1.2s" '
        f'repeatCount="indefinite"/></circle>',
        text(948, 29, "LIVE", 12, RED, anchor="end"),

        p_languages(20, 50, 300, 165, d.get("languages")),
        p_months(340, 50, 320, 165, d.get("months")),
        p_counter(680, 50, 300, 165, d["total"], d["public"], d["private"],
                  d["saw_private"], d["repo_count"], d["today"], d["label"],
                  d.get("bots", 0)),
        p_recent(20, 235, 470, 170, d.get("recent")),
        p_activity(510, 235, 470, 170, d.get("weeks")),
        '</svg>',
    ]
    return "".join(parts)

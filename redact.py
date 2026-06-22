#!/usr/bin/env python3
"""
redact.py — fail-closed redaction for the daily flight recorder.

Two modes:

  filter:  read a private morning-snapshot JSON, emit a PUBLIC-SAFE markdown log
           containing ONLY allowlisted fields. Anything not on the allowlist is
           dropped. Any allowlisted value that trips a deny-pattern is also dropped.
           Fail-closed: when in doubt, publish nothing.

  --check: scan already-published log files for deny-patterns. Exit non-zero if any
           leak is found. This is the CI guard — defense in depth, in case a bad
           value ever slips through the filter or is added by hand.

Usage:
  python3 redact.py snapshot.json                 # -> writes log/<date>.md
  python3 redact.py snapshot.json --stdout        # -> prints markdown, writes nothing
  python3 redact.py --check log/                  # -> CI leak scan, exits 1 on leak

No network. No third-party dependencies. Standard library only.
"""

import json
import os
import re
import sys

# ----------------------------------------------------------------------------
# ALLOWLIST — the ONLY fields that may ever be published. Edit deliberately.
# Each field maps to a validator: a value passes only if validator(value) is True.
# ----------------------------------------------------------------------------

DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")


def _is_date(v):
    return isinstance(v, str) and bool(DATE_RE.match(v))


def _is_small_int(v):
    return isinstance(v, int) and 0 <= v <= 100000


def _is_short_text(v):
    # one public-safe line: bounded length, single line
    return isinstance(v, str) and 0 < len(v) <= 200 and "\n" not in v


def _is_text_list(v):
    return (
        isinstance(v, list)
        and len(v) <= 25
        and all(_is_short_text(x) for x in v)
    )


ALLOWLIST = {
    "date": _is_date,                 # YYYY-MM-DD
    "streak_days": _is_small_int,     # unbroken build-streak counter
    "commits": _is_small_int,         # public commit count for the day
    "systems_shipped": _is_text_list, # short, public-safe system titles
    "build_status": _is_short_text,   # e.g. "shipped", "stalled", "rest day"
    "note": _is_short_text,           # one public-safe progress line
}

# ----------------------------------------------------------------------------
# DENY-PATTERNS — if any allowlisted value matches one of these, the field is
# dropped (filter mode) or the scan fails (check mode). Catches data that is
# structurally private even if it lands in an allowed field by mistake.
# ----------------------------------------------------------------------------

DENY_PATTERNS = [
    ("email",        re.compile(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}")),
    ("phone",        re.compile(r"(?<!\d)(?:\+?1[-.\s]?)?\(?\d{3}\)?[-.\s]?\d{3}[-.\s]?\d{4}(?!\d)")),
    ("money",        re.compile(r"\$\s?\d[\d,]*(?:\.\d+)?[kKmMbB]?")),
    ("ssn",          re.compile(r"(?<!\d)\d{3}-\d{2}-\d{4}(?!\d)")),
    ("api_key",      re.compile(r"(AKIA[0-9A-Z]{16}|sk-[A-Za-z0-9]{20,}|gh[pousr]_[A-Za-z0-9]{20,}|AIzaSy[A-Za-z0-9_-]{33})")),
    ("private_key",  re.compile(r"-----BEGIN [A-Z ]*PRIVATE KEY-----")),
    # banned topical keywords — health / finance / private relations / client work
    ("banned_topic", re.compile(
        r"\b(weight|sleep score|hrv|body battery|calorie|deal|client|invoice|"
        r"salary|bank|account number|diagnosis|medication|attendee|calendar invite)\b",
        re.IGNORECASE,
    )),
]


def find_leak(text):
    """Return (label, match) for the first deny-pattern that hits, else None."""
    for label, pat in DENY_PATTERNS:
        m = pat.search(text)
        if m:
            return label, m.group(0)
    return None


def _flatten_values(value):
    """Yield every string contained in a value (handles lists)."""
    if isinstance(value, list):
        for x in value:
            yield from _flatten_values(x)
    else:
        yield str(value)


# ----------------------------------------------------------------------------
# FILTER MODE
# ----------------------------------------------------------------------------

def redact(snapshot):
    """Return (clean_dict, dropped_list). Fail-closed."""
    clean, dropped = {}, []
    for key, validator in ALLOWLIST.items():
        if key not in snapshot:
            continue
        value = snapshot[key]
        if not validator(value):
            dropped.append((key, "failed validation"))
            continue
        leak = None
        for s in _flatten_values(value):
            leak = find_leak(s)
            if leak:
                break
        if leak:
            dropped.append((key, f"deny-pattern: {leak[0]}"))
            continue
        clean[key] = value
    # report keys present in input that are NOT on the allowlist (dropped silently-private)
    for key in snapshot:
        if key not in ALLOWLIST:
            dropped.append((key, "not on allowlist"))
    return clean, dropped


def to_markdown(clean):
    date = clean.get("date", "unknown-date")
    lines = [f"# Flight log — {date}", ""]
    if "build_status" in clean:
        lines.append(f"**Status:** {clean['build_status']}")
    if "streak_days" in clean:
        lines.append(f"**Streak:** {clean['streak_days']} days")
    if "commits" in clean:
        lines.append(f"**Commits:** {clean['commits']}")
    lines.append("")
    if clean.get("systems_shipped"):
        lines.append("## Systems shipped")
        for s in clean["systems_shipped"]:
            lines.append(f"- {s}")
        lines.append("")
    if "note" in clean:
        lines.append(clean["note"])
        lines.append("")
    return "\n".join(lines).rstrip() + "\n"


def run_filter(snapshot_path, stdout_only):
    with open(snapshot_path) as f:
        snapshot = json.load(f)
    clean, dropped = redact(snapshot)

    if not clean.get("date"):
        sys.stderr.write("FAIL-CLOSED: no valid 'date' field — refusing to publish.\n")
        return 1

    md = to_markdown(clean)

    # final belt-and-suspenders scan of the rendered output
    leak = find_leak(md)
    if leak:
        sys.stderr.write(f"FAIL-CLOSED: rendered output tripped {leak[0]} ({leak[1]!r}) — refusing.\n")
        return 1

    for key, reason in dropped:
        sys.stderr.write(f"dropped: {key} ({reason})\n")

    if stdout_only:
        sys.stdout.write(md)
    else:
        os.makedirs("log", exist_ok=True)
        out = os.path.join("log", f"{clean['date']}.md")
        with open(out, "w") as f:
            f.write(md)
        sys.stderr.write(f"wrote {out}\n")
    return 0


# ----------------------------------------------------------------------------
# CHECK MODE (CI leak guard)
# ----------------------------------------------------------------------------

def run_check(target):
    failures = []
    paths = []
    if os.path.isdir(target):
        for root, _dirs, files in os.walk(target):
            for name in files:
                if name.endswith(".md"):
                    paths.append(os.path.join(root, name))
    else:
        paths.append(target)

    for p in sorted(paths):
        with open(p) as f:
            text = f.read()
        leak = find_leak(text)
        if leak:
            failures.append((p, leak[0], leak[1]))

    if failures:
        sys.stderr.write("LEAK GUARD FAILED — private data found in published logs:\n")
        for p, label, match in failures:
            sys.stderr.write(f"  {p}: {label} -> {match!r}\n")
        return 1
    sys.stderr.write(f"leak guard passed: {len(paths)} file(s) clean\n")
    return 0


def main(argv):
    if "--check" in argv:
        rest = [a for a in argv[1:] if a != "--check"]
        target = rest[0] if rest else "log"
        return run_check(target)
    if len(argv) < 2:
        sys.stderr.write(__doc__)
        return 2
    stdout_only = "--stdout" in argv
    snapshot = [a for a in argv[1:] if not a.startswith("--")][0]
    return run_filter(snapshot, stdout_only)


if __name__ == "__main__":
    raise SystemExit(main(sys.argv))

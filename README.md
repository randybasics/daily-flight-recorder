# daily-flight-recorder

**The receipts.** An auto-committed daily snapshot of the build — the aviation black-box
principle: log every day immutably, including the bad ones. The value isn't any single entry;
it's the unbroken, auditable trail a buyer or operator can actually trust.

Most creators only publish wins. This publishes the whole flight: the streaks and the stalls,
the systems shipped and the outcomes moved. Receipts, not the highlight reel.

## What gets logged (and what doesn't)

Each morning a snapshot is committed automatically. It is **redacted to an allowlist** before
it ever lands here:

✅ **Published:** a small set of intended fields (systems shipped, streak/build status, a
public-safe progress line).
🚫 **Never published:** calendar contents, meeting attendees, client/deal names, contacts,
financial accounts, health specifics, or anything outside the allowlist. The filter strips
everything not explicitly allowed — **fail-closed, not fail-open**.

## How it works

```
morning snapshot (private) → redaction allowlist filter → commit only allowed fields → public log
```

Commits are authored by a scoped bot identity (no personal email). Redaction runs before the
commit, so private data never reaches git history.

## Why

A 90-day unbroken public record of systems shipped and numbers moved is a stronger proof-of-work
artifact than any curated portfolio.

## License

MIT.

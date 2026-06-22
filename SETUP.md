# Setup — wiring the daily flight recorder

The recorder is split across two trust zones on purpose:

```
PRIVATE machine                              PUBLIC repo (this one)
---------------                              ---------------------
morning snapshot (full, private JSON)
        │
        ▼
   redact.py  (fail-closed allowlist)
        │  only allowlisted, deny-scanned fields survive
        ▼
   log/<date>.md  ──────  git commit (bot identity)  ──────►  push
                                                                  │
                                                                  ▼
                                                          leak-guard CI re-scans
                                                          every push (defense in depth)
```

The private snapshot **never leaves your machine**. Only the redacted markdown is committed.

## 1. Generate today's log locally

On the private machine, point `redact.py` at the morning snapshot JSON:

```bash
python3 redact.py /path/to/morning-snapshot-$(date +%F).json
# writes log/<date>.md containing only allowlisted, deny-scanned fields
```

Preview without writing:

```bash
python3 redact.py /path/to/snapshot.json --stdout
```

`redact.py` prints every dropped field and why (`not on allowlist`, `failed validation`,
`deny-pattern: …`) to stderr, so you can audit what was withheld.

## 2. Commit with a scoped bot identity (no personal email)

Use a dedicated identity scoped to this repo, never your personal name/email:

```bash
git -C ~/path/to/daily-flight-recorder \
  -c user.name="flight-recorder-bot" \
  -c user.email="<your-id>+flight-recorder@users.noreply.github.com" \
  commit -am "log: $(date +%F)"
git push
```

(Replace `<your-id>` with your GitHub numeric user id so the no-reply address is valid.)

Automate it with cron or launchd that runs steps 1–2 each morning. For the push, use the
**most narrowly-scoped credential possible** — never a personal admin token:

- **Best:** a per-repo **deploy key with write access** (Settings → Deploy keys). Its blast
  radius is this one public repo, not the whole account. Generate a dedicated keypair, add the
  public half as a write deploy key, and point the repo's remote at it over SSH.
- **Acceptable:** a fine-grained PAT scoped to this single repo's contents.

Either way the unattended credential can write to exactly one repo and nothing else.

## 3. CI re-scans every push

`.github/workflows/leak-guard.yml` runs on every push touching `log/`:

- `redact.py --check log/` scans all published logs for deny-patterns (email, phone, money,
  keys, health/finance/client keywords) and fails the build if any are found.
- It also self-tests the filter against `examples/snapshot-input.example.json`, which carries
  deliberately-private fields — the filter must strip all of them.

## Editing the allowlist

The allowlist lives at the top of `redact.py` (`ALLOWLIST`). It is the single source of truth
for what may ever be published. Add fields deliberately, with a validator. When the filter and a
desire to publish something disagree, the filter wins — that is the whole point.

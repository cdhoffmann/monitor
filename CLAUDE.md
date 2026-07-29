# Monitor — Project Reference

## What This Is
A site change monitor that checks configured storefronts for product changes (new drops, restocks, sold outs, removals) and sends Discord notifications. Built to be multi-site from the start — adding a new site is just a config entry.

## How It Works
1. `monitor.py` loads `config.json` and runs each configured site
2. Each site uses an extractor (matched by `type`) to fetch and parse the page
3. The result is compared against the last known state in `snapshots/<site-id>.json`
4. If anything changed, a Discord embed is posted via webhook
5. The updated snapshot is saved (and committed back to the repo by GitHub Actions)

## File Structure
```
monitor.py               # main runner
config.json              # site configuration
extractors/
  bigcartel.py           # BigCartel product extractor (name, price, sold-out status)
  generic.py             # hash-based extractor for any site
snapshots/
  iviviv.json            # last known product state for IVIVIV (committed to repo)
.github/workflows/
  monitor.yml            # GitHub Actions workflow
```

## Running Locally
```bash
python3 monitor.py              # run all sites
python3 monitor.py iviviv       # run one site by id
```

Webhook URLs use `$ENV_VAR` references — set the env var before running:
```bash
DISCORD_WEBHOOK_IVIVIV="https://discord.com/api/webhooks/..." python3 monitor.py
```

## Scheduling
GitHub Actions' built-in cron scheduler was unreliable so it was removed. Instead, **cron-job.org** externally triggers the workflow every 5 minutes via the GitHub API:

- **URL:** `https://api.github.com/repos/cdhoffmann/monitor/actions/workflows/280387573/dispatches`
- **Method:** POST
- **Headers:** `Authorization: Bearer <PAT>` and `Accept: application/vnd.github+json`
- **Body:** `{"ref":"main"}`
- **Token:** Fine-grained PAT scoped to `cdhoffmann/monitor` with Actions read/write permission

The workflow commits snapshot changes back to the repo with `[skip ci]` to avoid loops.

## Daily Heartbeat
So silence can be told apart from a dead monitor, a once-per-day health check is posted to Discord. It piggybacks on the every-5-minute run rather than a separate cron: on the first run at/after the configured local hour, it fires and then stays quiet until the next day.

State lives in `snapshots/_heartbeat.json` (`last_sent_date` + a `changes_since` counter), which the existing commit step persists across runs. The counter increments whenever a real change alert fires and resets when the heartbeat posts, so the message honestly reports either "No product changes in the last 24 hours" or "N change alert(s) sent."

Configured via an optional top-level `heartbeat` block in `config.json`:
```json
"heartbeat": {
  "hour": 9,
  "tz": "America/Denver",
  "discord_webhook": "$DISCORD_WEBHOOK_IVIVIV"
}
```
Defaults: `hour` 9, `tz` `America/Denver`, webhook falls back to the first site's. Set `"enabled": false` to turn it off. Only runs on full scheduled runs (`python3 monitor.py`), not single-site debug runs.

## Discord Webhooks
Webhook URLs are never stored in the repo. Each site references an env var in `config.json`:
```json
"discord_webhook": "$DISCORD_WEBHOOK_IVIVIV"
```

The actual URL is stored as a **GitHub Actions secret** (`DISCORD_WEBHOOK_IVIVIV`).

**Important:** Discord auto-invalidates webhook URLs posted inside Discord messages. If a webhook stops working, create a new one and update the secret — don't paste the URL in chat.

**Also important:** Python's `urllib` is blocked by Cloudflare on Discord's API. All Discord requests use `curl` via subprocess.

## Adding a New Site

### BigCartel shop
Add to `config.json`:
```json
{
  "id": "mysite",
  "name": "My Site",
  "url": "https://mysite.bigcartel.com/products",
  "base_url": "https://mysite.bigcartel.com",
  "type": "bigcartel",
  "discord_webhook": "$DISCORD_WEBHOOK_MYSITE"
}
```
Add `DISCORD_WEBHOOK_MYSITE` as a GitHub Actions secret and expose it in the workflow env block.

### Any other site (hash-based)
Same config but `"type": "generic"` — notifies on any page content change, no product-level detail.

### Custom extractor
Add `extractors/<type>.py` with an `extract(url) -> dict` function. Return a dict of items keyed by a stable ID, each with whatever fields you want to track. The runner handles comparison and notification.

## Current Sites
| ID | Name | URL | Type |
|----|------|-----|------|
| iviviv | IVIVIV | https://iviviv.bigcartel.com/products | bigcartel |

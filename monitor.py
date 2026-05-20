#!/usr/bin/env python3
"""
Site change monitor. Checks configured sites for updates and notifies Discord.

Usage:
  python3 monitor.py              # run all sites
  python3 monitor.py <site-id>   # run one site
"""
import importlib.util
import json
import os
import subprocess
import sys
import urllib.request
from datetime import datetime, timezone
from pathlib import Path

BASE_DIR = Path(__file__).parent
SNAPSHOTS_DIR = BASE_DIR / 'snapshots'
LOGS_DIR = BASE_DIR / 'logs'
CONFIG_FILE = BASE_DIR / 'config.json'

SNAPSHOTS_DIR.mkdir(exist_ok=True)
LOGS_DIR.mkdir(exist_ok=True)


# ---------------------------------------------------------------------------
# Snapshot I/O
# ---------------------------------------------------------------------------

def load_snapshot(site_id):
    path = SNAPSHOTS_DIR / f'{site_id}.json'
    if not path.exists():
        return None
    with open(path) as f:
        return json.load(f)


def save_snapshot(site_id, data):
    path = SNAPSHOTS_DIR / f'{site_id}.json'
    with open(path, 'w') as f:
        json.dump(data, f, indent=2)


# ---------------------------------------------------------------------------
# Extractor loader
# ---------------------------------------------------------------------------

def load_extractor(extractor_type):
    extractor_path = BASE_DIR / 'extractors' / f'{extractor_type}.py'
    if not extractor_path.exists():
        raise FileNotFoundError(f"No extractor found for type '{extractor_type}' at {extractor_path}")
    spec = importlib.util.spec_from_file_location(extractor_type, extractor_path)
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


# ---------------------------------------------------------------------------
# Change detection
# ---------------------------------------------------------------------------

def compare_products(current, snapshot):
    """Detect product-level changes: new, removed, restocked, sold out."""
    changes = {}

    new_items = {k: v for k, v in current.items() if k not in snapshot}
    if new_items:
        changes['new'] = new_items

    removed = [k for k in snapshot if k not in current]
    if removed:
        changes['removed'] = removed

    restocked, sold_out_now = {}, []
    for key, data in current.items():
        if key not in snapshot:
            continue
        was_sold_out = snapshot[key].get('sold_out', False)
        is_sold_out = data.get('sold_out', False)
        if was_sold_out and not is_sold_out:
            restocked[key] = data
        elif not was_sold_out and is_sold_out:
            sold_out_now.append(key)

    if restocked:
        changes['restocked'] = restocked
    if sold_out_now:
        changes['sold_out'] = sold_out_now

    return changes


def compare_generic(current, snapshot):
    """Detect any content change via hash comparison."""
    changes = {}
    for key, data in current.items():
        if key not in snapshot or snapshot[key].get('hash') != data.get('hash'):
            changes['updated'] = [key]
    return changes


# ---------------------------------------------------------------------------
# Discord notification
# ---------------------------------------------------------------------------

def build_embed(site, changes):
    now = datetime.now(timezone.utc).strftime('%Y-%m-%d %H:%M UTC')
    base_url = site.get('base_url', '')
    fields = []

    def _label(path, data):
        return data.get('name') or path.split('/')[-1]

    def _link(path):
        return f"{base_url}{path}" if path.startswith('/') else path

    if changes.get('new'):
        lines = []
        for path, data in changes['new'].items():
            status = ' ~~Sold out~~' if data.get('sold_out') else ' **Available!**'
            lines.append(f"[{_label(path, data)}]({_link(path)}) — {data.get('price', '')}{status}")
        fields.append({"name": "🆕 New Products", "value": '\n'.join(lines)[:1024], "inline": False})

    if changes.get('restocked'):
        lines = [
            f"[{_label(p, d)}]({_link(p)}) — {d.get('price', '')} **Back in stock!**"
            for p, d in changes['restocked'].items()
        ]
        fields.append({"name": "✅ Back in Stock", "value": '\n'.join(lines)[:1024], "inline": False})

    if changes.get('sold_out'):
        lines = [f"`{p.split('/')[-1]}`" for p in changes['sold_out']]
        fields.append({"name": "❌ Sold Out", "value": '\n'.join(lines)[:1024], "inline": False})

    if changes.get('removed'):
        lines = [f"`{p.split('/')[-1]}`" for p in changes['removed']]
        fields.append({"name": "🗑️ Removed", "value": '\n'.join(lines)[:1024], "inline": False})

    if changes.get('updated'):
        fields.append({"name": "🔄 Page Updated", "value": f"[Visit site]({site['url']})", "inline": False})

    return {
        "embeds": [{
            "title": f"🛒 {site['name']} Updated!",
            "url": site['url'],
            "color": 0x9B59B6,
            "fields": fields,
            "footer": {"text": f"Detected at {now}"},
        }]
    }


def send_discord(webhook_url, payload):
    # urllib is blocked by Cloudflare on Discord's API; curl bypasses it
    result = subprocess.run(
        ['curl', '-s', '-o', '/dev/null', '-w', '%{http_code}',
         '-H', 'Content-Type: application/json',
         '-d', json.dumps(payload),
         webhook_url],
        capture_output=True, text=True, timeout=15,
    )
    return int(result.stdout.strip()) if result.stdout.strip().isdigit() else None


# ---------------------------------------------------------------------------
# Per-site runner
# ---------------------------------------------------------------------------

def log(site_id, message):
    ts = datetime.now().strftime('%Y-%m-%d %H:%M:%S')
    entry = f"[{ts}] {message}\n"
    with open(LOGS_DIR / f'{site_id}.log', 'a') as f:
        f.write(entry)
    print(f"[{site_id}] {message}")


def resolve_webhook(value):
    """Resolve $ENV_VAR references in webhook URLs."""
    if value and value.startswith('$'):
        env_var = value[1:]
        resolved = os.environ.get(env_var)
        if not resolved:
            raise ValueError(f"env var {env_var} is not set")
        return resolved
    return value


def run_site(site):
    site_id = site['id']
    extractor_type = site.get('type', 'generic')

    try:
        extractor = load_extractor(extractor_type)
        current = extractor.extract(site['url'])
    except Exception as e:
        log(site_id, f"ERROR fetching: {e}")
        return

    if not current:
        log(site_id, "WARNING: No items extracted — page structure may have changed")
        return

    snapshot = load_snapshot(site_id)

    if snapshot is None:
        save_snapshot(site_id, current)
        log(site_id, f"First run — baseline saved ({len(current)} items)")
        return

    changes = compare_generic(current, snapshot) if extractor_type == 'generic' else compare_products(current, snapshot)

    if changes:
        try:
            webhook = resolve_webhook(site['discord_webhook'])
            send_discord(webhook, build_embed(site, changes))
            log(site_id, f"Changes detected and Discord notified: {list(changes.keys())}")
        except Exception as e:
            log(site_id, f"ERROR sending Discord notification: {e}")
    else:
        log(site_id, f"No changes ({len(current)} items)")

    save_snapshot(site_id, current)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------

def main():
    with open(CONFIG_FILE) as f:
        config = json.load(f)

    sites = config.get('sites', [])

    if len(sys.argv) > 1:
        target = sys.argv[1]
        sites = [s for s in sites if s['id'] == target]
        if not sites:
            print(f"Site '{target}' not found in config.json", file=sys.stderr)
            sys.exit(1)

    for site in sites:
        run_site(site)


if __name__ == '__main__':
    main()

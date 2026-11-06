#!/usr/bin/env python3
"""Reject Discord webhook credentials in the Git index without printing them."""
import subprocess
import sys


PATTERN = (
    r'https?://((canary|ptb)\.)?discord(app)?\.com/'
    r'api/(v[0-9]+/)?webhooks/[0-9]+/[A-Za-z0-9_-]+'
)


def main():
    result = subprocess.run(
        ['git', 'grep', '--cached', '--ignore-case', '--files-with-matches',
         '--null', '--extended-regexp', '-e', PATTERN, '--', '.'],
        capture_output=True,
    )
    if result.returncode == 1:
        return 0
    if result.returncode != 0:
        print("ERROR: Could not scan staged files for webhook credentials.", file=sys.stderr)
        return 1
    print("ERROR: Discord webhook credentials detected. Use $ENV_VAR references.", file=sys.stderr)
    for path in result.stdout.split(b'\0'):
        if path:
            print(f"  {path.decode(errors='replace')!r}", file=sys.stderr)
    print("If exposed, rotate the webhook in Discord; do not just delete the text.", file=sys.stderr)
    return 1


if __name__ == '__main__':
    sys.exit(main())

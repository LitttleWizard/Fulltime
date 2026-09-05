#!/usr/bin/env python3
"""
Check the account and trading configuration without ever printing a secret.

Every check reports PRESENT / MISSING / shape-is-wrong. Values are never
echoed, never logged, and never written anywhere — the whole point of holding
them in environment variables is that they do not end up in a terminal
scrollback or a notes file.

Usage:
    python3 scripts/check_config.py              # local files + local env
    python3 scripts/check_config.py --vercel     # also list Vercel's env names
"""
import argparse
import json
import os
import re
import subprocess
import sys

import os as _os
_os.chdir(_os.path.join(_os.path.dirname(_os.path.abspath(__file__)), '..'))

OK, BAD, WARN = '  ✓', '  ✗', '  !'


def mask(v):
    """Never the value. Only enough to tell two things apart."""
    if not v:
        return '—'
    return f'set ({len(v)} chars, ends …{v[-4:]})' if len(v) > 8 else 'set (short)'


def check_public_config():
    print('\nPublic config — assets/supabase-config.js')
    print('  These two are PUBLIC by design. Row-level security is what protects')
    print('  the data, not the anon key.')
    try:
        src = open('assets/supabase-config.js').read()
    except FileNotFoundError:
        print(BAD, 'file missing')
        return False
    url = re.search(r"SUPABASE_URL\s*=\s*'([^']*)'", src)
    key = re.search(r"SUPABASE_ANON_KEY\s*=\s*'([^']*)'", src)
    u = url.group(1) if url else ''
    k = key.group(1) if key else ''
    ok = True
    if not u:
        print(BAD, 'SUPABASE_URL is empty — accounts are off, and the gate keeps everyone out')
        ok = False
    elif not re.match(r'^https://[a-z0-9-]+\.supabase\.co/?$', u):
        print(WARN, f'SUPABASE_URL looks unusual: {u}')
    else:
        print(OK, f'SUPABASE_URL {u}')
    if not k:
        print(BAD, 'SUPABASE_ANON_KEY is empty')
        ok = False
    elif k.count('.') != 2:
        print(WARN, 'SUPABASE_ANON_KEY does not look like a JWT (expected two dots)')
    elif 'service_role' in k:
        print(BAD, 'that is the SERVICE ROLE key — it bypasses row-level security. '
                   'Use the anon key.')
        ok = False
    else:
        print(OK, f'SUPABASE_ANON_KEY {mask(k)}')
    return ok


def check_server_env():
    print('\nServer secrets — environment only, never a file')
    need = {
        'KALSHI_KEY_ID':      'identifies the trading key',
        'KALSHI_PRIVATE_KEY': 'CAN PLACE AND CANCEL ORDERS',
        'OWNER_USER_ID':      'the one account allowed to trade',
        'SUPABASE_URL':       'for the owner check',
        'SUPABASE_ANON_KEY':  'for the owner check',
    }
    any_set = False
    for k, why in need.items():
        v = os.environ.get(k, '')
        if v:
            any_set = True
            print(OK, f'{k:<20} {mask(v):<28} {why}')
        else:
            print('  ·', f'{k:<20} {"not set locally":<28} {why}')
    if not any_set:
        print(WARN, 'none set in this shell — expected if they live only in Vercel')
    pem = os.environ.get('KALSHI_PRIVATE_KEY', '')
    if pem and 'BEGIN' not in pem:
        print(BAD, 'KALSHI_PRIVATE_KEY does not look like a PEM (no BEGIN line). '
                   'Newlines must be written as \\n.')
    return True


def check_repo_hygiene():
    print('\nRepo hygiene')
    ok = True
    for probe in ('.env', 'kalshi-key.pem', 'service-role.json', 'id_rsa'):
        r = subprocess.run(['git', 'check-ignore', '-q', probe])
        if r.returncode == 0:
            print(OK, f'{probe} would be ignored')
        else:
            print(BAD, f'{probe} is NOT ignored — a key in that file would be published')
            ok = False
    tracked = subprocess.run(['git', 'ls-files'], capture_output=True, text=True).stdout.split()
    risky = [f for f in tracked
             if re.search(r'\.(pem|key|p12|pfx)$|secret|credential', f, re.I)]
    if risky:
        print(BAD, f'secret-shaped files are TRACKED: {risky}')
        ok = False
    else:
        print(OK, 'no secret-shaped files tracked')
    return ok


def check_vercel():
    print('\nVercel environment (names only — values are never fetched)')
    try:
        r = subprocess.run(['vercel', 'env', 'ls'], capture_output=True, text=True, timeout=60)
    except (FileNotFoundError, subprocess.TimeoutExpired):
        print(WARN, 'vercel CLI unavailable; check the dashboard instead')
        return True
    if r.returncode != 0:
        print(WARN, 'could not list — are you linked and logged in?')
        return True
    for line in r.stdout.splitlines():
        if any(k in line for k in ('KALSHI', 'OWNER_USER_ID', 'SUPABASE')):
            print('   ', line.strip())
    if 'SERVICE_ROLE' in r.stdout:
        print(BAD, 'SUPABASE_SERVICE_ROLE_KEY is set in Vercel. Nothing here needs '
                   'it and it bypasses row-level security. Remove it.')
    return True


def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('--vercel', action='store_true', help='also list Vercel env var names')
    a = ap.parse_args()

    print('Fulltime configuration check')
    print('No secret values are printed by this script.')
    results = [check_public_config(), check_server_env(), check_repo_hygiene()]
    if a.vercel:
        results.append(check_vercel())

    print('\n' + ('All required local checks passed.' if all(results)
                  else 'Some checks failed — see above.'))
    print('Setup steps: supabase/README.md · what is sensitive: SECURITY.md')
    return 0 if all(results) else 1


if __name__ == '__main__':
    sys.exit(main())

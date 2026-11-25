#!/usr/bin/env python3
"""Record a profile's feed grid with an owner-supplied Browser Use session.

The logged-in profile page is scrolled slowly and only the web app's own timeline
responses are kept, read-only. Raw pages contain signed CDN URLs and stay in the
private output. Install browser-use separately; credentials are read only from
--storage-state.
"""
import argparse
import asyncio
import json
import os
import random
import re
from datetime import datetime, timezone
from pathlib import Path

CONNECTION = 'xdt_api__v1__feed__user_timeline_graphql_connection'
# Browser Use accepts only `(...args) =>` functions and awaits returned promises.
CAPTURE = '''() => {
  if (window.__timeline) return 'ready';
  window.__timeline = [];
  const keep = (url, body) => { if (/graphql/.test(url || '') && body && body.includes('%s')) window.__timeline.push(body); };
  const open = XMLHttpRequest.prototype.open, send = XMLHttpRequest.prototype.send;
  XMLHttpRequest.prototype.open = function (method, url, ...rest) { this.__url = url; return open.call(this, method, url, ...rest); };
  XMLHttpRequest.prototype.send = function (body) {
    this.addEventListener('load', () => { try { keep(this.__url, this.responseText); } catch (e) {} });
    return send.call(this, body);
  };
  const original = window.fetch;
  window.fetch = function (...args) {
    return original.apply(this, args).then(response => {
      const url = (args[0] && args[0].url) || String(args[0]);
      if (/graphql/.test(url)) response.clone().text().then(body => keep(url, body)).catch(() => {});
      return response;
    });
  };
  return 'patched';
}''' % CONNECTION
HYDRATED = '''() => {
  const found = [];
  const walk = x => { if (!x || typeof x !== 'object') return;
    if (x.%s) { found.push(JSON.stringify({data: {%s: x.%s}})); return; }
    for (const v of Object.values(x)) walk(v); };
  for (const s of document.querySelectorAll('script[type="application/json"]')) { try { walk(JSON.parse(s.textContent)); } catch (e) {} }
  return JSON.stringify(found);
}''' % (CONNECTION, CONNECTION, CONNECTION)
DRAIN = '() => JSON.stringify((window.__timeline || []).splice(0))'


def now():
    return datetime.now(timezone.utc).isoformat()


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    tmp = path.with_suffix(path.suffix + '.tmp')
    tmp.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    tmp.chmod(0o600)
    tmp.replace(path)


def connection(body):
    return json.loads(body)['data'][CONNECTION]


async def collect(args):
    os.umask(0o077)
    os.environ.update(ANONYMIZED_TELEMETRY='false', BROWSER_USE_CLOUD_SYNC='false', BROWSER_USE_LOGGING_LEVEL='error')
    from browser_use import Browser
    state = json.loads(args.storage_state.read_text())
    state['cookies'] = [c for c in state.get('cookies', []) if c['domain'].lstrip('.') == 'instagram.com' or c['domain'].endswith('.instagram.com')]
    state['origins'] = []
    if not state['cookies']:
        raise ValueError('No Instagram session cookies supplied')
    root = args.output.resolve()
    if args.storage_state.resolve().is_relative_to(root):
        raise ValueError('Raw output must be separate from the credential file')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    manifest = {'username': args.username, 'started_at': now(), 'pages': [], 'feed_exhausted': False,
                'account_complete': False, 'method': 'browser-use logged-in profile grid; web app timeline responses recorded while scrolling'}
    codes, owners = set(), {}
    browser = Browser(headless=True, executable_path=args.chrome, user_data_dir=None, storage_state=state,
                      allowed_domains=['*.instagram.com'], enable_default_extensions=False, permissions=[],
                      chromium_sandbox=False, args=['--disable-dev-shm-usage'], window_size={'width': 1280, 'height': 1600})

    def record(body, origin):
        page = connection(body)
        new = 0
        for edge in page.get('edges', []):
            node = edge['node']
            owners[str(node.get('user', {}).get('username', '')).lower()] = owners.get(str(node.get('user', {}).get('username', '')).lower(), 0) + 1
            if node['code'] not in codes:
                codes.add(node['code'])
                new += 1
        number = len(manifest['pages']) + 1
        write_json(root / 'feed' / f'page-{number:04d}.json', json.loads(body))
        info = page.get('page_info', {})
        manifest['pages'].append({'page': number, 'origin': origin, 'edges': len(page.get('edges', [])), 'new': new,
                                  'has_next_page': info.get('has_next_page'), 'retrieved_at': now()})
        return info.get('has_next_page')

    try:
        await browser.start()
        page = await browser.new_page('about:blank')
        # Install the recorder before the profile document loads, so its first grid request is kept.
        await page._client.send.Page.addScriptToEvaluateOnNewDocument(
            {'source': f'({CAPTURE})()'}, session_id=await page._ensure_session())
        await page.goto(f'https://www.instagram.com/{args.username}/')
        await asyncio.sleep(8)
        seen = json.loads(await page.evaluate('''() => JSON.stringify({path: location.pathname,
          loginForm: Boolean(document.querySelector('input[name="username"],input[name="password"]'))})'''))
        if seen['loginForm'] or re.search(r'challenge|checkpoint|accounts/login', seen['path']):
            raise ValueError('Session requires login or challenge completion')
        await page.evaluate(CAPTURE)
        more = True
        for body in json.loads(await page.evaluate(HYDRATED)) + json.loads(await page.evaluate(DRAIN)):
            more = record(body, 'initial_load')
        stalls = 0
        while more and len(manifest['pages']) < args.max_pages:
            await page.evaluate('() => { window.scrollTo(0, document.body.scrollHeight); return 1; }')
            await asyncio.sleep(random.uniform(args.delay_min, args.delay_max))
            bodies = json.loads(await page.evaluate(DRAIN))
            if not bodies:
                stalls += 1
                if stalls >= args.max_stalls:
                    manifest['stopped'] = f'no new timeline response after {stalls} scrolls'
                    break
                # Nudge the observer that triggers the next grid request.
                await page.evaluate('() => { window.scrollBy(0, -900); return 1; }')
                await asyncio.sleep(1.5)
                continue
            stalls = 0
            for body in bodies:
                more = record(body, 'scroll_response')
            manifest['posts_recorded'] = len(codes)
            write_json(root / 'feed-manifest.json', manifest)
            print(json.dumps({'pages': len(manifest['pages']), 'posts': len(codes), 'more': more}), flush=True)
        manifest.update(feed_exhausted=more is False, posts_recorded=len(codes), publishing_accounts=owners, finished_at=now())
        write_json(root / 'feed-manifest.json', manifest)
    finally:
        await browser.kill()
    return manifest


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage-state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--chrome', default='/usr/bin/google-chrome')
    parser.add_argument('--max-pages', type=int, default=600)
    parser.add_argument('--max-stalls', type=int, default=8)
    parser.add_argument('--delay-min', type=float, default=3.0)
    parser.add_argument('--delay-max', type=float, default=6.0)
    args = parser.parse_args()
    args.username = args.username.lower().removeprefix('@')
    if not re.fullmatch(r'[a-z0-9_.]{1,30}', args.username):
        parser.error('Invalid Instagram username')
    if args.delay_min < 1 or args.delay_max < args.delay_min:
        parser.error('Use a delay of at least one second')
    result = asyncio.run(collect(args))
    print(json.dumps({k: v for k, v in result.items() if k != 'pages'}, ensure_ascii=False))

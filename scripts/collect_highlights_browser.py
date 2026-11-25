#!/usr/bin/env python3
"""Read a profile's saved Highlights with an owner-supplied Browser Use session.

Raw media and signed CDN URLs belong in a private output, never the wiki/site.
Install browser-use separately; credentials are read only from --storage-state.
"""
import argparse
import asyncio
import hashlib
import json
import os
import re
from datetime import datetime, timezone
from pathlib import Path


def write_json(path, value):
    path.write_text(json.dumps(value, ensure_ascii=False, indent=2) + '\n')
    path.chmod(0o600)


async def collect(args):
    os.umask(0o077)
    os.environ.update(ANONYMIZED_TELEMETRY='false', BROWSER_USE_CLOUD_SYNC='false', BROWSER_USE_LOGGING_LEVEL='error')
    from browser_use import Browser
    state = json.loads(args.storage_state.read_text())
    state['cookies'] = [c for c in state.get('cookies', []) if c['domain'].lstrip('.') == 'instagram.com' or c['domain'].endswith('.instagram.com')]
    state['origins'] = [o for o in state.get('origins', []) if o['origin'] in {'https://www.instagram.com', 'https://instagram.com'}]
    if not state['cookies']:
        raise ValueError('No Instagram session cookies supplied')
    root = args.output.resolve()
    if root == args.storage_state.parent.resolve() or args.storage_state.resolve().is_relative_to(root):
        raise ValueError('Raw output must be separate from the credential directory')
    root.mkdir(parents=True, exist_ok=True, mode=0o700)
    browser = Browser(headless=True, executable_path=args.chrome, user_data_dir=None, storage_state=state,
                      allowed_domains=['*.instagram.com'], enable_default_extensions=False, permissions=[],
                      chromium_sandbox=False, args=['--disable-dev-shm-usage'])
    result = {'username': args.username, 'retrieved_at': datetime.now(timezone.utc).isoformat(),
              'method': 'browser-use authenticated profile and Highlight page hydration', 'collections': [],
              'account_complete': False, 'errors': []}
    try:
        await browser.start()
        page = await browser.new_page(f'https://www.instagram.com/{args.username}/')
        await asyncio.sleep(6)
        discovery = json.loads(await page.evaluate('''() => JSON.stringify({path:location.pathname,
          loginForm:Boolean(document.querySelector('input[name="username"],input[name="password"]')),
          links:Array.from(document.querySelectorAll('a[href*="/stories/highlights/"]')).map(a=>({title:a.innerText,url:a.href}))})'''))
        if discovery['loginForm'] or 'challenge' in discovery['path']:
            raise ValueError('Session requires login or challenge completion')
        links = {x['url']: x for x in discovery['links']}
        if not links:
            raise ValueError('No Highlight links exposed on the profile; completeness unknown')
        write_json(root / 'discovery.json', {'username': args.username, 'collections': list(links.values())})
        for link in links.values():
            hid = re.fullmatch(r'https://www\.instagram\.com/stories/highlights/(\d+)/', link['url'])[1]
            await page.goto(link['url'])
            node = None
            for _ in range(4):
                await asyncio.sleep(2)
                nodes = json.loads(await page.evaluate('''(id) => {
                  const found=[];
                  const walk=x=>{if(!x||typeof x!=='object')return;
                    if(x.id==='highlight:'+id&&Array.isArray(x.items)){found.push(x);return;}
                    for(const v of Object.values(x))walk(v);};
                  for(const s of document.querySelectorAll('script[type="application/json"]')){
                    try{walk(JSON.parse(s.textContent));}catch{}}
                  return JSON.stringify(found);
                }''', hid))
                if nodes:
                    node = max(nodes, key=lambda n: len(n['items']))
                    break
            if node is None:
                result['errors'].append({'highlight_id': hid, 'error': 'No story payload in page hydration'})
                write_json(root / 'manifest.json', result)
                continue
            if node.get('user', {}).get('username') != args.username:
                raise ValueError('Highlight publisher does not match requested profile')
            folder = root / hid
            folder.mkdir(exist_ok=True, mode=0o700)
            write_json(folder / 'raw.json', node)
            items = []
            for index, item in enumerate(node['items']):
                items.append({'index': index, 'story_id': str(item['pk']), 'kind': 'video' if item['media_type'] == 2 else 'image',
                              'taken_at': item.get('taken_at'), 'duration': item.get('video_duration'),
                              'source_url': link['url'] + '?story_media_id=' + str(item['pk']),
                              'image_candidates': item.get('image_versions2', {}).get('candidates', []),
                              'video_candidates': item.get('video_versions') or [], 'assets': []})
            result['collections'].append({'highlight_id': hid, 'title': node.get('title') or link['title'], 'url': link['url'],
                                          'returned_items': len(items), 'raw_sha256': hashlib.sha256((folder/'raw.json').read_bytes()).hexdigest(), 'items': items})
            write_json(root / 'manifest.json', result)
            print(json.dumps({'highlight': hid, 'title': node.get('title'), 'items': len(items)}, ensure_ascii=False), flush=True)
    finally:
        await browser.kill()
    return result


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--storage-state', type=Path, required=True)
    parser.add_argument('--output', type=Path, required=True)
    parser.add_argument('--username', required=True)
    parser.add_argument('--chrome', default='/usr/bin/google-chrome')
    args = parser.parse_args()
    if not re.fullmatch(r'[A-Za-z0-9_.]+', args.username):
        parser.error('Invalid Instagram username')
    asyncio.run(collect(args))

#!/usr/bin/env python3
"""Count recurring visual motifs from machine mentions with explicit, reviewable patterns.

Each motif is a documented regular expression over the model's English description of a
garment, accessory, setting, object or gesture (item + details). Counts, distinct items,
publication days, first/last dates, years and platforms are computed from the matching
mentions; the newest and oldest matches are kept as candidate evidence locators. Patterns
favour precision over recall — a motif can be under-counted, never invented.
"""
from __future__ import annotations

import argparse
import json
import re
from collections import Counter, defaultdict
from pathlib import Path

MOTIFS = {
    'wardrobe': {
        'satin-silk-blouse': r'(satin|silk|silky).{0,40}(blouse|shirt|button)|(blouse|shirt).{0,30}(satin|silk)',
        'white-shirt': r'white.{0,25}(shirt|button-down|button-up)',
        'blazer': r'blazer|suit jacket',
        'jeans': r'\bjeans\b|denim (pants|trousers)',
        'camisole-slip': r'camisole|spaghetti|slip (top|dress)|\bcami\b',
        'evening-dress': r'(evening|cocktail|maxi|midi|bodycon|halter|sequin).{0,15}dress|\bgown\b',
        'robe-kimono': r'\brobe\b|kimono',
        'knitwear': r'sweater|cardigan|\bknit',
        'turtleneck': r'turtleneck',
        'crop-tank': r'crop top|tank top',
        'athleisure': r'tracksuit|sweatpants|leggings|athletic|sportswear|hoodie|sports bra',
        'swimwear': r'bikini|swimsuit|swimwear',
        'corset': r'corset|bustier',
        'trench-coat': r'trench|wool coat|wrap coat',
        'all-black-look': r'all-black|black (outfit|ensemble)|monochrome black',
    },
    'accessories': {
        'clover-pendant': r'clover|alhambra|quatrefoil',
        'safety-pin-pendant': r'safety.?pin',
        'v-pendant': r'\bv[- ]?(shaped )?pendant|letter v\b|v-shaped (charm|pendant)',
        'layered-necklaces': r'layered.{0,25}(necklace|chain)|(necklaces|chains).{0,20}layered|multiple (necklaces|chains)',
        'link-watch': r'(link|bracelet|metal|silver|steel|gold|two-tone).{0,30}\bwatch|(?<!smart)\bwatch\b.{0,30}(link|bracelet|metal|silver|steel|gold)',
        'smartwatch': r'smart ?watch|apple watch|fitness (band|tracker)|\bwhoop\b|oura',
        'huggie-hoops': r'huggie|small hoop|hoop earring|small (silver|gold) hoops',
        'statement-rings': r'\brings?\b',
        'sunglasses': r'sunglasses',
        'red-string': r'red (string|thread|cord)',
        'bangle-cuff': r'bangle|cuff|love bracelet|nail bracelet',
        'earbuds': r'airpods|earbuds',
        'claw-clip': r'claw clip|hair clip',
        'handbag': r'handbag|tote|clutch|shoulder bag|crossbody|\bbag\b',
    },
    'settings': {
        'villa-pool': r'villa|infinity pool|swimming pool|\bpool\b',
        'rice-jungle-view': r'rice (field|paddies|paddy|terrace)|jungle',
        'beach-ocean': r'beach|ocean|\bsea\b|seaside',
        'podcast-studio': r'podcast',
        'dark-studio-lights': r'(circular|round|grid of).{0,20}lights|purple.{0,25}(studio|light)|neon',
        'bright-white-studio': r'white (studio|backdrop|background|wall)|bright studio',
        'video-call-live': r'split.?screen|video call|\bzoom\b|instagram live|live stream|livestream',
        'stage-conference': r'\bstage\b|conference|auditorium|audience|lecture hall|presentation hall',
        'car': r'car interior|inside (a|the) car|driver.?s seat|steering wheel|convertible|passenger seat',
        'cafe-restaurant': r'caf[eé]\b|restaurant|coffee shop|bistro',
        'golf': r'golf',
        'desk-workspace': r'\bdesk\b|workspace|home office|work table',
        'travel-airport': r'airport|airplane|plane cabin|aircraft|in-flight|private jet',
        'city-street': r'city street|street|urban|downtown',
        'gym': r'\bgym\b|fitness studio|workout',
        'mountains-snow': r'mountain|snow',
    },
    'objects': {
        'laptop': r'macbook|laptop',
        'smartphone': r'smartphone|iphone|\bphone\b',
        'podcast-mic': r'shure|sm7b|dynamic microphone|boom arm|podcast microphone|broadcast microphone|studio microphone',
        'wireless-mic': r'lavalier|wireless (clip|mic|lapel)|clip-on mic|lapel mic|handheld (wireless )?mic',
        'coffee': r'coffee|espresso|latte|cappuccino|\bmug\b',
        'water-glass': r'glass of water|water glass|drinking glass|water bottle|glass filled with water',
        'wine-champagne': r'\bwine\b|champagne|prosecco|cocktail glass',
        'books-notebook': r'\bbooks?\b|notebook|planner|journal',
        'golf-gear': r'golf (club|bag|cart|ball)',
        'flowers': r'bouquet|flowers|roses',
        'shopping-bags': r'shopping bag',
        'sports-car': r'sports car|convertible|porsche|lamborghini|ferrari|mercedes|bmw',
        'ring-light-tripod': r'ring light|tripod|selfie stick',
        'dog': r'\bdog\b|puppy',
        'scooter-bike': r'scooter|motorbike|motorcycle',
    },
    'gestures': {
        'index-finger': r'index finger|points? (her )?finger|finger raised|raises (her )?(index|finger)',
        'counting-fingers': r'count(s|ing)? (off )?(on )?(her )?fingers|counts off',
        'open-palms': r'open palms?|palms? (up|outward|open)|open hands?',
        'hands-together': r'hands together|clasp|fingertips together|steepl',
        'hair-touch': r'(touches|tucks|brushes|runs|adjusts).{0,25}hair|hair behind',
        'smile-laugh': r'laughs?|laughing|smiles? (broadly|widely|warmly)',
        'head-tilt': r'head tilt|tilts (her )?head',
        'direct-gaze': r'direct (eye contact|gaze)|directly into the (camera|lens)',
        'phone-in-hand': r'holding (a |her )?(phone|smartphone)|phone in (her )?hand',
    },
}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--mentions', type=Path, required=True)
    parser.add_argument('--out', type=Path, required=True)
    args = parser.parse_args()
    result = {'method': __doc__.strip().split('\n\n')[1].replace('\n', ' '), 'patterns': MOTIFS, 'categories': {}}
    for category, motifs in MOTIFS.items():
        rows = [json.loads(l) for l in (args.mentions / f'{category}.jsonl').read_text().split('\n') if l.strip()]
        out = {}
        for name, pattern in motifs.items():
            regex = re.compile(pattern, re.I)
            hits = [r for r in rows if regex.search(f"{r.get('item') or ''} {r.get('details') or ''}")]
            if not hits:
                continue
            by_item = {}
            for r in hits:
                by_item.setdefault(r['id'], r)
            dates = sorted({(r.get('date') or '') for r in by_item.values() if r.get('date')})
            years = Counter((r.get('date') or 'undated')[:4] for r in by_item.values())
            ordered = sorted(by_item.values(), key=lambda r: r.get('date') or '', reverse=True)
            out[name] = {'pattern': pattern, 'mentions': len(hits), 'items': len(by_item), 'publication_days': len(dates),
                         'first': dates[0] if dates else None, 'last': dates[-1] if dates else None, 'by_year': dict(sorted(years.items())),
                         'by_platform': dict(Counter(r['platform'] for r in by_item.values())),
                         'newest': [{k: r.get(k) for k in ['id', 'date', 'platform', 'time', 'asset_index', 'item', 'details']} for r in ordered[:25]],
                         'oldest': [{k: r.get(k) for k in ['id', 'date', 'platform', 'time', 'asset_index', 'item', 'details']} for r in ordered[-8:]]}
        result['categories'][category] = {'mentions': len(rows), 'motifs': dict(sorted(out.items(), key=lambda kv: -kv[1]['items']))}
    args.out.write_text(json.dumps(result, ensure_ascii=False, indent=1) + '\n')
    for category, data in result['categories'].items():
        print(category, [(k, v['items'], v['first'], v['last']) for k, v in list(data['motifs'].items())[:16]])


if __name__ == '__main__':
    main()

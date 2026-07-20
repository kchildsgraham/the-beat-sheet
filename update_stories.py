#!/usr/bin/env python3
import json, re, urllib.parse, urllib.request
from datetime import datetime, timezone, timedelta
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

OUTLETS = {
    'nytimes.com': ('The New York Times', 'General'),
    'npr.org': ('NPR', 'General'),
    'nbcnews.com': ('NBC News', 'General'),
    'cbsnews.com': ('CBS News', 'General'),
    'cnbc.com': ('CNBC', 'General'),
    'cnn.com': ('CNN', 'General'),
    'edweek.org': ('Education Week', 'General'),
    'k12dive.com': ('K-12 Dive', 'General'),
    'edsource.org': ('EdSource', 'General'),
    'lgbtqnation.com': ('LGBTQ Nation', 'LGBTQ press'),
    'advocate.com': ('The Advocate', 'LGBTQ press'),
    'queerty.com': ('Queerty', 'LGBTQ press'),
}

BEAT_QUERIES = {
    'Politics': '(politics OR election OR congress OR court OR governor OR policy)',
    'Business': '(business OR economy OR markets OR company OR labor OR jobs)',
    'Schools': '(schools OR education OR students OR teachers OR district OR university)',
    'LGBTQ': '(LGBTQ OR transgender OR gay OR lesbian OR queer OR bisexual)',
}

DOMAINS = ' OR '.join(f'site:{d}' for d in OUTLETS)
USER_AGENT = 'Mozilla/5.0 (compatible; BeatSheet/1.0)'


def clean(text):
    return re.sub(r'\s+', ' ', re.sub(r'<[^>]+>', '', text or '')).strip()


def source_for(title, description):
    hay = f'{title} {description}'.lower()
    for domain, value in OUTLETS.items():
        if domain in hay:
            return value
    # Google News commonly appends outlet after " - "
    suffix = title.rsplit(' - ', 1)[-1].strip().lower()
    aliases = {
        'the new york times': ('The New York Times', 'General'), 'npr': ('NPR', 'General'),
        'nbc news': ('NBC News', 'General'), 'cbs news': ('CBS News', 'General'),
        'cnbc': ('CNBC', 'General'), 'cnn': ('CNN', 'General'),
        'education week': ('Education Week', 'General'), 'k-12 dive': ('K-12 Dive', 'General'),
        'edsource': ('EdSource', 'General'), 'lgbtq nation': ('LGBTQ Nation', 'LGBTQ press'),
        'the advocate': ('The Advocate', 'LGBTQ press'), 'advocate.com': ('The Advocate', 'LGBTQ press'),
        'queerty': ('Queerty', 'LGBTQ press'),
    }
    return aliases.get(suffix)


def strip_source(title):
    return title.rsplit(' - ', 1)[0].strip()


def fetch(beat, query):
    q = f'{query} ({DOMAINS}) when:2d'
    url = 'https://news.google.com/rss/search?' + urllib.parse.urlencode({
        'q': q, 'hl': 'en-US', 'gl': 'US', 'ceid': 'US:en'
    })
    req = urllib.request.Request(url, headers={'User-Agent': USER_AGENT})
    with urllib.request.urlopen(req, timeout=30) as r:
        root = ET.fromstring(r.read())
    rows = []
    for item in root.findall('./channel/item'):
        raw_title = clean(item.findtext('title'))
        desc = clean(item.findtext('description'))
        src = source_for(raw_title, desc)
        if not src:
            continue
        try:
            published = parsedate_to_datetime(item.findtext('pubDate')).astimezone(timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)
        rows.append({
            'source': src[0], 'lane': src[1], 'title': strip_source(raw_title),
            'summary': desc[:280] or 'Open the source for the latest reporting.',
            'url': item.findtext('link'), 'published': published.isoformat(), 'beats': [beat]
        })
    return rows


def key(title):
    return re.sub(r'[^a-z0-9]+', ' ', title.lower()).strip()


def main():
    merged = {}
    for beat, query in BEAT_QUERIES.items():
        for s in fetch(beat, query):
            k = key(s['title'])
            if k in merged:
                if beat not in merged[k]['beats']:
                    merged[k]['beats'].append(beat)
            else:
                merged[k] = s
    cutoff = datetime.now(timezone.utc) - timedelta(hours=48)
    stories = [s for s in merged.values() if datetime.fromisoformat(s['published']) >= cutoff]
    stories.sort(key=lambda s: s['published'], reverse=True)
    stories = stories[:24]
    payload = {'updated_at': datetime.now(timezone.utc).isoformat(), 'stories': stories}
    with open('stories.json', 'w', encoding='utf-8') as f:
        json.dump(payload, f, ensure_ascii=False, indent=2)
    print(f'Wrote {len(stories)} stories')

if __name__ == '__main__':
    main()

#!/usr/bin/env python3
import html
import json
import re
import urllib.parse
import urllib.request
from datetime import datetime, timedelta, timezone
from email.utils import parsedate_to_datetime
from xml.etree import ElementTree as ET

# Each outlet is queried independently so larger publishers cannot crowd out
# education and LGBTQ-focused sources.
SOURCES = [
    {"name": "The New York Times", "domain": "nytimes.com", "lane": "General", "query": ""},
    {"name": "NPR", "domain": "npr.org", "lane": "General", "query": ""},
    {"name": "NBC News", "domain": "nbcnews.com", "lane": "General", "query": ""},
    {"name": "CBS News", "domain": "cbsnews.com", "lane": "General", "query": ""},
    {"name": "CBS News LGBTQ", "domain": "cbsnews.com", "lane": "General", "query": "LGBTQ OR transgender OR gay OR lesbian OR queer"},
    {"name": "CNBC", "domain": "cnbc.com", "lane": "General", "query": ""},
    {"name": "CNN", "domain": "cnn.com", "lane": "General", "query": ""},
    {"name": "Education Week", "domain": "edweek.org", "lane": "General", "query": ""},
    {"name": "K-12 Dive", "domain": "k12dive.com", "lane": "General", "query": ""},
    {"name": "EdSource", "domain": "edsource.org", "lane": "General", "query": ""},
    {"name": "LGBTQ Nation", "domain": "lgbtqnation.com", "lane": "LGBTQ press", "query": ""},
    {"name": "The Advocate", "domain": "advocate.com", "lane": "LGBTQ press", "query": ""},
    {"name": "Queerty", "domain": "queerty.com", "lane": "LGBTQ press", "query": ""},
]

BEAT_TERMS = {
    "Politics": [
        "politic", "election", "congress", "senate", "house", "supreme court",
        "court", "governor", "president", "white house", "administration",
        "legislation", "lawmakers", "policy", "federal", "statehouse", "mayor"
    ],
    "Business": [
        "business", "econom", "market", "company", "corporate", "labor", "jobs",
        "worker", "union", "stock", "trade", "tariff", "finance", "bank",
        "technology", "data center", "industry", "retail"
    ],
    "Schools": [
        "school", "education", "student", "teacher", "district", "classroom",
        "college", "university", "campus", "curriculum", "superintendent",
        "school board", "k-12", "higher education"
    ],
    "LGBTQ+": [
        "lgbtq", "lgbt", "transgender", "trans ", "gay", "lesbian", "bisexual",
        "queer", "nonbinary", "same-sex", "pride", "gender identity",
        "gender-affirming"
    ],
}

USER_AGENT = "Mozilla/5.0 (compatible; TheBeatSheet/2.0)"
PER_SOURCE_LIMIT = 3
MAX_STORIES = 30
LOOKBACK_HOURS = 72


def clean(value):
    value = html.unescape(value or "")
    value = re.sub(r"<[^>]+>", " ", value)
    return re.sub(r"\s+", " ", value).strip()


def normalize_title(title):
    # Google News usually appends " - Outlet Name".
    return title.rsplit(" - ", 1)[0].strip()


def story_key(title):
    return re.sub(r"[^a-z0-9]+", " ", title.lower()).strip()


def tag_beats(title, summary, source):
    text = f"{title} {summary}".lower()
    beats = [
        beat for beat, terms in BEAT_TERMS.items()
        if any(term in text for term in terms)
    ]

    # Source-informed fallback so every card belongs somewhere useful.
    if source in {"Education Week", "K-12 Dive", "EdSource"} and "Schools" not in beats:
        beats.append("Schools")
    if source in {"LGBTQ Nation", "The Advocate", "Queerty", "CBS News LGBTQ"} and "LGBTQ+" not in beats:
        beats.append("LGBTQ+")

    return beats or ["Politics"]


def google_news_url(source):
    parts = []
    if source["query"]:
        parts.append(f'({source["query"]})')
    parts.append(f'site:{source["domain"]}')
    parts.append("when:3d")
    query = " ".join(parts)
    return "https://news.google.com/rss/search?" + urllib.parse.urlencode({
        "q": query,
        "hl": "en-US",
        "gl": "US",
        "ceid": "US:en",
    })


def fetch_source(source):
    request = urllib.request.Request(
        google_news_url(source),
        headers={"User-Agent": USER_AGENT},
    )

    with urllib.request.urlopen(request, timeout=30) as response:
        root = ET.fromstring(response.read())

    stories = []
    seen = set()

    for item in root.findall("./channel/item"):
        raw_title = clean(item.findtext("title"))
        title = normalize_title(raw_title)
        if not title:
            continue

        # Require Google's source suffix to match the intended publisher.
        suffix = raw_title.rsplit(" - ", 1)[-1].lower() if " - " in raw_title else ""
        accepted = {
            source["name"].lower(),
            source["domain"].lower(),
        }
        # CBS LGBTQ results still appear as CBS News.
        if source["name"] == "CBS News LGBTQ":
            accepted.add("cbs news")
        if not any(name in suffix for name in accepted):
            continue

        key = story_key(title)
        if key in seen:
            continue
        seen.add(key)

        try:
            published = parsedate_to_datetime(item.findtext("pubDate")).astimezone(timezone.utc)
        except Exception:
            published = datetime.now(timezone.utc)

        description = clean(item.findtext("description"))
        # Google descriptions often repeat headline/source; keep a clean fallback.
        summary = description
        if not summary or story_key(summary) == key:
            summary = "Open the story for the latest reporting."

        display_source = "CBS News" if source["name"] == "CBS News LGBTQ" else source["name"]
        beats = tag_beats(title, summary, source["name"])

        stories.append({
            "source": display_source,
            "source_feed": source["name"],
            "lane": source["lane"],
            "title": title,
            "summary": summary[:320],
            "url": item.findtext("link"),
            "published": published.isoformat(),
            "beats": beats,
        })

        if len(stories) >= PER_SOURCE_LIMIT:
            break

    return stories


def main():
    cutoff = datetime.now(timezone.utc) - timedelta(hours=LOOKBACK_HOURS)
    all_stories = []
    errors = []

    for source in SOURCES:
        try:
            all_stories.extend(fetch_source(source))
        except Exception as exc:
            errors.append(f'{source["name"]}: {exc}')

    # Deduplicate across source queries while merging beat tags.
    merged = {}
    for story in all_stories:
        key = story_key(story["title"])
        if key in merged:
            for beat in story["beats"]:
                if beat not in merged[key]["beats"]:
                    merged[key]["beats"].append(beat)
        else:
            merged[key] = story

    stories = [
        story for story in merged.values()
        if datetime.fromisoformat(story["published"]) >= cutoff
    ]
    stories.sort(key=lambda story: story["published"], reverse=True)
    stories = stories[:MAX_STORIES]

    payload = {
        "updated_at": datetime.now(timezone.utc).isoformat(),
        "lookback_hours": LOOKBACK_HOURS,
        "story_count": len(stories),
        "sources_requested": [source["name"] for source in SOURCES],
        "errors": errors,
        "stories": stories,
    }

    with open("stories.json", "w", encoding="utf-8") as output:
        json.dump(payload, output, ensure_ascii=False, indent=2)

    print(f"Wrote {len(stories)} stories from {len(SOURCES)} source searches")
    if errors:
        print("Feed errors:")
        for error in errors:
            print(f"  - {error}")


if __name__ == "__main__":
    main()

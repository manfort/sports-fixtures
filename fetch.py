"""Read fixture posts from a Telegram channel and rebuild fixtures.json.

Runs in GitHub Actions. Needs these environment variables:
  TG_API_ID, TG_API_HASH  from my.telegram.org
  TG_SESSION              string printed by login.py
  TG_CHANNEL              channel id or exact channel name (login.py lists them)
  SOURCE_TZ               time zone of the times in the posts (default America/New_York)
"""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).with_name("fixtures.json")
# How long after the start an event stays listed, by category (hours). Keep in sync with index.html.
DURATION_H = {"foot": 2, "volley": 2, "motor": 2, "basket": 2.5, "hockey": 2.5, "amfoot": 3.5, "tennis": 4, "wrest": 4, "fight": 5}
DEFAULT_DURATION_H = 2.5
SCAN_LIMIT = int(os.environ.get("SCAN_LIMIT", "1000"))

PATTERN = re.compile(
    r"([A-Z]{2,3})\|\s*(.+?)\s+(\d{1,3})\s*\[(.+?)\s*\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}):\d{2}\)\]"
)

# Checked in order; the first match wins. Matched against "channel | name".
CATEGORIES = [
    ("motor", r"\b(F1|Formula|MotoGP|NASCAR|IndyCar|Grand Prix|Rally)\b"),
    ("fight", r"^UFC |\b(UFC|MMA|PFL|Bellator|Cage Warriors|FCC|Boxing|boxing|Muay|Kickboxing|NEXZONE|FN:|Fight Night)\b"),
    ("wrest", r"\b(GCW|TLP|AEW|WWE|NJPW|TNA|Deck the Halls|wrestling|Wrestling)\b"),
    ("basket", r"\b(hoops|Basketball|basketball|NBA|WNBA|NCAAB)\b"),
    ("hockey", r"\b(hockey|Hockey|NHL|AHL|OHL|WHL)\b"),
    ("amfoot", r"\b(Football|NFL|CFL|NCAAF)\b(?! Club)"),
    ("volley", r"\b(volleyball|Volleyball)\b"),
    ("tennis", r"\b(Tennis|tennis|ATP|WTA)\b"),
    ("foot", r"\b(soccer|Soccer|fc|FC|Liga|LaLiga|Premier League|Serie A|Bundesliga|UEFA|Champions League|MLS|Copa)\b"),
]
# Channels whose plain "A vs B" events are football (soccer) matches.
SOCCER_CHANNELS = {"TRILLER TV", "VIX PPV", "PARAMOUNT PPV"}

# FLO SPORTS style lowercase prefix ("hoops: ...") and ESPN+ time suffix ("... Nov 03 6:00PM ET").
PREFIX = re.compile(r"^[a-z][a-z ]*:\s+")
SUFFIX = re.compile(r"\s+[A-Z][a-z]{2} \d{1,2} \d{1,2}:\d{2}\s*[AP]M\s+[A-Z]{1,3}T$")


def source_tz():
    from zoneinfo import ZoneInfo

    return ZoneInfo(os.environ.get("SOURCE_TZ", "America/New_York"))


def categorize(channel, name):
    text = f"{channel} | {name}"
    for cat, rx in CATEGORIES:
        if re.search(rx, text):
            return cat
    if channel in SOCCER_CHANNELS and re.search(r"\svs\.?\s", name):
        return "foot"
    return "other"


def parse(text, tz):
    """Yield fixtures found in one post. Handles entries that wrap over several lines."""
    flat = re.sub(r"\s+", " ", text)
    for _region, ch_raw, num, name_raw, when in PATTERN.findall(flat):
        ch = re.match(r"^(.*?)\s*\[(\w+)\]$", ch_raw)
        channel = (ch.group(1) if ch else ch_raw).strip()
        name = re.sub(r"\s+", " ", name_raw.replace("_", " ")).strip()
        cat = categorize(channel, name)
        name = SUFFIX.sub("", PREFIX.sub("", name)) or name
        start = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=tz).astimezone(timezone.utc)
        yield {
            "channel": channel,
            "num": num,
            "name": name,
            "cat": cat,
            "time": start.strftime("%Y-%m-%dT%H:%M:%SZ"),
        }


def key(item):
    return f"{item['channel']}|{item['num']}|{item['time']}"


def load():
    if DATA.exists():
        return json.loads(DATA.read_text(encoding="utf-8")).get("items", [])
    return []


def save(items):
    now = datetime.now(timezone.utc)

    def still_on(i):
        start = datetime.strptime(i["time"], "%Y-%m-%dT%H:%M:%SZ").replace(tzinfo=timezone.utc)
        return start + timedelta(hours=DURATION_H.get(i["cat"], DEFAULT_DURATION_H)) >= now

    items = sorted(filter(still_on, items), key=lambda i: (i["time"], i["channel"], i["num"]))
    if items == load():
        print("no changes")
        return
    DATA.write_text(
        json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}, ensure_ascii=False, separators=(",", ":")),
        encoding="utf-8",
    )
    print(f"saved {len(items)} fixtures")


async def find_channel(client, wanted):
    # A fresh StringSession has no entity cache, so look the channel up among the account's chats.
    async for dialog in client.iter_dialogs():
        if str(dialog.id) == wanted or dialog.name == wanted:
            return dialog.entity
    raise SystemExit(f"channel not found: {wanted!r} (run login.py to list channel ids)")


async def main():
    if not os.environ.get("TG_SESSION"):
        print("TG_SESSION is not set yet: skipping, the site keeps its current data")
        return

    from telethon import TelegramClient
    from telethon.sessions import StringSession

    tz = source_tz()
    client = TelegramClient(StringSession(os.environ["TG_SESSION"]), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("TG_SESSION is not valid any more: run login.py again and update the secret")

    channel = await find_channel(client, os.environ["TG_CHANNEL"].strip())
    # Rebuilt from the latest posts every run, so edited or deleted posts drop out on their own.
    found = {}
    async for msg in client.iter_messages(channel, limit=SCAN_LIMIT):
        for item in parse(msg.message or "", tz):
            found.setdefault(key(item), item)
    await client.disconnect()
    if not found:
        raise SystemExit("no fixtures found in the latest posts: the post format may have changed")
    save(list(found.values()))


if __name__ == "__main__":
    asyncio.run(main())

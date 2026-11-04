"""Read fixture posts from a Telegram channel and update fixtures.json.

Runs in GitHub Actions. Needs these environment variables:
  TG_API_ID, TG_API_HASH  from my.telegram.org
  TG_SESSION              string printed by login.py
  TG_CHANNEL              channel id or exact channel name (login.py lists them)
  SOURCE_UTC_OFFSET       hours offset of the times in the posts (0 = UTC)
"""
import asyncio
import json
import os
import re
from datetime import datetime, timedelta, timezone
from pathlib import Path

DATA = Path(__file__).with_name("fixtures.json")
KEEP_PAST = timedelta(days=1)
SCAN_LIMIT = int(os.environ.get("SCAN_LIMIT", "300"))

PATTERN = re.compile(
    r"([A-Z]{2,3})\|\s*(.+?)\s+(\d{1,3})\s*\[(.+?)\s*\((\d{4}-\d{2}-\d{2} \d{2}:\d{2}):\d{2}\)\]"
)


def categorize(name):
    if re.search(r"\b(GCW|TLP|AEW|WWE|Deck the Halls)\b", name, re.I):
        return "wrest"
    if re.search(r"\b(NEXZONE|FN|MMA|UFC|ONE|Boxing|Muay)\b", name, re.I):
        return "fight"
    if re.search(r"\svs\.?\s", name, re.I):
        return "foot"
    return "other"


def parse(text, utc_offset):
    """Yield fixtures found in one post. Handles entries that wrap over several lines."""
    tz = timezone(timedelta(hours=utc_offset))
    flat = re.sub(r"\s+", " ", text)
    for region, ch_raw, num, name_raw, when in PATTERN.findall(flat):
        ch = re.match(r"^(.*?)\s*\[(\w+)\]$", ch_raw)
        channel = (ch.group(1) if ch else ch_raw).strip()
        name = re.sub(r"\s+", " ", name_raw.replace("_", " ")).strip()
        start = datetime.strptime(when, "%Y-%m-%d %H:%M").replace(tzinfo=tz).astimezone(timezone.utc)
        yield {
            "region": region,
            "channel": channel,
            "num": num,
            "name": name,
            "cat": categorize(name),
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
    cutoff = (now - KEEP_PAST).strftime("%Y-%m-%dT%H:%M:%SZ")
    items = sorted((i for i in items if i["time"] >= cutoff), key=lambda i: (i["time"], i["channel"], i["num"]))
    if items == load():
        print("no changes")
        return
    DATA.write_text(
        json.dumps({"updated": now.strftime("%Y-%m-%dT%H:%M:%SZ"), "items": items}, ensure_ascii=False, indent=1),
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
    from telethon import TelegramClient
    from telethon.sessions import StringSession

    if not os.environ.get("TG_SESSION"):
        print("TG_SESSION is not set yet: skipping, the site keeps its current data")
        return

    offset = float(os.environ.get("SOURCE_UTC_OFFSET", "0"))
    client = TelegramClient(StringSession(os.environ["TG_SESSION"]), int(os.environ["TG_API_ID"]), os.environ["TG_API_HASH"])
    await client.connect()
    if not await client.is_user_authorized():
        raise SystemExit("TG_SESSION is not valid any more: run login.py again and update the secret")

    channel = await find_channel(client, os.environ["TG_CHANNEL"].strip())
    found = {key(i): i for i in load()}
    async for msg in client.iter_messages(channel, limit=SCAN_LIMIT):
        for item in parse(msg.message or "", offset):
            found[key(item)] = item
    await client.disconnect()
    save(list(found.values()))


if __name__ == "__main__":
    asyncio.run(main())

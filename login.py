"""Run once on your own computer to create TG_SESSION for GitHub Actions.

    pip3 install telethon
    python3 login.py

Telegram sends a login code to the app. The printed session string logs in to
your account: put it only in GitHub Secrets, never in a file or a chat.
"""
import asyncio
from getpass import getpass

from telethon import TelegramClient
from telethon.sessions import StringSession


async def main():
    api_id = int(input("api_id: ").strip())
    api_hash = getpass("api_hash (hidden): ").strip()
    client = TelegramClient(StringSession(), api_id, api_hash)
    await client.start()

    print("\nChannels on this account (use the id as TG_CHANNEL):")
    async for dialog in client.iter_dialogs():
        if dialog.is_channel:
            print(f"  {dialog.id}  {dialog.name}")

    print("\nTG_SESSION (copy everything on the next line):")
    print(client.session.save())
    await client.disconnect()


asyncio.run(main())

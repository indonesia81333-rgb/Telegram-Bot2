"""Run this where the bot runs (Render Shell or locally):  python diagnose.py
Checks credentials format, reachability of Telegram servers, and a real bot login."""
import asyncio
import re
import socket
import sys

import config

DCS = {"DC1": "149.154.175.53", "DC2": "149.154.167.51", "DC4": "149.154.167.91", "DC5": "91.108.56.130"}


def ok(flag):
    return "OK  " if flag else "FAIL"


async def main():
    print("== Credentials ==")
    print(ok(config.API_ID > 0), "API_ID =", config.API_ID)
    print(ok(bool(re.fullmatch(r"[0-9a-fA-F]{32}", config.API_HASH))), "API_HASH length", len(config.API_HASH), "(need 32)")
    print(ok(bool(re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{30,}", config.BOT_TOKEN))), "BOT_TOKEN format")

    print("\n== Can this machine reach Telegram? ==")
    for name, ip in DCS.items():
        try:
            with socket.create_connection((ip, 443), timeout=8):
                print(ok(True), name, ip)
        except Exception as e:
            print(ok(False), name, ip, e)

    print("\n== Bot login ==")
    from pyrogram import Client
    app = Client("diag", api_id=config.API_ID, api_hash=config.API_HASH,
                 bot_token=config.BOT_TOKEN, in_memory=True, ipv6=False)
    try:
        await app.start()
        me = await app.get_me()
        print(ok(True), f"Logged in as @{me.username}")
        await app.stop()
    except Exception as e:
        print(ok(False), type(e).__name__, e)
        print("\nIf the error is RPC_CALL_FAIL / 500 for every token while the DC checks above pass,\n"
              "Telegram is rejecting this API_ID/API_HASH pair or this host's IP. Create a new\n"
              "API_ID/API_HASH on my.telegram.org with a different Telegram account, or run from a\n"
              "different host/region and compare.")
        sys.exit(1)


asyncio.run(main())

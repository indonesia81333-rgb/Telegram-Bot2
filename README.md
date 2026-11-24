# Gofile Telegram Upload Bot

Send any file to the bot. It uploads it to **Gofile** and replies with the full file details, an expiry date/time, and Download / Share / Delete buttons.

## How folders work
- Each Telegram user gets their own **private** folder on your Gofile account (`<username>_<id>`).
- Every upload goes into its own sub-folder with an **expiry time** (and an optional password), so each link has its own lifetime. Only that sub-folder is shared by link; the user folder stays private.

## Commands
`/expiry 6h` (10m to 30d) · `/private on|off` (password-protect links) · `/myfiles` · `/me` · `/status`

## Setup
1. `API_ID` / `API_HASH` from https://my.telegram.org, `BOT_TOKEN` from @BotFather.
2. `GOFILE_TOKEN`: Gofile > My Profile > Account API token. Note: Gofile's API may require a premium account, and expiry/password settings may depend on your plan.
3. Run: `pip install -r requirements.txt && python bot.py`. Dashboard at http://localhost:8080.

## Deploy on Render
Push to GitHub, create a Blueprint from the repo, fill the secret env vars. Use a paid instance or an uptime monitor on `/health` for non-stop running. Attach a disk at `/app/data` or the `/myfiles` history is lost on redeploy.

## USER_SESSION (4 GB uploads, owner only)
Needs a Telegram Premium account. Generate a Pyrogram session string for that account (see Pyrogram's `export_session_string()`), put it in `USER_SESSION`, set `OWNER_ID` to that account's id, and send the large file to the bot from that account. Treat the string like a password: it grants full access to that Telegram account.

## Troubleshooting Telegram login (`RPC_CALL_FAIL` / 500)
Run `python diagnose.py` (Render: Shell tab). It checks your credentials, whether the host can reach Telegram, and attempts a real login, then prints which step fails.

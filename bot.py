import asyncio
import logging
import mimetypes
import os
import re
import secrets
import time
import uuid
from datetime import datetime
from urllib.parse import quote
from zoneinfo import ZoneInfo

from pyrogram import Client, filters, idle
from pyrogram.errors import FloodWait, InternalServerError, RPCError
from pyrogram.types import (CallbackQuery, InlineKeyboardButton,
                            InlineKeyboardMarkup, Message)

import config
import db
import gofile
import web

logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
log = logging.getLogger("bot")
os.makedirs(config.DOWNLOAD_DIR, exist_ok=True)

try:
    TZ = ZoneInfo(config.TIMEZONE)
except Exception:
    TZ = ZoneInfo("UTC")

bot = Client("gofile_bot", api_id=config.API_ID, api_hash=config.API_HASH,
             bot_token=config.BOT_TOKEN, in_memory=True, ipv6=False)
user_client = None
if config.USER_SESSION:
    user_client = Client("owner_user", api_id=config.API_ID, api_hash=config.API_HASH,
                         session_string=config.USER_SESSION, in_memory=True)

HELP = (
    "<b>Gofile Upload Bot</b>\n\n"
    "Send me any file, video, audio or photo. I upload it to your own private folder "
    "on Gofile and send back a link with its full details and expiry time.\n\n"
    "/expiry &lt;time&gt; - link lifetime, e.g. <code>/expiry 6h</code>, <code>2d</code>, <code>30m</code>\n"
    "/private &lt;on|off&gt; - protect each link with a password\n"
    "/myfiles - your uploads with expiry\n"
    "/me - your folder, settings and usage\n"
    "/status - bot status\n\n"
    "Limit: 2 GB per file (4 GB for the owner with a Premium session)."
)


def human(n):
    return web.fmt_size(n)


def bar(pct, n=14):
    f = int(n * pct / 100)
    return "▰" * f + "▱" * (n - f)


def fmt_eta(sec):
    sec = int(sec)
    if sec <= 0:
        return "--"
    m, s = divmod(sec, 60)
    h, m = divmod(m, 60)
    return f"{h}h {m}m" if h else (f"{m}m {s}s" if m else f"{s}s")


def fmt_dt(ts):
    return datetime.fromtimestamp(ts, TZ).strftime("%d %b %Y, %I:%M %p %Z")


def fmt_left(ts):
    left = int(ts - time.time())
    if left <= 0:
        return "expired"
    d, r = divmod(left, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return " ".join(p for p in (f"{d}d" if d else "", f"{h}h" if h else "", f"{m}m") if p)


def fmt_dur(secs):
    d, r = divmod(secs, 86400)
    h, r = divmod(r, 3600)
    m = r // 60
    return " ".join(p for p in (f"{d}d" if d else "", f"{h}h" if h else "", f"{m}m" if m else "") if p) or "0m"


def parse_duration(text):
    m = re.fullmatch(r"(\d+)\s*([mhd])", text.strip().lower())
    if not m:
        return None
    n, u = int(m.group(1)), m.group(2)
    secs = n * {"m": 60, "h": 3600, "d": 86400}[u]
    if secs < 600 or secs > config.MAX_EXPIRY_DAYS * 86400:
        return None
    return secs


def media_of(msg: Message):
    for kind in ("document", "video", "audio", "voice", "animation", "video_note", "photo"):
        m = getattr(msg, kind, None)
        if m:
            return kind, m
    return None, None


def safe_name(name):
    return re.sub(r"[\\/\x00-\x1f]", "_", name).strip() or "file"


def folder_label(user):
    base = user.username or user.first_name or "user"
    base = re.sub(r"[^A-Za-z0-9_.-]", "_", base)[:40] or "user"
    return f"{base}_{user.id}"


def make_progress(status: Message, label: str, job: dict):
    """Live progress. Must be a plain async function so Pyrogram awaits it."""
    last = [0.0]
    t0 = time.time()

    async def progress(current, total):
        now = time.time()
        pct = current * 100 / total if total else 0
        job.update(stage=label, pct=round(pct, 1))
        if now - last[0] < 3 and current != total:
            return
        last[0] = now
        speed = current / max(now - t0, 0.001)
        eta = (total - current) / speed if speed and total else 0
        try:
            await status.edit_text(
                f"<b>{label}</b>\n<code>{bar(pct)}</code> {pct:.0f}%\n"
                f"{human(current)} / {human(total)}\n"
                f"Speed {human(speed)}/s · ETA {fmt_eta(eta)}"
            )
        except Exception:
            pass

    return progress


async def user_folder(user):
    """Get or create the user's private Gofile folder."""
    folder_id = (await db.get_user(user.id))[0]
    if folder_id:
        return folder_id
    root = await gofile.root_folder()
    data = await gofile.create_folder(root, folder_label(user))
    folder_id = data["id"]
    await gofile.update(folder_id, "public", False)  # user folder stays private
    await db.set_folder(user.id, folder_id)
    return folder_id


def details_text(name, size, mime, md5, link, created, expires, password, folder, header="Upload complete"):
    lines = [
        f"<b>{header}</b>",
        "",
        f"<b>Name:</b> <code>{name}</code>",
        f"<b>Size:</b> {human(size)}",
        f"<b>Type:</b> {mime or 'unknown'}",
    ]
    if md5:
        lines.append(f"<b>MD5:</b> <code>{md5}</code>")
    lines += [
        f"<b>Folder:</b> <code>{folder}</code> (private)",
        f"<b>Uploaded:</b> {fmt_dt(created)}",
        f"<b>Expires:</b> {fmt_dt(expires)} ({fmt_left(expires)} left)",
    ]
    if password:
        lines.append(f"<b>Password:</b> <code>{password}</code>")
    lines += ["", f"<b>Link:</b> {link}"]
    return "\n".join(lines)


def buttons(link, name, file_id):
    share = f"https://t.me/share/url?url={quote(link)}&text={quote(name)}"
    return InlineKeyboardMarkup([[
        InlineKeyboardButton("Download", url=link),
        InlineKeyboardButton("Share", url=share),
        InlineKeyboardButton("Delete", callback_data=f"del:{file_id}"),
    ]])


@bot.on_message(filters.command(["start", "help"]) & filters.private)
async def start_cmd(_, msg: Message):
    await db.ensure_user(msg.from_user.id, msg.from_user.username)
    await msg.reply_text(HELP)


@bot.on_message(filters.command("expiry") & filters.private)
async def expiry_cmd(_, msg: Message):
    await db.ensure_user(msg.from_user.id, msg.from_user.username)
    if len(msg.command) < 2:
        secs = (await db.get_user(msg.from_user.id))[1] or config.DEFAULT_EXPIRY_HOURS * 3600
        return await msg.reply_text(
            f"Current expiry: <b>{fmt_dur(secs)}</b>\nChange it: <code>/expiry 6h</code> "
            f"(min 10m, max {config.MAX_EXPIRY_DAYS}d)")
    secs = parse_duration(msg.command[1])
    if not secs:
        return await msg.reply_text(
            f"Use a number plus m/h/d, like <code>30m</code>, <code>12h</code>, <code>3d</code>. "
            f"Min 10m, max {config.MAX_EXPIRY_DAYS}d.")
    await db.set_expiry(msg.from_user.id, secs)
    await msg.reply_text(f"New uploads will expire after <b>{fmt_dur(secs)}</b>.")


@bot.on_message(filters.command("private") & filters.private)
async def private_cmd(_, msg: Message):
    await db.ensure_user(msg.from_user.id, msg.from_user.username)
    arg = msg.command[1].lower() if len(msg.command) > 1 else ""
    if arg not in ("on", "off"):
        cur = (await db.get_user(msg.from_user.id))[2]
        return await msg.reply_text(f"Password protection is <b>{'on' if cur else 'off'}</b>. Use <code>/private on</code> or <code>/private off</code>.")
    await db.set_private(msg.from_user.id, arg == "on")
    await msg.reply_text("New links will be password protected." if arg == "on" else "New links won't need a password.")


@bot.on_message(filters.command("me") & filters.private)
async def me_cmd(_, msg: Message):
    u = msg.from_user
    await db.ensure_user(u.id, u.username)
    folder_id, expiry, private, files, size = await db.get_user(u.id)
    expiry = expiry or config.DEFAULT_EXPIRY_HOURS * 3600
    await msg.reply_text(
        f"<b>Your account</b>\n\n"
        f"<b>Name:</b> {u.first_name}\n<b>Username:</b> @{u.username or '-'}\n<b>ID:</b> <code>{u.id}</code>\n"
        f"<b>Gofile folder:</b> <code>{folder_label(u)}</code> (private)\n"
        f"<b>Folder ID:</b> <code>{folder_id or 'created on first upload'}</code>\n"
        f"<b>Link expiry:</b> {fmt_dur(expiry)}\n<b>Password links:</b> {'on' if private else 'off'}\n"
        f"<b>Uploads:</b> {files} ({human(size)})")


@bot.on_message(filters.command("status") & filters.private)
async def status_cmd(_, msg: Message):
    s = await web.snapshot()
    await msg.reply_text(
        f"<b>Status:</b> {s['status']}\n<b>Uptime:</b> {s['uptime']}\n"
        f"<b>Active transfers:</b> {s['active_jobs']}\n<b>Users:</b> {s['users']}\n"
        f"<b>Files:</b> {s['files']} ({s['size_human']})\n"
        f"<b>Gofile:</b> {'connected' if s['backend_ok'] else 'unreachable'}\n"
        f"<b>Premium session:</b> {'on' if s['premium_session'] else 'off'}")


@bot.on_message(filters.command("myfiles") & filters.private)
async def myfiles_cmd(_, msg: Message):
    rows = await db.list_files(msg.from_user.id, 10)
    if not rows:
        return await msg.reply_text("No uploads yet. Send me a file!")
    out = []
    for fid, name, size, link, expires, deleted in rows:
        state = "deleted" if deleted else fmt_left(expires)
        out.append(f"• <a href=\"{link}\">{name}</a> ({human(size)})\n   expires {fmt_dt(expires)} · {state}")
    await msg.reply_text("<b>Your latest files</b>\n\n" + "\n".join(out), disable_web_page_preview=True)


@bot.on_callback_query(filters.regex(r"^del:(\d+)$"))
async def delete_cb(_, cq: CallbackQuery):
    fid = int(cq.matches[0].group(1))
    row = await db.get_file(fid, cq.from_user.id)
    if not row or row[10]:
        return await cq.answer("Already deleted or not yours.", show_alert=True)
    try:
        await gofile.delete(row[6])
    except Exception as e:
        return await cq.answer(f"Delete failed: {e}", show_alert=True)
    await db.mark_deleted(fid)
    await cq.message.edit_text(f"Deleted <code>{row[1]}</code> from Gofile.")
    await cq.answer("Deleted")


async def fetch_large_via_user(msg: Message, dest: str):
    """Owner-only: >2GB files are pulled with the Premium user session."""
    me = await bot.get_me()
    _, media = media_of(msg)
    async for m in user_client.get_chat_history(me.username, limit=20):
        _, um = media_of(m)
        if um and um.file_unique_id == media.file_unique_id:
            return await user_client.download_media(m, file_name=dest)
    raise RuntimeError("Couldn't find the file in the owner's chat with the bot.")


@bot.on_message(
    (filters.document | filters.video | filters.audio | filters.voice
     | filters.animation | filters.video_note | filters.photo) & filters.private
)
async def handle_file(_, msg: Message):
    u = msg.from_user
    if not gofile.enabled():
        return await msg.reply_text("Gofile isn't configured. The owner must set GOFILE_TOKEN.")
    await db.ensure_user(u.id, u.username)

    kind, media = media_of(msg)
    size = getattr(media, "file_size", 0) or 0
    name = safe_name(getattr(media, "file_name", None) or f"{kind}_{msg.id}")
    if "." not in name:
        name += mimetypes.guess_extension(getattr(media, "mime_type", "") or "") or (".jpg" if kind == "photo" else "")
    use_user = False
    if size > config.BOT_MAX_SIZE:
        if user_client and u.id == config.OWNER_ID and size <= config.PREMIUM_MAX_SIZE:
            use_user = True
        else:
            return await msg.reply_text(
                f"File is {human(size)}. Limit is {human(config.BOT_MAX_SIZE)} for bots "
                f"(4 GB needs the owner's Premium session).")

    _, expiry_secs, private, _, _ = await db.get_user(u.id)
    expiry_secs = expiry_secs or config.DEFAULT_EXPIRY_HOURS * 3600

    status = await msg.reply_text("Starting...")
    work_dir = os.path.join(config.DOWNLOAD_DIR, uuid.uuid4().hex)
    os.makedirs(work_dir, exist_ok=True)
    dest = os.path.join(work_dir, name)
    job_id = uuid.uuid4().hex
    job = {"stage": "Queued", "pct": 0}
    web.state["jobs"][job_id] = job
    share_folder = None
    try:
        if use_user:
            await status.edit_text("Downloading via Premium session...")
            path = await fetch_large_via_user(msg, dest)
        else:
            path = await msg.download(file_name=dest, progress=make_progress(status, "Downloading from Telegram", job))
        real_size = os.path.getsize(path)

        await status.edit_text("Preparing your private folder...")
        parent = await user_folder(u)
        # each upload gets its own sub-folder so it can have its own expiry/password
        share_folder = await gofile.create_folder(parent, f"{int(time.time())}_{name}"[:100])
        expires = int(time.time()) + expiry_secs
        password = secrets.token_urlsafe(6) if private else None
        await gofile.update(share_folder["id"], "expiry", expires)
        if password:
            await gofile.update(share_folder["id"], "password", password)
        await gofile.update(share_folder["id"], "public", True)  # reachable by link only; parent stays private

        data = await gofile.upload(path, name, share_folder["id"], make_progress(status, "Uploading to Gofile", job))
        code = share_folder.get("code") or data.get("parentFolderCode")
        link = data.get("downloadPage") or f"https://gofile.io/d/{code}"
        md5 = data.get("md5")
        mime = data.get("mimetype") or mimetypes.guess_type(name)[0]

        fid = await db.add_file(u.id, name, real_size, mime, md5, link, share_folder["id"], password, expires)
        await db.add_usage(u.id, real_size)
        await status.edit_text(
            details_text(name, real_size, mime, md5, link, time.time(), expires, password, folder_label(u)),
            reply_markup=buttons(link, name, fid), disable_web_page_preview=True)
    except Exception as e:
        web.state["errors"] += 1
        log.exception("handler failed")
        if share_folder:  # don't leave empty orphan folders behind
            try:
                await gofile.delete(share_folder["id"])
            except Exception:
                pass
        await status.edit_text(f"Upload failed: {e}")
    finally:
        web.state["jobs"].pop(job_id, None)
        try:
            for f in os.listdir(work_dir):
                os.remove(os.path.join(work_dir, f))
            os.rmdir(work_dir)
        except Exception:
            pass


async def start_with_retry(client, name):
    """Telegram sometimes returns 500s on login; wait and retry instead of crashing."""
    delay = 10
    while True:
        try:
            await client.start()
            return
        except FloodWait as e:
            wait = int(e.value) + 5
            log.warning("%s: FloodWait, sleeping %ss", name, wait)
            await asyncio.sleep(wait)
        except (InternalServerError, ConnectionError, TimeoutError, OSError) as e:
            log.warning("%s: Telegram login failed (%s). Retrying in %ss", name, e, delay)
            try:
                await client.disconnect()
            except Exception:
                pass
            await asyncio.sleep(delay)
            delay = min(delay * 2, 300)
        except RPCError:
            raise  # bad token / api id etc: retrying won't help


def check_credentials():
    """Log clear errors for malformed Telegram credentials before trying to log in."""
    problems = []
    if config.API_ID <= 0:
        problems.append("API_ID is missing or not a number")
    if not re.fullmatch(r"[0-9a-fA-F]{32}", config.API_HASH):
        problems.append("API_HASH should be 32 hex characters")
    if not re.fullmatch(r"\d{6,}:[A-Za-z0-9_-]{30,}", config.BOT_TOKEN):
        problems.append("BOT_TOKEN doesn't look like 123456:ABC... (copy the whole token from @BotFather)")
    for p in problems:
        log.error("CONFIG PROBLEM: %s", p)
    return not problems


async def main():
    check_credentials()
    runner = await web.start_web()
    await start_with_retry(bot, "bot")
    web.state["bot_connected"] = True
    if user_client:
        await start_with_retry(user_client, "user")
        web.state["user_connected"] = True
    log.info("Bot started")
    try:
        await idle()
    finally:
        web.state["bot_connected"] = False
        await bot.stop()
        if user_client:
            await user_client.stop()
        await runner.cleanup()


if __name__ == "__main__":
    asyncio.get_event_loop().run_until_complete(main())

import asyncio
import os
import sqlite3
import time

import config

os.makedirs(os.path.dirname(config.DB_PATH) or ".", exist_ok=True)
_conn = sqlite3.connect(config.DB_PATH, check_same_thread=False)
_lock = asyncio.Lock()
_conn.executescript(
    """
    CREATE TABLE IF NOT EXISTS users (
        user_id INTEGER PRIMARY KEY,
        username TEXT,
        folder_id TEXT,
        expiry_secs INTEGER,
        private INTEGER DEFAULT 0,
        files INTEGER DEFAULT 0,
        bytes INTEGER DEFAULT 0
    );
    CREATE TABLE IF NOT EXISTS files (
        id INTEGER PRIMARY KEY AUTOINCREMENT,
        user_id INTEGER,
        name TEXT,
        size INTEGER,
        mime TEXT,
        md5 TEXT,
        link TEXT,
        folder_id TEXT,
        password TEXT,
        created REAL,
        expires REAL,
        deleted INTEGER DEFAULT 0
    );
    """
)
_conn.commit()


async def _run(sql, args=(), fetch=False):
    async with _lock:
        def work():
            cur = _conn.execute(sql, args)
            rows = cur.fetchall() if fetch else None
            lastid = cur.lastrowid
            _conn.commit()
            return rows if fetch else lastid
        return await asyncio.to_thread(work)


async def ensure_user(user_id, username):
    await _run(
        "INSERT INTO users(user_id, username) VALUES(?, ?) "
        "ON CONFLICT(user_id) DO UPDATE SET username=excluded.username",
        (user_id, username),
    )


async def get_user(user_id):
    rows = await _run(
        "SELECT folder_id, expiry_secs, private, files, bytes FROM users WHERE user_id=?",
        (user_id,), fetch=True,
    )
    return rows[0] if rows else (None, None, 0, 0, 0)


async def set_folder(user_id, folder_id):
    await _run("UPDATE users SET folder_id=? WHERE user_id=?", (folder_id, user_id))


async def set_expiry(user_id, secs):
    await _run("UPDATE users SET expiry_secs=? WHERE user_id=?", (secs, user_id))


async def set_private(user_id, flag):
    await _run("UPDATE users SET private=? WHERE user_id=?", (1 if flag else 0, user_id))


async def add_usage(user_id, size):
    await _run("UPDATE users SET files=files+1, bytes=bytes+? WHERE user_id=?", (size, user_id))


async def totals():
    rows = await _run(
        "SELECT COUNT(*), COALESCE(SUM(files),0), COALESCE(SUM(bytes),0) FROM users", fetch=True
    )
    return rows[0]


async def add_file(user_id, name, size, mime, md5, link, folder_id, password, expires):
    return await _run(
        "INSERT INTO files(user_id,name,size,mime,md5,link,folder_id,password,created,expires) "
        "VALUES(?,?,?,?,?,?,?,?,?,?)",
        (user_id, name, size, mime, md5, link, folder_id, password, time.time(), expires),
    )


async def get_file(file_id, user_id):
    rows = await _run(
        "SELECT id,name,size,mime,md5,link,folder_id,password,created,expires,deleted "
        "FROM files WHERE id=? AND user_id=?",
        (file_id, user_id), fetch=True,
    )
    return rows[0] if rows else None


async def list_files(user_id, limit=10):
    return await _run(
        "SELECT id,name,size,link,expires,deleted FROM files WHERE user_id=? "
        "ORDER BY created DESC LIMIT ?",
        (user_id, limit), fetch=True,
    )


async def mark_deleted(file_id):
    await _run("UPDATE files SET deleted=1 WHERE id=?", (file_id,))

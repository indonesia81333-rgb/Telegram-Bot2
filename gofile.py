"""Minimal async Gofile client: user folders, expiring/private share folders, uploads."""
import asyncio
import io
import time

import aiohttp

import config


class GofileError(Exception):
    pass


_root = {"id": config.GOFILE_ROOT_FOLDER_ID or None}


def enabled():
    return bool(config.GOFILE_TOKEN)


def _headers():
    return {"Authorization": f"Bearer {config.GOFILE_TOKEN}"}


def _check(payload, http_status):
    if not isinstance(payload, dict) or payload.get("status") != "ok":
        status = payload.get("status") if isinstance(payload, dict) else f"http-{http_status}"
        raise GofileError(f"Gofile error: {status}")
    return payload.get("data") or {}


async def _api(method, path, json=None, params=None):
    url = config.GOFILE_API + path
    timeout = aiohttp.ClientTimeout(total=60)
    async with aiohttp.ClientSession(timeout=timeout, headers=_headers()) as s:
        async with s.request(method, url, json=json, params=params) as r:
            try:
                payload = await r.json(content_type=None)
            except Exception:
                raise GofileError(f"Gofile returned an unreadable response (HTTP {r.status})")
            return _check(payload, r.status)


async def root_folder():
    if _root["id"]:
        return _root["id"]
    acc = await _api("GET", "/accounts/getid")
    info = await _api("GET", f"/accounts/{acc['id']}")
    rid = info.get("rootFolder") or info.get("rootfolder")
    if not rid:
        raise GofileError("Could not find the account's root folder.")
    _root["id"] = rid
    return rid


async def create_folder(parent_id, name):
    return await _api("POST", "/contents/createFolder", json={"parentFolderId": parent_id, "folderName": name})


async def update(content_id, attribute, value):
    return await _api(
        "PUT", f"/contents/{content_id}/update", json={"attribute": attribute, "attributeValue": value}
    )


async def delete(content_id):
    return await _api("DELETE", "/contents", json={"contentsId": content_id})


async def check():
    """Dashboard health check: token valid and API reachable."""
    try:
        await _api("GET", "/accounts/getid")
        return True
    except Exception:
        return False


class _ProgressFile(io.BufferedReader):
    """File object that reports bytes read (aiohttp reads it in a worker thread)."""

    def __init__(self, path, cb):
        super().__init__(io.FileIO(path, "rb"), buffer_size=1024 * 1024)
        self._cb = cb

    def read(self, size=-1):
        data = super().read(size)
        if data:
            self._cb(len(data))
        return data


async def upload(path, filename, folder_id, progress_cb):
    """Stream a file to Gofile into folder_id. Returns the file's data dict."""
    total = max(1, __import__("os").path.getsize(path))
    loop = asyncio.get_running_loop()
    sent = [0]
    last = [0.0]

    def on_read(n):
        sent[0] += n
        now = time.time()
        if now - last[0] >= 1.5 or sent[0] >= total:
            last[0] = now
            asyncio.run_coroutine_threadsafe(progress_cb(min(sent[0], total), total), loop)

    timeout = aiohttp.ClientTimeout(total=None, sock_connect=30)
    fh = _ProgressFile(path, on_read)
    try:
        form = aiohttp.FormData()
        form.add_field("folderId", folder_id)
        form.add_field("file", fh, filename=filename, content_type="application/octet-stream")
        async with aiohttp.ClientSession(timeout=timeout, headers=_headers()) as s:
            async with s.post(config.GOFILE_UPLOAD_URL, data=form) as r:
                try:
                    payload = await r.json(content_type=None)
                except Exception:
                    raise GofileError(f"Upload response unreadable (HTTP {r.status})")
                return _check(payload, r.status)
    finally:
        fh.close()

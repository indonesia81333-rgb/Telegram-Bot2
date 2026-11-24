import asyncio
import time
from datetime import datetime, timezone

import aiohttp
from aiohttp import web

import config
import db
import gofile

STARTED = time.time()
state = {"bot_connected": False, "user_connected": False, "jobs": {}, "errors": 0}
_health = {"at": 0.0, "ok": False}


def fmt_uptime(sec):
    sec = int(sec)
    d, sec = divmod(sec, 86400)
    h, sec = divmod(sec, 3600)
    m, s = divmod(sec, 60)
    return f"{d}d {h}h {m}m {s}s"


def fmt_size(n):
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{n:.2f} {unit}"
        n /= 1024
    return f"{n:.2f} PB"


async def backend_ok():
    # cache the Gofile check so a 3-second dashboard poll doesn't hammer the backend
    if time.time() - _health["at"] > 60:
        _health["at"] = time.time()
        _health["ok"] = gofile.enabled() and await gofile.check()
    return _health["ok"]


async def snapshot():
    users, files, size = await db.totals()
    jobs = [
        # file names are deliberately not exposed on the public dashboard
        {"label": f"Transfer #{i + 1}", "stage": j.get("stage", ""), "pct": j.get("pct", 0)}
        for i, j in enumerate(list(state["jobs"].values()))
    ]
    return {
        "status": "running" if state["bot_connected"] else "connecting",
        "uptime_seconds": int(time.time() - STARTED),
        "uptime": fmt_uptime(time.time() - STARTED),
        "started": datetime.fromtimestamp(STARTED, timezone.utc).strftime("%Y-%m-%d %H:%M UTC"),
        "backend": "gofile",
        "backend_ok": await backend_ok(),
        "premium_session": state["user_connected"],
        "active_jobs": len(jobs),
        "jobs": jobs,
        "errors": state["errors"],
        "users": users,
        "files": files,
        "bytes": size,
        "size_human": fmt_size(size),
    }


PAGE = r"""<!doctype html><html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width,initial-scale=1"><title>Cloud Upload Bot</title>
<style>
:root{--bg:#07080d;--card:rgba(255,255,255,.045);--line:rgba(255,255,255,.09);--tx:#eef0f6;--mu:#8a91a5;--ok:#34d399;--bad:#fb7185;--a:#7c5cff;--b:#22d3ee}
*{box-sizing:border-box}body{margin:0;min-height:100vh;background:var(--bg);color:var(--tx);font-family:Inter,system-ui,sans-serif;overflow-x:hidden}
.blob{position:fixed;width:46vmax;height:46vmax;border-radius:50%;filter:blur(90px);opacity:.28;z-index:0;animation:float 18s ease-in-out infinite}
.b1{background:var(--a);top:-18vmax;left:-12vmax}.b2{background:var(--b);bottom:-20vmax;right:-14vmax;animation-delay:-9s}
@keyframes float{50%{transform:translate(6vmax,4vmax) scale(1.12)}}
.wrap{position:relative;z-index:1;max-width:880px;margin:0 auto;padding:40px 20px 60px}
header{display:flex;align-items:center;justify-content:space-between;gap:12px;flex-wrap:wrap;margin-bottom:28px;animation:rise .7s both}
h1{font-size:26px;margin:0;letter-spacing:-.02em;background:linear-gradient(90deg,#fff,#b9a8ff 60%,#7ee8fa);-webkit-background-clip:text;color:transparent}
.pill{display:flex;align-items:center;gap:8px;padding:8px 14px;border-radius:99px;background:var(--card);border:1px solid var(--line);font-size:13px;backdrop-filter:blur(12px)}
.dot{width:9px;height:9px;border-radius:50%;background:var(--bad);position:relative}
.dot.ok{background:var(--ok)}.dot.ok::after{content:"";position:absolute;inset:-5px;border-radius:50%;border:2px solid var(--ok);animation:ping 1.8s ease-out infinite}
@keyframes ping{from{transform:scale(.5);opacity:.9}to{transform:scale(1.6);opacity:0}}
.grid{display:grid;grid-template-columns:repeat(auto-fit,minmax(190px,1fr));gap:14px}
.card{background:var(--card);border:1px solid var(--line);border-radius:18px;padding:18px;backdrop-filter:blur(14px);transition:transform .25s,border-color .25s;animation:rise .7s both}
.card:hover{transform:translateY(-4px);border-color:rgba(124,92,255,.5)}
.k{font-size:11px;letter-spacing:.09em;text-transform:uppercase;color:var(--mu)}.v{font-size:24px;font-weight:600;margin-top:8px;font-variant-numeric:tabular-nums}
.v.sm{font-size:15px;line-height:1.5}.ok{color:var(--ok)}.bad{color:var(--bad)}
h2{font-size:15px;color:var(--mu);font-weight:500;margin:34px 0 12px}
.job{background:var(--card);border:1px solid var(--line);border-radius:14px;padding:14px 16px;margin-bottom:10px;animation:rise .4s both}
.jh{display:flex;justify-content:space-between;font-size:13px;margin-bottom:10px}
.track{height:8px;background:rgba(255,255,255,.08);border-radius:9px;overflow:hidden}
.fill{height:100%;border-radius:9px;background:linear-gradient(90deg,var(--a),var(--b));position:relative;transition:width .8s cubic-bezier(.2,.8,.2,1)}
.fill::after{content:"";position:absolute;inset:0;background:linear-gradient(110deg,transparent 30%,rgba(255,255,255,.45),transparent 70%);background-size:200% 100%;animation:shimmer 1.4s linear infinite}
@keyframes shimmer{from{background-position:200% 0}to{background-position:-200% 0}}
.empty{color:var(--mu);font-size:14px;padding:18px;border:1px dashed var(--line);border-radius:14px;text-align:center}
@keyframes rise{from{opacity:0;transform:translateY(14px)}to{opacity:1;transform:none}}
@media (prefers-reduced-motion:reduce){*{animation:none!important;transition:none!important}}
</style></head><body><div class="blob b1"></div><div class="blob b2"></div>
<div class="wrap">
<header><h1>Cloud Upload Bot</h1><div class="pill"><span class="dot" id="dot"></span><span id="status">connecting</span></div></header>
<div class="grid">
<div class="card" style="animation-delay:.05s"><div class="k">Uptime</div><div class="v" id="uptime">-</div></div>
<div class="card" style="animation-delay:.1s"><div class="k">Storage</div><div class="v sm" id="backend">-</div></div>
<div class="card" style="animation-delay:.15s"><div class="k">Active transfers</div><div class="v" id="active">0</div></div>
<div class="card" style="animation-delay:.2s"><div class="k">Users</div><div class="v" id="users">0</div></div>
<div class="card" style="animation-delay:.25s"><div class="k">Files</div><div class="v" id="files">0</div></div>
<div class="card" style="animation-delay:.3s"><div class="k">Data transferred</div><div class="v" id="size">-</div></div>
<div class="card" style="animation-delay:.35s"><div class="k">4 GB session</div><div class="v sm" id="prem">-</div></div>
<div class="card" style="animation-delay:.4s"><div class="k">Started</div><div class="v sm" id="started">-</div></div>
</div>
<h2>Live transfers</h2><div id="jobs"><div class="empty">No active transfers</div></div>
</div>
<script>
const $=id=>document.getElementById(id);
let up=0,t0=Date.now();
function fmt(s){s=Math.floor(s);const d=Math.floor(s/86400),h=Math.floor(s%86400/3600),m=Math.floor(s%3600/60);return `${d}d ${h}h ${m}m ${s%60}s`}
setInterval(()=>{if(up)$("uptime").textContent=fmt(up+(Date.now()-t0)/1000)},1000);
function tween(el,to){const from=parseInt(el.dataset.n||"0");el.dataset.n=to;const s=performance.now();
 (function f(t){const p=Math.min((t-s)/600,1);el.textContent=Math.round(from+(to-from)*(1-Math.pow(1-p,3)));if(p<1)requestAnimationFrame(f)})(s)}
async function tick(){
 try{const r=await fetch("/api/status");const s=await r.json();
  up=s.uptime_seconds;t0=Date.now();
  const run=s.status==="running";$("dot").className="dot"+(run?" ok":"");$("status").textContent=run?"Online":"Connecting";
  $("backend").innerHTML=s.backend.charAt(0).toUpperCase()+s.backend.slice(1)+` <span class="${s.backend_ok?"ok":"bad"}">${s.backend_ok?"connected":"unreachable"}</span>`;
  tween($("active"),s.active_jobs);tween($("users"),s.users);tween($("files"),s.files);
  $("size").textContent=s.size_human;$("prem").textContent=s.premium_session?"Active":"Off";$("started").textContent=s.started;
  $("jobs").innerHTML=s.jobs.length?s.jobs.map(j=>`<div class="job"><div class="jh"><span>${j.label} · ${j.stage}</span><span>${Math.round(j.pct)}%</span></div><div class="track"><div class="fill" style="width:${j.pct}%"></div></div></div>`).join(""):'<div class="empty">No active transfers</div>';
 }catch(e){$("dot").className="dot";$("status").textContent="Offline"}
}
tick();setInterval(tick,3000);
</script></body></html>"""


async def index(request):
    return web.Response(text=PAGE, content_type="text/html")


async def api_status(request):
    return web.json_response(await snapshot())


async def health(request):
    return web.Response(text="ok")


async def keep_alive():
    """Self-ping so Render-style hosts that sleep on idle stay awake."""
    if not config.APP_URL:
        return
    while True:
        await asyncio.sleep(600)
        try:
            async with aiohttp.ClientSession(timeout=aiohttp.ClientTimeout(total=15)) as s:
                await s.get(config.APP_URL.rstrip("/") + "/health")
        except Exception:
            pass


async def start_web():
    app = web.Application()
    app.add_routes([
        web.get("/", index),
        web.get("/api/status", api_status),
        web.get("/health", health),
    ])
    runner = web.AppRunner(app)
    await runner.setup()
    await web.TCPSite(runner, "0.0.0.0", config.PORT).start()
    asyncio.create_task(keep_alive())
    return runner

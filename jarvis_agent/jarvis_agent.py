"""
JARVIS Local Helper Agent
=========================
A tiny FastAPI server that JARVIS (the web UI) calls to actually control
your computer. It runs ENTIRELY on your machine — nothing is sent to the
cloud beyond what JARVIS itself decides.

⚠️  SECURITY WARNING ⚠️
This agent will execute ANY shell command the web UI tells it to. Only run it
on a machine you trust, only while you're using JARVIS, and never expose port
7337 to the public internet. By default it binds to 127.0.0.1 only.

Setup
-----
1. pip install fastapi uvicorn
2. python jarvis_agent.py
3. Leave it running. Open the JARVIS web app — the "LOCAL AGENT" indicator
   should turn cyan.

Optional: set JARVIS_TOKEN env var to require an auth header (future).
"""

import os
import sys
import shutil
import platform
import subprocess
import threading
import webbrowser
from pathlib import Path

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from pydantic import BaseModel

# ---- Browser cowork (Playwright) ----
# Lazy-imported so the agent still runs if Playwright isn't installed yet.
_browser_lock = threading.Lock()
_browser_state = {
    "playwright": None,
    "browser": None,
    "context": None,
    "page": None,
}

CURSOR_OVERLAY_JS = r"""
(() => {
  if (window.__jarvisCursor) return;
  const c = document.createElement('div');
  c.id = '__jarvis_cursor';
  c.style.cssText = [
    'position:fixed','left:-100px','top:-100px','width:22px','height:22px',
    'border-radius:50%','background:radial-gradient(circle,#ff2a2a 0%,#ff0000 50%,rgba(255,0,0,0) 80%)',
    'box-shadow:0 0 18px 6px rgba(255,40,40,0.85),0 0 40px 12px rgba(255,0,0,0.45)',
    'pointer-events:none','z-index:2147483647','transition:left 120ms linear,top 120ms linear',
    'border:2px solid #fff'
  ].join(';');
  const label = document.createElement('div');
  label.textContent = 'JARVIS';
  label.style.cssText = 'position:absolute;left:26px;top:6px;font:bold 10px monospace;color:#fff;text-shadow:0 0 4px #ff0000;letter-spacing:2px;';
  c.appendChild(label);
  document.documentElement.appendChild(c);
  window.__jarvisCursor = c;
  window.__jarvisMove = (x,y) => { c.style.left = (x-11)+'px'; c.style.top = (y-11)+'px'; };
  window.__jarvisFlash = () => {
    c.animate([{transform:'scale(1)'},{transform:'scale(1.8)'},{transform:'scale(1)'}],{duration:300});
  };
})();
"""

def _ensure_browser(headless: bool = False):
    """Start Chromium (once) and return the active page."""
    with _browser_lock:
        if _browser_state["page"] is not None:
            try:
                # Cheap liveness check
                _ = _browser_state["page"].url
                return _browser_state["page"]
            except Exception:
                _browser_state["page"] = None

        try:
            from playwright.sync_api import sync_playwright
        except ImportError:
            raise HTTPException(500, "Playwright not installed. Run: pip install playwright && playwright install chromium")

        pw = sync_playwright().start()
        browser = pw.chromium.launch(headless=headless, args=["--start-maximized"])
        context = browser.new_context(no_viewport=True)
        page = context.new_page()
        page.goto("about:blank")
        # Re-inject cursor on every navigation
        context.add_init_script(CURSOR_OVERLAY_JS)
        try:
            page.evaluate(CURSOR_OVERLAY_JS)
        except Exception:
            pass
        _browser_state.update({"playwright": pw, "browser": browser, "context": context, "page": page})
        return page


def _move_cursor(page, x: float, y: float):
    try:
        page.evaluate("([x,y]) => window.__jarvisMove && window.__jarvisMove(x,y)", [x, y])
    except Exception:
        pass


def _flash_cursor(page):
    try:
        page.evaluate("() => window.__jarvisFlash && window.__jarvisFlash()")
    except Exception:
        pass

app = FastAPI(title="JARVIS Local Agent")

# CORS — allow the web UI to call us from any origin (you control the browser).
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# Chrome's Private Network Access requires these headers so an HTTPS page
# (the JARVIS web UI) is allowed to call http://127.0.0.1 / localhost.
@app.middleware("http")
async def private_network_access(request: Request, call_next):
    if request.method == "OPTIONS":
        resp = Response(status_code=204)
    else:
        resp = await call_next(request)
    resp.headers["Access-Control-Allow-Private-Network"] = "true"
    resp.headers["Access-Control-Allow-Origin"] = "*"
    resp.headers["Access-Control-Allow-Methods"] = "*"
    resp.headers["Access-Control-Allow-Headers"] = "*"
    resp.headers["Access-Control-Max-Age"] = "86400"
    return resp

IS_WIN = platform.system() == "Windows"
IS_MAC = platform.system() == "Darwin"


class RunCmd(BaseModel):
    command: str
    cwd: str | None = None


class PathArg(BaseModel):
    path: str


class UrlArg(BaseModel):
    url: str


class SearchArg(BaseModel):
    root: str
    query: str


class WriteArg(BaseModel):
    path: str
    content: str


@app.get("/health")
def health():
    return {"ok": True, "os": platform.system(), "release": platform.release()}


@app.post("/tool/run_command")
def run_command(arg: RunCmd):
    try:
        # shell=True so users can pipe / chain like a real terminal
        result = subprocess.run(
            arg.command,
            shell=True,
            cwd=arg.cwd or None,
            capture_output=True,
            text=True,
            timeout=120,
        )
        out = (result.stdout or "") + (("\n[stderr]\n" + result.stderr) if result.stderr else "")
        return {
            "exit_code": result.returncode,
            "output": out[-8000:] or "(no output)",
        }
    except subprocess.TimeoutExpired:
        raise HTTPException(408, "Command timed out after 120s")
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/tool/open_path")
def open_path(arg: PathArg):
    p = Path(arg.path).expanduser()
    try:
        if IS_WIN:
            os.startfile(str(p))  # type: ignore[attr-defined]
        elif IS_MAC:
            subprocess.Popen(["open", str(p)])
        else:
            subprocess.Popen(["xdg-open", str(p)])
        return {"ok": True, "opened": str(p)}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/tool/open_url")
def open_url(arg: UrlArg):
    webbrowser.open(arg.url)
    return {"ok": True, "opened": arg.url}


@app.post("/tool/list_dir")
def list_dir(arg: PathArg):
    p = Path(arg.path).expanduser()
    if not p.exists():
        raise HTTPException(404, f"Not found: {p}")
    items = []
    for child in sorted(p.iterdir()):
        items.append({
            "name": child.name,
            "type": "dir" if child.is_dir() else "file",
            "size": child.stat().st_size if child.is_file() else None,
        })
    return {"path": str(p), "items": items}


@app.post("/tool/search_files")
def search_files(arg: SearchArg):
    root = Path(arg.root).expanduser()
    if not root.exists():
        raise HTTPException(404, f"Not found: {root}")
    q = arg.query.lower()
    matches = []
    for p in root.rglob("*"):
        try:
            if q in p.name.lower():
                matches.append(str(p))
                if len(matches) >= 100:
                    break
        except Exception:
            continue
    return {"root": str(root), "query": arg.query, "matches": matches}


@app.post("/tool/read_file")
def read_file(arg: PathArg):
    p = Path(arg.path).expanduser()
    if not p.exists():
        raise HTTPException(404, f"Not found: {p}")
    try:
        text = p.read_text(encoding="utf-8", errors="replace")
        return {"path": str(p), "content": text[:50000]}
    except Exception as e:
        raise HTTPException(500, str(e))


@app.post("/tool/write_file")
def write_file(arg: WriteArg):
    p = Path(arg.path).expanduser()
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(arg.content, encoding="utf-8")
    return {"ok": True, "path": str(p), "bytes": len(arg.content)}


@app.post("/tool/system_info")
def system_info():
    info = {
        "os": platform.system(),
        "release": platform.release(),
        "version": platform.version(),
        "machine": platform.machine(),
        "python": sys.version.split()[0],
        "cwd": os.getcwd(),
        "user": os.environ.get("USER") or os.environ.get("USERNAME"),
    }
    # Optional: psutil for richer info
    try:
        import psutil  # type: ignore
        info["cpu_percent"] = psutil.cpu_percent(interval=0.1)
        info["cpu_count"] = psutil.cpu_count()
        mem = psutil.virtual_memory()
        info["ram_total_gb"] = round(mem.total / 1e9, 2)
        info["ram_used_pct"] = mem.percent
        disk = psutil.disk_usage("/")
        info["disk_total_gb"] = round(disk.total / 1e9, 2)
        info["disk_used_pct"] = disk.percent
    except ImportError:
        info["note"] = "Install `psutil` for CPU/RAM/disk metrics."
    return info


if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  J.A.R.V.I.S. Local Agent")
    print("  Listening on http://127.0.0.1:7337")
    print("  Keep this window open while using the JARVIS web UI.")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=7337, log_level="info")

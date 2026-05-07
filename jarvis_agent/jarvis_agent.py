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

def _run_current_python_module(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a Python module using the exact interpreter that launched this agent."""
    return subprocess.run(
        [sys.executable, "-m", *args],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _import_sync_playwright():
    """Import Playwright, installing the Python package into this interpreter if needed."""
    try:
        from playwright.sync_api import sync_playwright
        return sync_playwright
    except ImportError as first_error:
        install = _run_current_python_module("pip", "install", "playwright")
        if install.returncode != 0:
            raise HTTPException(
                500,
                "Playwright is not installed for the Python interpreter running this agent. "
                f"Agent Python: {sys.executable}\n"
                f"Install failed:\n{install.stdout}\n{install.stderr}\n"
                "Fix manually with:\n"
                f'"{sys.executable}" -m pip install playwright\n'
                f'"{sys.executable}" -m playwright install chromium',
            ) from first_error
        try:
            from playwright.sync_api import sync_playwright
            return sync_playwright
        except ImportError as second_error:
            raise HTTPException(
                500,
                "Playwright still cannot be imported by the agent after install. "
                f"Agent Python: {sys.executable}\n"
                "Fix manually with:\n"
                f'"{sys.executable}" -m pip install playwright\n'
                f'"{sys.executable}" -m playwright install chromium',
            ) from second_error

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

        sync_playwright = _import_sync_playwright()

        pw = sync_playwright().start()
        launch_errors = []
        try:
            browser = pw.chromium.launch(headless=headless, args=["--start-maximized"])
        except Exception as e:
            launch_errors.append(f"bundled Chromium failed: {e}")
            installed = _run_current_python_module("playwright", "install", "chromium")
            if installed.returncode == 0:
                try:
                    browser = pw.chromium.launch(headless=headless, args=["--start-maximized"])
                except Exception as retry_error:
                    launch_errors.append(f"bundled Chromium after install failed: {retry_error}")
                else:
                    context = browser.new_context(no_viewport=True)
                    page = context.new_page()
                    page.goto("about:blank")
                    context.add_init_script(CURSOR_OVERLAY_JS)
                    try:
                        page.evaluate(CURSOR_OVERLAY_JS)
                    except Exception:
                        pass
                    _browser_state.update({"playwright": pw, "browser": browser, "context": context, "page": page})
                    return page
            else:
                launch_errors.append(f"python -m playwright install chromium failed: {installed.stdout}\n{installed.stderr}")
            try:
                browser = pw.chromium.launch(channel="chrome", headless=headless, args=["--start-maximized"])
            except Exception as chrome_error:
                launch_errors.append(f"installed Chrome failed: {chrome_error}")
                try:
                    pw.stop()
                except Exception:
                    pass
                raise HTTPException(
                    500,
                    "Could not launch a browser. The agent uses this Python interpreter: "
                    f"{sys.executable}\n"
                    "Run these exact commands in the agent terminal, then restart jarvis_agent.py:\n"
                    f'"{sys.executable}" -m pip install playwright\n'
                    f'"{sys.executable}" -m playwright install chromium\n\n'
                    + "\n\n".join(launch_errors),
                )
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


# ===================== BROWSER COWORK =====================
class BrowserGoto(BaseModel):
    url: str

class BrowserClick(BaseModel):
    selector: str | None = None
    text: str | None = None

class BrowserType(BaseModel):
    selector: str
    text: str
    submit: bool = False

class BrowserScroll(BaseModel):
    dy: int = 400

class BrowserKey(BaseModel):
    key: str


@app.post("/tool/browser_open")
def browser_open():
    page = _ensure_browser(headless=False)
    return {"ok": True, "url": page.url, "title": page.title()}


@app.post("/tool/browser_goto")
def browser_goto(arg: BrowserGoto):
    page = _ensure_browser(headless=False)
    url = arg.url if "://" in arg.url else f"https://{arg.url}"
    page.goto(url, wait_until="domcontentloaded", timeout=30000)
    try:
        page.evaluate(CURSOR_OVERLAY_JS)
    except Exception:
        pass
    return {"ok": True, "url": page.url, "title": page.title()}


@app.post("/tool/browser_click")
def browser_click(arg: BrowserClick):
    page = _ensure_browser(headless=False)
    locator = page.locator(arg.selector) if arg.selector else page.get_by_text(arg.text or "", exact=False).first
    try:
        box = locator.bounding_box(timeout=5000)
        if box:
            cx, cy = box["x"] + box["width"] / 2, box["y"] + box["height"] / 2
            _move_cursor(page, cx, cy)
            page.wait_for_timeout(200)
            _flash_cursor(page)
        locator.click(timeout=5000)
        return {"ok": True, "clicked": arg.selector or arg.text}
    except Exception as e:
        raise HTTPException(500, f"Click failed: {e}")


@app.post("/tool/browser_type")
def browser_type(arg: BrowserType):
    page = _ensure_browser(headless=False)
    try:
        loc = page.locator(arg.selector)
        box = loc.bounding_box(timeout=5000)
        if box:
            _move_cursor(page, box["x"] + box["width"] / 2, box["y"] + box["height"] / 2)
            page.wait_for_timeout(150)
            _flash_cursor(page)
        loc.click(timeout=5000)
        loc.fill("")
        loc.type(arg.text, delay=30)
        if arg.submit:
            loc.press("Enter")
        return {"ok": True, "typed": arg.text, "into": arg.selector}
    except Exception as e:
        raise HTTPException(500, f"Type failed: {e}")


@app.post("/tool/browser_press")
def browser_press(arg: BrowserKey):
    page = _ensure_browser(headless=False)
    page.keyboard.press(arg.key)
    return {"ok": True, "pressed": arg.key}


@app.post("/tool/browser_scroll")
def browser_scroll(arg: BrowserScroll):
    page = _ensure_browser(headless=False)
    page.evaluate(f"window.scrollBy(0, {int(arg.dy)})")
    return {"ok": True, "dy": arg.dy}


@app.post("/tool/browser_read")
def browser_read():
    page = _ensure_browser(headless=False)
    try:
        return page.evaluate(r"""
() => {
  const text = (document.body.innerText || '').slice(0, 4000);
  const els = [];
  document.querySelectorAll('a,button,input,textarea,select,[role=button]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (r.width < 4 || r.height < 4) return;
    if (r.bottom < 0 || r.top > innerHeight + 200) return;
    els.push({
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0,80),
      id: el.id || null,
      name: el.getAttribute('name') || null,
      type: el.getAttribute('type') || null,
      selector: el.id ? '#' + CSS.escape(el.id) :
                el.getAttribute('name') ? `${el.tagName.toLowerCase()}[name="${el.getAttribute('name')}"]` : null,
    });
  });
  return { url: location.href, title: document.title, text, controls: els.slice(0, 60) };
}
""")
    except Exception as e:
        raise HTTPException(500, f"Read failed: {e}")


@app.post("/tool/browser_close")
def browser_close():
    with _browser_lock:
        try:
            if _browser_state["browser"]:
                _browser_state["browser"].close()
            if _browser_state["playwright"]:
                _browser_state["playwright"].stop()
        finally:
            _browser_state.update({"playwright": None, "browser": None, "context": None, "page": None})
    return {"ok": True}

if __name__ == "__main__":
    import uvicorn
    print("=" * 60)
    print("  J.A.R.V.I.S. Local Agent")
    print("  Listening on http://127.0.0.1:7337")
    print("  Browser cowork: ask JARVIS to 'open a browser and...'")
    print("  Keep this window open while using the JARVIS web UI.")
    print("=" * 60)
    uvicorn.run(app, host="127.0.0.1", port=7337, log_level="info")

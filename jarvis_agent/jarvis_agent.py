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

# ---- Browser cowork (Selenium / installed Chrome) ----
# Lazy-imported so the agent still runs if Selenium isn't installed yet.
_browser_lock = threading.Lock()
_browser_state = {
    "driver": None,
}


def _run_current_python_module(*args: str) -> subprocess.CompletedProcess[str]:
    """Run a Python module using the exact interpreter that launched this agent."""
    return subprocess.run(
        [sys.executable, "-m", *args],
        capture_output=True,
        text=True,
        timeout=180,
    )


def _import_selenium():
    """Import Selenium, installing it into this interpreter if needed."""
    try:
        from selenium import webdriver
        from selenium.webdriver.common.by import By
        from selenium.webdriver.common.keys import Keys
        from selenium.webdriver.common.action_chains import ActionChains
        from selenium.webdriver.support.ui import WebDriverWait
        from selenium.webdriver.support import expected_conditions as EC
        return webdriver, By, Keys, ActionChains, WebDriverWait, EC
    except ImportError as first_error:
        install = _run_current_python_module("pip", "install", "selenium")
        if install.returncode != 0:
            raise HTTPException(
                500,
                "Selenium is not installed for the Python interpreter running this agent. "
                f"Agent Python: {sys.executable}\n"
                f"Install failed:\n{install.stdout}\n{install.stderr}\n"
                "Fix manually with:\n"
                f'"{sys.executable}" -m pip install selenium',
            ) from first_error
        try:
            from selenium import webdriver
            from selenium.webdriver.common.by import By
            from selenium.webdriver.common.keys import Keys
            from selenium.webdriver.common.action_chains import ActionChains
            from selenium.webdriver.support.ui import WebDriverWait
            from selenium.webdriver.support import expected_conditions as EC
            return webdriver, By, Keys, ActionChains, WebDriverWait, EC
        except ImportError as second_error:
            raise HTTPException(
                500,
                "Selenium still cannot be imported by the agent after install. "
                f"Agent Python: {sys.executable}\n"
                "Fix manually with:\n"
                f'"{sys.executable}" -m pip install selenium',
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
    """Start installed Chrome through Selenium (once) and return the driver."""
    with _browser_lock:
        driver = _browser_state.get("driver")
        if driver is not None:
            try:
                _ = driver.current_url
                _inject_cursor(driver)
                return driver
            except Exception:
                _browser_state["driver"] = None

        webdriver, _By, _Keys, _ActionChains, _WebDriverWait, _EC = _import_selenium()
        options = webdriver.ChromeOptions()
        if headless:
            options.add_argument("--headless=new")
        options.add_argument("--start-maximized")
        options.add_argument("--disable-infobars")
        options.add_experimental_option("excludeSwitches", ["enable-automation"])
        options.add_experimental_option("useAutomationExtension", False)

        launch_errors = []
        try:
            driver = webdriver.Chrome(options=options)
        except Exception as chrome_error:
            launch_errors.append(f"installed Chrome via Selenium failed: {chrome_error}")
            try:
                edge_options = webdriver.EdgeOptions()
                if headless:
                    edge_options.add_argument("--headless=new")
                edge_options.add_argument("--start-maximized")
                driver = webdriver.Edge(options=edge_options)
            except Exception as edge_error:
                launch_errors.append(f"Edge fallback via Selenium failed: {edge_error}")
                raise HTTPException(
                    500,
                    "Could not launch Chrome with Selenium. Make sure normal Google Chrome is installed, then run:\n"
                    f'"{sys.executable}" -m pip install --upgrade selenium\n\n'
                    + "\n\n".join(launch_errors),
                )

        driver.get("about:blank")
        _inject_cursor(driver)
        _browser_state["driver"] = driver
        return driver


def _inject_cursor(driver):
    try:
        driver.execute_script(CURSOR_OVERLAY_JS)
    except Exception:
        pass


def _move_cursor(driver, x: float, y: float):
    try:
        _inject_cursor(driver)
        driver.execute_script("window.__jarvisMove && window.__jarvisMove(arguments[0], arguments[1])", float(x), float(y))
    except Exception:
        pass


def _flash_cursor(driver):
    try:
        _inject_cursor(driver)
        driver.execute_script("window.__jarvisFlash && window.__jarvisFlash()")
    except Exception:
        pass


def _xpath_literal(value: str) -> str:
    if '"' not in value:
        return f'"{value}"'
    if "'" not in value:
        return f"'{value}'"
    return "concat(" + ", '\"', ".join(f'"{part}"' for part in value.split('"')) + ")"


def _find_element(driver, selector: str | None = None, text: str | None = None, clickable: bool = False, nth: int = 0):
    _webdriver, By, _Keys, _ActionChains, WebDriverWait, EC = _import_selenium()
    wait = WebDriverWait(driver, 8)
    if selector:
        elements = wait.until(lambda d: d.find_elements(By.CSS_SELECTOR, selector) or False)
    else:
        needle = _xpath_literal(text or "")
        # Broaden: any element (links, headings, divs that wrap result titles, etc.)
        xpath = (
            f"//*[(self::a or self::button or self::input or self::textarea or self::select "
            f"or self::h1 or self::h2 or self::h3 or self::span or self::div or @role='button' or @role='link') "
            f"and (contains(normalize-space(.), {needle}) or contains(@value, {needle}) "
            f"or contains(@placeholder, {needle}) or contains(@aria-label, {needle}) or contains(@title, {needle}))]"
        )
        elements = wait.until(lambda d: d.find_elements(By.XPATH, xpath) or False)

    # Filter to visible elements
    visible = []
    for el in elements:
        try:
            rect = el.rect
            if rect.get("width", 0) >= 2 and rect.get("height", 0) >= 2 and el.is_displayed():
                visible.append(el)
        except Exception:
            continue
    if not visible:
        visible = elements

    # When matching by text, prefer the most specific (smallest) matching element,
    # and when many siblings match, pick the nth distinct clickable ancestor link.
    if text and not selector:
        # Sort by depth (deepest first) so we prefer the inner result title over wrapping containers
        def depth(el):
            try:
                return driver.execute_script(
                    "let n=arguments[0],d=0;while(n.parentElement){d++;n=n.parentElement;}return d;", el
                )
            except Exception:
                return 0
        visible.sort(key=depth, reverse=True)
        # Walk up to nearest <a> or [role=link]/[role=button] for actual click target
        clickable_targets = []
        seen = set()
        for el in visible:
            try:
                target = driver.execute_script(
                    "let n=arguments[0];while(n && n!==document.body){if(n.tagName==='A'||n.tagName==='BUTTON'||n.getAttribute('role')==='button'||n.getAttribute('role')==='link')return n;n=n.parentElement;}return arguments[0];",
                    el,
                )
                key = driver.execute_script("const r=arguments[0].getBoundingClientRect();return r.top+'_'+r.left+'_'+r.width+'_'+r.height;", target)
                if key in seen:
                    continue
                seen.add(key)
                clickable_targets.append(target)
            except Exception:
                continue
        if clickable_targets:
            visible = clickable_targets

    idx = max(0, min(nth, len(visible) - 1))
    chosen = visible[idx]
    try:
        driver.execute_script("arguments[0].scrollIntoView({block:'center', inline:'center'});", chosen)
    except Exception:
        pass
    return chosen


def _element_center(driver, element):
    return driver.execute_script(
        "const r = arguments[0].getBoundingClientRect(); return {x: r.left + r.width / 2, y: r.top + r.height / 2};",
        element,
    )

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
    nth: int = 0  # which match to use when multiple match (0-based)

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
    driver = _ensure_browser(headless=False)
    return {"ok": True, "url": driver.current_url, "title": driver.title, "engine": "selenium-chrome"}


@app.post("/tool/browser_goto")
def browser_goto(arg: BrowserGoto):
    driver = _ensure_browser(headless=False)
    url = arg.url if "://" in arg.url else f"https://{arg.url}"
    driver.get(url)
    _inject_cursor(driver)
    return {"ok": True, "url": driver.current_url, "title": driver.title}


@app.post("/tool/browser_click")
def browser_click(arg: BrowserClick):
    driver = _ensure_browser(headless=False)
    try:
        element = _find_element(driver, arg.selector, arg.text, clickable=True, nth=arg.nth)
        center = _element_center(driver, element)
        _move_cursor(driver, center["x"], center["y"])
        _flash_cursor(driver)
        try:
            element.click()
        except Exception:
            # Fallback: JS click bypasses overlay/intercept issues common on SERPs
            driver.execute_script("arguments[0].click();", element)
        return {"ok": True, "clicked": arg.selector or arg.text, "nth": arg.nth}
    except Exception as e:
        raise HTTPException(500, f"Click failed: {e}")


@app.post("/tool/browser_type")
def browser_type(arg: BrowserType):
    driver = _ensure_browser(headless=False)
    try:
        _webdriver, _By, Keys, _ActionChains, _WebDriverWait, _EC = _import_selenium()
        element = _find_element(driver, arg.selector, clickable=True)
        center = _element_center(driver, element)
        _move_cursor(driver, center["x"], center["y"])
        _flash_cursor(driver)
        element.click()
        element.send_keys(Keys.CONTROL, "a")
        element.send_keys(arg.text)
        if arg.submit:
            element.send_keys(Keys.ENTER)
        return {"ok": True, "typed": arg.text, "into": arg.selector}
    except Exception as e:
        raise HTTPException(500, f"Type failed: {e}")


@app.post("/tool/browser_press")
def browser_press(arg: BrowserKey):
    driver = _ensure_browser(headless=False)
    _webdriver, _By, Keys, ActionChains, _WebDriverWait, _EC = _import_selenium()
    key = getattr(Keys, arg.key.upper(), arg.key)
    ActionChains(driver).send_keys(key).perform()
    return {"ok": True, "pressed": arg.key}


@app.post("/tool/browser_scroll")
def browser_scroll(arg: BrowserScroll):
    driver = _ensure_browser(headless=False)
    driver.execute_script("window.scrollBy(0, arguments[0])", int(arg.dy))
    return {"ok": True, "dy": arg.dy}


@app.post("/tool/browser_read")
def browser_read():
    driver = _ensure_browser(headless=False)
    try:
        _inject_cursor(driver)
        return driver.execute_script(r"""
  const text = (document.body.innerText || '').slice(0, 4000);
  const els = [];
  const seenKeys = new Set();
  const isVisible = (el, r) => {
    if (r.width < 4 || r.height < 4) return false;
    if (r.bottom < 0 || r.top > innerHeight + 400) return false;
    const cs = getComputedStyle(el);
    if (cs.visibility === 'hidden' || cs.display === 'none' || parseFloat(cs.opacity) < 0.05) return false;
    return true;
  };
  const cssPath = (el) => {
    if (el.id) return '#' + CSS.escape(el.id);
    const parts = [];
    let n = el;
    while (n && n.nodeType === 1 && parts.length < 5) {
      let part = n.tagName.toLowerCase();
      if (n.classList && n.classList.length) {
        const cls = Array.from(n.classList).slice(0,2).map(c => '.' + CSS.escape(c)).join('');
        part += cls;
      }
      const parent = n.parentElement;
      if (parent) {
        const sibs = Array.from(parent.children).filter(c => c.tagName === n.tagName);
        if (sibs.length > 1) part += `:nth-of-type(${sibs.indexOf(n)+1})`;
      }
      parts.unshift(part);
      n = n.parentElement;
      if (n && n.id) { parts.unshift('#' + CSS.escape(n.id)); break; }
    }
    return parts.join(' > ');
  };

  // 1) Search-result links (Google/Bing/DuckDuckGo etc.) — enumerated for easy nth targeting
  const results = [];
  const resultSelectors = [
    'div#search a h3',           // Google
    'div.g a h3',                // Google
    'li.b_algo h2 a',            // Bing
    'h2 a[href]',                // generic
    'article a[href]',           // generic
    '#links .result__a',         // DuckDuckGo
    '[data-testid="result-title-a"]', // DDG new
  ];
  const resultLinks = new Set();
  for (const sel of resultSelectors) {
    document.querySelectorAll(sel).forEach(el => {
      const a = el.tagName === 'A' ? el : el.closest('a');
      if (!a || !a.href) return;
      if (a.href.startsWith('javascript:') || a.href.includes('#')) {/* still allow */}
      if (resultLinks.has(a.href)) return;
      const r = a.getBoundingClientRect();
      if (!isVisible(a, r)) return;
      resultLinks.add(a.href);
      results.push({
        index: results.length,
        title: (el.innerText || a.innerText || '').trim().slice(0, 140),
        href: a.href,
        selector: cssPath(a),
      });
    });
    if (results.length >= 15) break;
  }

  // 2) Generic interactive controls
  document.querySelectorAll('a,button,input,textarea,select,[role=button],[role=link]').forEach(el => {
    const r = el.getBoundingClientRect();
    if (!isVisible(el, r)) return;
    const key = Math.round(r.top)+'_'+Math.round(r.left)+'_'+el.tagName;
    if (seenKeys.has(key)) return;
    seenKeys.add(key);
    els.push({
      tag: el.tagName.toLowerCase(),
      text: (el.innerText || el.value || el.placeholder || el.getAttribute('aria-label') || '').trim().slice(0,100),
      href: el.tagName === 'A' ? el.href : null,
      id: el.id || null,
      name: el.getAttribute('name') || null,
      type: el.getAttribute('type') || null,
      selector: cssPath(el),
    });
  });

  return { url: location.href, title: document.title, text, results, controls: els.slice(0, 80) };
""")
    except Exception as e:
        raise HTTPException(500, f"Read failed: {e}")


@app.post("/tool/browser_close")
def browser_close():
    with _browser_lock:
        try:
            if _browser_state["driver"]:
                _browser_state["driver"].quit()
        finally:
            _browser_state.update({"driver": None})
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

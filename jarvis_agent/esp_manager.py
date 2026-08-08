"""
JARVIS ESP / IoT Project Manager
================================
Generic, schema-driven registry of ESP8266 / ESP32 (or any HTTP/REST) projects.

Design principle:
    NEW ESP PROJECT = REGISTER PROJECT + DESCRIBE ITS API
    (never "modify JARVIS code")

This module is imported by jarvis_agent.py and mounted as a set of routes.
Projects are stored in a plain JSON file next to the agent so they survive
restarts and never leave the user's machine (credentials stay local).

Schema (one project):
{
  "id": "smart_aquarium",
  "name": "Smart Aquarium",
  "description": "...",
  "host": "192.168.1.42",          # ip / hostname / full base url
  "protocol": "http",              # http only for now (https accepted)
  "port": 80,                      # optional
  "timeout": 5,                    # seconds, default per-project
  "retries": 1,
  "auth": {                        # optional
     "type": "none|basic|bearer|header",
     "username": "", "password": "", "token": "",
     "header_name": "", "header_value": ""
  },
  "devices": [
    {
      "id": "pump", "name": "Water Pump", "description": "",
      "commands": [
        {"id": "on", "name": "Turn On", "method": "POST", "endpoint": "/pump/on"},
        {"id": "brightness", "name": "Set Brightness", "method": "POST",
         "endpoint": "/led/{brightness}",
         "parameters": {"brightness": {"type": "number", "min": 0, "max": 100,
                                       "required": true, "description": "..."}},
         "body": {"speed": "{speed}"},        # optional JSON body template
         "headers": {"X-Foo": "bar"},         # optional
         "expects": "json|text",              # optional
         "timeout": 5, "retries": 1,
         "confirm": false                     # true => destructive, needs confirmation
        }
      ],
      "sensors": [
        {"id": "temp", "name": "Temperature", "method": "GET", "endpoint": "/temp"}
      ]
    }
  ]
}
"""

from __future__ import annotations

import base64
import json
import re
import socket
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple

STORE_PATH = Path(__file__).resolve().parent / "esp_projects.json"

SECRET_KEYS = {"password", "token", "header_value", "secret", "api_key", "apikey"}
ALLOWED_METHODS = {"GET", "POST", "PUT", "PATCH", "DELETE"}


# --------------------------------------------------------------------------- #
# helpers
# --------------------------------------------------------------------------- #
def slugify(value: str, fallback: str = "item") -> str:
    s = re.sub(r"[^a-z0-9]+", "_", str(value or "").strip().lower()).strip("_")
    return s or fallback


def _load_raw() -> Dict[str, Any]:
    if not STORE_PATH.exists():
        return {"projects": []}
    try:
        data = json.loads(STORE_PATH.read_text(encoding="utf-8"))
        if isinstance(data, list):
            return {"projects": data}
        if not isinstance(data, dict):
            return {"projects": []}
        data.setdefault("projects", [])
        return data
    except Exception:
        return {"projects": []}


def _save_raw(data: Dict[str, Any]) -> None:
    STORE_PATH.write_text(json.dumps(data, indent=2), encoding="utf-8")


def list_projects() -> List[Dict[str, Any]]:
    return _load_raw().get("projects", [])


def get_project(project_id: str) -> Optional[Dict[str, Any]]:
    pid = slugify(project_id)
    for p in list_projects():
        if p.get("id") == pid or slugify(p.get("name", "")) == pid:
            return p
    # loose match: name contains
    needle = str(project_id or "").strip().lower()
    for p in list_projects():
        if needle and needle in str(p.get("name", "")).lower():
            return p
    return None


def redact(obj: Any) -> Any:
    """Deep-copy with secret values masked — used for anything the AI/UI sees."""
    if isinstance(obj, dict):
        out = {}
        for k, v in obj.items():
            if str(k).lower() in SECRET_KEYS and v:
                out[k] = "***stored locally***"
            else:
                out[k] = redact(v)
        return out
    if isinstance(obj, list):
        return [redact(v) for v in obj]
    return obj


# --------------------------------------------------------------------------- #
# validation / normalisation
# --------------------------------------------------------------------------- #
class EspError(Exception):
    pass


def _normalize_parameters(raw: Any) -> Dict[str, Any]:
    params: Dict[str, Any] = {}
    if isinstance(raw, dict):
        for name, spec in raw.items():
            if not isinstance(spec, dict):
                spec = {"type": str(spec or "string")}
            ptype = str(spec.get("type", "string")).lower()
            if ptype not in {"string", "number", "integer", "boolean"}:
                ptype = "string"
            params[slugify(name, name)] = {
                "type": ptype,
                "description": spec.get("description", ""),
                "required": bool(spec.get("required", True)),
                **({"min": spec["min"]} if spec.get("min") is not None else {}),
                **({"max": spec["max"]} if spec.get("max") is not None else {}),
                **({"enum": list(spec["enum"])} if isinstance(spec.get("enum"), list) else {}),
                **({"default": spec["default"]} if "default" in spec else {}),
            }
    elif isinstance(raw, list):
        for spec in raw:
            if isinstance(spec, dict) and spec.get("name"):
                nm = slugify(spec["name"], spec["name"])
                params[nm] = _normalize_parameters({nm: spec})[nm]
    return params


def _normalize_action(raw: Dict[str, Any], kind: str) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise EspError(f"Each {kind} must be an object")
    name = raw.get("name") or raw.get("id") or ""
    aid = slugify(raw.get("id") or name, kind)
    method = str(raw.get("method") or ("GET" if kind == "sensor" else "POST")).upper()
    if method not in ALLOWED_METHODS:
        raise EspError(f"Unsupported HTTP method '{method}' on {kind} '{aid}'")
    endpoint = str(raw.get("endpoint") or raw.get("path") or "").strip()
    if not endpoint:
        raise EspError(f"{kind} '{aid}' is missing an endpoint/path")
    if "://" in endpoint:
        raise EspError(f"{kind} '{aid}' endpoint must be a path like /pump/on, not a full URL")
    if not endpoint.startswith("/"):
        endpoint = "/" + endpoint
    action = {
        "id": aid,
        "name": name or aid.replace("_", " ").title(),
        "description": raw.get("description", ""),
        "method": method,
        "endpoint": endpoint,
        "parameters": _normalize_parameters(raw.get("parameters")),
        "expects": str(raw.get("expects") or "auto").lower(),
        "confirm": bool(raw.get("confirm", False)),
    }
    if isinstance(raw.get("body"), (dict, list, str)):
        action["body"] = raw["body"]
    if isinstance(raw.get("headers"), dict):
        action["headers"] = {str(k): str(v) for k, v in raw["headers"].items()}
    if raw.get("timeout") is not None:
        action["timeout"] = float(raw["timeout"])
    if raw.get("retries") is not None:
        action["retries"] = int(raw["retries"])
    if kind == "sensor":
        action["unit"] = raw.get("unit", "")
    return action


def _normalize_auth(raw: Any) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        return {"type": "none"}
    atype = str(raw.get("type") or "none").lower()
    if atype not in {"none", "basic", "bearer", "header"}:
        atype = "none"
    auth = {"type": atype}
    for k in ("username", "password", "token", "header_name", "header_value"):
        if raw.get(k):
            auth[k] = str(raw[k])
    return auth


def normalize_project(raw: Dict[str, Any], existing: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    if not isinstance(raw, dict):
        raise EspError("Project must be an object")
    name = str(raw.get("name") or "").strip()
    if not name:
        raise EspError("Project 'name' is required")
    pid = slugify(raw.get("id") or name, "project")

    host = str(raw.get("host") or raw.get("ip") or raw.get("address") or "").strip()
    if not host:
        raise EspError("Project 'host' (IP address or hostname) is required")
    protocol = str(raw.get("protocol") or "http").lower()
    if "://" in host:
        parsed = urllib.parse.urlparse(host)
        protocol = parsed.scheme or protocol
        host = parsed.netloc or parsed.path
    host = host.strip("/")
    if protocol not in {"http", "https"}:
        raise EspError(f"Protocol '{protocol}' is not supported yet — only http/https")
    if not re.match(r"^[A-Za-z0-9_.:\-]+$", host):
        raise EspError(f"Host '{host}' is not a valid IP address or hostname")

    port = raw.get("port")
    if ":" in host:
        host, _, maybe_port = host.partition(":")
        if maybe_port.isdigit():
            port = int(maybe_port)
    if port is not None:
        port = int(port)
        if not (1 <= port <= 65535):
            raise EspError("Port must be between 1 and 65535")

    devices: List[Dict[str, Any]] = []
    raw_devices = raw.get("devices") or []
    if not isinstance(raw_devices, list):
        raise EspError("'devices' must be a list")
    for d in raw_devices:
        if not isinstance(d, dict):
            raise EspError("Each device must be an object")
        dname = d.get("name") or d.get("id") or ""
        did = slugify(d.get("id") or dname, "device")
        commands = [_normalize_action(c, "command") for c in (d.get("commands") or [])]
        sensors = [_normalize_action(s, "sensor") for s in (d.get("sensors") or d.get("readings") or [])]
        if not commands and not sensors:
            raise EspError(f"Device '{did}' has no commands or sensors")
        devices.append({
            "id": did,
            "name": dname or did.replace("_", " ").title(),
            "description": d.get("description", ""),
            "commands": commands,
            "sensors": sensors,
        })
    if not devices:
        raise EspError("A project needs at least one device with one command or sensor")

    now = time.time()
    project = {
        "id": pid,
        "name": name,
        "description": raw.get("description", ""),
        "host": host,
        "protocol": protocol,
        "transport": "http",
        "timeout": float(raw.get("timeout") or 5),
        "retries": int(raw.get("retries") or 1),
        "auth": _normalize_auth(raw.get("auth")),
        "devices": devices,
        "created_at": (existing or {}).get("created_at", now),
        "updated_at": now,
    }
    if port is not None:
        project["port"] = port
    # keep previously stored credentials when the caller sent masked placeholders
    if existing:
        old_auth = existing.get("auth") or {}
        for k, v in list(project["auth"].items()):
            if isinstance(v, str) and v.startswith("***") and old_auth.get(k):
                project["auth"][k] = old_auth[k]
    return project


def save_project(raw: Dict[str, Any]) -> Dict[str, Any]:
    data = _load_raw()
    projects = data.get("projects", [])
    incoming_id = slugify(raw.get("id") or raw.get("name") or "", "project")
    existing = next((p for p in projects if p.get("id") == incoming_id), None)
    project = normalize_project(raw, existing)
    projects = [p for p in projects if p.get("id") != project["id"]]
    projects.append(project)
    data["projects"] = projects
    _save_raw(data)
    return project


def delete_project(project_id: str) -> bool:
    data = _load_raw()
    before = len(data.get("projects", []))
    target = get_project(project_id)
    if not target:
        return False
    data["projects"] = [p for p in data["projects"] if p.get("id") != target["id"]]
    _save_raw(data)
    return len(data["projects"]) != before


# --------------------------------------------------------------------------- #
# execution
# --------------------------------------------------------------------------- #
def _base_url(project: Dict[str, Any]) -> str:
    port = project.get("port")
    host = project["host"]
    netloc = f"{host}:{port}" if port and int(port) not in (80, 443) else host
    return f"{project.get('protocol', 'http')}://{netloc}"


def _coerce(value: Any, spec: Dict[str, Any], name: str) -> Any:
    ptype = spec.get("type", "string")
    try:
        if ptype in ("number", "integer"):
            num = float(value)
            if ptype == "integer" or float(num).is_integer():
                num = int(num)
            if spec.get("min") is not None and num < float(spec["min"]):
                raise EspError(f"Parameter '{name}' must be >= {spec['min']}")
            if spec.get("max") is not None and num > float(spec["max"]):
                raise EspError(f"Parameter '{name}' must be <= {spec['max']}")
            return num
        if ptype == "boolean":
            if isinstance(value, bool):
                return value
            return str(value).strip().lower() in {"1", "true", "yes", "on"}
        val = str(value)
        if spec.get("enum") and val not in [str(e) for e in spec["enum"]]:
            raise EspError(f"Parameter '{name}' must be one of {spec['enum']}")
        return val
    except EspError:
        raise
    except Exception:
        raise EspError(f"Parameter '{name}' must be of type {ptype}")


def _substitute(template: Any, values: Dict[str, Any], used: set) -> Any:
    if isinstance(template, str):
        exact = re.fullmatch(r"\{(\w+)\}", template.strip())
        if exact and exact.group(1) in values:
            used.add(exact.group(1))
            return values[exact.group(1)]

        def repl(m):
            key = m.group(1)
            if key in values:
                used.add(key)
                return str(values[key])
            return m.group(0)

        return re.sub(r"\{(\w+)\}", repl, template)
    if isinstance(template, dict):
        return {k: _substitute(v, values, used) for k, v in template.items()}
    if isinstance(template, list):
        return [_substitute(v, values, used) for v in template]
    return template


def resolve_action(project_id: str, device_id: str, command_id: str) -> Tuple[Dict[str, Any], Dict[str, Any], Dict[str, Any]]:
    project = get_project(project_id)
    if not project:
        known = ", ".join(p["id"] for p in list_projects()) or "none registered"
        raise EspError(f"No registered project matching '{project_id}'. Known projects: {known}")
    did = slugify(device_id)
    device = next(
        (d for d in project["devices"] if d["id"] == did or slugify(d.get("name", "")) == did),
        None,
    )
    if not device:
        raise EspError(
            f"Project '{project['name']}' has no device '{device_id}'. "
            f"Devices: {', '.join(d['id'] for d in project['devices'])}"
        )
    cid = slugify(command_id)
    pool = list(device.get("commands", [])) + list(device.get("sensors", []))
    action = next((a for a in pool if a["id"] == cid or slugify(a.get("name", "")) == cid), None)
    if not action:
        raise EspError(
            f"Device '{device['id']}' has no command '{command_id}'. "
            f"Available: {', '.join(a['id'] for a in pool) or 'none'}. "
            "Ask the user for the correct endpoint instead of guessing."
        )
    return project, device, action


def execute_device_command(
    project_id: str,
    device_id: str,
    command_id: str,
    parameters: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    parameters = parameters or {}
    project, device, action = resolve_action(project_id, device_id, command_id)

    # validate + coerce parameters against the registered spec
    values: Dict[str, Any] = {}
    specs = action.get("parameters") or {}
    for name, spec in specs.items():
        if name in parameters and parameters[name] is not None:
            values[name] = _coerce(parameters[name], spec, name)
        elif "default" in spec:
            values[name] = spec["default"]
        elif spec.get("required", True):
            raise EspError(f"Missing required parameter '{name}' ({spec.get('type', 'string')})")
    for extra in parameters:
        if extra not in specs:
            raise EspError(
                f"Parameter '{extra}' is not registered for command '{action['id']}'. "
                f"Registered parameters: {', '.join(specs) or 'none'}"
            )

    used: set = set()
    endpoint = _substitute(action["endpoint"], values, used)
    leftovers = {k: v for k, v in values.items() if k not in used}

    body = None
    if "body" in action:
        body = _substitute(action["body"], values, used)
        leftovers = {k: v for k, v in values.items() if k not in used}
    elif leftovers and action["method"] in {"POST", "PUT", "PATCH"}:
        body = leftovers

    url = _base_url(project) + urllib.parse.quote(endpoint, safe="/?&=:%,._~-")
    headers = {"Accept": "*/*", "User-Agent": "JARVIS-Agent/1.0"}
    headers.update(action.get("headers") or {})
    auth = project.get("auth") or {}
    atype = auth.get("type", "none")
    if atype == "basic" and auth.get("username"):
        raw = f"{auth.get('username','')}:{auth.get('password','')}".encode()
        headers["Authorization"] = "Basic " + base64.b64encode(raw).decode()
    elif atype == "bearer" and auth.get("token"):
        headers["Authorization"] = f"Bearer {auth['token']}"
    elif atype == "header" and auth.get("header_name"):
        headers[auth["header_name"]] = auth.get("header_value", "")

    data_bytes = None
    if body is not None and action["method"] != "GET":
        if isinstance(body, str):
            data_bytes = body.encode()
            headers.setdefault("Content-Type", "text/plain")
        else:
            data_bytes = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"

    timeout = float(action.get("timeout") or project.get("timeout") or 5)
    retries = max(0, int(action.get("retries", project.get("retries", 1))))

    attempt = 0
    last_error = ""
    while attempt <= retries:
        attempt += 1
        started = time.time()
        req = urllib.request.Request(url, data=data_bytes, headers=headers, method=action["method"])
        try:
            with urllib.request.urlopen(req, timeout=timeout) as resp:
                text = resp.read().decode("utf-8", "replace")
                ms = int((time.time() - started) * 1000)
                parsed: Any = None
                try:
                    parsed = json.loads(text)
                except Exception:
                    parsed = None
                return {
                    "ok": True,
                    "project": project["id"],
                    "device": device["id"],
                    "command": action["id"],
                    "request": {"method": action["method"], "url": url, "body": body},
                    "status": resp.status,
                    "duration_ms": ms,
                    "response": parsed if parsed is not None else text[:4000],
                }
        except urllib.error.HTTPError as e:
            detail = e.read().decode("utf-8", "replace")[:1000]
            last_error = f"HTTP {e.code}: {detail}"
            if 400 <= e.code < 500:
                break
        except urllib.error.URLError as e:
            last_error = f"Cannot reach {url} — {getattr(e, 'reason', e)}"
        except socket.timeout:
            last_error = f"Timed out after {timeout}s contacting {url}"
        except Exception as e:  # noqa: BLE001
            last_error = f"{type(e).__name__}: {e}"
        time.sleep(0.25)

    return {
        "ok": False,
        "project": project["id"],
        "device": device["id"],
        "command": action["id"],
        "request": {"method": action["method"], "url": url, "body": body},
        "attempts": attempt,
        "error": last_error or "Unknown failure",
    }


def project_status(project_id: str) -> Dict[str, Any]:
    project = get_project(project_id)
    if not project:
        raise EspError(f"No registered project matching '{project_id}'")
    host = project["host"]
    port = int(project.get("port") or (443 if project.get("protocol") == "https" else 80))
    started = time.time()
    try:
        with socket.create_connection((host, port), timeout=2):
            return {
                "project": project["id"],
                "online": True,
                "host": host,
                "port": port,
                "latency_ms": int((time.time() - started) * 1000),
            }
    except Exception as e:  # noqa: BLE001
        return {"project": project["id"], "online": False, "host": host, "port": port, "error": str(e)}


def capabilities_summary() -> Dict[str, Any]:
    """Compact, secret-free description of everything the AI may control."""
    out = []
    for p in list_projects():
        out.append({
            "project_id": p["id"],
            "name": p["name"],
            "description": p.get("description", ""),
            "host": p["host"],
            "protocol": p.get("protocol", "http"),
            "auth": (p.get("auth") or {}).get("type", "none"),
            "devices": [
                {
                    "device_id": d["id"],
                    "name": d["name"],
                    "commands": [
                        {
                            "command_id": c["id"],
                            "name": c["name"],
                            "method": c["method"],
                            "endpoint": c["endpoint"],
                            "parameters": c.get("parameters") or {},
                            "confirm": c.get("confirm", False),
                        }
                        for c in d.get("commands", [])
                    ],
                    "sensors": [
                        {
                            "command_id": s["id"],
                            "name": s["name"],
                            "method": s["method"],
                            "endpoint": s["endpoint"],
                            "unit": s.get("unit", ""),
                        }
                        for s in d.get("sensors", [])
                    ],
                }
                for d in p.get("devices", [])
            ],
        })
    return {"projects": out, "store": str(STORE_PATH)}

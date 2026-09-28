#!/usr/bin/env python3
"""
terminal_bridge.py — Generic tmux WebSocket Terminal Bridge (Sidecar)

FastAPI/uvicorn-Dienst, der tmux-Sessions über WebSocket als interaktives
Terminal verfügbar macht — e.g. eingebettet in ein Web-UI. Token-Auth (Bearer),
bindet nur auf einer konfigurierten (z. B. Tailscale-) IP. Registry (targets.json)
erlaubt zusätzlich ssh/remote-Ziele.

Kanal: Jede WS-Verbindung startet einen PTY-Prozess `tmux attach -t <session>`
(in einem Pseudo-Terminal) — so erhält der Client echtes interaktives Terminal-
Verhalten inkl. resize (ioctl TIOCSWINSZ).

Endpunkte:
  GET /api/sessions                  -> JSON-Liste verfügbarer (lokaler) tmux-Sessions
  WS  /ws/terminal/{session}         -> bidirektional (PTY + tmux attach)
  GET /health                        -> {"ok": true} (ohne Auth, für systemd/Probe)

Konfiguration (Env):
  TERMINAL_BRIDGE_TOKEN   Pflicht - Bearer/Query token (ody_... o.ä.)
  TERMINAL_REGISTRY       optional - Pfad zu targets.json
  TERMINAL_HOST/TERMINAL_PORT optional - Bind (leer => alle Interfaces)
"""

from __future__ import annotations

import asyncio
import fcntl
import json
import logging
import os
import pty
import select
import signal
import subprocess
import sys
import termios
import struct
from pathlib import Path
from typing import Any, Optional

try:
    from fastapi import FastAPI, WebSocket, WebSocketDisconnect, HTTPException, Depends
    from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
    import uvicorn
except ImportError as e:  # pragma: no cover
    sys.stderr.write(f"Missing dependency: {e}. Install via: uv venv && uv pip install fastapi uvicorn\n")
    raise SystemExit(2)

logger = logging.getLogger("terminal_bridge")

app = FastAPI(title="Odysseus Terminal Bridge", version="0.2.0")
_bearer = HTTPBearer(auto_error=False)

# ---------------------------------------------------------------------------
# config
# ---------------------------------------------------------------------------

DEFAULT_HOST = "127.0.0.1"   # sicherer Default; Bind-IP via TERMINAL_HOST setzen (z. B. Tailscale-IP)
DEFAULT_PORT = 5233
TOKEN = os.environ.get("TERMINAL_BRIDGE_TOKEN", "").strip()

REGISTRY_PATH = Path(
    os.environ.get("TERMINAL_REGISTRY", os.path.expanduser("~/terminal-bridge/targets.json"))
)

SESSION_SAFE = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789._-")


def _load_registry() -> list[dict[str, Any]]:
    """Registry laden: [{id,name,mode,session,host,port}]. local = tmux auf diesem Host."""
    try:
        if REGISTRY_PATH.exists():
            data = json.loads(REGISTRY_PATH.read_text(encoding="utf-8"))
            return data if isinstance(data, list) else []
    except Exception as e:  # pragma: no cover
        logger.warning("Registry unlesbar: %s", e)
    return []


def _refresh_local_sessions() -> list[dict[str, Any]]:
    """tmux-Sessions dieses Hosts abfragen (read-only)."""
    try:
        out = subprocess.check_output(
            ["tmux", "list-sessions", "-F", "#{session_name}\t#{session_attached}"],
            stderr=subprocess.DEVNULL, timeout=5,
        ).decode("utf-8", "replace")
        res = []
        for line in out.splitlines():
            parts = line.split("\t")
            if parts:
                res.append({"name": parts[0], "attached": parts[1] == "1" if len(parts) > 1 else False})
        return res
    except Exception:
        return []


def _discover_targets() -> set[str]:
    """Vereinigt Registry (local + ssh) mit den aktuell real laufenden tmux-Sessions."""
    registry = _load_registry()
    names = {t["session"] for t in registry if t.get("session")}
    for s in _refresh_local_sessions():
        names.add(s["name"])
    return names


# ---------------------------------------------------------------------------
# auth
# ---------------------------------------------------------------------------

def _check_token(creds: Optional[HTTPAuthorizationCredentials]) -> bool:
    if not TOKEN:
        return False
    if creds is None or creds.scheme.lower() != "bearer":
        return False
    return creds.credentials == TOKEN


def _session_allowed(name: str) -> bool:
    return name in _discover_targets()


def _target_for(name: str) -> Optional[dict[str, Any]]:
    """Registry-Eintrag zu einer Session (local oder ssh)."""
    for t in _load_registry():
        if t.get("mode", "local") == "local" and t.get("session") == name:
            return t
    return None


# ---------------------------------------------------------------------------
# API
# ---------------------------------------------------------------------------

@app.get("/health")
async def health():
    return {"ok": True}


@app.get("/api/sessions")
async def api_sessions(creds: Optional[HTTPAuthorizationCredentials] = Depends(_bearer)):
    if not _check_token(creds):
        raise HTTPException(status_code=401, detail="Invalid or missing token")
    rows = _refresh_local_sessions()
    seen = {r["name"] for r in rows}
    # Registry-Targets (local+ssh) ergänzen, damit auch entfernte Sessions sichtbar sind
    targets = _load_registry()
    for t in targets:
        name = t.get("session")
        if name and name not in seen:
            rows.append({
                "name": name,
                "attached": False,
                "remote": t.get("mode", "local") == "ssh",
                "target": t.get("name", name),
            })
            seen.add(name)
    return {"sessions": rows, "targets": targets}


# ---------------------------------------------------------------------------
# PTY-Terminal-Kanal
# ---------------------------------------------------------------------------

def _spawn_tmux_pty(session: str):
    """Startet `tmux attach -t <session>` in einem PTY; Rückgabe (master_fd, proc)."""
    master, slave = pty.openpty()
    # tmux attach fordert eine Session; hat die nicht existiert -> leere neue Session
    cmd = ["tmux", "attach", "-t", session]
    proc = subprocess.Popen(
        cmd,
        stdin=slave, stdout=slave, stderr=slave,
        env={**os.environ, "TERM": "xterm-256color"},
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)
    os.set_blocking(master, False)
    return master, proc


def _spawn_ssh_pty(target: dict[str, Any], remote_session: str):
    """Startet SSH zu einer entfernten CC und attach-t deren tmux-Session (Mode ssh).

    Erwartet im Registry-Eintrag: host, user, port (optional), key (optional),
    session (remote tmux-Name). Führt aus:
        ssh [ -p port ] [ -i key ] user@host "tmux attach -t <session>"
    """
    import shlex
    host = target.get("host") or ""
    user = target.get("user") or "ubuntu"
    port = target.get("port")
    key = target.get("key")
    remote = f"{user}@{host}" if user and host else host
    ssh_cmd = ["ssh", "-tt"]  # -tt: pty für interaktive Remote-Session
    if port:
        ssh_cmd += ["-p", str(port)]
    if key:
        ssh_cmd += ["-i", key]
    ssh_cmd += [remote, f"tmux attach -t {shlex.quote(remote_session)}"]

    master, slave = pty.openpty()
    proc = subprocess.Popen(
        ssh_cmd,
        stdin=slave, stdout=slave, stderr=slave,
        env={**os.environ, "TERM": "xterm-256color"},
        start_new_session=True,
        close_fds=True,
    )
    os.close(slave)
    os.set_blocking(master, False)
    return master, proc


def _set_pty_size(master: int, cols: int, rows: int) -> None:
    try:
        fcntl.ioctl(master, termios.TIOCSWINSZ, struct.pack("HHHH", rows, cols, 0, 0))
    except OSError:
        pass


@app.websocket("/ws/terminal/{session}")
async def ws_terminal(ws: WebSocket, session: str):
    """Bidirektionaler Terminal-Kanal via PTY + tmux attach."""
    token = ws.query_params.get("token", "")
    logger.warning("WS-DEBUG session=%s token_len=%s token_prefix=%s self_token=%s",
                   session, len(token), token[:8] if token else "", TOKEN[:8] if TOKEN else "")
    allowed = _session_allowed(session)
    logger.warning("WS-DEBUG session_allowed=%s targets=%s", allowed, sorted(_discover_targets()))
    if not TOKEN or token != TOKEN:
        await ws.close(code=4401, reason="unauthorized")
        return
    if not session or not all(c in SESSION_SAFE for c in session) or not allowed:
        await ws.close(code=4404, reason="session-not-allowed")
        return

    await ws.accept()

    target = _target_for(session)
    if target and target.get("mode", "local") == "ssh":
        master, proc = _spawn_ssh_pty(target, target.get("session") or session)
    else:
        master, proc = _spawn_tmux_pty(session)
    loop = asyncio.get_running_loop()
    ws_open = True

    def _read_master() -> bytes:
        """Synchroner Reader: liefert Daten oder b'' am Lebensende."""
        try:
            r, _, _ = select.select([master], [], [], 0.2)
            if not r:
                return b""
            data = os.read(master, 65536)
            return data
        except OSError:
            return b""

    async def _pump_out():
        nonlocal ws_open
        while ws_open:
            data = await loop.run_in_executor(None, _read_master)
            if data:
                try:
                    await ws.send_bytes(data)
                except Exception:
                    ws_open = False
                    break
            elif proc.poll() is not None:
                # Prozess beendet und kein Rest mehr -> schließen
                try:
                    await asyncio.wait_for(ws.send_text("__BRIDGE_EOF__"), timeout=2)
                except Exception:
                    pass
                ws_open = False
                break
            else:
                await asyncio.sleep(0.02)

    async def _pump_in():
        nonlocal ws_open
        try:
            while ws_open:
                msg = await ws.receive_text()
                if msg.startswith("RESIZE:"):
                    try:
                        _, cols, rows = msg.split(":", 2)
                        _set_pty_size(master, int(cols), int(rows))
                    except Exception:
                        pass
                    continue
                try:
                    os.write(master, msg.encode())
                except OSError:
                    ws_open = False
        except WebSocketDisconnect:
            ws_open = False
        except Exception:
            ws_open = False

    out_task = asyncio.create_task(_pump_out())
    in_task = asyncio.create_task(_pump_in())

    try:
        await asyncio.gather(out_task, in_task)
    except Exception:
        pass
    finally:
        ws_open = False
        for t in (out_task, in_task):
            t.cancel()
        try:
            proc.terminate()
            await asyncio.wait_for(proc.wait(), timeout=2)
        except Exception:
            try:
                proc.kill()
            except Exception:
                pass
        try:
            os.close(master)
        except Exception:
            pass


def main() -> None:
    logging.basicConfig(level=os.environ.get("LOG_LEVEL", "INFO"),
                        format="%(asctime)s %(levelname)s %(name)s %(message)s")
    if not TOKEN:
        logger.error("TERMINAL_BRIDGE_TOKEN nicht gesetzt — Dienst startet nicht.")
        raise SystemExit(1)
    host = os.environ.get("TERMINAL_HOST", DEFAULT_HOST)
    port = int(os.environ.get("TERMINAL_PORT", str(DEFAULT_PORT)))
    logger.info("Starte terminal-bridge auf %s:%s", host, port)
    uvicorn.run(app, host=host, port=port, log_level="info")


if __name__ == "__main__":
    main()

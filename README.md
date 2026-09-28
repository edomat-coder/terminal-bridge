# Generic tmux WebSocket Terminal Bridge — publizierbare Bausteine

Sammlung **generisch nutzbarer Implementierungs-Bausteine** (`.sh` / `.py`) für eine
tmux-basierte Terminal-Bridge und ein automatisiertes Vault-Sync.

> **Hinweis:** Diese Dateien sind **sanitized** (keine IPs, Pfade, Sessions oder
> Credentials) und dienen als Vorlage/Blaupause. Alle konkreten Daten & Doku bleiben
> im **privaten** Second-Brain-Vault.

## Inhalt

| Datei | Zweck |
|---|---|
| `terminal_bridge.py` | FastAPI/uvicorn-Sidecar: jede WS-Verbindung → `tmux attach` in einem PTY → interaktives Terminal (inkl. resize). Env: `TERMINAL_BRIDGE_TOKEN` (Pflicht), `TERMINAL_REGISTRY`, `TERMINAL_HOST`/`TERMINAL_PORT`. |
| `terminal.js` | xterm.js-Frontend (UI-Overlay + `RESIZE:cols:rows`-Kanal) für den Browser. |
| `install_bridge.sh` | Idempotentes Setup: venv, `.env`-Token, `targets.json`-Vorlage, systemd-Unit. Anpassbar via `BRIDGE_*`-Umgebungsvariablen (`APP_DIR`, `BIND_IP`, `BIND_PORT`, `SERVICE`, `USER`). |
| `targets.example.json` | Registry-Vorlage (lokale + künftige ssh/remote-Ziele); real immer als `targets.json` + `chmod 600`. |
| `patch_router_models.py` | SQLite-Patch für ccr-Router: matcht `claudeCode`-Profile auf `openrouter/free` (Router-Workaround). DB-Pfad via `CCR_CONFIG_DB`. |
| `vault-sync.sh` | Git-Sync (pull --rebase → add −A → commit → push) für ein Vault-Repo. Pfad/Branch via `VAULT_DIR`/`VAULT_SYNC_LOG`/`VAULT_BRANCH`. |
| `vault-consolidate-nightly.sh` | Nächtliche Konsolidierung (obsidian-second-brain): Health-Scan + Claude-Session in tmux + Git-Sync danach. Pfade via `VAULT_DIR`/`OSB_SKILL_DIR`. |

## Kernprinzipien

- **Credentials nie im Code** — nur über Env/`.env` (`.env` wird mit `chmod 600` abgelegt).
- **Keine hartcodierten IPs/Usernames** — Defaults auf `127.0.0.1`, alle Deployment-Parameter überschreibbar.
- **Kontextfenster schützen** (Lessons aus Hermes-Skills): nur notwendige Ausgaben in den Agent-Context; Terminal-Noise filtern; Registry klein halten.

## Lizenz / Herkunft

Vorlagen für eine selbst gehostete Edge-KI-Umgebung. Ohne explizite Angabe einer Fremd-Lizenz;
vor Weiterverwendung Deployment-Pfade prüfen und eigene Secrets nicht committen.
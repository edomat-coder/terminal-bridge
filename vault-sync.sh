#!/usr/bin/env bash
# vault-sync — Git-Sync für das Second-Brain-Vault.
# pull --rebase → add −A (ohne lokale Settings) → commit → push.
# Läuft als systemd-Timer (siehe vault-sync.timer).

set -uo pipefail

VAULT="${VAULT_DIR:-$HOME/vault}"
LOG="${VAULT_SYNC_LOG:-$HOME/vault-sync.log}"
BRANCH="${VAULT_BRANCH:-main}"

cd "$VAULT" || exit 1

ts() { date '+%Y-%m-%d %H:%M:%S'; }

echo "[$(ts)] vault-sync start" >>"$LOG"

# 1) remote abholen (Reihenfolge vor dem eigenen Commit — Konflikte zuerst)
if ! git pull --rebase --autostash origin "$BRANCH" >>"$LOG" 2>&1; then
  echo "[$(ts)] pull FEHLGESCHLAGEN — break" >>"$LOG"
  exit 1
fi

# 2) Änderungen stagen (lokale Settings/Permissions ausschließen)
git add -A -- . ':!.claude/settings.local.json' >>"$LOG" 2>&1

# 3) Wenn etwas gestaged → commit
if ! git diff --cached --quiet; then
  git commit -m "chore: vault auto-sync $(ts)" >>"$LOG" 2>&1
fi

# 4) pushen
if ! git push origin "$BRANCH" >>"$LOG" 2>&1; then
  echo "[$(ts)] push FEHLGESCHLAGEN" >>"$LOG"
  exit 1
fi

echo "[$(ts)] vault-sync fertig" >>"$LOG"

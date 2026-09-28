#!/usr/bin/env bash
# vault-consolidate-nightly — nächtliche Vault-Konsolidierung (obsidian-second-brain)
#
# 1. Deterministic health scan (read-only) -> Bericht in Log
# 2. Echte Claude-Session in einer tmux-Session (im Vault-Ordner), die die
#    Konsolidierung mit vollen Fähigkeiten der 47 Befehle ausführt.
# 3. Danach Git-Sync (vault-sync.sh) — der läuft NACH der Konsolidierung,
#    damit die Änderungen gepusht werden.
#
# HINWEIS: Die tmux-Session 'vault-consolidate' bleibt nach dem Lauf bestehen
# und zeigt das Ergebnis; sie wird bei Bedarf manuell gelöscht. Im RoutinebBild
# ist die Session am Morgen sichtbar (wie osb-init).

set -uo pipefail
export PATH="$HOME/.local/bin:$PATH"

VAULT="${VAULT_DIR:-$HOME/vault}"
LOG="${VAULT_CONSOLIDATE_LOG:-$HOME/vault-consolidate.log}"
SKILL="${OSB_SKILL_DIR:-$HOME/.claude/skills/obsidian-second-brain}"
SESSION="vault-consolidate"

ts() { date '+%Y-%m-%d %H:%M:%S'; }

# --- Stufe 1: Health-Scan (deterministisch, read-only) ---
{
  echo "===== [$(ts)] consolidate nightly start ====="
  cd "$VAULT" || exit 1
  echo "---- health scan ----"
  uv run --directory "$SKILL/scripts" python "$SKILL/scripts/vault_health.py" --path "$VAULT" 2>&1 | tail -40
} >>"$LOG" 2>&1

# --- Stufe 2: Konsolidierung in echte Claude-Session (tmux) ---
if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux kill-session -t "$SESSION" 2>/dev/null || true
fi
# Claude im Vault starten (tmux detached, überlebt den systemd-Oneshot)
tmux new-session -d -s "$SESSION" -c "$VAULT" "claude"

# Kurz warten bis Claude bereit, dann Konsolidierungs-Auftrag senden
sleep 25
tmux send-keys -t "$SESSION" "Führe Vault-Pflege in DIESEM Vault aus: 1. /obsidian-health — scanne Duplikate, Widersprüche, stale claims, Orphans; Bericht. 2. /obsidian-reconcile — löse belegbare Widersprüche auf, Unsicheres mit needs_review. 3. /obsidian-merge — führe klare Duplikate zusammen (Trockenlauf zuerst; pensionierte Datei wird Redirect, NIE löschen). 4. /obsidian-save bzw. Ingest — arbeite neue Daten aus Inbox ein, ordne Einträge. 5. Aktualisiere Frontmatter/Tags (aktuelle Infos statt an alte anhängen); vorhandene Notizen nie ohne Markierung überschreiben. 6. Recency-Marker (as of) aktualisieren. Am Ende: kurzer Abschlussbericht, was konsolidiert wurde." Enter

# Warten bis die Konsolidierung in der Session abgeschlossen ist (Prompt = fertig).
# Polling ohne endlos zu blockieren: bis zu ~45 min, dann abbrechen (Session bleibt erhaltbar).
for i in $(seq 1 90); do   # 90 x 30s = 45 min
  sleep 30
  # Session weg = fertig
  if ! tmux has-session -t "$SESSION" 2>/dev/null; then
    break
  fi
  # Prompt-Zeichen sichtbar ('❯' oder 'manual mode on') = Claude wieder idle
  if tmux capture-pane -t "$SESSION" -p 2>/dev/null | grep -qE '❯|manual mode on'; then
    break
  fi
done
echo "[$(ts)] consolidate nightly: Konsolidierung abgeschlossen/Timeout" >>"$LOG"

# Session-Abschluss-Key (sobald Claude wieder am Prompt ist) für sauberen Abschluss
tmux send-keys -t "$SESSION" Enter 2>/dev/null || true

# --- Stufe 3: Git-Sync ---
"$HOME/vault-sync.sh" >>"$LOG" 2>&1 || true
echo "[$(ts)] consolidate nightly Ende" >>"$LOG"

#!/usr/bin/env bash
#
# morf-gpt - Start- und Stop-Skript für Datenbank (Docker), Backend (FastAPI)
# und Oberfläche (Vite/Svelte).
#
# Verwendung:
#   ./start.sh start     Datenbank + Transkriptionsdienst + Backend + Oberfläche starten (richtet beim ersten Mal alles ein)
#   ./start.sh stop      Transkriptionsdienst + Backend + Oberfläche stoppen (Datenbank läuft weiter)
#   ./start.sh restart   Transkriptionsdienst + Backend + Oberfläche neu starten
#   ./start.sh status    Laufstatus anzeigen
#   ./start.sh logs      Protokolle live anzeigen (Strg+C zum Beenden)
#   ./start.sh setup     Abhängigkeiten (neu) installieren
#   ./start.sh db        Nur die Datenbank starten
#   ./start.sh migrate   Datenbankschema auf den neuesten Stand bringen
#   ./start.sh backend   Nur das Backend (neu) starten
#   ./start.sh frontend  Nur die Oberfläche (neu) starten
#   ./start.sh transkription  Nur den eigenen Transkriptionsdienst (neu) starten
#
# Der Transkriptionsdienst (hilfsdienste/transkription, Whisper) hat ein eigenes venv und
# startet nur bei MORF_TRANSKRIPTION_AKTIV=true (Vorgabe); wer einen fremden Dienst nutzt,
# setzt den Wert in der .env auf false.
#
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"
TRANSKRIPTION_DIR="$ROOT_DIR/hilfsdienste/transkription"
TRANSKRIPTION_VENV="$TRANSKRIPTION_DIR/.venv"
RUN_DIR="$ROOT_DIR/.run"
VENV_DIR="$BACKEND_DIR/.venv"
ENV_FILE="$ROOT_DIR/.env"

BACKEND_PID="$RUN_DIR/backend.pid"
FRONTEND_PID="$RUN_DIR/frontend.pid"
BACKEND_LOG="$RUN_DIR/backend.log"
FRONTEND_LOG="$RUN_DIR/frontend.log"
TRANSKRIPTION_PID="$RUN_DIR/transkription.pid"
TRANSKRIPTION_LOG="$RUN_DIR/transkription.log"

if [ -t 1 ]; then
  C_RESET="\033[0m"; C_GREEN="\033[32m"; C_YELLOW="\033[33m"; C_RED="\033[31m"; C_BLUE="\033[34m"
else
  C_RESET=""; C_GREEN=""; C_YELLOW=""; C_RED=""; C_BLUE=""
fi
info() { printf '%b[i]%b %s\n'  "$C_BLUE"   "$C_RESET" "$*"; }
ok()   { printf '%b[ok]%b %s\n' "$C_GREEN"  "$C_RESET" "$*"; }
warn() { printf '%b[!]%b %s\n'  "$C_YELLOW" "$C_RESET" "$*" >&2; }
err()  { printf '%b[x]%b %s\n'  "$C_RED"    "$C_RESET" "$*" >&2; }
die()  { err "$*"; exit 1; }

# ---------------------------------------------------------------------------
# Umgebung (.env) - wird beim ersten Start aus .env.example angelegt, nie überschrieben
# ---------------------------------------------------------------------------
env_sicherstellen() {
  if [ ! -f "$ENV_FILE" ]; then
    cp "$ROOT_DIR/.env.example" "$ENV_FILE"
    # Eindeutiger Docker-Projektname je Klon (aus dem absoluten Pfad abgeleitet)
    local kennung
    kennung="$(printf '%s' "$ROOT_DIR" | cksum | awk '{print $1}')"
    sed -i.bak "s/^COMPOSE_PROJECT_NAME=.*/COMPOSE_PROJECT_NAME=morf-gpt-${kennung}/" "$ENV_FILE" && rm -f "$ENV_FILE.bak"
    ok ".env angelegt (Projektname morf-gpt-${kennung})"
  fi
  set -a; . "$ENV_FILE"; set +a
  BACKEND_HOST="${MORF_BACKEND_HOST:-127.0.0.1}"
  BACKEND_PORT="${MORF_BACKEND_PORT:-8460}"
  FRONTEND_PORT="${MORF_FRONTEND_PORT:-5460}"
  DB_PORT="${MORF_DB_PORT:-5462}"
  TRANSKRIPTION_HOST="${MORF_TRANSKRIPTION_HOST:-127.0.0.1}"
  TRANSKRIPTION_PORT="${MORF_TRANSKRIPTION_PORT:-8463}"
  TRANSKRIPTION_AKTIV="${MORF_TRANSKRIPTION_AKTIV:-true}"
  mkdir -p "$RUN_DIR" "$ROOT_DIR/data"
  git -C "$ROOT_DIR" config core.hooksPath tools/git-hooks 2>/dev/null || true
}

read_pid() { local f="$1" pid; [ -f "$f" ] || return 1; pid="$(cat "$f" 2>/dev/null || true)"; [[ "$pid" =~ ^[0-9]+$ ]] || return 1; printf '%s' "$pid"; }
pid_alive() { kill -0 "$1" 2>/dev/null; }

port_belegt() { lsof -nP -iTCP:"$1" -sTCP:LISTEN >/dev/null 2>&1; }

# Startet einen Dienst im Hintergrund: hintergrund <verzeichnis> <logdatei> <piddatei> <befehl...>
# Bewusst ohne Unterschale um den Aufruf: in "( cd && nohup ... & echo $! )" merkt sich $! eine
# Zwischenschale, die auf den Dienst wartet und die Ausgabe offen hält; der Dienst selbst hatte
# eine andere PID und überlebte den Stop.
hintergrund() {
  local verzeichnis="$1" log="$2" piddatei="$3"
  shift 3
  cd "$verzeichnis"
  nohup "$@" > "$log" 2>&1 < /dev/null &
  echo $! > "$piddatei"
  cd "$ROOT_DIR"
}

# ---------------------------------------------------------------------------
# Datenbank (Docker Compose)
# ---------------------------------------------------------------------------
compose() { docker compose --env-file "$ENV_FILE" -f "$ROOT_DIR/docker/docker-compose.yml" "$@"; }

db_start() {
  command -v docker >/dev/null 2>&1 || die "Docker fehlt."
  docker info >/dev/null 2>&1 || die "Docker läuft nicht."
  mkdir -p "$ROOT_DIR/data/postgres"
  compose up -d datenbank >/dev/null
  info "Warte auf die Datenbank (Port $DB_PORT) ..."
  local i
  for i in $(seq 1 60); do
    if compose exec -T datenbank pg_isready -U "${MORF_DB_NUTZER:-morf}" -d "${MORF_DB_NAME:-morfgpt}" >/dev/null 2>&1; then
      ok "Datenbank bereit"
      return 0
    fi
    sleep 1
  done
  die "Datenbank wurde nicht bereit (docker compose logs datenbank)."
}

db_status() {
  if compose ps --status running datenbank 2>/dev/null | grep -q datenbank; then
    ok "Datenbank läuft (127.0.0.1:$DB_PORT)"
  else
    warn "Datenbank aus"
  fi
}

# ---------------------------------------------------------------------------
# Backend (uv-venv, FastAPI)
# ---------------------------------------------------------------------------
backend_deps() {
  command -v uv >/dev/null 2>&1 || die "uv fehlt (brew install uv)."
  if [ ! -d "$VENV_DIR" ]; then
    info "Lege Python-Umgebung an ..."
    (cd "$BACKEND_DIR" && uv venv --quiet --python 3.12 "$VENV_DIR")
  fi
  (cd "$BACKEND_DIR" && uv pip install --quiet --python "$VENV_DIR/bin/python" -e ".[dev]")
  ok "Backend-Abhängigkeiten aktuell"
}

migrate() {
  (cd "$BACKEND_DIR" && "$VENV_DIR/bin/alembic" upgrade head)
  ok "Datenbankschema aktuell"
}

backend_stop() {
  local pid
  if pid="$(read_pid "$BACKEND_PID")" && pid_alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    pid_alive "$pid" && kill -9 "$pid" 2>/dev/null || true
    ok "Backend gestoppt"
  fi
  rm -f "$BACKEND_PID"
}

backend_start() {
  backend_stop
  if port_belegt "$BACKEND_PORT"; then
    die "Port $BACKEND_PORT ist belegt (fremder Prozess). MORF_BACKEND_PORT in .env ändern."
  fi
  hintergrund "$BACKEND_DIR" "$BACKEND_LOG" "$BACKEND_PID" "$VENV_DIR/bin/uvicorn" app.main:app \
      --host "$BACKEND_HOST" --port "$BACKEND_PORT" --reload --reload-dir app
  local i
  for i in $(seq 1 40); do
    if curl -fsS "http://$BACKEND_HOST:$BACKEND_PORT/api/system/health" >/dev/null 2>&1; then
      ok "Backend läuft: http://$BACKEND_HOST:$BACKEND_PORT (Doku: /docs)"
      return 0
    fi
    sleep 0.5
  done
  warn "Backend antwortet noch nicht - siehe $BACKEND_LOG"
}

# ---------------------------------------------------------------------------
# Transkriptionsdienst (eigenes uv-venv, Whisper) - hilfsdienste/transkription
# ---------------------------------------------------------------------------
transkription_extra() {
  # Apple Silicon: MLX (Grafikeinheit); alle anderen Rechner: CTranslate2 (Prozessor oder CUDA)
  if [ "$(uname -s)" = "Darwin" ] && [ "$(uname -m)" = "arm64" ]; then echo "mlx"; else echo "cpu"; fi
}

transkription_deps() {
  command -v uv >/dev/null 2>&1 || die "uv fehlt (brew install uv)."
  if [ ! -d "$TRANSKRIPTION_VENV" ]; then
    info "Lege Python-Umgebung des Transkriptionsdienstes an ..."
    (cd "$TRANSKRIPTION_DIR" && uv venv --quiet --python 3.12 "$TRANSKRIPTION_VENV")
  fi
  (cd "$TRANSKRIPTION_DIR" && uv pip install --quiet --python "$TRANSKRIPTION_VENV/bin/python" -e ".[$(transkription_extra),dev]")
  ok "Transkriptionsdienst-Abhängigkeiten aktuell (Engine $(transkription_extra))"
}

transkription_stop() {
  # Beendet den gemerkten Prozess und jeden weiteren Server des Dienstes (etwa einen, der nach einem
  # früheren Stop noch eine laufende Transkription zu Ende bringt); Arbeiterprozesse enden mit ihrem Server.
  local pid pids
  pids="$(pgrep -f "$TRANSKRIPTION_VENV/bin/uvicorn app.main:app" 2>/dev/null || true)"
  if pid="$(read_pid "$TRANSKRIPTION_PID")" && pid_alive "$pid"; then pids="$pids $pid"; fi
  if [ -n "${pids// /}" ]; then
    for pid in $pids; do kill "$pid" 2>/dev/null || true; done
    local i
    for i in $(seq 1 12); do
      sleep 0.5
      pid_alive_einer=0
      for pid in $pids; do pid_alive "$pid" && pid_alive_einer=1; done
      [ "$pid_alive_einer" = 0 ] && break
    done
    for pid in $pids; do pid_alive "$pid" && kill -9 "$pid" 2>/dev/null || true; done
    ok "Transkriptionsdienst gestoppt"
  fi
  rm -f "$TRANSKRIPTION_PID"
}

transkription_start() {
  transkription_stop
  if port_belegt "$TRANSKRIPTION_PORT"; then
    die "Port $TRANSKRIPTION_PORT ist belegt (fremder Prozess). MORF_TRANSKRIPTION_PORT in .env ändern."
  fi
  [ -d "$TRANSKRIPTION_VENV" ] || transkription_deps
  # Beim Stoppen wartet der Server höchstens 5 Sekunden auf laufende Transkriptionen; das Backend
  # wiederholt einen abgebrochenen Auftrag von selbst.
  hintergrund "$TRANSKRIPTION_DIR" "$TRANSKRIPTION_LOG" "$TRANSKRIPTION_PID" "$TRANSKRIPTION_VENV/bin/uvicorn" app.main:app \
      --host "$TRANSKRIPTION_HOST" --port "$TRANSKRIPTION_PORT" --timeout-graceful-shutdown 5
  local i
  for i in $(seq 1 60); do
    if curl -fsS "http://$TRANSKRIPTION_HOST:$TRANSKRIPTION_PORT/health" >/dev/null 2>&1; then
      ok "Transkriptionsdienst läuft: http://$TRANSKRIPTION_HOST:$TRANSKRIPTION_PORT (Modell lädt im Hintergrund, beim ersten Mal aus dem Netz)"
      return 0
    fi
    sleep 0.5
  done
  warn "Transkriptionsdienst antwortet noch nicht - siehe $TRANSKRIPTION_LOG"
}

transkription_status() {
  local pid
  if [ "$TRANSKRIPTION_AKTIV" != "true" ]; then info "Transkriptionsdienst nicht aktiv (MORF_TRANSKRIPTION_AKTIV)"; return 0; fi
  if pid="$(read_pid "$TRANSKRIPTION_PID")" && pid_alive "$pid"; then
    ok "Transkriptionsdienst läuft (PID $pid, Port $TRANSKRIPTION_PORT): $(curl -fsS "http://$TRANSKRIPTION_HOST:$TRANSKRIPTION_PORT/health" 2>/dev/null || echo 'antwortet nicht')"
  else
    warn "Transkriptionsdienst aus"
  fi
}

# ---------------------------------------------------------------------------
# Oberfläche (Vite)
# ---------------------------------------------------------------------------
frontend_deps() {
  command -v npm >/dev/null 2>&1 || die "npm fehlt."
  if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
    info "Installiere Oberflächen-Abhängigkeiten ..."
    (cd "$FRONTEND_DIR" && npm install --no-audit --no-fund --loglevel=error)
  fi
  ok "Oberflächen-Abhängigkeiten aktuell"
}

frontend_stop() {
  local pid
  if pid="$(read_pid "$FRONTEND_PID")" && pid_alive "$pid"; then
    kill "$pid" 2>/dev/null || true
    sleep 1
    pid_alive "$pid" && kill -9 "$pid" 2>/dev/null || true
    ok "Oberfläche gestoppt"
  fi
  rm -f "$FRONTEND_PID"
}

frontend_start() {
  frontend_stop
  if port_belegt "$FRONTEND_PORT"; then
    die "Port $FRONTEND_PORT ist belegt (fremder Prozess). MORF_FRONTEND_PORT in .env ändern."
  fi
  MORF_BACKEND_PORT="$BACKEND_PORT" MORF_FRONTEND_PORT="$FRONTEND_PORT" \
    hintergrund "$FRONTEND_DIR" "$FRONTEND_LOG" "$FRONTEND_PID" npm run dev -- --host 127.0.0.1 --port "$FRONTEND_PORT" --strictPort
  local i
  for i in $(seq 1 40); do
    if curl -fsS "http://127.0.0.1:$FRONTEND_PORT/" >/dev/null 2>&1; then
      ok "Oberfläche läuft: http://127.0.0.1:$FRONTEND_PORT"
      return 0
    fi
    sleep 0.5
  done
  warn "Oberfläche antwortet noch nicht - siehe $FRONTEND_LOG"
}

status() {
  db_status
  transkription_status
  local pid
  if pid="$(read_pid "$BACKEND_PID")" && pid_alive "$pid"; then ok "Backend läuft (PID $pid, Port $BACKEND_PORT)"; else warn "Backend aus"; fi
  if pid="$(read_pid "$FRONTEND_PID")" && pid_alive "$pid"; then ok "Oberfläche läuft (PID $pid, Port $FRONTEND_PORT)"; else warn "Oberfläche aus"; fi
}

transkription_wenn_aktiv() { if [ "$TRANSKRIPTION_AKTIV" = "true" ]; then "$@"; fi; }

env_sicherstellen
case "${1:-start}" in
  start)    db_start; backend_deps; migrate; frontend_deps; transkription_wenn_aktiv transkription_deps
            transkription_wenn_aktiv transkription_start; backend_start; frontend_start ;;
  stop)     frontend_stop; backend_stop; transkription_stop ;;
  restart)  frontend_stop; backend_stop; transkription_stop; transkription_wenn_aktiv transkription_start; backend_start; frontend_start ;;
  status)   status ;;
  logs)     tail -n 40 -f "$BACKEND_LOG" "$FRONTEND_LOG" "$TRANSKRIPTION_LOG" ;;
  setup)    backend_deps; frontend_deps; transkription_wenn_aktiv transkription_deps ;;
  db)       db_start ;;
  migrate)  migrate ;;
  backend)  backend_start ;;
  frontend) frontend_start ;;
  transkription) transkription_deps; transkription_start ;;
  *) echo "Nutzung: $0 [start|stop|restart|status|logs|setup|db|migrate|backend|frontend|transkription]"; exit 1 ;;
esac

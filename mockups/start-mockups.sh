#!/usr/bin/env bash
# Mockup-Viewer steuern:  ./start-mockups.sh [start|stop|restart|status] [port]
#
# Baut das Bootstrap-Thema aus frontend/src/bootstrap.scss nach mockups/bootstrap.css
# und startet einen statischen Server im Hintergrund, der die PROJEKTWURZEL ausliefert -
# so laden die Mockups Schrift, Icons und app.css direkt aus dem Frontend-Ordner.
# Es läuft höchstens EINE Instanz; PID und Port stehen unter mockups/.run/.
set -uo pipefail

HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"   # .../mockups
WURZEL="$(cd "$HIER/.." && pwd)"                         # Projektwurzel
RUN="$HIER/.run"; mkdir -p "$RUN"
PIDF="$RUN/mockups.pid"; PORTF="$RUN/mockups.port"; LOG="$RUN/mockups.log"

lebt() { [ -f "$PIDF" ] && kill -0 "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; }
stop() { [ -f "$PIDF" ] && kill "$(cat "$PIDF" 2>/dev/null)" 2>/dev/null; rm -f "$PIDF" "$PORTF"; }

bauen() {
  if [ ! -d "$WURZEL/frontend/node_modules" ]; then
    (cd "$WURZEL/frontend" && npm install --no-audit --no-fund --loglevel=error)
  fi
  (cd "$WURZEL/frontend" && npm run -s stil:mockups) || { echo "Thema konnte nicht gebaut werden"; exit 1; }
}

start() {
  stop
  bauen
  nohup python3 -m http.server "$PORT" --bind 127.0.0.1 --directory "$WURZEL" > "$LOG" 2>&1 &
  echo "$!" > "$PIDF"; echo "$PORT" > "$PORTF"; sleep 0.4
  if lebt; then
    echo "Mockup-Viewer läuft auf Port $PORT (PID $(cat "$PIDF"))"
    echo "  Galerie: http://127.0.0.1:$PORT/mockups/index.html"
  else
    echo "Start fehlgeschlagen - Protokoll: $LOG"; tail -n 3 "$LOG" 2>/dev/null; exit 1
  fi
}

CMD=""; PORT_ARG=""
for arg in "$@"; do
  case "$arg" in
    start|stop|restart|status) CMD="$arg" ;;
    *[!0-9]*|'') echo "Nutzung: $0 [start|stop|restart|status] [port]"; exit 1 ;;
    *) PORT_ARG="$arg" ;;
  esac
done
CMD="${CMD:-start}"
if [ -n "$PORT_ARG" ]; then PORT="$PORT_ARG"
elif [ -f "$PORTF" ]; then PORT="$(cat "$PORTF")"
else PORT="${MOCKUP_PORT:-6460}"; fi

case "$CMD" in
  start|restart) start ;;
  stop)   stop; echo "Mockup-Viewer gestoppt" ;;
  status) if lebt; then echo "läuft auf Port $PORT (PID $(cat "$PIDF"))"; else echo "aus"; fi ;;
esac

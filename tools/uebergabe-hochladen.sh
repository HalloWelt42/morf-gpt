#!/usr/bin/env bash
#
# Lädt einen Übergabeordner (data/uebergabe/<kennung>) auf einen Webspace, über SFTP/SSH.
# Der Ordner landet unter <ZIEL>/<kennung>/ samt einer .htaccess, die Verzeichnislisten
# abschaltet und Suchmaschinen fernhält. Die Kennung im Pfad ist der Zugang.
#
# Nutzung: tools/uebergabe-hochladen.sh <kennung> <nutzer@host> <zielpfad-auf-dem-server> [port]
# Beispiel: tools/uebergabe-hochladen.sh 8b415956-... hosting123@beispiel.de httpdocs/morf
#
# Danach lautet die Adresse für den Empfänger: https://<domain>/<zielpfad ohne httpdocs>/<kennung>/
#
# Voraussetzungen: ssh/sftp-Zugang mit Schlüssel oder Passwort (das Skript fragt nie selbst nach
# Zugangsdaten, das tut ssh). rsync wird benutzt, wenn es auf beiden Seiten vorhanden ist (setzt
# abgebrochene Uploads fort); sonst sftp mit Wiederaufnahme über "reput".
set -euo pipefail

KENNUNG="${1:?Kennung der Übergabe fehlt}"
ZIELHOST="${2:?nutzer@host fehlt}"
ZIELPFAD="${3:?Zielpfad auf dem Server fehlt}"
PORT="${4:-22}"

WURZEL="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
QUELLE="$WURZEL/data/uebergabe/$KENNUNG"
[ -f "$QUELLE/uebergabe.json" ] || { echo "Kein Übergabeordner: $QUELLE" >&2; exit 1; }

HTACCESS="$(mktemp)"
cat > "$HTACCESS" <<'HT'
# morf-gpt Übergabe: keine Verzeichnisliste, keine Suchmaschinen, große Dateien mit Bereichen
Options -Indexes
<IfModule mod_headers.c>
  Header set X-Robots-Tag "noindex, nofollow, noarchive"
  Header set Accept-Ranges "bytes"
</IfModule>
<IfModule mod_mime.c>
  AddType application/octet-stream .tar
  AddType application/gzip .gz
  AddType application/json .json
  AddType text/markdown .md
  AddType text/plain .sha256
</IfModule>
HT

echo "[i] Lade $QUELLE nach $ZIELHOST:$ZIELPFAD/$KENNUNG/ (Port $PORT)"
if command -v rsync >/dev/null 2>&1 && ssh -p "$PORT" "$ZIELHOST" 'command -v rsync >/dev/null 2>&1'; then
  ssh -p "$PORT" "$ZIELHOST" "mkdir -p '$ZIELPFAD/$KENNUNG'"
  rsync -av --partial --progress -e "ssh -p $PORT" "$HTACCESS" "$ZIELHOST:$ZIELPFAD/$KENNUNG/.htaccess"
  rsync -av --partial --progress -e "ssh -p $PORT" "$QUELLE/" "$ZIELHOST:$ZIELPFAD/$KENNUNG/"
else
  echo "[i] rsync fehlt auf einer Seite, nutze sftp (Wiederaufnahme mit reput)"
  {
    echo "-mkdir $ZIELPFAD"
    echo "-mkdir $ZIELPFAD/$KENNUNG"
    echo "cd $ZIELPFAD/$KENNUNG"
    echo "put $HTACCESS .htaccess"
    echo "reput $QUELLE/* ."
    echo "bye"
  } | sftp -P "$PORT" -b - "$ZIELHOST"
fi
rm -f "$HTACCESS"
echo "[ok] Hochgeladen. Prüfung: curl -sI https://<domain>/<pfad>/$KENNUNG/uebergabe.json (HTTP 200) und https://<domain>/<pfad>/$KENNUNG/ (403, keine Liste)"

#!/usr/bin/env bash
# Zentrale Versionierung. Schema: vMAJOR.MINOR.PATCH-<id>.
# Einzige Wahrheit: version.json im Projektwurzelverzeichnis.
# Nutzung: tools/version.sh [patch|minor|major|id]   (Standard: patch)
#   patch/minor/major - Nummer hochzählen und neue id vergeben
#   id                - Nummer unverändert, nur neue Build-id
set -euo pipefail
HIER="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
DATEI="$HIER/version.json"
TEIL="${1:-patch}"
ID="$(openssl rand -hex 3)"

python3 - "$DATEI" "$TEIL" "$ID" <<'PY'
import json, sys
datei, teil, neue_id = sys.argv[1], sys.argv[2], sys.argv[3]
try:
    d = json.load(open(datei))
except Exception:
    d = {}
teile = str(d.get("version", "0.0.0")).split("-")[0].split(".")
while len(teile) < 3:
    teile.append("0")
major, minor, patch = (int(x) for x in teile[:3])
if teil == "major":
    major, minor, patch = major + 1, 0, 0
elif teil == "minor":
    minor, patch = minor + 1, 0
elif teil == "patch":
    patch += 1
version = f"{major}.{minor}.{patch}"
neu = {"version": version, "id": neue_id, "voll": f"v{version}-{neue_id}"}
with open(datei, "w") as f:
    json.dump(neu, f, ensure_ascii=False)
    f.write("\n")
print(neu["voll"])
PY

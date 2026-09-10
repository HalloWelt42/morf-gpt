# morf-gpt

Wissensbibliothek und Chat über die Erklärvideos des Kanals morf: Audios werden bezogen,
transkribiert, behutsam korrigiert, in große Stücke zerlegt, eingebettet und im Chat
befragt. Jede Antwort belegt ihre Stellen mit Video, Zeitfenster und Sprung ins Audio.

Die Architektur steht in [docs/ARCHITEKTUR.md](docs/ARCHITEKTUR.md).

## Start

```bash
./start.sh start
```

Datenbank (PostgreSQL mit pgvector) läuft im Docker-Container, Backend (FastAPI) und
Oberfläche (Svelte) direkt auf dem Rechner. Adressen stehen nach dem Start in der Konsole.

## Lizenz

**Nicht-kommerzielle Nutzung** - Siehe [LICENSE](LICENSE)

Erlaubt: Private Nutzung, Installation, persönliche Anpassungen, Teilen mit Quellenangabe

Verboten: Kommerzielle Nutzung, Verkauf, Einbindung in kommerzielle Produkte

---

## Unterstützen

morf-gpt ist ein privates Hobby-Projekt. Kein Tracking, keine Werbung, keine Kompromisse.

Wenn dir das Projekt gefällt, kannst du die Weiterentwicklung unterstützen - oder direkt hier:

[![Ko-fi](https://ko-fi.com/img/githubbutton_sm.svg)](https://ko-fi.com/HalloWelt42)

**Crypto:**

| Coin | Adresse |
|------|---------|
| BTC | `bc1qnd599khdkv3v3npmj9ufxzf6h4fzanny2acwqr` |
| DOGE | `DL7tuiYCqm3xQjMDXChdxeQxqUGMACn1ZV` |
| ETH | `0x8A28fc47bFFFA03C8f685fa0836E2dBe1CA14F27` |

Copyright (c) 2025-2026 HalloWelt42

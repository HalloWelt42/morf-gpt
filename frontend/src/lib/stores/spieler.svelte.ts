// Audiospieler: ein Video, eine Position, Themen für die Zeitleiste. Lebt über alle
// Ansichten hinweg (Leiste am unteren Rand). Das <audio>-Element hält die Komponente.

export interface SpielerThema {
  titel: string;
  start_s: number;
  end_s: number;
}

export interface SpielerVideo {
  id: string;
  titel: string;
  serie: string;
  folge_nr: number | null;
  dauer_s: number;
  original_url: string;
  themen: SpielerThema[];
}

class Spieler {
  video = $state<SpielerVideo | null>(null);
  position = $state(0);
  laeuft = $state(false);
  tempo = $state(1);
  /** Wunschposition, die die Komponente beim nächsten Tick übernimmt. */
  sprungZiel = $state<number | null>(null);
  ladefehler = $state("");

  /** Video laden und ab Sekunde abspielen. Gleiches Video: nur springen. */
  spiele(video: SpielerVideo, abSekunde = 0): void {
    if (!this.video || this.video.id !== video.id) {
      this.video = video;
      this.position = abSekunde;
    }
    this.sprungZiel = abSekunde;
    this.laeuft = true;
    this.ladefehler = "";
  }

  springe(sekunden: number): void {
    if (!this.video) return;
    const ziel = Math.max(0, Math.min(this.video.dauer_s || Number.MAX_SAFE_INTEGER, sekunden));
    this.sprungZiel = ziel;
  }

  relativ(delta: number): void {
    this.springe(this.position + delta);
  }

  umschalten(): void {
    this.laeuft = !this.laeuft;
  }

  schliessen(): void {
    this.laeuft = false;
    this.video = null;
    this.position = 0;
    this.sprungZiel = null;
  }

  get quelle(): string {
    return this.video ? `/api/audio/${this.video.id}` : "";
  }

  get aktuellesThema(): SpielerThema | null {
    if (!this.video) return null;
    return this.video.themen.find((t) => this.position >= t.start_s && this.position < t.end_s) ?? null;
  }
}

export const spieler = new Spieler();

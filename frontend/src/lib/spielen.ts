// Ein Video im Spieler starten: holt einmalig Dauer und Themen aus dem Backend.
import { api } from "./api";
import { spieler, type SpielerVideo } from "./stores/spieler.svelte";
import { meldeFehler } from "./stores/meldungen.svelte";
import type { VideoDetail } from "./typen";

const zwischenspeicher = new Map<string, SpielerVideo>();

export async function spieleVideo(videoId: string, abSekunde = 0): Promise<void> {
  let v = zwischenspeicher.get(videoId);
  if (!v) {
    try {
      const d = await api.get<VideoDetail>(`/videos/${videoId}`);
      if (!d.hat_audio) {
        meldeFehler(new Error("Für dieses Video liegt noch kein Audio vor"), "Abspielen");
        return;
      }
      v = {
        id: d.id,
        titel: d.titel,
        serie: d.serie,
        folge_nr: d.folge_nr,
        dauer_s: d.audio?.dauer_s ?? d.dauer_s ?? 0,
        original_url: d.original_url,
        themen: (d.korrektur?.themen ?? []).map((t) => ({ titel: t.titel, start_s: t.start_s, end_s: t.end_s })),
      };
      zwischenspeicher.set(videoId, v);
    } catch (e) {
      meldeFehler(e, "Abspielen");
      return;
    }
  }
  spieler.spiele(v, abSekunde);
}

export function spielerVergessen(videoId: string): void {
  zwischenspeicher.delete(videoId);
}

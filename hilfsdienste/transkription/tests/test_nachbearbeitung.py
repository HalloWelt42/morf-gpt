from app.engines.basis import Segment, Wort
from app.nachbearbeitung import Blockregeln, bereinigen, ist_halluzination, nachbearbeiten, volltext, zusammenfuehren


def s(start: float, end: float, text: str) -> Segment:
    return Segment(start, end, text, [Wort(w, start, end) for w in text.split()])


def test_halluzinationen_erkannt():
    assert ist_halluzination("", "")
    assert ist_halluzination("Danke.", "Danke.")
    assert ist_halluzination("ja ja ja ja ja ja ja ja", "")
    assert ist_halluzination("Untertitel von Sender", "")
    assert not ist_halluzination("Untertitel von Sender " + "und ein ganz normaler langer Satz, der weitergeht und weitergeht.", "")
    assert not ist_halluzination("Das ist ein normaler Satz.", "Ein anderer Satz.")


def test_bereinigen_entfernt_nur_treffer():
    aus = bereinigen([s(0, 1, "Hallo."), s(1, 2, "Hallo."), s(2, 3, ""), s(3, 4, "Weiter geht es.")])
    assert [x.text for x in aus] == ["Hallo.", "Weiter geht es."]


def test_zusammenfuehren_min_max_und_pause():
    regeln = Blockregeln(min_s=6, max_s=15, pause_s=0.3)
    segmente = [s(0, 3, "A"), s(3, 6.5, "B"), s(7, 9, "C"), s(9, 25, "D"), s(25, 26, "E")]
    bloecke = zusammenfuehren(segmente, regeln)
    # A+B (6,5 s, dann Pause 0,5 s) | C+D (D überschreitet max, danach Schnitt) | E
    assert [b.text for b in bloecke] == ["A B", "C D", "E"]
    assert bloecke[0].start == 0 and bloecke[0].end == 6.5
    assert [w.wort for w in bloecke[0].woerter] == ["A", "B"]


def test_nachbearbeiten_und_volltext():
    bloecke = nachbearbeiten([s(0, 1, "Eins."), s(1, 2, "Eins."), s(2, 3, "Zwei.")], Blockregeln())
    assert volltext(bloecke) == "Eins. Zwei."
    assert zusammenfuehren([], Blockregeln()) == []

from app.dienste.quellen.abgleich import Auswahlregeln, ist_im_umfang
from app.dienste.quellen.basis import QuellVideo

WERTE = {"quelle.mindest_dauer_s": 300, "quelle.hoechst_dauer_s": 0, "quelle.typen": "video,live", "quelle.nur_heruntergeladene": False}


def video(dauer: int | None, typ: str = "video", heruntergeladen: bool = True) -> QuellVideo:
    return QuellVideo(extern_id="x", titel="t", dauer_s=dauer, typ=typ, heruntergeladen=heruntergeladen)


def test_mindestdauer_und_ohne_hoechstdauer():
    r = Auswahlregeln.aus_werten(WERTE)
    assert r.hoechst_dauer_s == 0
    assert not ist_im_umfang(video(300), r)
    assert ist_im_umfang(video(301), r)
    assert ist_im_umfang(video(20 * 3600), r), "0 heißt keine Grenze"
    assert not ist_im_umfang(video(None), r)


def test_hoechstdauer_aus_einstellung_und_je_quelle():
    r = Auswahlregeln.aus_werten({**WERTE, "quelle.hoechst_dauer_s": 3600})
    assert ist_im_umfang(video(3600), r)
    assert not ist_im_umfang(video(3601), r)
    eigene = Auswahlregeln.aus_werten({**WERTE, "quelle.hoechst_dauer_s": 3600}, {"hoechst_dauer_s": 0})
    assert ist_im_umfang(video(3601), eigene), "eine Quelle darf die Grenze auf 0 (keine) setzen"
    eigene = Auswahlregeln.aus_werten(WERTE, {"hoechst_dauer_s": 600, "mindest_dauer_s": 60})
    assert ist_im_umfang(video(61), eigene) and not ist_im_umfang(video(601), eigene)


def test_art_und_downloadstand_bleiben():
    r = Auswahlregeln.aus_werten({**WERTE, "quelle.nur_heruntergeladene": True})
    assert not ist_im_umfang(video(400, typ="short"), r)
    assert not ist_im_umfang(video(400, heruntergeladen=False), r)

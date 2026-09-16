from app.dienste.einbettung.familie import familie, gleiche_familie


def test_familie_erkennt_bge_m3_unter_allen_namen():
    for name in ("text-embedding-bge-m3", "BAAI/bge-m3", "bge-m3", "bge-m3-gguf", "bge-m3@q8_0", "gpustack/bge-m3-GGUF"):
        assert familie(name) == "bge-m3", name
    assert gleiche_familie("text-embedding-bge-m3", "BAAI/bge-m3")
    assert not gleiche_familie("BAAI/bge-m3", "intfloat/multilingual-e5-large")
    assert familie("intfloat/multilingual-e5-large") == "multilingual-e5-large"
    assert familie("Unbekanntes-Modell") == "unbekanntes-modell"

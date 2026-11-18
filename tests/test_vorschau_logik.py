"""0.4.2: Fensterposition, Seitenraster, Drehwinkel, Bild-Cache (ohne Qt/Windows)."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent.parent))
from core import vorschau_logik as vl  # noqa: E402

BILDSCHIRM = (0, 0, 1920, 1040)
ZWEITER = (1920, 0, 2560, 1400)                      # rechter Monitor


def test_fenster_bleibt_immer_im_bildschirm():
    b, h = 700, 830
    for maus in [(5, 5), (1915, 1035), (960, 520), (1900, 10), (10, 1030)]:
        x, y = vl.fenster_position(maus, (b, h), BILDSCHIRM)
        assert 0 <= x and x + b <= 1920 and 0 <= y and y + h <= 1040, maus
    x, y = vl.fenster_position((100, 500), (b, h), BILDSCHIRM)
    assert x >= 100                                     # rechts neben der Maus, wenn Platz
    x, y = vl.fenster_position((1800, 500), (b, h), BILDSCHIRM)
    assert x + b <= 1800                                # sonst links von der Maus
    x, y = vl.fenster_position((3000, 700), (b, h), ZWEITER)
    assert 1920 <= x and x + b <= 1920 + 2560           # auf dem Monitor der Maus
    x, y = vl.fenster_position((50, 50), (3000, 2000), BILDSCHIRM)
    assert (x, y) == (0, 0)                             # größer als der Bildschirm → an die Ecke


def test_vorschau_groesse_80_prozent():
    b, h = vl.vorschau_groesse(1040, 0.7071)
    assert h == 832 and b == int(832 * 0.7071)
    b, h = vl.vorschau_groesse(1040, 1.414, bildschirm_breite=1000)   # Querformat auf schmalem Schirm
    assert b <= 900


def test_seitenraster_ein_und_mehrseitig():
    r1 = vl.seiten_raster(1, 600, 700)
    assert (r1.spalten, r1.zeilen, r1.rollen) == (1, 1, False) and r1.kachel_b > 450
    r2 = vl.seiten_raster(2, 1100, 700)
    assert (r2.spalten, r2.zeilen) == (2, 1) and not r2.rollen          # nebeneinander
    r4 = vl.seiten_raster(4, 1100, 1400)
    assert (r4.spalten, r4.zeilen) == (2, 2) and not r4.rollen          # 2×2
    r3 = vl.seiten_raster(3, 1100, 1400)
    assert r3.spalten * r3.zeilen >= 3 and r3.kachel_b >= 260
    viele = vl.seiten_raster(20, 600, 700)
    assert viele.rollen and viele.kachel_b >= 260                       # lesbar statt winzig → scrollen
    for n in range(1, 9):                                               # nie größer als die Fläche
        r = vl.seiten_raster(n, 800, 600)
        assert r.kachel_b <= 800 and (r.rollen or r.kachel_h <= 600)


def test_drehen_volle_runde_links_rechts_mehrere_seiten():
    w = 0
    folge = []
    for _ in range(4):
        w = vl.drehen(w, 1)
        folge.append(w)
    assert folge == [90, 180, 270, 0]
    assert vl.drehen(0, -1) == 270 and vl.drehen(90, -1) == 0
    offen = {}
    for _ in range(3):                                                  # drei schnelle Klicks, nichts geht verloren
        offen = vl.drehungen_sammeln(offen, [0, 2], +1)
    offen = vl.drehungen_sammeln(offen, [2], -1)
    assert offen == {0: 3, 2: 2}
    assert vl.endwinkel({0: 0, 2: 180}, offen) == {0: 270, 2: 0}         # jede Seite ab ihrem eigenen Winkel


def test_bild_cache_grenze_und_lru():
    c = vl.BildCache(max_bytes=100)
    c.put(("a", 1), "A1", 40)
    c.put(("a", 2), "A2", 40)
    assert c.get(("a", 1)) == "A1"                                      # A1 jetzt zuletzt benutzt
    c.put(("b", 1), "B1", 40)                                           # verdrängt A2
    assert c.get(("a", 2)) is None and c.get(("a", 1)) == "A1" and c.belegt <= 100
    c.put(("x", 9), "riesig", 500)
    assert c.get(("x", 9)) is None and c.belegt <= 100
    c.entfernen(("a",))
    assert c.get(("a", 1)) is None and len(c) == 1

"""Önizleme hesapları (0.4.2) – Qt/Windows olmadan test edilir.

- `fenster_position`: büyük önizleme penceresi fareye yakın, ama her zaman ekranın içinde (çok monitör: fareyi
  içeren ekranın alanı verilir).
- `seiten_raster`: „Vorschau“ alanında sayfaları mümkün olan en büyük boyutta dizmek (tek sayfa alanı doldurur,
  2 sayfa yan yana, 3–4 sayfa 2×2 …); okunamayacak kadar küçülürse kaydırmalı görünüm.
- `drehen`: art arda basışlarda açıyı doğru toplamak (her sayfa kendi açısından ±90°).
- `BildCache`: render edilmiş sayfalar için bellek sınırlı LRU önbellek.
"""
from __future__ import annotations

import math
from collections import OrderedDict
from dataclasses import dataclass


# ---------------------------------------------------------------- Fensterposition
def fenster_position(maus: tuple[int, int], groesse: tuple[int, int], bildschirm: tuple[int, int, int, int],
                     abstand: int = 18) -> tuple[int, int]:
    """Linke obere Ecke für ein Fenster der Größe `groesse` nahe der Maus im verfügbaren Bildschirmbereich
    `bildschirm` = (x, y, breite, hoehe). Bevorzugt rechts unten neben der Maus, sonst links/oben; immer ganz
    sichtbar. Ist das Fenster größer als der Bildschirm, wird es an die linke/obere Kante gelegt."""
    mx, my = maus
    b, h = groesse
    sx, sy, sb, sh = bildschirm
    x = mx + abstand
    if x + b > sx + sb:                         # rechts kein Platz → links von der Maus
        x = mx - abstand - b
    y = my - h // 3                              # leicht über der Maus, damit das Bild „neben“ dem Zeiger liegt
    x = max(sx, min(x, sx + sb - b))
    y = max(sy, min(y, sy + sh - h))
    return x, y


def vorschau_groesse(bildschirm_hoehe: int, seitenverhaeltnis: float, anteil: float = 0.8,
                     bildschirm_breite: int | None = None) -> tuple[int, int]:
    """Größe der großen Vorschau: ca. 80 % der Bildschirmhöhe, Seitenverhältnis (Breite/Höhe) der Seite."""
    h = int(bildschirm_hoehe * anteil)
    b = int(h * seitenverhaeltnis)
    if bildschirm_breite and b > bildschirm_breite * 0.9:
        b = int(bildschirm_breite * 0.9)
        h = int(b / seitenverhaeltnis)
    return b, h


# ---------------------------------------------------------------- Seitenraster
@dataclass
class Raster:
    spalten: int
    zeilen: int
    kachel_b: int                 # Bildgröße einer Seite (ohne Beschriftung)
    kachel_h: int
    rollen: bool                  # True: nicht alles passt lesbar hinein → senkrecht scrollen


def seiten_raster(anzahl: int, flaeche_b: int, flaeche_h: int, seitenverhaeltnis: float = 0.7071,
                  min_breite: int = 260, abstand: int = 12, beschriftung: int = 22) -> Raster:
    """Beste Anordnung von `anzahl` Seiten (Breite/Höhe = seitenverhaeltnis) in der Fläche.

    Alle Spaltenzahlen werden probiert; gewählt wird die mit der größten Seitengröße, bei der alle Seiten
    ohne Scrollen passen. Wird eine Seite dabei schmaler als `min_breite` (nicht mehr lesbar), wird stattdessen
    gescrollt: so viele Spalten, wie in Lesegröße nebeneinander passen, Höhe beliebig.
    """
    anzahl = max(anzahl, 1)
    flaeche_b, flaeche_h = max(flaeche_b, 50), max(flaeche_h, 50)
    bestes: Raster | None = None
    for spalten in range(1, anzahl + 1):
        zeilen = math.ceil(anzahl / spalten)
        b = (flaeche_b - abstand * (spalten + 1)) / spalten
        h = (flaeche_h - abstand * (zeilen + 1)) / zeilen - beschriftung
        if b <= 0 or h <= 0:
            continue
        kb = min(b, h * seitenverhaeltnis)               # Seitenverhältnis beibehalten
        kh = kb / seitenverhaeltnis
        if bestes is None or kb > bestes.kachel_b:
            bestes = Raster(spalten, zeilen, int(kb), int(kh), False)
    if bestes is not None and (bestes.kachel_b >= min_breite or anzahl == 1):
        return bestes
    # Scrollmodus: lesbare Größe, möglichst viele Spalten nebeneinander
    kb = min(max(min_breite, 1), flaeche_b - 2 * abstand)
    spalten = max(1, int((flaeche_b - abstand) // (kb + abstand)))
    kb = int((flaeche_b - abstand * (spalten + 1)) / spalten)
    return Raster(spalten, math.ceil(anzahl / spalten), kb, int(kb / seitenverhaeltnis), True)


# ---------------------------------------------------------------- Drehen
def drehen(winkel: int, schritte: int) -> int:
    """Neuer Winkel nach `schritte` × 90° (positiv = rechts/im Uhrzeigersinn, negativ = links). Immer 0/90/180/270."""
    return (int(winkel) + 90 * int(schritte)) % 360


def drehungen_sammeln(offen: dict[int, int], seiten: list[int], richtung: int) -> dict[int, int]:
    """Offene (noch nicht gespeicherte) Drehungen je Seite in Schritten aufsummieren – jede Betätigung zählt."""
    neu = dict(offen)
    for s in seiten:
        neu[s] = neu.get(s, 0) + (1 if richtung > 0 else -1)
    return neu


def endwinkel(start: dict[int, int], offen: dict[int, int]) -> dict[int, int]:
    """Endwinkel je Seite: jeder Seite ihr eigener Startwinkel + ihre Schritte."""
    return {s: drehen(start.get(s, 0), n) for s, n in offen.items()}


# ---------------------------------------------------------------- Cache
class BildCache:
    """LRU-Cache mit Speichergrenze (Bytes). Werte: beliebige Objekte; Größe wird übergeben."""

    def __init__(self, max_bytes: int = 160 * 1024 * 1024):
        self.max_bytes = max_bytes
        self._daten: OrderedDict = OrderedDict()
        self.belegt = 0

    def get(self, schluessel):
        if schluessel not in self._daten:
            return None
        self._daten.move_to_end(schluessel)
        return self._daten[schluessel][0]

    def put(self, schluessel, wert, groesse: int) -> None:
        if schluessel in self._daten:
            self.belegt -= self._daten.pop(schluessel)[1]
        if groesse > self.max_bytes:
            return                                       # zu groß für den Cache → nicht speichern
        self._daten[schluessel] = (wert, groesse)
        self.belegt += groesse
        while self.belegt > self.max_bytes and self._daten:
            _, (_, g) = self._daten.popitem(last=False)
            self.belegt -= g

    def entfernen(self, praefix) -> None:
        """Alle Einträge, deren Schlüssel (Tupel) mit `praefix` beginnt – z. B. nach einer Änderung der Anlage."""
        for k in [k for k in self._daten if isinstance(k, tuple) and k[:len(praefix)] == praefix]:
            self.belegt -= self._daten.pop(k)[1]

    def __len__(self):
        return len(self._daten)

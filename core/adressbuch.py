"""Versicherer-Adressbuch: sigorta adı -> bir veya birden fazla e-posta adresi.

Program adres defterini yalnızca avukatın onayladığı işlemlerden öğrenir.
Windows/Word'e bağımlı değildir; ad eşleştirme ve öneri mantığı burada test edilir.

Eşleştirme kuralı (bilerek katı tutuldu):
  * Büyük/küçük harf, umlaut (ä=ae), tire/nokta/boşluk farkları ve bilinen kısaltmalar
    ("Vers." = "Versicherung") yok sayılır.
  * Bunun dışında kelimeler birebir aynı olmalıdır. "Allianz Versicherungs-AG" ile
    "Allianz Lebensversicherungs-AG" farklı şirkettir ve asla birleştirilmez.
  * Hukuki biçim (AG, SE, VVaG …) farklıysa farklı şirkettir. Sadece bir tarafta hiç
    hukuki biçim yazmıyorsa eşleşme olabilir; birden fazla aday çıkarsa seçim kullanıcıya bırakılır.
"""
from __future__ import annotations

import re
import sqlite3
from dataclasses import dataclass, field
from datetime import datetime

# Hukuki biçimlerin yazım varyantları -> tek biçim (normalize edilmiş, noktasız metin üzerinde)
RECHTSFORMEN = {
    "ag": "ag", "aktiengesellschaft": "ag",
    "se": "se",
    "vvag": "vvag", "v v a g": "vvag", "a g": "vvag",
    "versicherungsverein auf gegenseitigkeit": "vvag",
    "gmbh": "gmbh", "gesellschaft mit beschraenkter haftung": "gmbh",
    "kgaa": "kgaa", "kg": "kg", "ohg": "ohg", "eg": "eg", "ev": "ev",
    "sa": "sa", "nv": "nv", "plc": "plc", "ltd": "ltd", "dac": "dac",
}

HINT_BRIEF = "aus Brief – bitte prüfen"
HINT_VORLAGE = "aus Vorlage"
HINT_BUCH = "aus Adressbuch – bitte prüfen"
HINT_WAEHLEN = "mehrere Adressen – bitte auswählen"
HINT_NICHT = "nicht gefunden"


def _umlaute(s: str) -> str:
    return (s.lower().replace("ä", "ae").replace("ö", "oe").replace("ü", "ue")
            .replace("ß", "ss"))


def _rechtsform_abtrennen(woerter: list[str]) -> tuple[list[str], str]:
    """Sondaki hukuki biçimi ayırır: ['allianz','versicherung','ag'] -> (['allianz','versicherung'], 'ag')."""
    for laenge in (4, 3, 2, 1):
        if len(woerter) > laenge:
            ende = " ".join(woerter[-laenge:])
            if ende in RECHTSFORMEN:
                return woerter[:-laenge], RECHTSFORMEN[ende]
    return woerter, ""


@dataclass(frozen=True)
class NamensSchluessel:
    basis: str          # hukuki biçim olmadan, ör. "fiktiva versicherung"
    form: str           # "ag" | "se" | "vvag" | … | ""

    @property
    def voll(self) -> str:
        return f"{self.basis}|{self.form}"


def _abkuerzungen_aufloesen(s: str, abkuerzungen: dict[str, str] | None) -> str:
    """Küçük harfli/umlautsuz metinde kısaltmaları açar: "vers. ag" -> " versicherung  ag"."""
    for kurz, lang in sorted((abkuerzungen or {}).items(), key=lambda kv: -len(kv[0])):
        k = re.escape(_umlaute(kurz))
        s = re.sub(rf"(?<![a-z0-9]){k}(?![a-z0-9])", f" {_umlaute(lang)} ", s)
    return s


def schluessel(name: str, abkuerzungen: dict[str, str] | None = None) -> NamensSchluessel:
    """Adın karşılaştırma anahtarı. Görünen ad değişmez; sadece karşılaştırmada kullanılır."""
    s = _umlaute(name)
    s = re.sub(r"\([^)]*\)", " ", s)                 # parantez içi ek bilgi: "(fiktiv)"
    s = re.sub(r"^\s*(firma|fa\.)\s+", "", s)
    # Kısaltmaları noktalı haliyle değiştir ("vers." -> "versicherung"), sonra noktalama sil
    s = _abkuerzungen_aufloesen(s, abkuerzungen)
    s = re.sub(r"[.\-–/&,+'’]", " ", s)
    woerter = [w for w in re.split(r"\s+", s) if w]
    # "Versicherungs-AG" -> "versicherungs ag" ; ek "s" farkı yok sayılır
    woerter = [w[:-1] if w.endswith("versicherungs") else w for w in woerter]
    basis, form = _rechtsform_abtrennen(woerter)
    return NamensSchluessel(" ".join(basis), form)


def passt(a: NamensSchluessel, b: NamensSchluessel) -> bool:
    if not a.basis or a.basis != b.basis:
        return False
    return a.form == b.form or not a.form or not b.form


# --- Sigorta adını mektuptan bulma ------------------------------------------

PLZ_ZEILE = re.compile(r"^(?:D\s*-\s*)?\d{5}\s+\S")
ZUSATZ_ZEILE = re.compile(
    r"^(per\s|vorab\s|z\.\s*hd|zu\s*h(ae|ä)nden|einschreiben|postfach|herrn?\b|frau\b)",
    re.IGNORECASE)


def _stichwort_muster(wort: str) -> re.Pattern:
    """Uzun anahtar kelime (>= 8 harf) kelime içinde de eşleşir ("Lebensversicherung"),
    kısa olanlar ("HDI", "AXA") sadece tam kelime olarak – yanlış eşleşmeyi önler."""
    w = re.escape(_umlaute(wort.strip()))
    return re.compile(w if len(wort.strip()) >= 8 else rf"(?<![a-z0-9]){w}(?![a-z0-9])")


def _zeilen(text: str) -> list[str]:
    # Word: \r paragraf, \x0b satır sonu (Shift+Enter), \x07 tablo hücresi
    return [z.strip() for z in re.split(r"[\r\n\x0b\x07]", text)]


def versicherer_aus_text(text: str, stichwoerter: list[str], kanzlei_name: str = "",
                         kanzlei_plz: str = "", abkuerzungen: dict[str, str] | None = None) -> str:
    """Adres bloğundaki sigorta adını bulur. Bulamazsa boş döner (tahmin yapmaz).

    Adres bloğu: "12345 Ort" satırıyla biten, boş satırla ayrılmış satır grubu.
    Büronun kendi adresi (Kanzlei adı veya posta kodu) atlanır.
    Sadece sigorta anahtar kelimesi içeren satır kabul edilir; "Ihr Zeichen" vb. satırlara bakılmaz.
    Kısaltmalar ("FIKTIVA Vers. AG") anahtar kelime aranırken açılır; döndürülen ad değişmez.
    """
    zeilen = _zeilen(text)
    stich = [_stichwort_muster(s) for s in stichwoerter if s.strip()]
    eigen = _umlaute(kanzlei_name).strip()
    for i, zeile in enumerate(zeilen):
        if not PLZ_ZEILE.match(zeile):
            continue
        if kanzlei_plz and zeile.replace(" ", "").lstrip("D-").startswith(kanzlei_plz.strip()):
            continue
        block: list[str] = []
        for j in range(i - 1, max(-1, i - 8), -1):
            if not zeilen[j]:
                break
            block.insert(0, zeilen[j])
        for z in block:
            if ZUSATZ_ZEILE.match(z) or len(z) > 90 or "@" in z:
                continue
            if eigen and eigen in _umlaute(z):
                continue                              # büronun kendi satırı
            z_norm = _abkuerzungen_aufloesen(_umlaute(z), abkuerzungen)
            if any(m.search(z_norm) for m in stich):
                return re.sub(r"^(firma|fa\.)\s+", "", z, flags=re.IGNORECASE).strip()
    return ""


def versicherer_erkennen(text: str, controls: dict[str, str], cfg: dict,
                         kanzlei_name: str = "", kanzlei_plz: str = "") -> tuple[str, str]:
    """(ad, ipucu). Önce şablondaki içerik denetimi, sonra adres bloğu."""
    feld = controls.get(cfg.get("feld_versicherer", "Versicherer"), "").strip()
    if feld:
        return feld, HINT_VORLAGE
    name = versicherer_aus_text(text, cfg.get("versicherer_stichwoerter", []),
                                kanzlei_name, kanzlei_plz, cfg.get("versicherer_abkuerzungen"))
    return (name, "erkannt – bitte prüfen") if name else ("", "nicht gefunden – bitte eintragen")


# --- E-posta önerisi --------------------------------------------------------

@dataclass
class EmailVorschlag:
    wert: str                                       # önceden seçili değer ("" = kullanıcı seçmeli)
    hint: str
    auswahl: list[tuple[str, str]] = field(default_factory=list)   # (adres, kaynak)
    muss_waehlen: bool = False


def email_vorschlag(brief_email: str, brief_hint: str, brief_kandidaten: list[str],
                    buch: list[tuple[str, str]]) -> EmailVorschlag:
    """Mektuptaki adres ile adres defterini birleştirir.

    buch: [(adres, kayıtlı_ad)], en son kullanılan önce.
    - Mektupta adres var, defterde yok/aynı  -> mektup adresi seçili
    - Mektup adresi defterdekilerden farklı  -> hiçbiri seçili değil, kullanıcı seçer
    - Mektupta adres yok, defterde 1 adres   -> o adres önerilir ("aus Adressbuch – bitte prüfen")
    - Mektupta adres yok, defterde >1 adres  -> kullanıcı seçer
    """
    auswahl: list[tuple[str, str]] = []
    gesehen: set[str] = set()

    def neu(adr: str, quelle: str) -> None:
        if adr and adr.lower() not in gesehen:
            gesehen.add(adr.lower())
            auswahl.append((adr, quelle))

    brief_quelle = HINT_VORLAGE if brief_hint == HINT_VORLAGE else HINT_BRIEF
    neu(brief_email, brief_quelle)
    for k in brief_kandidaten:
        neu(k, HINT_BRIEF)
    buch_adr = {a.lower() for a, _ in buch}
    for adr, name in buch:
        neu(adr, f"{HINT_BUCH} ({name})" if name else HINT_BUCH)

    if brief_email:
        if not buch or brief_email.lower() in buch_adr:
            return EmailVorschlag(brief_email, brief_hint, auswahl)
        return EmailVorschlag("", "Brief und Adressbuch weichen ab – bitte auswählen",
                              auswahl, muss_waehlen=True)
    if len(buch) == 1:
        return EmailVorschlag(buch[0][0], HINT_BUCH, auswahl)
    if len(buch) > 1:
        return EmailVorschlag("", HINT_WAEHLEN, auswahl, muss_waehlen=True)
    return EmailVorschlag("", HINT_NICHT, auswahl)


# --- Kayıt (SQLite, Journal ile aynı veritabanı) ----------------------------

SCHEMA = """
CREATE TABLE IF NOT EXISTS versicherer (
    id INTEGER PRIMARY KEY AUTOINCREMENT,
    name TEXT NOT NULL, email TEXT NOT NULL,
    angelegt TEXT, zuletzt TEXT, anzahl INTEGER DEFAULT 0);
"""


def _jetzt() -> str:
    return datetime.now().strftime("%Y-%m-%d %H:%M:%S")


class Adressbuch:
    def __init__(self, con: sqlite3.Connection, abkuerzungen: dict[str, str] | None = None):
        self.con = con
        self.abk = abkuerzungen or {}
        self.con.executescript(SCHEMA)
        self.con.commit()

    def _key(self, name: str) -> NamensSchluessel:
        return schluessel(name, self.abk)

    def alle(self) -> list[dict]:
        return [dict(r) for r in self.con.execute(
            "SELECT id, name, email, angelegt, zuletzt, anzahl FROM versicherer"
            " ORDER BY name COLLATE NOCASE, zuletzt DESC")]

    def treffer(self, name: str) -> list[dict]:
        """Bu ada uyan tüm kayıtlar, en son kullanılan önce."""
        k = self._key(name)
        if not k.basis:
            return []
        rows = [r for r in self.alle() if passt(k, self._key(r["name"]))]
        return sorted(rows, key=lambda r: r["zuletzt"] or "", reverse=True)

    def emails(self, name: str) -> list[tuple[str, str]]:
        return [(r["email"], r["name"]) for r in self.treffer(name)]

    def lernen(self, name: str, email: str) -> str:
        """Onaylanmış çifti kaydeder. Aynı şirket+adres varsa yeni satır açılmaz.

        Döndürür: "neu" | "aktualisiert" | "" (ad veya adres boşsa).
        """
        name, email = name.strip(), email.strip()
        if not name or not email:
            return ""
        jetzt = _jetzt()
        for r in self.treffer(name):
            if r["email"].lower() == email.lower():
                self.con.execute("UPDATE versicherer SET zuletzt = ?, anzahl = anzahl + 1"
                                 " WHERE id = ?", (jetzt, r["id"]))
                self.con.commit()
                return "aktualisiert"
        self.con.execute("INSERT INTO versicherer (name, email, angelegt, zuletzt, anzahl)"
                         " VALUES (?, ?, ?, ?, 1)", (name, email, jetzt, jetzt))
        self.con.commit()
        return "neu"

    def _doppelt(self, name: str, email: str, ausser_id: int | None) -> bool:
        k = self._key(name)
        return any(r["id"] != ausser_id and r["email"].lower() == email.lower()
                   and self._key(r["name"]) == k for r in self.alle())

    def hinzufuegen(self, name: str, email: str) -> int:
        name, email = name.strip(), email.strip()
        if self._doppelt(name, email, None):
            raise ValueError("Dieser Eintrag ist bereits vorhanden.")
        cur = self.con.execute("INSERT INTO versicherer (name, email, angelegt, zuletzt, anzahl)"
                               " VALUES (?, ?, ?, '', 0)", (name, email, _jetzt()))
        self.con.commit()
        return int(cur.lastrowid)

    def aendern(self, eintrag_id: int, name: str, email: str) -> None:
        name, email = name.strip(), email.strip()
        if self._doppelt(name, email, eintrag_id):
            raise ValueError(f"„{name}“ mit {email} ist bereits vorhanden.")
        self.con.execute("UPDATE versicherer SET name = ?, email = ? WHERE id = ?",
                         (name, email, eintrag_id))
        self.con.commit()

    def loeschen(self, eintrag_id: int) -> None:
        self.con.execute("DELETE FROM versicherer WHERE id = ?", (eintrag_id,))
        self.con.commit()

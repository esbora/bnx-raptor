"""Büro bilgileri (Kanzleidaten): ad, adres, vergi numarası, banka, logo …

Bir kez girilir, tüm iş akışları kullanır (imza, ileride antet, PDF altbilgisi).
Saklama: <daten_ordner>/kanzlei.json, logo: <daten_ordner>/logo.<uzantı>
"""
from __future__ import annotations

import html
import json
import re
import shutil
from dataclasses import asdict, dataclass, fields
from pathlib import Path


@dataclass
class Kanzlei:
    name: str = ""                      # "Rechtsanwaltskanzlei Muster"
    anwaelte: str = ""                  # her satıra bir avukat: "RA Max Muster, Fachanwalt für …"
    strasse: str = ""
    plz: str = ""
    ort: str = ""
    telefon: str = ""
    fax: str = ""
    email: str = ""
    website: str = ""
    steuernummer: str = ""
    ust_id: str = ""                    # USt-IdNr., ör. DE123456789
    kammer: str = ""                    # "Rechtsanwaltskammer Köln"
    berufsbezeichnung: str = "Rechtsanwalt (verliehen in der Bundesrepublik Deutschland)"
    bank: str = ""
    iban: str = ""
    bic: str = ""
    logo: str = ""                      # veri klasöründeki dosya adı, ör. "logo.png"

    @property
    def domain(self) -> str:
        return self.email.split("@", 1)[1].lower() if "@" in self.email else ""

    @property
    def ist_leer(self) -> bool:
        return not self.name.strip()


# --- Doğrulama (saf Python, test edilebilir) ---------------------------------

def iban_gueltig(iban: str) -> bool:
    """ISO 13616 mod-97 kontrolü. Boş IBAN geçerli sayılır (zorunlu alan değil)."""
    s = re.sub(r"\s+", "", iban).upper()
    if not s:
        return True
    if not re.fullmatch(r"[A-Z]{2}\d{2}[A-Z0-9]{11,30}", s):
        return False
    if s.startswith("DE") and len(s) != 22:
        return False
    num = "".join(str(int(c, 36)) for c in s[4:] + s[:4])
    return int(num) % 97 == 1


def iban_formatieren(iban: str) -> str:
    s = re.sub(r"\s+", "", iban).upper()
    return " ".join(s[i:i + 4] for i in range(0, len(s), 4))


def ust_id_gueltig(ust_id: str) -> bool:
    """Alman USt-IdNr. biçimi: DE + 9 rakam. Boş geçerli."""
    s = re.sub(r"\s+", "", ust_id).upper()
    return not s or bool(re.fullmatch(r"DE\d{9}", s))


def pruefen(k: Kanzlei) -> list[str]:
    """Kullanıcıya gösterilecek hata listesi (Almanca)."""
    fehler = []
    if not k.name.strip():
        fehler.append("Name der Kanzlei fehlt.")
    if k.email and not re.fullmatch(r"[^@\s]+@[^@\s]+\.[A-Za-z]{2,}", k.email.strip()):
        fehler.append("E-Mail-Adresse ist ungültig.")
    if not iban_gueltig(k.iban):
        fehler.append("IBAN ist ungültig (Prüfziffer stimmt nicht).")
    if not ust_id_gueltig(k.ust_id):
        fehler.append("USt-IdNr. muss das Format DE123456789 haben.")
    return fehler


# --- Saklama ------------------------------------------------------------------

class KanzleiStore:
    def __init__(self, ordner: Path):
        self.ordner = ordner
        self.ordner.mkdir(parents=True, exist_ok=True)
        self.datei = ordner / "kanzlei.json"

    def laden(self) -> Kanzlei:
        if not self.datei.exists():
            return Kanzlei()
        data = json.loads(self.datei.read_text(encoding="utf-8"))
        bekannt = {f.name for f in fields(Kanzlei)}
        return Kanzlei(**{k: v for k, v in data.items() if k in bekannt})

    def speichern(self, k: Kanzlei) -> None:
        k.iban = iban_formatieren(k.iban)
        k.ust_id = re.sub(r"\s+", "", k.ust_id).upper()
        tmp = self.datei.with_suffix(".tmp")
        tmp.write_text(json.dumps(asdict(k), ensure_ascii=False, indent=2), encoding="utf-8")
        tmp.replace(self.datei)                       # yarım yazılmış dosya kalmasın

    def logo_uebernehmen(self, quelle: Path) -> str:
        """Seçilen logoyu veri klasörüne kopyalar; orijinal taşınsa da logo kaybolmaz."""
        ziel = self.ordner / f"logo{quelle.suffix.lower()}"
        for alt in self.ordner.glob("logo.*"):
            if alt != ziel:
                alt.unlink()
        shutil.copyfile(quelle, ziel)
        return ziel.name

    def logo_pfad(self, k: Kanzlei) -> Path | None:
        if k.logo and (self.ordner / k.logo).exists():
            return self.ordner / k.logo
        return None


# --- E-posta imzası -----------------------------------------------------------

def signatur_html(k: Kanzlei, logo_cid: str | None = None) -> str:
    """Almanya'daki ticari e-posta zorunlu bilgilerini içeren HTML imza."""
    e = html.escape
    zeilen: list[str] = []
    if logo_cid:
        zeilen.append(f'<img src="cid:{logo_cid}" alt="{e(k.name)}" style="max-height:60px"><br>')
    zeilen.append(f"<b>{e(k.name)}</b>")
    zeilen += [e(a) for a in k.anwaelte.splitlines() if a.strip()]
    adresse = ", ".join(x for x in [k.strasse, f"{k.plz} {k.ort}".strip()] if x)
    if adresse:
        zeilen.append(e(adresse))
    kontakt = " · ".join(x for x in [
        f"Tel. {k.telefon}" if k.telefon else "", f"Fax {k.fax}" if k.fax else "",
        k.email, k.website] if x)
    if kontakt:
        zeilen.append(e(kontakt))
    klein: list[str] = []
    if k.berufsbezeichnung:
        klein.append(e(k.berufsbezeichnung))
    if k.kammer:
        klein.append(f"Zuständige Kammer: {e(k.kammer)}")
    if k.ust_id:
        klein.append(f"USt-IdNr.: {e(k.ust_id)}")
    elif k.steuernummer:
        klein.append(f"Steuernummer: {e(k.steuernummer)}")
    bank = " · ".join(x for x in [k.bank, f"IBAN {k.iban}" if k.iban else "",
                                   f"BIC {k.bic}" if k.bic else ""] if x)
    if bank:
        klein.append(e(bank))
    teil = "<br>".join(zeilen)
    if klein:
        teil += '<br><span style="font-size:8pt;color:#555">' + "<br>".join(klein) + "</span>"
    return f'<div style="font-family:Arial,sans-serif;font-size:10pt">-- <br>{teil}</div>'

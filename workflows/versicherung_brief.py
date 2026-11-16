"""İş akışı 1: Sigorta mektubu -> PDF/A -> e-posta taslağı (gönderilmez).

İsteğe bağlı: aynı PDF ile müvekkile ikinci bir taslak.
Her işlem sigorta numarasına bağlı bir dosyaya (Akte) kaydedilir.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from core.adressbuch import email_vorschlag, versicherer_erkennen
from core.entwurf import entwurf_erstellen
from core.extractor import extract, safe_filename
from core.mail_service import MailDraft
from core.word_service import WordService

from .base import Field, Result, Workflow


def unique_path(p: Path) -> Path:
    if not p.exists():
        return p
    i = 2
    while True:
        cand = p.with_name(f"{p.stem}_{i}{p.suffix}")
        if not cand.exists():
            return cand
        i += 1


def mandant_vorschlag(feld_wert: str, akte_wert: str) -> tuple[str, str]:
    """Müvekkil e-postası ve kaynağı: önce şablon alanı, sonra kayıtlı dosya (Akte)."""
    if feld_wert:
        return feld_wert, "aus Vorlage"
    if akte_wert:
        return akte_wert, "aus Akte"
    return "", "leer = keine Kopie"


class VersicherungBrief(Workflow):
    id = "versicherung_brief"
    name = "Schreiben an Versicherung → PDF → E-Mail-Entwurf"
    description = ("Liest Versicherer, E-Mail und Versicherungsnummer, erzeugt PDF/A und öffnet "
                   "einen Mail-Entwurf.")

    def prepare(self, path: Path) -> list[Field]:
        with WordService() as w:
            text, controls = w.read(path)
        return self.felder(text, controls)

    def felder(self, text: str, controls: dict[str, str]) -> list[Field]:
        """Kontrol penceresinin alanları (Word'süz; testlerde doğrudan çağrılır)."""
        r = extract(text, controls, dict(self.cfg, eigene_domains=self.ctx.eigene_domains()))
        hint = {"feld": "aus Vorlage", "text": "erkannt – bitte prüfen", "": "nicht gefunden"}
        k = self.ctx.kanzlei
        versicherer, versicherer_hint = versicherer_erkennen(text, controls, self.cfg, k.name, k.plz)

        def empfaenger_feld(name: str) -> Field:
            buch = self.ctx.adressbuch.emails(name) if name.strip() else []
            v = email_vorschlag(r.email, hint[r.quelle_email] if r.email else "",
                                r.email_candidates, buch)
            return Field("empfaenger", "Empfänger-E-Mail", v.wert, [a for a, _ in v.auswahl],
                         kind="email", hint=v.hint, choice_hints=dict(v.auswahl),
                         must_choose=v.muss_waehlen)

        # Dosya daha önce varsa müvekkil e-postası oradan önerilir
        akte = self.ctx.journal.akte(r.nummer) if r.nummer else None
        feld_mandant = controls.get(self.cfg.get("feld_mandant_email", "Mandant_Email"), "").strip()
        mandant, mandant_hint = mandant_vorschlag(feld_mandant, (akte or {}).get("mandant_email", ""))
        return [
            Field("versicherer", "Versicherer", versicherer, required=False, hint=versicherer_hint,
                  on_change=lambda name: [empfaenger_feld(name)]),
            empfaenger_feld(versicherer),
            Field("nummer", "Versicherungsnummer", r.nummer, hint=hint[r.quelle_nummer]),
            Field("mandant_email", "Kopie an Mandant (optional)", mandant, required=False,
                  kind="email", hint=mandant_hint),
        ]

    def pdf_path(self, path: Path, nummer: str) -> Path:
        folder = Path(self.cfg["pdf_ordner"]) if self.cfg.get("pdf_ordner") else path.parent
        name = self.cfg["pdf_dateiname"].format(
            datum=date.today().isoformat(), nummer=safe_filename(nummer),
            dokument=safe_filename(path.stem),
        )
        return unique_path(folder / f"{safe_filename(name, 150)}.pdf")

    def execute(self, path: Path, values: dict[str, str]) -> Result:
        empfaenger, nummer = values["empfaenger"].strip(), values["nummer"].strip()
        mandant = values.get("mandant_email", "").strip()
        pdf = self.pdf_path(path, nummer)
        with WordService() as w:
            w.export_pdf(path, pdf, pdfa=self.cfg.get("pdfa", True))

        self.ctx.journal.akte_speichern(nummer, ordner=str(path.parent),
                                        versicherer_email=empfaenger, mandant_email=mandant)

        msg = entwurf_erstellen(self.ctx, MailDraft(
            to=empfaenger,
            subject=self.cfg["betreff_vorlage"].format(nummer=nummer),
            html_body=self.cfg["mail_text_html"],
            attachments=[pdf],
        ), pdf.parent)

        if mandant:
            m = entwurf_erstellen(self.ctx, MailDraft(
                to=mandant,
                subject=self.cfg["mandant_betreff_vorlage"].format(nummer=nummer),
                html_body=self.cfg["mandant_text_html"],
                attachments=[pdf],
            ), pdf.parent)
            self.ctx.journal.add(self.id, str(path), str(pdf), mandant, nummer,
                                 meldung=m, art="mandant")
            msg += " + Kopie an Mandant"

        # Adres defteri SADECE PDF ve taslak(lar) başarıyla oluşturulduktan sonra öğrenir.
        # Buraya kadar bir hata olursa (istisna) bu satıra hiç gelinmez.
        msg += self.adressbuch_lernen(values.get("versicherer", ""), empfaenger)
        return Result(True, f"{msg} – PDF: {pdf.name}", str(pdf), empfaenger, nummer)

    def adressbuch_lernen(self, versicherer: str, email: str) -> str:
        """Onaylanmış sigorta/e-posta çiftini kaydeder; sonuç mesajına eklenecek metni döndürür."""
        if not versicherer.strip():
            return ""
        try:
            ergebnis = self.ctx.adressbuch.lernen(versicherer, email)
        except Exception:  # noqa: BLE001 – taslak zaten açıldı; defter hatası işi bozmasın
            return " · Adressbuch konnte nicht gespeichert werden"
        return {"neu": " · Adressbuch: neuer Eintrag",
                "aktualisiert": " · Adressbuch: Eintrag bestätigt"}.get(ergebnis, "")

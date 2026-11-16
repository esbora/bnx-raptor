"""İş akışı 1: Sigorta mektubu -> PDF/A -> e-posta taslağı (gönderilmez).

İsteğe bağlı: aynı PDF ile müvekkile ikinci bir taslak.
Her işlem sigorta numarasına bağlı bir dosyaya (Akte) kaydedilir.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

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


class VersicherungBrief(Workflow):
    id = "versicherung_brief"
    name = "Schreiben an Versicherung → PDF → E-Mail-Entwurf"
    description = "Liest E-Mail und Versicherungsnummer, erzeugt PDF/A und öffnet einen Mail-Entwurf."

    def prepare(self, path: Path) -> list[Field]:
        with WordService() as w:
            text, controls = w.read(path)
        r = extract(text, controls, dict(self.cfg, eigene_domains=self.ctx.eigene_domains()))
        hint = {"feld": "aus Vorlage", "text": "erkannt – bitte prüfen", "": "nicht gefunden"}

        # Dosya daha önce varsa müvekkil e-postası oradan önerilir
        akte = self.ctx.journal.akte(r.nummer) if r.nummer else None
        mandant = (akte or {}).get("mandant_email", "")
        feld_mandant = controls.get(self.cfg.get("feld_mandant_email", "Mandant_Email"), "").strip()
        mandant = feld_mandant or mandant
        return [
            Field("empfaenger", "Empfänger-E-Mail", r.email, r.email_candidates,
                  kind="email", hint=hint[r.quelle_email]),
            Field("nummer", "Versicherungsnummer", r.nummer, hint=hint[r.quelle_nummer]),
            Field("mandant_email", "Kopie an Mandant (optional)", mandant, required=False,
                  kind="email", hint="aus Akte" if mandant else "leer = keine Kopie"),
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
        return Result(True, f"{msg} – PDF: {pdf.name}", str(pdf), empfaenger, nummer)

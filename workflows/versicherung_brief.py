"""İş akışı 1: Sigorta mektubu -> PDF/A -> e-posta taslağı (gönderilmez).

İsteğe bağlı: aynı PDF ile müvekkile ikinci bir taslak.
Her işlem sigorta numarasına bağlı bir dosyaya (Akte) kaydedilir.
"""
from __future__ import annotations

from datetime import date
from pathlib import Path

from core.adressbuch import email_vorschlag, versicherer_erkennen
from core.entwurf import entwurf_erstellen
from core.extractor import ART_VERSICHERUNG, ART_SCHADEN, ExtractResult, betreff, extract, safe_filename
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
    description = ("Liest Versicherer, E-Mail und Versicherungs- bzw. Schaden-Nr., erzeugt PDF/A "
                   "und öffnet einen Mail-Entwurf.")

    def __init__(self, ctx):
        super().__init__(ctx)
        self._nummer_arten: dict[str, str] = {}     # numara -> tür (son okunan belge)

    def _word(self) -> WordService:
        return WordService(zeitlimit=float(self.cfg.get("word_zeitlimit_sekunden", 90)))

    def _frist(self) -> float:
        return float(self.cfg.get("word_zeitlimit_sekunden", 90)) + 30

    def prepare(self, path: Path) -> list[Field]:
        def lesen():
            with self._word() as w:
                return w.read(path)
        text, controls = self.ctx.im_hintergrund(lesen, self._frist())
        return self.felder(text, controls)

    def nummer_feld(self, r: ExtractResult) -> Field:
        """Konu için numara: bulunan tüm numaralar açılır listede, kaynaklarıyla.
        Varsayılan: Versicherungsnummer; yoksa Schaden-Nr. (açıkça belirtilir)."""
        hinweise = {f.wert: f"aus ‚{f.bezeichnung}‘" for f in r.nummern}
        self._nummer_arten = {f.wert: f.art for f in r.nummern}
        if r.quelle_nummer == "feld":
            hint = "aus Vorlage"
            self._nummer_arten[r.nummer] = ART_VERSICHERUNG
            hinweise[r.nummer] = hint
        elif r.nummern:
            erster = r.nummern[0]
            if erster.art == ART_SCHADEN:
                hint = f"aus ‚{erster.bezeichnung}‘ – keine Versicherungsnummer gefunden"
            else:
                hint = f"aus ‚{erster.bezeichnung}‘ – bitte prüfen"
            hinweise[erster.wert] = hint
        else:
            hint = "nicht gefunden"
        return Field("nummer", "Nummer (Betreff)", r.nummer, [f.wert for f in r.nummern],
                     hint=hint, choice_hints=hinweise)

    def nummer_art(self, nummer: str) -> str:
        """Seçilen numaranın türü. Elle yazılmışsa varsayılan numaranın türü kullanılır."""
        if nummer in self._nummer_arten:
            return self._nummer_arten[nummer]
        return next(iter(self._nummer_arten.values()), ART_VERSICHERUNG)

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
            if not v.wert and not v.auswahl and r.eigene_adresse_gefunden:
                # Mektupta sadece büronun kendi adresi var: alan boş kalır, elle girilir
                v.hint = "nur Kanzlei-Adresse im Brief – bitte manuell eintragen"
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
            self.nummer_feld(r),
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
        art = self.nummer_art(nummer)
        pdf = self.pdf_path(path, nummer)

        def pdf_erstellen():
            with self._word() as w:
                w.export_pdf(path, pdf, pdfa=self.cfg.get("pdfa", True))
        self.ctx.im_hintergrund(pdf_erstellen, self._frist())

        self.ctx.journal.akte_speichern(nummer, ordner=str(path.parent), nummer_art=art,
                                        versicherer_email=empfaenger, mandant_email=mandant)

        msg = entwurf_erstellen(self.ctx, MailDraft(
            to=empfaenger,
            subject=betreff(self.cfg["betreff_vorlage"], nummer, art),
            html_body=self.cfg["mail_text_html"],
            attachments=[pdf],
        ), pdf.parent)

        if mandant:
            m = entwurf_erstellen(self.ctx, MailDraft(
                to=mandant,
                subject=betreff(self.cfg["mandant_betreff_vorlage"], nummer, art),
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

"""Klasik Outlook'tan gelen cevapları bulma ve dosyaya kaydetme (COM, sadece Windows)."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from .eingang import dateiname_eingang, finde_referenz
from .mail_service import MailError

PR_INTERNET_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
PR_ATTACHMENT_HIDDEN = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"
OL_INBOX, OL_MAIL_ITEM, OL_MSG_UNICODE, OL_BY_VALUE = 6, 43, 9, 1
MAX_ELEMENTE = 3000


@dataclass
class Kandidat:
    quelle_id: str
    datum: datetime | None
    absender: str
    betreff: str
    referenz: str
    entry_id: str
    store_id: str
    anhaenge: int


def _outlook():
    try:
        import pythoncom
        import win32com.client as win32
        pythoncom.CoInitialize()
        return win32.Dispatch("Outlook.Application").GetNamespace("MAPI")
    except Exception as e:  # noqa: BLE001
        raise MailError("Klassisches Outlook nicht gefunden. Antworten bitte als .eml/.msg "
                        "in den Reiter „Akten“ ziehen.") from e


def _absender(item) -> str:
    try:
        if item.SenderEmailType == "EX":
            return item.Sender.GetExchangeUser().PrimarySmtpAddress
    except Exception:  # noqa: BLE001
        pass
    return getattr(item, "SenderEmailAddress", "") or ""


def _quelle_id(item) -> str:
    try:
        mid = item.PropertyAccessor.GetProperty(PR_INTERNET_MESSAGE_ID)
        if mid:
            return mid
    except Exception:  # noqa: BLE001
        pass
    return item.EntryID


def _datum(item) -> datetime | None:
    try:
        d = item.ReceivedTime
        return datetime(d.year, d.month, d.day, d.hour, d.minute)
    except Exception:  # noqa: BLE001
        return None


class OutlookPosteingang:
    def __init__(self):
        self.ns = _outlook()

    def suchen(self, referenzen: list[str], tage: int, bereits_importiert) -> list[Kandidat]:
        """Gelen kutusunda son `tage` gündeki, bilinen bir numara içeren e-postalar."""
        inbox = self.ns.GetDefaultFolder(OL_INBOX)
        items = inbox.Items
        items.Sort("[ReceivedTime]", True)              # en yeni önce
        grenze = datetime.now() - timedelta(days=tage)
        ergebnis: list[Kandidat] = []
        for n, item in enumerate(items):
            if n >= MAX_ELEMENTE:
                break
            if getattr(item, "Class", None) != OL_MAIL_ITEM:
                continue
            datum = _datum(item)
            if datum and datum < grenze:
                break
            ref = finde_referenz(f"{item.Subject}\n{(item.Body or '')[:8000]}", referenzen)
            if not ref:
                continue
            qid = _quelle_id(item)
            if bereits_importiert(qid):
                continue
            ergebnis.append(Kandidat(qid, datum, _absender(item), item.Subject or "", ref,
                                     item.EntryID, item.Parent.StoreID, item.Attachments.Count))
        return ergebnis

    def msg_lesen(self, pfad: Path):
        """Sürüklenen .msg dosyasını açar (Outlook gerekir)."""
        return self.ns.OpenSharedItem(str(pfad))

    def kandidat_aus_item(self, item, referenzen: list[str]) -> Kandidat:
        ref = finde_referenz(f"{item.Subject}\n{(item.Body or '')[:8000]}", referenzen) or ""
        return Kandidat(_quelle_id(item), _datum(item), _absender(item), item.Subject or "",
                        ref, "", "", item.Attachments.Count)

    def ablegen(self, k: Kandidat, ordner: Path, item=None) -> list[Path]:
        """E-postayı .msg olarak ve eklerini ayrı dosyalar olarak kaydeder."""
        item = item or self.ns.GetItemFromID(k.entry_id, k.store_id)
        ordner.mkdir(parents=True, exist_ok=True)
        basis = dateiname_eingang(k.datum, k.absender, k.betreff)
        msg_pfad = _frei(ordner / f"{basis}.msg")
        item.SaveAs(str(msg_pfad), OL_MSG_UNICODE)
        dateien = [msg_pfad]
        for att in item.Attachments:
            try:
                if att.Type != OL_BY_VALUE:
                    continue
                try:
                    if att.PropertyAccessor.GetProperty(PR_ATTACHMENT_HIDDEN):
                        continue                       # imzadaki logo vb.
                except Exception:  # noqa: BLE001
                    pass
                ziel = _frei(ordner / f"{basis}_Anlage_{att.FileName}")
                att.SaveAsFile(str(ziel))
                dateien.append(ziel)
            except Exception:  # noqa: BLE001
                continue
        return dateien


def _frei(p: Path) -> Path:
    i = 2
    while p.exists():
        p = p.with_name(f"{p.stem}_{i}{p.suffix}")
        i += 1
    return p

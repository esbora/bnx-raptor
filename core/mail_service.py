"""E-posta taslağı oluşturma. Program ASLA göndermez.

İki yöntem var (config.json -> "mail_modus"):
  outlook : Klasik Outlook'ta taslak penceresi açılır (avukatın imzası otomatik gelir).
  eml     : 'X-Unsent: 1' içeren .eml dosyası; yeni Outlook dahil her programda
            gönderilmemiş taslak olarak açılır.
"""
from __future__ import annotations

import mimetypes
import os
import re
from dataclasses import dataclass, field
from email.message import EmailMessage
from pathlib import Path


@dataclass
class MailDraft:
    to: str
    subject: str
    html_body: str
    attachments: list[Path] = field(default_factory=list)
    signature_html: str = ""          # boş = Outlook'un kendi imzası kullanılır
    logo: Path | None = None          # imzadaki logo (cid:kanzleilogo)


LOGO_CID = "kanzleilogo"
PR_ATTACH_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"


class MailError(Exception):
    pass


def insert_into_body(full_html: str, snippet: str) -> str:
    """Metni <body> etiketinin hemen arkasına, yani imzanın önüne koyar."""
    m = re.search(r"<body[^>]*>", full_html, re.IGNORECASE)
    if not m:
        return snippet + full_html
    return full_html[: m.end()] + snippet + full_html[m.end():]


class OutlookClassicDrafter:
    def create(self, draft: MailDraft) -> str:
        try:
            import pythoncom
            import win32com.client as win32
            pythoncom.CoInitialize()
            ol = win32.Dispatch("Outlook.Application")
        except Exception as e:  # noqa: BLE001
            raise MailError(
                "Klassisches Outlook nicht gefunden. In config.json "
                '"mail_modus": "eml" einstellen.'
            ) from e
        mail = ol.CreateItem(0)
        mail.To = draft.to
        mail.Subject = draft.subject
        mail.Display()                       # önce göster -> standart imza yüklenir
        if draft.signature_html:
            # Programın imzası: Outlook imzasının yerine geçer
            mail.HTMLBody = f"<html><body>{draft.html_body}{draft.signature_html}</body></html>"
            if draft.logo and draft.logo.exists():
                att = mail.Attachments.Add(str(draft.logo), 1, 0)   # 0 = gövde içinde, ek olarak görünmez
                att.PropertyAccessor.SetProperty(PR_ATTACH_CONTENT_ID, LOGO_CID)
        else:
            mail.HTMLBody = insert_into_body(mail.HTMLBody, draft.html_body)
        for a in draft.attachments:
            mail.Attachments.Add(str(a))
        # KEIN mail.Send()
        return "Outlook-Entwurf geöffnet"


class EmlDrafter:
    def build(self, draft: MailDraft) -> EmailMessage:
        msg = EmailMessage()
        msg["To"] = draft.to
        msg["Subject"] = draft.subject
        msg["X-Unsent"] = "1"
        msg.set_content("Bitte HTML-Ansicht verwenden.")
        msg.add_alternative(
            f"<html><body>{draft.html_body}{draft.signature_html}</body></html>", subtype="html")
        if draft.signature_html and draft.logo and draft.logo.exists():
            ctype = mimetypes.guess_type(draft.logo.name)[0] or "image/png"
            html_part = msg.get_payload()[1]
            html_part.add_related(draft.logo.read_bytes(), maintype="image",
                                  subtype=ctype.split("/", 1)[1], cid=f"<{LOGO_CID}>")
        for a in draft.attachments:
            ctype = mimetypes.guess_type(a.name)[0] or "application/octet-stream"
            main, sub = ctype.split("/", 1)
            msg.add_attachment(a.read_bytes(), maintype=main, subtype=sub, filename=a.name)
        return msg

    def create(self, draft: MailDraft, target: Path) -> str:
        target.write_bytes(bytes(self.build(draft)))
        if hasattr(os, "startfile"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        return f"Entwurf als {target.name} geöffnet"

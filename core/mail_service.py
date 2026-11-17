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


def _sha256(daten: bytes) -> str:
    import hashlib
    return hashlib.sha256(daten).hexdigest()


def anhaenge_vergleichen(ist: list[tuple[str, str]], soll: list[Path]) -> list[str]:
    """Taslaktaki ekler onaylanan dosyalarla aynı sırada ve birebir aynı mı? Sorunları döndürür."""
    probleme = []
    if len(ist) != len(soll):
        probleme.append(f"Anzahl Anhänge: {len(ist)} statt {len(soll)}")
    for i, (a, s) in enumerate(zip(ist, soll), start=1):
        if a[0] != s.name:
            probleme.append(f"Position {i}: {a[0]} statt {s.name}")
        elif a[1] != _sha256(s.read_bytes()):
            probleme.append(f"Position {i}: {s.name} weicht vom geprüften Inhalt ab")
    return probleme


def eml_anhaenge(pfad: Path) -> list[tuple[str, str]]:
    import email
    from email import policy
    msg = email.message_from_bytes(Path(pfad).read_bytes(), policy=policy.default)
    return [(p.get_filename(), _sha256(p.get_payload(decode=True)))
            for p in msg.iter_attachments() if p.get_filename()]


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
        self.mail = mail
        return "Outlook-Entwurf geöffnet"

    def anhaenge(self) -> list[tuple[str, str]]:
        """Taslaktaki ekler (imza logosu hariç) sırayla: (dosya adı, SHA-256) – Outlook'tan geri okunur."""
        import tempfile
        out = []
        with tempfile.TemporaryDirectory(prefix="bnx-anh-") as td:
            for k in range(1, self.mail.Attachments.Count + 1):
                att = self.mail.Attachments.Item(k)
                try:
                    if att.PropertyAccessor.GetProperty(PR_ATTACH_CONTENT_ID) == LOGO_CID:
                        continue
                except Exception:  # noqa: BLE001 – Eigenschaft fehlt = normaler Anhang
                    pass
                f = Path(td) / f"{k}_{att.FileName}"
                att.SaveAsFile(str(f))
                out.append((att.FileName, _sha256(f.read_bytes())))
        return out


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
        self.ziel = target
        if hasattr(os, "startfile"):
            os.startfile(str(target))  # type: ignore[attr-defined]
        return f"Entwurf als {target.name} geöffnet"

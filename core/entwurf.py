"""E-posta taslağı oluşturmanın tek giriş noktası.

Ayara göre Outlook ya da .eml kullanır; büro imzasını ve logoyu ekler.
Tüm iş akışları ve arayüz bunu çağırır – mantık tek yerde kalır.
"""
from __future__ import annotations

from pathlib import Path

from .kanzlei import signatur_html
from .mail_service import (LOGO_CID, EmlDrafter, MailDraft, MailError, OutlookClassicDrafter,
                           anhaenge_vergleichen, eml_anhaenge)


def klassisches_outlook_verfuegbar() -> bool:
    """Klasik Outlook COM üzerinden erişilebilir mi? (Yeni Outlook'ta False)"""
    try:
        import pythoncom
        import win32com.client as win32
        pythoncom.CoInitialize()
        win32.Dispatch("Outlook.Application")
        return True
    except Exception:  # noqa: BLE001
        return False


def mail_modus(cfg: dict) -> str:
    """'auto' ise algılar: klasik Outlook varsa 'outlook', yoksa 'eml'. Sonuç önbelleğe alınır."""
    modus = cfg.get("mail_modus", "auto")
    if modus != "auto":
        return modus
    if "_mail_modus_erkannt" not in cfg:
        cfg["_mail_modus_erkannt"] = "outlook" if klassisches_outlook_verfuegbar() else "eml"
    return cfg["_mail_modus_erkannt"]


def entwurf_erstellen(ctx, draft: MailDraft, eml_ordner: Path, anhaenge_pruefen: bool = False) -> str:
    """Taslağı açar, kullanıcıya gösterilecek mesajı döndürür. ASLA göndermez.

    anhaenge_pruefen=True: ekler taslaktan geri okunur ve onaylanan dosyalarla (sıra + SHA-256)
    karşılaştırılır; fark varsa MailError.
    """
    if not anhaenge_pruefen:
        return _erstellen(ctx, draft, eml_ordner)
    drafter_box: list = []
    msg = _erstellen(ctx, draft, eml_ordner, drafter_box)
    ist = drafter_box[0].anhaenge() if hasattr(drafter_box[0], "mail") else eml_anhaenge(drafter_box[0].ziel)
    probleme = anhaenge_vergleichen(ist, list(draft.attachments))
    if probleme:
        raise MailError("Die Anhänge im Entwurf stimmen nicht mit den geprüften Dateien überein:\n"
                        + "\n".join(probleme))
    return f"{msg} – {len(ist)} Anhänge geprüft (Reihenfolge und Inhalt identisch)"


def _erstellen(ctx, draft: MailDraft, eml_ordner: Path, drafter_box: list | None = None) -> str:
    box = drafter_box if drafter_box is not None else []
    cfg = ctx.cfg
    eml_modus = mail_modus(cfg) == "eml"
    # .eml modunda Outlook imzası yok -> imza her zaman programdan gelir
    if cfg.get("signatur_quelle") == "programm" or eml_modus:
        k = ctx.kanzlei
        if not k.ist_leer:
            logo = ctx.kanzlei_store.logo_pfad(k)
            draft.signature_html = signatur_html(k, LOGO_CID if logo else None)
            draft.logo = logo
    if eml_modus:
        from .extractor import safe_filename
        ziel = eml_ordner / f"Entwurf_{safe_filename(draft.subject, 80)}.eml"
        i = 2
        while ziel.exists():
            ziel = ziel.with_name(f"{ziel.stem.rsplit('_', 1)[0]}_{i}.eml")
            i += 1
        d = EmlDrafter()
        box.append(d)
        return d.create(draft, ziel)
    try:
        d = OutlookClassicDrafter()
        msg = d.create(draft)
        box.append(d)
        return msg
    except MailError:
        if cfg.get("mail_modus", "auto") != "auto":
            raise
        # Outlook bu arada kapanmış/değişmiş olabilir -> .eml ile devam et
        cfg["_mail_modus_erkannt"] = "eml"
        return _erstellen(ctx, draft, eml_ordner, drafter_box)

"""E-posta taslağı oluşturmanın tek giriş noktası.

Ayara göre Outlook ya da .eml kullanır; büro imzasını ve logoyu ekler.
Tüm iş akışları ve arayüz bunu çağırır – mantık tek yerde kalır.
"""
from __future__ import annotations

from pathlib import Path

from .kanzlei import signatur_html
from .mail_service import LOGO_CID, EmlDrafter, MailDraft, OutlookClassicDrafter


def entwurf_erstellen(ctx, draft: MailDraft, eml_ordner: Path) -> str:
    """Taslağı açar, kullanıcıya gösterilecek mesajı döndürür. ASLA göndermez."""
    cfg = ctx.cfg
    eml_modus = cfg.get("mail_modus") == "eml"
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
        return EmlDrafter().create(draft, ziel)
    return OutlookClassicDrafter().create(draft)

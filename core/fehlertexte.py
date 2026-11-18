"""Verständliche deutsche Fehlermeldungen (0.4.1) – nie rohe COM-Fehlertupel in der Oberfläche.

`meldung(fehler)` übersetzt bekannte Word-/Outlook-/COM-Fehler in einen kurzen deutschen Satz. Die technischen
Einzelheiten (HRESULT, Quelle, Originaltext, Traceback) werden nur ins Protokoll geschrieben
(`bnx-raptor.log` im Datenordner, siehe `protokoll_einrichten`).

Funktioniert ohne Windows: COM-Fehler werden an ihrer Form erkannt (args = (hresult, text, excepinfo, argerr)).
"""
from __future__ import annotations

import logging
import traceback
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG = logging.getLogger("bnx")

# HRESULT bzw. scode (aus excepinfo[5]) → Meldung
BEKANNT: dict[int, str] = {
    -2146822260: ("Word konnte diesen Teil des Dokuments nicht ändern: Er ist geschützt oder gesperrt "
                  "(z. B. ein gesperrtes Inhaltssteuerelement oder eingeschränkte Bearbeitung)."),
    -2146822494: "Word kann die Datei nicht öffnen – sie ist beschädigt oder kein Word-Dokument.",
    -2146823135: "Die Datei wurde nicht gefunden oder der Pfad ist ungültig.",
    -2146821993: "Das Dokument ist kennwortgeschützt. Bitte das Kennwort in Word entfernen und erneut versuchen.",
    -2146822003: "Die Datei ist gerade in einem anderen Programm geöffnet. Bitte dort schließen und erneut versuchen.",
    -2146959355: ("Microsoft Word konnte nicht gestartet werden. Bitte Word einmal normal öffnen "
                  "(ggf. anmelden), wieder schließen und erneut versuchen."),
    -2147221005: "Microsoft Word bzw. Outlook ist auf diesem Rechner nicht installiert.",
    -2147221164: "Microsoft Word bzw. Outlook ist auf diesem Rechner nicht registriert.",
    -2147023170: "Word bzw. Outlook wurde unerwartet beendet. Bitte erneut versuchen.",
    -2147023174: "Word bzw. Outlook ist nicht mehr erreichbar (wurde beendet). Bitte erneut versuchen.",
    -2147417846: ("Word bzw. Outlook ist gerade beschäftigt – vermutlich ist dort ein Dialogfenster offen. "
                  "Bitte das Fenster schließen und erneut versuchen."),
    -2147418111: "Word bzw. Outlook hat den Aufruf abgelehnt (beschäftigt). Bitte kurz warten und erneut versuchen.",
    -2147467259: "Word bzw. Outlook meldet einen allgemeinen Fehler.",
    -2147024891: "Zugriff verweigert – fehlende Berechtigung für Datei oder Ordner.",
    -2147024864: "Die Datei ist gesperrt (von einem anderen Programm geöffnet).",
}
ALLGEMEIN = "Microsoft Office meldet einen Fehler. Technische Einzelheiten stehen im Protokoll (bnx-raptor.log)."


def _com_teile(fehler: BaseException) -> tuple[int | None, int | None]:
    """(hresult, scode) eines COM-Fehlers – erkennt pywintypes.com_error an der Form seiner args."""
    a = getattr(fehler, "args", ())
    if len(a) >= 3 and isinstance(a[0], int) and (a[2] is None or isinstance(a[2], tuple)):
        scode = a[2][5] if isinstance(a[2], tuple) and len(a[2]) > 5 and isinstance(a[2][5], int) else None
        return a[0], scode
    return None, None


def ist_com_fehler(fehler: BaseException) -> bool:
    return _com_teile(fehler)[0] is not None or type(fehler).__name__ == "com_error"


def meldung(fehler: BaseException, aktion: str = "") -> str:
    """Kurze deutsche Meldung für die Oberfläche; Einzelheiten → Protokoll."""
    protokollieren(fehler, aktion)
    hr, scode = _com_teile(fehler)
    vorne = f"{aktion}: " if aktion else ""
    if hr is not None or type(fehler).__name__ == "com_error":
        text = BEKANNT.get(scode) or BEKANNT.get(hr) or ALLGEMEIN
        return vorne + text
    ursache = fehler.__cause__ or fehler.__context__
    if ursache is not None and ist_com_fehler(ursache) and not str(fehler).strip():
        return meldung(ursache, aktion)
    text = str(fehler).strip() or type(fehler).__name__
    # Sicherheitsnetz: eingebettete COM-Tupel nie anzeigen
    if text.startswith("(-21") and "," in text[:16]:
        return vorne + ALLGEMEIN
    return vorne + text


def protokollieren(fehler: BaseException, aktion: str = "") -> None:
    hr, scode = _com_teile(fehler)
    LOG.error("%s%s | %s | hresult=%s scode=%s | %r\n%s", aktion + " – " if aktion else "", type(fehler).__name__,
              str(fehler)[:500], hr, scode, getattr(fehler, "args", None),
              "".join(traceback.format_exception(type(fehler), fehler, fehler.__traceback__))[-4000:])


def protokoll_einrichten(ordner: Path) -> Path:
    """Protokolldatei im Datenordner (max. 1 MB × 3). Keine Dokumentinhalte, nur Fehler."""
    pfad = Path(ordner) / "bnx-raptor.log"
    if not any(isinstance(h, RotatingFileHandler) for h in LOG.handlers):
        h = RotatingFileHandler(pfad, maxBytes=1_000_000, backupCount=3, encoding="utf-8")
        h.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
        LOG.addHandler(h)
        LOG.setLevel(logging.INFO)
    return pfad

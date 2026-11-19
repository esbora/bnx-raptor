"""BnX-Raptor – başlangıç noktası.

Kullanım:
  BnX-Raptor.exe                         -> pencere açılır
  BnX-Raptor.exe brief1.docx ...         -> dosyalar listeye eklenmiş olarak açılır
                                            (Windows "Gönder" menüsü kısayolu bunu kullanır)
  BnX-Raptor.exe --anlagen a.docx b.pdf  -> Anlagen-Assistent, dosyalar eklenmiş olarak
  BnX-Raptor.exe --pdf-bearbeiten x.pdf  -> doğrudan PDF-Editor
"""
from __future__ import annotations

import sys
from pathlib import Path

from PySide6.QtWidgets import QApplication, QMessageBox

from core.config import ConfigFehler, config_pfad_setzen, data_dir, load_config
from core.journal import Journal
from core.kanzlei import KanzleiStore
from ui.main_window import MainWindow
from workflows import ALL_WORKFLOWS
from version import __version__
from workflows.base import AppContext


def main() -> int:
    app = QApplication(sys.argv)
    app.setApplicationName("BnX-Raptor")
    app.setApplicationVersion(__version__)
    from ui import theme
    theme.anwenden(app)
    argumente = sys.argv[1:]
    if len(argumente) >= 2 and argumente[0] == "--config":   # weiterer Arbeitsplatz mit eigener config.json
        config_pfad_setzen(Path(argumente[1]))
        argumente = argumente[2:]
    try:
        cfg = load_config()
    except ConfigFehler as e:
        QMessageBox.critical(None, "BnX-Raptor – Einstellungen", str(e))
        return 1
    modus = argumente.pop(0) if argumente and argumente[0] in ("--anlagen", "--pdf-bearbeiten") else ""
    pfade = [Path(a) for a in argumente]
    if modus == "--pdf-bearbeiten":
        from core.pdf_engine import SPRACHEN
        from ui.pdf_editor import PdfEditor
        PdfEditor(None, pfade[0] if pfade else None, sprachen=tuple(cfg.get("ocr_sprachen", SPRACHEN))).exec()
        return 0
    ordner = data_dir(cfg)
    from core.fehlertexte import protokoll_einrichten
    protokoll_einrichten(ordner)        # nur Fehlerdetails, keine Dokumentinhalte
    # Unterbrochene Wiederherstellung (Absturz/Stromausfall) → vorherigen Stand zurückschreiben
    from core.sicherung import offene_wiederherstellung_zuruecksetzen
    netz_modus = cfg.get("modus") or "einzelplatz"
    # Neuer PC (noch keine Daten): gleich fragen – neue Kanzlei hier oder mit bestehender Kanzlei verbinden
    if netz_modus == "einzelplatz" and not cfg.get("willkommen_erledigt") \
            and not (ordner / "verlauf.sqlite").exists() and KanzleiStore(ordner).laden().ist_leer:
        from core.config import einstellung_speichern
        from ui.netz_ui import VerbindenDialog, Willkommen
        w = Willkommen()
        if w.exec() != w.Accepted:
            return 0
        einstellung_speichern("willkommen_erledigt", True)
        if w.wahl == "verbinden":
            if VerbindenDialog(None, cfg).exec() != VerbindenDialog.Accepted:
                return 0
            netz_modus = "client"
    zurueckgesetzt = netz_modus != "client" and offene_wiederherstellung_zuruecksetzen(ordner)
    if zurueckgesetzt:
        cfg = load_config()
    dienst = None
    if netz_modus in ("server", "client"):
        from core import netz
        from core import protokoll as pr
        from core.config import app_dir
        from ui import netz_ui
        if netz_modus == "server":
            import time as _time
            fehler = None
            for _ in range(20):
                try:
                    dienst = netz.Dienst(ordner, app_dir(), port=int(cfg.get("server_port") or netz.STANDARD_PORT),
                                         cfg=cfg, version=__version__).starten()
                    break
                except OSError as e:                  # Port noch vom vorherigen Prozess belegt (Neustart)
                    fehler = e
                    _time.sleep(0.5)
            if dienst is None:
                e = fehler
                QMessageBox.critical(None, "BnX-Raptor – Server", "Der Server-Dienst konnte nicht gestartet werden "
                                     f"(Port {cfg.get('server_port')} belegt? Läuft BnX-Raptor schon?).\n\n{e}")
                return 1
        verbindung = netz_ui.verbinden(cfg, dienst is not None)
        if verbindung is None:
            if dienst:
                dienst.beenden()
            return 0
        b = verbindung.benutzer or {}
        pr.setzen(pr.Benutzer(b.get("name", ""), b.get("rolle", ""), b.get("anzeigename") or ""), standard=True)
        kopien_ordner = ordner / ("Arbeitskopien" if netz_modus == "client" else "Arbeitskopien_Server")
        kopien = netz.Arbeitskopien(verbindung, kopien_ordner)
        journal = netz.FernJournal(verbindung, kopien)
        ctx = AppContext(cfg, netz.FernKanzlei(verbindung, kopien), journal, verbindung=verbindung, kopien=kopien)
    else:
        journal = Journal(ordner / "verlauf.sqlite")
        ctx = AppContext(cfg, KanzleiStore(ordner), journal)
    ctx.dienst = dienst
    workflows = [wf(ctx) for wf in ALL_WORKFLOWS]

    win = MainWindow(ctx, journal, workflows)
    win.show()
    _fehler_abfangen(win)
    if modus == "--anlagen":
        win.anlagen_oeffnen(pfade)
    else:
        win.add_files(pfade)
    if zurueckgesetzt:
        QMessageBox.warning(win, "Wiederherstellung unterbrochen",
                            "Eine Wiederherstellung wurde beim letzten Mal nicht abgeschlossen. Der vorherige Stand "
                            "wurde automatisch wiederhergestellt – es sind keine Daten verloren gegangen.")
    if ctx.kanzlei.ist_leer and ctx.darf("kanzlei", "speichern"):   # ilk açılış: büro bilgileri iste
        win.kanzleidaten_bearbeiten(erster_start=True)
    code = app.exec()
    if dienst:
        dienst.beenden()
    return code


def _fehler_abfangen(win) -> None:
    """Unbehandelte Fehler in Knöpfen: Netzwerk/Rechte/Konflikt verständlich melden statt still zu scheitern."""
    import logging
    alt = sys.excepthook

    def haken(typ, wert, tb):
        try:
            from ui.netz_ui import ausnahme_behandeln
            if ausnahme_behandeln(win, wert):
                return
        except Exception:  # noqa: BLE001
            pass
        logging.getLogger("BnX-Raptor").error("Unbehandelter Fehler", exc_info=(typ, wert, tb))
        alt(typ, wert, tb)
    sys.excepthook = haken


if __name__ == "__main__":
    sys.exit(main())

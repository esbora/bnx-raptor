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

from core.config import ConfigFehler, data_dir, load_config
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
    try:
        cfg = load_config()
    except ConfigFehler as e:
        QMessageBox.critical(None, "BnX-Raptor – Einstellungen", str(e))
        return 1
    argumente = sys.argv[1:]
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
    zurueckgesetzt = offene_wiederherstellung_zuruecksetzen(ordner)
    if zurueckgesetzt:
        cfg = load_config()
    journal = Journal(ordner / "verlauf.sqlite")
    ctx = AppContext(cfg, KanzleiStore(ordner), journal)
    workflows = [wf(ctx) for wf in ALL_WORKFLOWS]

    win = MainWindow(ctx, journal, workflows)
    win.show()
    if modus == "--anlagen":
        win.anlagen_oeffnen(pfade)
    else:
        win.add_files(pfade)
    if zurueckgesetzt:
        QMessageBox.warning(win, "Wiederherstellung unterbrochen",
                            "Eine Wiederherstellung wurde beim letzten Mal nicht abgeschlossen. Der vorherige Stand "
                            "wurde automatisch wiederhergestellt – es sind keine Daten verloren gegangen.")
    if ctx.kanzlei.ist_leer:                      # ilk açılış: büro bilgileri iste
        win.kanzleidaten_bearbeiten(erster_start=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

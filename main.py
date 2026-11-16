"""BnX-Raptor – başlangıç noktası.

Kullanım:
  BnX-Raptor.exe                    -> pencere açılır
  BnX-Raptor.exe brief1.docx ...    -> dosyalar listeye eklenmiş olarak açılır
                                             (Windows "Gönder" menüsü kısayolu bunu kullanır)
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
    try:
        cfg = load_config()
    except ConfigFehler as e:
        QMessageBox.critical(None, "BnX-Raptor – Einstellungen", str(e))
        return 1
    ordner = data_dir(cfg)
    journal = Journal(ordner / "verlauf.sqlite")
    ctx = AppContext(cfg, KanzleiStore(ordner), journal)
    workflows = [wf(ctx) for wf in ALL_WORKFLOWS]

    win = MainWindow(ctx, journal, workflows)
    win.add_files([Path(a) for a in sys.argv[1:]])
    win.show()
    if ctx.kanzlei.ist_leer:                      # ilk açılış: büro bilgileri iste
        win.kanzleidaten_bearbeiten(erster_start=True)
    return app.exec()


if __name__ == "__main__":
    sys.exit(main())

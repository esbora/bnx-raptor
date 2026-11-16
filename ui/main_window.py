"""Ana pencere: iş akışı seçimi, sürükle-bırak, kontrol penceresi, geçmiş."""
from __future__ import annotations

import threading
import traceback
from pathlib import Path

from PySide6.QtCore import QObject, Qt, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.extractor import is_valid_email
from core.journal import ARTEN, Journal
from core.update import ReleaseInfo, ist_neuer, neueste_release
from version import __version__
from workflows.base import AppContext, Field, Workflow

from .akten_tab import AktenTab
from .kanzlei_dialog import KanzleiDialog


class _UpdateSignal(QObject):
    gefunden = Signal(object)        # ReleaseInfo | None


class ReviewDialog(QDialog):
    """Bulunan değerleri gösterir; avukat düzeltir ve onaylar."""

    def __init__(self, parent, doc: Path, fields: list[Field]):
        super().__init__(parent)
        self.setWindowTitle(f"Prüfen – {doc.name}")
        self.setMinimumWidth(520)
        self.fields = fields
        self.editors: dict[str, QComboBox] = {}

        form = QFormLayout()
        for f in fields:
            box = QComboBox()
            box.setEditable(True)
            items = [f.value] + [c for c in f.choices if c != f.value] if f.value else f.choices
            box.addItems(items)
            box.setCurrentText(f.value)
            self.editors[f.key] = box
            hint = QLabel(f.hint)
            hint.setStyleSheet("color: #b45309;" if "prüfen" in f.hint or "nicht" in f.hint
                               else "color: #15803d;")
            row = QHBoxLayout()
            row.addWidget(box, 1)
            row.addWidget(hint)
            form.addRow(f.label + ":", row)

        buttons = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        buttons.button(QDialogButtonBox.Ok).setText("PDF + Entwurf erstellen")
        buttons.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        buttons.accepted.connect(self._check)
        buttons.rejected.connect(self.reject)

        lay = QVBoxLayout(self)
        lay.addLayout(form)
        lay.addWidget(buttons)

    def _check(self):
        for f in self.fields:
            v = self.editors[f.key].currentText().strip()
            if f.required and not v:
                QMessageBox.warning(self, "Fehlt", f"Bitte „{f.label}“ ausfüllen.")
                return
            if f.kind == "email" and v and not is_valid_email(v):
                QMessageBox.warning(self, "Ungültig", f"„{v}“ ist keine gültige E-Mail-Adresse.")
                return
        self.accept()

    def values(self) -> dict[str, str]:
        return {k: e.currentText().strip() for k, e in self.editors.items()}


class DropList(QListWidget):
    def __init__(self, on_files):
        super().__init__()
        self.on_files = on_files
        self.setAcceptDrops(True)
        self.setMinimumHeight(140)

    def dragEnterEvent(self, e):
        if e.mimeData().hasUrls():
            e.acceptProposedAction()

    dragMoveEvent = dragEnterEvent

    def dropEvent(self, e):
        self.on_files([Path(u.toLocalFile()) for u in e.mimeData().urls()])


class MainWindow(QMainWindow):
    def __init__(self, ctx: AppContext, journal: Journal, workflows: list[Workflow]):
        super().__init__()
        self.ctx, self.cfg, self.journal, self.workflows = ctx, ctx.cfg, journal, workflows
        self.resize(900, 560)
        self.titel_aktualisieren()

        menu = self.menuBar().addMenu("Einstellungen")
        menu.addAction("Kanzleidaten…", self.kanzleidaten_bearbeiten)
        hilfe = self.menuBar().addMenu("Hilfe")
        hilfe.addAction("Nach Updates suchen", lambda: self.update_pruefen(manuell=True))
        hilfe.addAction("Über BnX-Raptor", self.ueber)

        # Güncelleme uyarı şeridi (yeni sürüm varsa görünür)
        self.update_band = QPushButton()
        self.update_band.setStyleSheet(
            "background:#fef3c7; color:#92400e; border:1px solid #f59e0b; padding:6px; text-align:left;")
        self.update_band.hide()
        self.update_band.clicked.connect(self.update_zeigen)
        self.release: ReleaseInfo | None = None

        self.tabs = QTabWidget()
        self.tabs.addTab(self._build_work_tab(), "Bearbeiten")
        self.akten_tab = AktenTab(ctx)
        self.tabs.addTab(self.akten_tab, "Akten")
        self.tabs.addTab(self._build_history_tab(), "Verlauf")
        self.tabs.currentChanged.connect(self.tab_gewechselt)

        zentral = QWidget()
        zl = QVBoxLayout(zentral)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.addWidget(self.update_band)
        zl.addWidget(self.tabs, 1)
        self.setCentralWidget(zentral)

        self._update_signal = _UpdateSignal()
        self._update_signal.gefunden.connect(self._update_ergebnis)
        if self.cfg.get("update_pruefen", True):
            self.update_pruefen()

    def tab_gewechselt(self, i: int):
        if self.tabs.widget(i) is self.akten_tab:
            self.akten_tab.laden()
        elif i == 2:
            self.refresh_history()

    def titel_aktualisieren(self):
        k = self.ctx.kanzlei
        self.setWindowTitle(f"BnX-Raptor {__version__}" + (f" – {k.name}" if k.name else ""))

    # --- Güncelleme ---
    def update_pruefen(self, manuell: bool = False):
        """Arka planda kontrol – program açılışını yavaşlatmaz."""
        self._manuell = manuell
        repo = self.cfg.get("update_repo", "")
        if not repo:
            if manuell:
                QMessageBox.information(self, "Updates", "Kein Update-Server eingestellt (update_repo).")
            return
        threading.Thread(target=lambda: self._update_signal.gefunden.emit(neueste_release(repo)),
                         daemon=True).start()

    def _update_ergebnis(self, info: ReleaseInfo | None):
        if info and ist_neuer(info.version, __version__):
            self.release = info
            self.update_band.setText(
                f"⚠  Neue Version {info.version} verfügbar (installiert: {__version__}). "
                "Hier klicken für Details und Download.")
            self.update_band.show()
        elif self._manuell:
            QMessageBox.information(self, "Updates",
                                    "Update-Server nicht erreichbar." if info is None
                                    else f"BnX-Raptor {__version__} ist aktuell.")

    def update_zeigen(self):
        info = self.release
        if not info:
            return
        box = QMessageBox(self)
        box.setWindowTitle(f"BnX-Raptor {info.version}")
        box.setText(f"<b>Neue Version {info.version}</b> (installiert: {__version__})")
        box.setInformativeText(
            "So aktualisieren Sie:\n1. BnX-Raptor schließen\n2. ZIP herunterladen und entpacken\n"
            "3. Alle Dateien in den Programmordner kopieren (vorhandene ersetzen)\n\n"
            "Ihre Einstellungen (config.json), Kanzleidaten und Akten bleiben erhalten.")
        box.setDetailedText(info.notizen or "")
        b_dl = box.addButton("Herunterladen", QMessageBox.AcceptRole)
        box.addButton("Später", QMessageBox.RejectRole)
        box.exec()
        if box.clickedButton() is b_dl:
            QDesktopServices.openUrl(QUrl(info.download or info.url))

    def ueber(self):
        QMessageBox.about(self, "Über BnX-Raptor",
                          f"<b>BnX-Raptor</b> Version {__version__}<br>"
                          f"Daten: {self.ctx.kanzlei_store.ordner}")

    def kanzleidaten_bearbeiten(self, erster_start: bool = False):
        if KanzleiDialog(self, self.ctx.kanzlei_store, erster_start).exec() == QDialog.Accepted:
            self.titel_aktualisieren()

    # --- İş sekmesi ---
    def _build_work_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)

        self.wf_box = QComboBox()
        for wf in self.workflows:
            self.wf_box.addItem(wf.name)
        lay.addWidget(QLabel("Vorgang:"))
        lay.addWidget(self.wf_box)

        lay.addWidget(QLabel("Word-Dokumente hierher ziehen oder auswählen:"))
        self.files = DropList(self.add_files)
        lay.addWidget(self.files)

        row = QHBoxLayout()
        b_add = QPushButton("Dateien wählen…")
        b_add.clicked.connect(self.pick_files)
        b_clear = QPushButton("Liste leeren")
        b_clear.clicked.connect(self.files.clear)
        self.b_run = QPushButton("Starten")
        self.b_run.setDefault(True)
        self.b_run.clicked.connect(self.run_all)
        row.addWidget(b_add)
        row.addWidget(b_clear)
        row.addStretch(1)
        row.addWidget(self.b_run)
        lay.addLayout(row)

        self.status = QLabel("")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        return w

    def current_workflow(self) -> Workflow:
        return self.workflows[self.wf_box.currentIndex()]

    def add_files(self, paths: list[Path]):
        wf = self.current_workflow()
        existing = {self.files.item(i).text() for i in range(self.files.count())}
        for p in paths:
            if p.is_file() and wf.accepts(p) and str(p) not in existing:
                self.files.addItem(str(p))

    def pick_files(self):
        names, _ = QFileDialog.getOpenFileNames(self, "Dokumente wählen", "", "Word (*.docx *.doc)")
        self.add_files([Path(n) for n in names])

    def run_all(self):
        from core.word_service import WordService

        wf = self.current_workflow()
        paths = [Path(self.files.item(i).text()) for i in range(self.files.count())]
        if not paths:
            self.status.setText("Keine Dokumente in der Liste.")
            return
        done = 0
        for p in paths:
            if WordService.unsaved_in_running_word(p):
                QMessageBox.warning(self, "Nicht gespeichert",
                                    f"{p.name} ist in Word geöffnet und nicht gespeichert.\n"
                                    "Bitte zuerst speichern.")
                continue
            try:
                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    fields = wf.prepare(p)
                finally:
                    QGuiApplication.restoreOverrideCursor()

                dlg = ReviewDialog(self, p, fields)
                if dlg.exec() != QDialog.Accepted:
                    self.journal.add(wf.id, str(p), status="abgebrochen")
                    continue

                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    res = wf.execute(p, dlg.values())
                finally:
                    QGuiApplication.restoreOverrideCursor()
                self.journal.add(wf.id, str(p), res.output, res.recipient, res.reference,
                                 "ok" if res.ok else "fehler", res.message)
                self.status.setText(res.message)
                done += 1
            except Exception as e:  # noqa: BLE001
                self.journal.add(wf.id, str(p), status="fehler",
                                 meldung=f"{e}\n{traceback.format_exc()}")
                QMessageBox.critical(self, "Fehler", f"{p.name}:\n{e}")
        self.status.setText(f"{done} von {len(paths)} Dokument(en) bearbeitet.")
        self.files.clear()

    # --- Geçmiş sekmesi ---
    def _build_history_tab(self) -> QWidget:
        w = QWidget()
        lay = QVBoxLayout(w)
        self.table = QTableWidget(0, 8)
        self.table.setHorizontalHeaderLabels(
            ["Zeit", "Art", "Versicherungsnr.", "Datei", "An / Von", "Status", "Meldung", "Benutzer"])
        self.table.horizontalHeader().setSectionResizeMode(QHeaderView.Interactive)
        self.table.setEditTriggers(QTableWidget.NoEditTriggers)
        lay.addWidget(self.table)
        return w

    def refresh_history(self):
        rows = self.journal.recent()
        self.table.setRowCount(len(rows))
        for r, v in enumerate(rows):
            datei = v["ergebnis"] or v["dokument"]
            werte = [v["zeit"], ARTEN.get(v["art"], v["art"]), v["referenz"],
                     Path(datei).name if datei else "", v["empfaenger"], v["status"],
                     (v["meldung"] or "").splitlines()[0] if v["meldung"] else "", v["benutzer"]]
            for c, text in enumerate(werte):
                self.table.setItem(r, c, QTableWidgetItem(str(text or "")))
        self.table.resizeColumnsToContents()

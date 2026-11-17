"""Ana pencere: iş akışı seçimi, sürükle-bırak, kontrol penceresi, geçmiş."""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QMainWindow, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.extractor import is_valid_email
from core.journal import ARTEN, Journal
from core.update import ReleaseInfo, ist_neuer, neueste_release
from version import __version__
from workflows.base import AppContext, Field, Workflow

from .adressbuch_dialog import AdressbuchDialog
from .akten_tab import AktenTab
from .kanzlei_dialog import KanzleiDialog


def im_hintergrund(fn, frist_sekunden: float):
    """fn'i ayrı iş parçacığında çalıştırır; bu sırada pencere tepki vermeye devam eder.

    Word'ün kendi zaman sınırı (WordService) normalde önce devreye girer. Bu frist sadece
    son güvencedir: dolarsa iş parçacığı arkada bırakılır ve Almanca hata verilir.
    """
    from core.word_service import WordError, zeitlimit_meldung

    sonuc: dict = {}

    def lauf():
        try:
            sonuc["wert"] = fn()
        except BaseException as e:  # noqa: BLE001
            sonuc["fehler"] = e

    t = threading.Thread(target=lauf, daemon=True)
    t.start()
    ende = time.monotonic() + frist_sekunden
    schleife = QEventLoop()
    timer = QTimer()
    timer.timeout.connect(
        lambda: schleife.quit() if (not t.is_alive() or time.monotonic() > ende) else None)
    timer.start(100)
    if t.is_alive():
        schleife.exec()
    timer.stop()
    if t.is_alive():
        raise WordError(zeitlimit_meldung(frist_sekunden, beendet=False))
    if "fehler" in sonuc:
        raise sonuc["fehler"]
    return sonuc.get("wert")


class AbbruchDurchNutzer(Exception):
    """Nutzer hat im Ablauf abgebrochen (kein Fehler)."""


class _UpdateSignal(QObject):
    gefunden = Signal(object)        # ReleaseInfo | None


class ReviewDialog(QDialog):
    """Bulunan değerleri kaynağıyla gösterir; avukat düzeltir, seçer ve onaylar."""

    TRENNER = "   —   "                    # açılır listede "adres — kaynak"
    WARN_WOERTER = ("prüfen", "nicht", "keine", "auswählen", "weichen", "manuell")

    def __init__(self, parent, doc: Path, fields: list[Field]):
        super().__init__(parent)
        self.setWindowTitle(f"Prüfen – {doc.name}")
        self.setMinimumWidth(640)
        self.fields = list(fields)
        self.editors: dict[str, QComboBox] = {}
        self.hints: dict[str, QLabel] = {}
        self.manuell: set[str] = set()       # kullanıcı elle yazdı -> otomatik yenileme ezmez
        self._letzter: dict[str, str] = {}

        form = QFormLayout()
        for f in fields:
            box = QComboBox()
            box.setEditable(True)
            box.setInsertPolicy(QComboBox.NoInsert)
            hint = QLabel()
            self.editors[f.key], self.hints[f.key] = box, hint
            self._fuellen(f)
            box.currentIndexChanged.connect(lambda i, k=f.key: self._gewaehlt(k, i))
            box.lineEdit().textEdited.connect(lambda _t, k=f.key: self._bearbeitet(k))
            box.lineEdit().editingFinished.connect(lambda k=f.key: self._geaendert(k))
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

    # --- yardımcılar ---
    def _feld(self, key: str) -> Field:
        return next(f for f in self.fields if f.key == key)

    def _hint_setzen(self, key: str, text: str):
        lbl = self.hints[key]
        lbl.setText(text)
        warn = any(w in text for w in self.WARN_WOERTER)
        lbl.setStyleSheet("color: #b45309;" if warn else "color: #15803d;")

    def _fuellen(self, f: Field):
        box = self.editors[f.key]
        box.blockSignals(True)
        box.clear()
        werte = list(f.choices)
        if f.value and f.value not in werte:
            werte.insert(0, f.value)
        for w in werte:
            q = f.choice_hints.get(w)
            box.addItem(f"{w}{self.TRENNER}{q}" if q else w, w)
        if f.must_choose:
            box.setCurrentIndex(-1)
            box.setEditText("")
            box.lineEdit().setPlaceholderText("Bitte auswählen …")
        else:
            box.setEditText(f.value)
        box.blockSignals(False)
        self._letzter[f.key] = f.value
        self._hint_setzen(f.key, f.hint)

    def _wert(self, key: str) -> str:
        box = self.editors[key]
        text = box.currentText().strip()
        for i in range(box.count()):                 # "adres — kaynak" -> adres
            if box.itemText(i).strip() == text:
                return str(box.itemData(i)).strip()
        return text

    # --- olaylar ---
    def _gewaehlt(self, key: str, index: int):
        if index < 0:
            return
        box, f = self.editors[key], self._feld(key)
        wert = str(box.itemData(index))
        box.blockSignals(True)
        box.setEditText(wert)
        box.blockSignals(False)
        self.manuell.discard(key)
        self._hint_setzen(key, f.choice_hints.get(wert) or (f.hint if wert == f.value else "ausgewählt"))
        self._geaendert(key)

    def _bearbeitet(self, key: str):
        self.manuell.add(key)
        self._hint_setzen(key, "manuell geändert")

    def _geaendert(self, key: str):
        """Değer değişti: bağlı alanların önerilerini yenile (örn. Versicherer -> E-Mail)."""
        f, wert = self._feld(key), self._wert(key)
        if wert == self._letzter.get(key) or not f.on_change:
            self._letzter[key] = wert
            return
        self._letzter[key] = wert
        for neu in f.on_change(wert):
            if neu.key in self.editors and neu.key not in self.manuell:
                self.fields = [neu if x.key == neu.key else x for x in self.fields]
                self._fuellen(neu)

    def _check(self):
        for f in self.fields:
            v = self._wert(f.key)
            if f.required and not v:
                text = (f"Bitte für „{f.label}“ eine Adresse auswählen." if f.must_choose
                        else f"Bitte „{f.label}“ ausfüllen.")
                QMessageBox.warning(self, "Fehlt", text)
                return
            if f.kind == "email" and v and not is_valid_email(v):
                QMessageBox.warning(self, "Ungültig", f"„{v}“ ist keine gültige E-Mail-Adresse.")
                return
        self.accept()

    def values(self) -> dict[str, str]:
        return {k: self._wert(k) for k in self.editors}


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
        menu.addAction("Versicherer-Adressbuch…", self.adressbuch_bearbeiten)
        werkzeuge = self.menuBar().addMenu("Werkzeuge")
        werkzeuge.addAction("PDF bearbeiten…", self.pdf_bearbeiten)
        werkzeuge.addAction("Anlagenpaket erstellen", lambda: self.anlagen_oeffnen([]))
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
        # Anlagen-Assistent wird erst beim ersten Öffnen aufgebaut (PDF-Bibliothek nicht beim Start laden)
        self.anlagen_huelle = QWidget()
        QVBoxLayout(self.anlagen_huelle).setContentsMargins(0, 0, 0, 0)
        self.anlagen_tab = None
        self.tabs.addTab(self.anlagen_huelle, "Anlagen")
        self.akten_tab = AktenTab(ctx)
        self.tabs.addTab(self.akten_tab, "Akten")
        self.verlauf_tab = self._build_history_tab()
        self.tabs.addTab(self.verlauf_tab, "Verlauf")
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
        w = self.tabs.widget(i)
        if w is self.akten_tab:
            self.akten_tab.laden()
        elif w is self.verlauf_tab:
            self.refresh_history()
        elif w is self.anlagen_huelle:
            self._anlagen_tab()

    # --- PDF-Editor / Anlagen-Assistent (0.4) ---
    def _anlagen_tab(self):
        if self.anlagen_tab is None:
            from .anlagen_tab import AnlagenTab
            self.anlagen_tab = AnlagenTab(self.ctx, im_hintergrund)
            self.anlagen_huelle.layout().addWidget(self.anlagen_tab)
        return self.anlagen_tab

    def anlagen_oeffnen(self, pfade: list[Path]):
        self.tabs.setCurrentWidget(self.anlagen_huelle)
        tab = self._anlagen_tab()
        if pfade:
            tab.hinzufuegen(pfade)

    def pdf_bearbeiten(self, pfad: Path | None = None):
        if pfad is None:
            name, _ = QFileDialog.getOpenFileName(self, "PDF bearbeiten", "", "PDF (*.pdf)")
            if not name:
                return
            pfad = Path(name)
        from core.pdf_engine import SPRACHEN
        from .pdf_editor import PdfEditor
        PdfEditor(self, pfad, sprachen=tuple(self.cfg.get("ocr_sprachen", SPRACHEN))).exec()

    def _pdf_nachbearbeiten(self, pdf: Path) -> Path:
        """Word→PDF-Ablauf: erzeugtes PDF im Editor prüfen; danach zeigen, welche Fassung angehängt wird."""
        from core.pdf_engine import SPRACHEN
        from .pdf_editor import PdfEditor
        from .pdf_ui import AnhangVorschau
        ed = PdfEditor(self, pdf, sprachen=tuple(self.cfg.get("ocr_sprachen", SPRACHEN)))
        ed.exec()
        wahl = ed.gespeichert or pdf
        dlg = AnhangVorschau(self, [(wahl, "bearbeitete Fassung" if ed.gespeichert else "PDF aus Word (unverändert)",
                                     True)], "Anhang für den Entwurf")
        if dlg.exec() != QDialog.Accepted or not dlg.auswahl():
            raise AbbruchDurchNutzer()
        return wahl

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

    def _modus_text(self) -> str:
        from core.entwurf import mail_modus
        return {"outlook": "klassisches Outlook", "eml": ".eml-Entwurf (neues Outlook / andere)"}.get(
            mail_modus(self.cfg), "?")

    def ueber(self):
        QMessageBox.about(self, "Über BnX-Raptor",
                          f"<b>BnX-Raptor</b> Version {__version__}<br>"
                          f"E-Mail-Modus: {self._modus_text()}<br>"
                          f"Daten: {self.ctx.kanzlei_store.ordner}")

    def adressbuch_bearbeiten(self):
        AdressbuchDialog(self, self.ctx.adressbuch).exec()

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

        self.cb_pdf_pruefen = QCheckBox("PDF vor dem Entwurf im PDF-Editor prüfen/bearbeiten")
        lay.addWidget(self.cb_pdf_pruefen)

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
        wf = self.current_workflow()
        paths = [Path(self.files.item(i).text()) for i in range(self.files.count())]
        if not paths:
            self.status.setText("Keine Dokumente in der Liste.")
            return
        zeit = float(self.ctx.cfg.get("word_zeitlimit_sekunden", 90))
        # Word işi arka planda: pencere tepki vermeye devam eder, takılırsa süre sonunda biter
        self.ctx.im_hintergrund = lambda fn, frist=None: im_hintergrund(fn, frist or zeit + 30)
        self.ctx.pdf_nachbearbeiten = (self._pdf_nachbearbeiten if self.cb_pdf_pruefen.isChecked()
                                       else (lambda pdf: pdf))
        self.b_run.setEnabled(False)                # işlem sürerken ikinci kez başlatılamaz
        try:
            done = self._dokumente_bearbeiten(wf, paths)
        finally:
            self.b_run.setEnabled(True)
        self.status.setText(f"{done} von {len(paths)} Dokument(en) bearbeitet.")
        self.files.clear()

    def _dokumente_bearbeiten(self, wf, paths: list[Path]) -> int:
        from core.word_service import WordService

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
                    self.status.setText(f"{p.name}: Word liest das Dokument …")
                    fields = wf.prepare(p)
                finally:
                    QGuiApplication.restoreOverrideCursor()

                dlg = ReviewDialog(self, p, fields)
                if dlg.exec() != QDialog.Accepted:
                    self.journal.add(wf.id, str(p), status="abgebrochen")
                    continue

                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    self.status.setText(f"{p.name}: PDF und Entwurf werden erstellt …")
                    res = wf.execute(p, dlg.values())
                finally:
                    QGuiApplication.restoreOverrideCursor()
                self.journal.add(wf.id, str(p), res.output, res.recipient, res.reference,
                                 "ok" if res.ok else "fehler", res.message)
                self.status.setText(res.message)
                done += 1
            except AbbruchDurchNutzer:
                self.journal.add(wf.id, str(p), status="abgebrochen", meldung="Anhang nicht bestätigt")
                self.status.setText(f"{p.name}: abgebrochen – kein Entwurf erstellt.")
            except Exception as e:  # noqa: BLE001
                self.journal.add(wf.id, str(p), status="fehler",
                                 meldung=f"{e}\n{traceback.format_exc()}")
                QMessageBox.critical(self, "Fehler", f"{p.name}:\n{e}")
        return done

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

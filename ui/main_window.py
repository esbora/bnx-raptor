"""Ana pencere: iş akışı seçimi, sürükle-bırak, kontrol penceresi, geçmiş."""
from __future__ import annotations

import threading
import time
import traceback
from pathlib import Path

from PySide6.QtCore import QEventLoop, QObject, QSize, Qt, QTimer, QUrl, Signal
from PySide6.QtGui import QDesktopServices, QGuiApplication, QKeySequence, QShortcut
from PySide6.QtWidgets import (
    QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFileDialog, QFormLayout, QFrame, QHBoxLayout,
    QHeaderView, QLabel, QListWidget, QListWidgetItem, QMainWindow, QMessageBox, QPushButton,
    QTableWidget, QTableWidgetItem, QTabWidget, QVBoxLayout, QWidget,
)

from core.extractor import is_valid_email
from core.journal import ARTEN, Journal
from core.update import ReleaseInfo, ist_neuer, neueste_release
from version import __version__
from workflows.base import AppContext, Field, Workflow

from . import theme
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
        lbl.setStyleSheet(f"color: {theme.F['warn'] if warn else theme.F['ok']};")

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
            f"background:{theme.F['warn_grund']}; color:{theme.F['warn']}; border:none; "
            f"border-bottom:1px solid {theme.F['rand']}; padding:8px 14px; text-align:left;")
        self.update_band.hide()
        self.update_band.clicked.connect(self.update_zeigen)
        self.release: ReleaseInfo | None = None

        # Seiten (früher Reiter): Logik unverändert über self.tabs; sichtbar ist die Seitenleiste links.
        self.tabs = QTabWidget()
        self.tabs.tabBar().hide()
        self.tabs.setDocumentMode(True)
        self.start_seite = self._build_start_seite()
        self.tabs.addTab(self.start_seite, "Start")
        self.arbeit_seite = self._seite("Versicherungsschreiben vorbereiten",
                                        "Word-Schreiben an eine Versicherung → PDF/A → E-Mail-Entwurf (wird nie gesendet).",
                                        self._build_work_tab(), zurueck=True)
        self.tabs.addTab(self.arbeit_seite, "Bearbeiten")
        # Anlagen-Assistent wird erst beim ersten Öffnen aufgebaut (PDF-Bibliothek nicht beim Start laden)
        self.anlagen_huelle = QWidget()
        self.anlagen_huelle.setObjectName("seite")
        QVBoxLayout(self.anlagen_huelle).setContentsMargins(0, 0, 0, 0)
        self.anlagen_tab = None
        self.tabs.addTab(self.anlagen_huelle, "Anlagen")
        self.pdf_seite = self._build_pdf_seite()
        self.tabs.addTab(self.pdf_seite, "PDF-Editor")
        self.akten_tab = AktenTab(ctx)
        self.akten_seite = self._seite("Akten", "Versicherungsakten: Schreiben, Antworten und E-Mails an Mandanten.",
                                       self.akten_tab)
        self.tabs.addTab(self.akten_seite, "Akten")
        self.verlauf_tab = self._build_history_tab()
        self.einst_seite = self._build_einst_seite()
        self.tabs.addTab(self.einst_seite, "Einstellungen")
        self.tabs.currentChanged.connect(self.tab_gewechselt)

        self.nav = QListWidget()
        self.nav.setObjectName("navigation")
        self.nav.setIconSize(QSize(20, 20))
        self._nav_seiten = [self.start_seite, self.anlagen_huelle, self.pdf_seite, self.akten_seite, self.einst_seite]
        for i, (text, ic) in enumerate((("Start", "start"), ("Anlagen", "anlagen"), ("PDF-Editor", "pdf"),
                                        ("Akten", "akten"), ("Einstellungen", "einstellungen"))):
            it = QListWidgetItem(theme.icon(ic, "titel"), text)
            it.setToolTip(f"{text} (Strg+{i + 1})")
            self.nav.addItem(it)
        self.nav.currentRowChanged.connect(lambda i: i >= 0 and self.tabs.setCurrentWidget(self._nav_seiten[i]))
        for i in range(len(self._nav_seiten)):
            QShortcut(QKeySequence(f"Ctrl+{i + 1}"), self, lambda i=i: self.nav.setCurrentRow(i))
        leiste = QWidget()
        leiste.setObjectName("seitenleiste")
        leiste.setAttribute(Qt.WA_StyledBackground, True)
        leiste.setFixedWidth(208)
        ll = QVBoxLayout(leiste)
        ll.setContentsMargins(8, 18, 8, 14)
        kopf = QHBoxLayout()
        kopf.setContentsMargins(10, 0, 0, 0)
        kopf.addWidget(theme.Marke(32))
        marke = QLabel("BnX-Raptor")
        marke.setObjectName("marke")
        kopf.addWidget(marke)
        kopf.addStretch(1)
        ll.addLayout(kopf)
        unter = QLabel("für Anwaltskanzleien")
        unter.setObjectName("marke_klein")
        unter.setContentsMargins(14, 0, 0, 12)
        ll.addWidget(unter)
        ll.addWidget(self.nav, 1)
        ver = QLabel(f"Version {__version__} · Pilot")
        ver.setObjectName("marke_klein")
        ver.setContentsMargins(14, 0, 0, 0)
        ll.addWidget(ver)

        rechts = QWidget()
        rl = QVBoxLayout(rechts)
        rl.setContentsMargins(0, 0, 0, 0)
        rl.setSpacing(0)
        rl.addWidget(self.update_band)
        rl.addWidget(self.tabs, 1)
        zentral = QWidget()
        zl = QHBoxLayout(zentral)
        zl.setContentsMargins(0, 0, 0, 0)
        zl.setSpacing(0)
        zl.addWidget(leiste)
        zl.addWidget(rechts, 1)
        self.setCentralWidget(zentral)
        self.resize(1180, 740)
        self.setMinimumSize(980, 600)
        self.nav.setCurrentRow(0)

        self._update_signal = _UpdateSignal()
        self._update_signal.gefunden.connect(self._update_ergebnis)
        if self.cfg.get("update_pruefen", True):
            self.update_pruefen()

    def tab_gewechselt(self, i: int):
        w = self.tabs.widget(i)
        if w is self.akten_seite:
            self.akten_tab.laden()
        elif w is self.einst_seite:
            self.refresh_history()
        elif w is self.anlagen_huelle:
            self._anlagen_tab()
        nav_seite = self.start_seite if w is self.arbeit_seite else w     # Versicherungsschreiben gehört zu „Start“
        if hasattr(self, "nav") and nav_seite in self._nav_seiten:
            self.nav.blockSignals(True)
            self.nav.setCurrentRow(self._nav_seiten.index(nav_seite))
            self.nav.blockSignals(False)

    # --- Seiten (0.4.0: Start, PDF-Editor, Einstellungen) ---
    def _seite(self, titel: str, unter: str, inhalt: QWidget, zurueck: bool = False) -> QWidget:
        w = QWidget()
        w.setObjectName("seite")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(28, 20, 28, 18)
        lay.setSpacing(10)
        kopf = QHBoxLayout()
        if zurueck:
            b = QPushButton("← Start")
            theme.rolle(b, "link")
            b.clicked.connect(lambda: self.tabs.setCurrentWidget(self.start_seite))
            kopf.addWidget(b)
        kopf.addWidget(theme.ueberschrift(titel, "h1"), 1)
        lay.addLayout(kopf)
        if unter:
            lay.addWidget(theme.rolle(QLabel(unter), "gedimmt"))
        lay.addWidget(inhalt, 1)
        return w

    def _aufgabe(self, symbol: str, titel: str, text: str, knopf: str, fn) -> QFrame:
        k = theme.karte(QFrame(), klickbar=True)
        lay = QVBoxLayout(k)
        lay.setContentsMargins(20, 18, 20, 18)
        lay.setSpacing(8)
        sym = QLabel()
        sym.setPixmap(theme.icon(symbol, "primaer", 30).pixmap(30, 30))
        lay.addWidget(sym)
        lay.addWidget(theme.ueberschrift(titel, "h3"))
        t = theme.rolle(QLabel(text), "gedimmt")
        t.setWordWrap(True)
        lay.addWidget(t, 1)
        b = QPushButton(knopf)
        b.clicked.connect(fn)
        lay.addWidget(b, 0, Qt.AlignLeft)
        k.mousePressEvent = lambda e, fn=fn: fn() if e.button() == Qt.LeftButton else None
        k.setCursor(Qt.PointingHandCursor)
        return k

    def _build_start_seite(self) -> QWidget:
        w = QWidget()
        w.setObjectName("seite")
        lay = QVBoxLayout(w)
        lay.setContentsMargins(32, 26, 32, 24)
        lay.setSpacing(18)
        k = self.ctx.kanzlei
        self.l_gruss = theme.ueberschrift("Guten Tag" + (f" – {k.name}" if k.name else ""), "h2")
        lay.addWidget(self.l_gruss)
        haupt = theme.karte(QFrame())
        hl = QHBoxLayout(haupt)
        hl.setContentsMargins(30, 26, 26, 26)
        links = QVBoxLayout()
        links.setSpacing(10)
        links.addWidget(theme.rolle(QLabel("ANLAGEN-ASSISTENT"), "akzent"), 0, Qt.AlignLeft)
        links.addWidget(theme.ueberschrift("Schriftsatz und Anlagen vorbereiten", "h1"))
        t = theme.rolle(QLabel("Word-Schriftsatz, Scans und PDFs hineinziehen, Anlagen ordnen und nummerieren, "
                               "einzelne PDFs und ein Anlagenverzeichnis in Word erstellen – anschließend als "
                               "Entwurf im klassischen Outlook prüfen."), "gedimmt")
        t.setWordWrap(True)
        links.addWidget(t)
        links.addStretch(1)
        b = QPushButton(theme.icon("paket", "primaer_text", 20), "  Anlagenpaket erstellen")
        theme.rolle(b, "primaer")
        b.setIconSize(QSize(20, 20))
        b.clicked.connect(lambda: self.anlagen_oeffnen([]))
        links.addWidget(b, 0, Qt.AlignLeft)
        hl.addLayout(links, 3)
        hl.addWidget(theme.SchriftsatzGrafik(), 2)
        lay.addWidget(haupt, 3)
        lay.addWidget(theme.ueberschrift("Weitere Aufgaben", "h2"))
        reihe = QHBoxLayout()
        reihe.setSpacing(16)
        reihe.addWidget(self._aufgabe("pdf", "PDF bearbeiten", "Seiten ordnen, Text ändern, schwärzen und als Kopie speichern.",
                                      "PDF öffnen…", lambda: self.pdf_bearbeiten()))
        reihe.addWidget(self._aufgabe("ocr", "Scan durchsuchbar machen",
                                      "Texterkennung auf diesem Rechner – Deutsch, Türkisch, Englisch.",
                                      "Scan öffnen…", self.scan_durchsuchbar))
        reihe.addWidget(self._aufgabe("mail", "Versicherungsschreiben vorbereiten",
                                      "Word-Schreiben als PDF/A und E-Mail-Entwurf an die Versicherung.",
                                      "Schreiben wählen…", self.versicherung_oeffnen))
        lay.addLayout(reihe, 2)
        return w

    def _build_pdf_seite(self) -> QWidget:
        inhalt = QWidget()
        lay = QVBoxLayout(inhalt)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(16)
        reihe = QHBoxLayout()
        reihe.setSpacing(16)
        reihe.addWidget(self._aufgabe("pdf", "PDF öffnen", "Seiten, Text, Texterkennung (OCR) und endgültiges Schwärzen. "
                                      "Das Original bleibt unverändert – gespeichert wird eine Kopie.",
                                      "PDF öffnen…", lambda: self.pdf_bearbeiten()))
        reihe.addWidget(self._aufgabe("ocr", "Scan durchsuchbar machen", "Öffnet den Scan und startet die Texterkennung "
                                      "für alle Seiten.", "Scan öffnen…", self.scan_durchsuchbar))
        lay.addLayout(reihe)
        lay.addStretch(1)
        return self._seite("PDF-Editor", "PDF-Dateien ansehen und bearbeiten – alles auf diesem Rechner.", inhalt)

    def _build_einst_seite(self) -> QWidget:
        inhalt = QWidget()
        lay = QVBoxLayout(inhalt)
        lay.setContentsMargins(0, 8, 0, 0)
        lay.setSpacing(14)
        reihe = QHBoxLayout()
        reihe.setSpacing(16)
        reihe.addWidget(self._aufgabe("kanzlei", "Kanzleidaten", "Name, Anschrift, E-Mail und Logo für Signatur und Briefkopf.",
                                      "Kanzleidaten…", self.kanzleidaten_bearbeiten))
        reihe.addWidget(self._aufgabe("adressbuch", "Versicherer-Adressbuch", "E-Mail-Adressen der Versicherer pflegen.",
                                      "Versicherer-Adressbuch…", self.adressbuch_bearbeiten))
        reihe.addWidget(self._aufgabe("info", "Programm", f"Version {__version__}. Updates werden nur angezeigt, nie "
                                      "automatisch installiert.", "Nach Updates suchen",
                                      lambda: self.update_pruefen(manuell=True)))
        lay.addLayout(reihe)
        lay.addWidget(theme.ueberschrift("Verlauf", "h2"))
        lay.addWidget(self.verlauf_tab, 1)
        return self._seite("Einstellungen", "Kanzleidaten, Adressbuch, Programm und Verlauf.", inhalt)

    def scan_durchsuchbar(self):
        name, _ = QFileDialog.getOpenFileName(self, "Scan durchsuchbar machen", "", "PDF (*.pdf)")
        if name:
            self.pdf_bearbeiten(Path(name), ocr_alle=True)

    def versicherung_oeffnen(self):
        i = next((i for i, wf in enumerate(self.workflows) if wf.id == "versicherung_brief"), 0)
        self.wf_box.setCurrentIndex(i)
        self.tabs.setCurrentWidget(self.arbeit_seite)
        if not self.files.count():
            self.pick_files()

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

    def pdf_bearbeiten(self, pfad: Path | None = None, ocr_alle: bool = False):
        if pfad is None:
            name, _ = QFileDialog.getOpenFileName(self, "PDF bearbeiten", "", "PDF (*.pdf)")
            if not name:
                return
            pfad = Path(name)
        from core.pdf_engine import SPRACHEN
        from .pdf_editor import PdfEditor
        ed = PdfEditor(self, pfad, sprachen=tuple(self.cfg.get("ocr_sprachen", SPRACHEN)))
        if ocr_alle and ed.sitzung:
            ed.ocr_umfang.setCurrentText("Alle Seiten")
            QTimer.singleShot(300, ed.ocr)
        ed.exec()

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
        if hasattr(self, "l_gruss"):
            self.l_gruss.setText("Guten Tag" + (f" – {k.name}" if k.name else ""))

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
        w = theme.karte(QFrame())
        lay = QVBoxLayout(w)
        lay.setContentsMargins(22, 18, 22, 18)
        lay.setSpacing(8)

        self.wf_box = QComboBox()
        for wf in self.workflows:
            self.wf_box.addItem(wf.name)
        lay.addWidget(QLabel("Vorgang:"))
        lay.addWidget(self.wf_box)

        lay.addWidget(QLabel("Word-Dokumente hierher ziehen oder auswählen:"))
        self.files = DropList(self.add_files)
        self.files.setToolTip("Word-Dateien (.docx) aus dem Explorer hierher ziehen")
        lay.addWidget(self.files)

        row = QHBoxLayout()
        b_add = QPushButton("Dateien wählen…")
        b_add.clicked.connect(self.pick_files)
        b_clear = QPushButton("Liste leeren")
        b_clear.clicked.connect(self.files.clear)
        self.b_run = QPushButton("&Starten")
        theme.rolle(self.b_run, "primaer")
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
                self.tabs.setCurrentWidget(self.arbeit_seite)

    def pick_files(self):
        names, _ = QFileDialog.getOpenFileNames(self, "Dokumente wählen", "", "Word (*.docx *.doc)")
        self.add_files([Path(n) for n in names])

    def run_all(self):
        wf = self.current_workflow()
        paths = [Path(self.files.item(i).text()) for i in range(self.files.count())]
        if not paths:
            theme.status_setzen(self.status, "warn", "Keine Dokumente in der Liste.")
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
        theme.status_setzen(self.status, "ok" if done == len(paths) else "warn",
                            f"{done} von {len(paths)} Dokument(en) bearbeitet." + (f" {self._letzte}" if self._letzte else ""))
        self.files.clear()

    def _dokumente_bearbeiten(self, wf, paths: list[Path]) -> int:
        from core.word_service import WordService

        done = 0
        self._letzte = ""
        for p in paths:
            if WordService.unsaved_in_running_word(p):
                QMessageBox.warning(self, "Nicht gespeichert",
                                    f"{p.name} ist in Word geöffnet und nicht gespeichert.\n"
                                    "Bitte zuerst speichern.")
                continue
            try:
                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    theme.status_setzen(self.status, None, f"⏳ {p.name}: Word liest das Dokument …")
                    fields = wf.prepare(p)
                finally:
                    QGuiApplication.restoreOverrideCursor()

                dlg = ReviewDialog(self, p, fields)
                if dlg.exec() != QDialog.Accepted:
                    self.journal.add(wf.id, str(p), status="abgebrochen")
                    continue

                QGuiApplication.setOverrideCursor(Qt.WaitCursor)
                try:
                    theme.status_setzen(self.status, None, f"⏳ {p.name}: PDF und Entwurf werden erstellt …")
                    res = wf.execute(p, dlg.values())
                finally:
                    QGuiApplication.restoreOverrideCursor()
                self.journal.add(wf.id, str(p), res.output, res.recipient, res.reference,
                                 "ok" if res.ok else "fehler", res.message)
                self._letzte = res.message
                done += 1
            except AbbruchDurchNutzer:
                self.journal.add(wf.id, str(p), status="abgebrochen", meldung="Anhang nicht bestätigt")
                self._letzte = f"{p.name}: abgebrochen – kein Entwurf erstellt."
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

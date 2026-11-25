"""Versandkontrolle in der Oberfläche (0.5): kurze Statuszeile im vorhandenen „Anhänge“-Fenster, Details bei Bedarf,
EINE Bestätigung (mit Begründung) nur bei Empfänger-Abweichung, fehlender Anlage oder nicht lesbarer Datei.
Gemeinsam für Anlagen-Assistent, Akten-E-Mails und Erinnerungen. Es wird nie gesendet.
"""
from __future__ import annotations

from pathlib import Path

from PySide6.QtCore import Qt, QTimer
from PySide6.QtGui import QBrush
from PySide6.QtWidgets import (QAbstractItemView, QCheckBox, QComboBox, QDialog, QDialogButtonBox, QFrame,
                               QHBoxLayout, QHeaderView, QInputDialog, QLabel, QListWidget, QListWidgetItem,
                               QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QTextBrowser,
                               QVBoxLayout, QWidget)

from core import versand as vk
from core import versand_service as vs
from core.extractor import is_valid_email
from core.fehlertexte import meldung

from . import theme
from .pdf_ui import AnhangVorschau

try:
    from core.netz import SitzungFehler, VerbindungFehler, WartungFehler
    OFFLINE = (VerbindungFehler, WartungFehler, SitzungFehler)
except ImportError:  # pragma: no cover
    OFFLINE = ()

STUFE_ART = {"fehler": "fehler", "warnung": "warn", "nicht_geprueft": "warn", "hinweis": "info", "ok": "ok"}
SYMBOL = {"fehler": "✖", "warnung": "⚠", "nicht_geprueft": "◌", "hinweis": "ℹ", "ok": "✓"}


def bezeichnung_aus_name(name: str) -> str:
    """„Anlage_K1.pdf“ → „Anlage K1“ (nur wenn eine Anlagennummer erkennbar ist)."""
    stamm = Path(name).stem.replace("_", " ").strip()
    m = vk.bezeichnung_nummer(stamm)
    return f"Anlage {m[0]}{m[1]}" if m and stamm.lower().startswith("anlage") else ""


class VersandDialog(AnhangVorschau):
    """Bestehendes Anhänge-Fenster + Versandkontrolle oben (Akte, Empfänger, Hauptdokument, Status, Details)."""

    def __init__(self, parent, ctx, dateien: list[tuple[Path, str, bool, str]], titel: str, akte: str = "",
                 akte_fest: bool = False, empfaenger: str = "", hauptdokument: Path | None = None):
        super().__init__(parent, [(p, b, an) for p, b, an, _ in dateien], titel,
                         aktiv=lambda: bool(ctx.cfg.get("grosse_vorschau", True)))
        self.ctx = ctx
        self.bezeichnung = {str(p): bez for p, _b, _an, bez in dateien}
        self.ergebnis: vk.Ergebnis | None = None
        self.akzeptiert: list[dict] = []
        self.resize(1040, 700)
        panel = QWidget()
        pl = QVBoxLayout(panel)
        pl.setContentsMargins(0, 0, 0, 6)
        reihe = QHBoxLayout()
        self.akte = QComboBox()
        self.akte.setAccessibleName("Akte")
        self.akte.addItem("— keine Akte —", "")
        try:
            for ref in sorted(ctx.journal.referenzen()):
                self.akte.addItem(ref, ref)
        except OFFLINE:
            pass
        self.akte.setCurrentIndex(max(self.akte.findData(akte), 0))
        self.akte.setEnabled(not akte_fest)
        self.empfaenger = QComboBox()
        self.empfaenger.setEditable(True)
        self.empfaenger.setAccessibleName("Empfänger")
        self.empfaenger.setMinimumWidth(260)
        self.haupt = QComboBox()
        self.haupt.setAccessibleName("Hauptdokument")
        self.haupt.addItem("— kein Hauptdokument —", "")
        for p, _b, _an, _bez in dateien:
            self.haupt.addItem(p.name, str(p))
        if hauptdokument is not None:
            self.haupt.setCurrentIndex(max(self.haupt.findData(str(hauptdokument)), 0))
        reihe.addWidget(QLabel("Akte:"))
        reihe.addWidget(self.akte)
        reihe.addWidget(QLabel("Empfänger:"))
        reihe.addWidget(self.empfaenger, 1)
        reihe.addWidget(QLabel("Hauptdokument:"))
        reihe.addWidget(self.haupt)
        pl.addLayout(reihe)
        zeile = QHBoxLayout()
        self.status = QLabel("Versandkontrolle läuft …")
        self.status.setWordWrap(True)
        self.status.setAccessibleName("Versandkontrolle")
        self.b_details = QPushButton("Details ▾")
        theme.rolle(self.b_details, "link")
        self.b_details.clicked.connect(self._details_umschalten)
        b_neu = QPushButton("Erneut prüfen")
        theme.rolle(b_neu, "link")
        b_neu.clicked.connect(self.pruefen)
        zeile.addWidget(self.status, 1)
        zeile.addWidget(self.b_details)
        zeile.addWidget(b_neu)
        pl.addLayout(zeile)
        self.details = QListWidget()
        self.details.setAccessibleName("Prüfergebnisse")
        self.details.setWordWrap(True)
        self.details.setMaximumHeight(170)
        self.details.setVisible(False)
        pl.addWidget(self.details)
        br = QHBoxLayout()
        self.cb_meta = QCheckBox("Metadaten (Autor, Firma …) in den Versandkopien entfernen – Originale bleiben unverändert")
        self.cb_komm = QCheckBox("Kommentare in Word-Kopien entfernen")
        self.cb_meta.setVisible(False)
        self.cb_komm.setVisible(False)
        br.addWidget(self.cb_meta)
        br.addWidget(self.cb_komm)
        br.addStretch(1)
        pl.addLayout(br)
        self.layout().insertWidget(1, panel)
        self.ok.setText("Prüfen und Outlook-Entwurf erstellen")
        self._timer = QTimer(self)
        self._timer.setSingleShot(True)
        self._timer.setInterval(450)
        self._timer.timeout.connect(self.pruefen)
        self._empfaenger_fuellen(empfaenger)
        self.akte.currentIndexChanged.connect(lambda *_: (self._empfaenger_fuellen(""), self._timer.start()))
        self.empfaenger.editTextChanged.connect(lambda *_: self._timer.start())
        self.haupt.currentIndexChanged.connect(lambda *_: self._timer.start())
        self.liste.itemChanged.connect(lambda *_: self._timer.start())
        QTimer.singleShot(0, self.pruefen)

    # --------------------------------------------------------------- Eingaben
    def _empfaenger_fuellen(self, vorgabe: str):
        ref = self.akte.currentData() or ""
        text = vorgabe or self.empfaenger.currentText()
        self.empfaenger.blockSignals(True)
        self.empfaenger.clear()
        if ref:
            try:
                p = vs.parteien(self.ctx, ref)
            except OFFLINE:
                p = None
            if p:
                for m in dict.fromkeys(p.mandant):
                    self.empfaenger.addItem(f"{m}", m)
                    self.empfaenger.setItemData(self.empfaenger.count() - 1, "Mandant", Qt.ToolTipRole)
                for m in dict.fromkeys(p.versicherung):
                    self.empfaenger.addItem(f"{m}", m)
                    self.empfaenger.setItemData(self.empfaenger.count() - 1, "Versicherung", Qt.ToolTipRole)
        self.empfaenger.setCurrentIndex(-1)
        self.empfaenger.setEditText(text)
        self.empfaenger.blockSignals(False)

    def empfaenger_text(self) -> str:
        return self.empfaenger.currentText().strip()

    def akte_ref(self) -> str:
        return self.akte.currentData() or ""

    def hauptdokument(self) -> Path | None:
        d = self.haupt.currentData()
        return Path(d) if d else None

    def _gewaehlt(self) -> list[Path]:
        out = []
        for i in range(self.liste.count()):
            it = self.liste.item(i)
            if it.checkState() == Qt.Checked:
                out.append(Path(it.data(Qt.UserRole)))
        return out

    # --------------------------------------------------------------- Prüfung
    def pruefen(self):
        gewaehlt = self._gewaehlt()
        haupt = self.hauptdokument()
        if haupt is not None and haupt not in gewaehlt:
            haupt = None
        anlagen = [(p, self.bezeichnung.get(str(p), "")) for p in gewaehlt if p != haupt
                   and self.bezeichnung.get(str(p))]
        weitere = [p for p in gewaehlt if p != haupt and not self.bezeichnung.get(str(p))]
        try:
            self.ergebnis = vs.kontrolle(self.ctx, self.akte_ref(), self.empfaenger_text(), haupt, anlagen, weitere)
        except OFFLINE as e:
            self.ergebnis = vk.pruefen(self.empfaenger_text(), "", None, haupt, anlagen, weitere)
            self.ergebnis.add("nicht_geprueft", "empfaenger", f"Beteiligte der Akte nicht abrufbar ({e}).")
        except Exception as e:  # noqa: BLE001 – Prüfung nie still als bestanden werten
            self.ergebnis = vk.Ergebnis()
            self.ergebnis.add("fehler", "text", f"Versandkontrolle konnte nicht ausgeführt werden: {meldung(e)}")
        erg = self.ergebnis
        art = STUFE_ART[erg.schlimmste]
        theme.status_setzen(self.status, art if art != "info" else None, "Versandkontrolle: " + erg.zusammenfassung())
        self.details.clear()
        for b in sorted(erg.befunde, key=lambda b: vk.STUFEN.index(b.stufe)):
            it = QListWidgetItem(f"{SYMBOL[b.stufe]} {vk.STUFE_TEXT[b.stufe]}: {b.text}"
                                 + (f"\n    Fundstelle: {b.beleg}" if b.beleg else ""))
            it.setForeground(QBrush(theme.status_farbe(STUFE_ART[b.stufe] if STUFE_ART[b.stufe] != "info"
                                                       else "info")))
            self.details.addItem(it)
        if erg.zu_bestaetigen and not self.details.isVisible():
            self._details_umschalten()
        self.cb_meta.setVisible(bool(erg.metadaten))
        self.cb_komm.setVisible(bool(erg.kommentare))

    def _details_umschalten(self):
        an = not self.details.isVisible()
        self.details.setVisible(an)
        self.b_details.setText("Details ▴" if an else "Details ▾")

    def accept(self):
        self._timer.stop()
        self.pruefen()
        erg = self.ergebnis
        if erg is None:
            return
        gewaehlt = {str(p) for p in self._gewaehlt()}
        fehlt = [b for b in erg.befunde if b.art == "lesbar" and b.stufe == "fehler" and b.datei in gewaehlt]
        if fehlt:
            QMessageBox.warning(self, "Versandkontrolle", "Diese Dateien können nicht angehängt werden:\n\n"
                                + "\n".join(f"• {b.text}" for b in fehlt) + "\n\nBitte abwählen oder ersetzen.")
            return
        ungueltig = [b for b in erg.befunde if b.art == "empfaenger" and b.stufe == "fehler"]
        if ungueltig:
            QMessageBox.warning(self, "Versandkontrolle", "\n".join(b.text for b in ungueltig))
            return
        offen = erg.zu_bestaetigen
        if offen:
            dlg = BestaetigenDialog(self, offen)
            if dlg.exec() != QDialog.Accepted:
                return
            self.akzeptiert = [{"text": b.text, "art": b.art, "begruendung": dlg.begruendung()} for b in offen]
        super().accept()


class BestaetigenDialog(QDialog):
    """EINE Bestätigung für alle wesentlichen Abweichungen – mit kurzer Begründung (wird protokolliert)."""

    def __init__(self, parent, befunde: list[vk.Befund]):
        super().__init__(parent)
        self.setWindowTitle("Versandkontrolle – bitte bestätigen")
        self.resize(640, 380)
        lay = QVBoxLayout(self)
        lay.addWidget(theme.ueberschrift("Vor dem Entwurf bitte prüfen", "h3"))
        t = QTextBrowser()
        t.setHtml("<ul>" + "".join(f"<li>{_esc(b.text)}" + (f"<br><i>Fundstelle: {_esc(b.beleg)}</i>" if b.beleg else "")
                                   + "</li>" for b in befunde) + "</ul>")
        lay.addWidget(t, 1)
        lay.addWidget(QLabel("Warum soll der Entwurf trotzdem so erstellt werden? (wird mit Ihrem Namen und der Zeit "
                             "im Versandnachweis gespeichert)"))
        self.text = QPlainTextEdit()
        self.text.setFixedHeight(70)
        self.text.setPlaceholderText("z. B. „Anlage K2 wird mit getrennter Post nachgereicht“")
        lay.addWidget(self.text)
        bb = QDialogButtonBox()
        self.ok = bb.addButton("Trotzdem Entwurf erstellen", QDialogButtonBox.AcceptRole)
        korr = bb.addButton("Zurück und korrigieren", QDialogButtonBox.RejectRole)
        korr.setDefault(True)
        self.ok.setEnabled(False)
        self.text.textChanged.connect(lambda: self.ok.setEnabled(len(self.text.toPlainText().strip()) >= 3))
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def begruendung(self) -> str:
        return self.text.toPlainText().strip()


def _esc(s: str) -> str:
    from html import escape
    return escape(s or "")


def versand_vorbereiten(parent, ctx, dateien: list[tuple[Path, str, bool, str]], titel: str, betreff: str,
                        html: str, akte: str = "", akte_fest: bool = False, empfaenger: str = "",
                        hauptdokument: Path | None = None, erwartungen: list[int] | None = None) -> dict | None:
    """Anhänge-Fenster mit Versandkontrolle → feste Kopien → Entwurf → Versandnachweis. → Nachweis oder None.
    dateien: [(Datei, Beschreibung, angehakt, Anlagenbezeichnung oder '')]."""
    from core import pdf_engine as pe_sha
    dlg = VersandDialog(parent, ctx, dateien, titel, akte, akte_fest, empfaenger, hauptdokument)
    if dlg.exec() != QDialog.Accepted:
        return None
    auswahl = dlg.auswahl()
    geaendert = [p.name for p, sha in auswahl if pe_sha.sha256(p) != sha]
    if geaendert:
        QMessageBox.critical(parent, "Entwurf", "Diese Dateien wurden nach der Vorschau verändert – bitte erneut "
                                                "öffnen:\n" + "\n".join(geaendert))
        return None
    empf = dlg.empfaenger_text()
    if empf and not all(is_valid_email(a.strip()) for a in empf.replace(";", ",").split(",") if a.strip()):
        QMessageBox.warning(parent, "Empfänger", f"„{empf}“ ist keine gültige E-Mail-Adresse.")
        return None
    haupt = dlg.hauptdokument()
    erg = dlg.ergebnis
    anhaenge = []
    for p, _sha in auswahl:
        bez = dlg.bezeichnung.get(str(p), "")
        rolle = "hauptdokument" if haupt is not None and p == haupt else ("anlage" if bez else "weitere")
        anhaenge.append(vs.Anhang(p, rolle, bez, bereinigen=dlg.cb_meta.isChecked() and str(p) in erg.metadaten,
                                  kommentare_entfernen=dlg.cb_komm.isChecked() and str(p) in erg.kommentare))
    try:
        e = vs.entwurf_mit_nachweis(ctx, dlg.akte_ref(), empf, betreff, html, anhaenge, erg, dlg.akzeptiert,
                                    erwartungen)
    except Exception as ex:  # noqa: BLE001
        QMessageBox.critical(parent, "Entwurf nicht erstellt", meldung(ex))
        return None
    teile = [f"{e.meldung}.", "Die E-Mail wurde NICHT gesendet – bitte im Entwurf prüfen und selbst senden."]
    for b in e.bereinigungen:
        teile.append(("✓ " if b.ok else "⚠ ") + b.text)
    if e.eintrag:
        teile.append(f"Versandnachweis Nr. {e.eintrag['id']}: „Entwurf erstellt“ – nach dem Senden unter Akten → "
                     "Versand „Gesendet-Ordner prüfen“ oder „Als gesendet bestätigen…“.")
    else:
        teile.append(f"⚠ Versandnachweis noch nicht gespeichert ({e.nachweis_fehler}). Er wird beim nächsten "
                     "Verbinden erneut gespeichert.")
    QMessageBox.information(parent, "Entwurf erstellt", "\n\n".join(teile))
    return e.eintrag or {}


# =========================================================================== Akte → „Versand“
class VersandListe(QWidget):
    """Versandnachweise einer Akte: Status, Prüfung, Bestätigung (Outlook „Gesendete Elemente“ oder manuell)."""

    def __init__(self, ctx):
        super().__init__()
        self.ctx = ctx
        self.akte = ""
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        self.tab = QTableWidget(0, 6)
        self.tab.setHorizontalHeaderLabels(["Erstellt", "Empfänger", "Betreff", "Anhänge", "Status", "Prüfung"])
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab.setSelectionMode(QAbstractItemView.SingleSelection)
        self.tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab.verticalHeader().hide()
        self.tab.setAccessibleName("Versandnachweise")
        self.tab.cellDoubleClicked.connect(lambda *_: self.details())
        lay.addWidget(self.tab, 1)
        reihe = QHBoxLayout()
        for text, fn, tip in (
                ("Details…", self.details, "Dateien, Prüfsummen, Prüfung und bestätigte Hinweise"),
                ("Gesendet-Ordner prüfen", self.gesendet_pruefen,
                 "Im klassischen Outlook unter „Gesendete Elemente“ eine E-Mail mit genau diesen Anhängen suchen"),
                ("Als gesendet bestätigen…", self.manuell_bestaetigen, "Ausdrückliche Bestätigung durch Sie"),
                ("Als nicht gesendet markieren…", self.nicht_gesendet, "Entwurf verworfen / nicht gesendet"),
                ("Originale prüfen", self.originale_pruefen, "Wurden angehängte Originale seit dem Entwurf geändert?")):
            b = QPushButton(text)
            b.setToolTip(tip)
            b.clicked.connect(fn)
            reihe.addWidget(b)
        reihe.addStretch(1)
        lay.addLayout(reihe)
        self.status = theme.rolle(QLabel("„Entwurf erstellt“ heißt nicht gesendet. Bestätigt wird erst durch den "
                                         "Gesendet-Ordner oder durch Sie."), "gedimmt")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)

    def laden(self, akte: str):
        self.akte = akte
        try:
            zeilen = self.ctx.versand.liste(akte) if akte else []
        except OFFLINE as e:
            theme.status_setzen(self.status, "fehler", str(e))
            return
        self.tab.setRowCount(len(zeilen))
        for r, v in enumerate(zeilen):
            from .posteingang_ui import _de
            it = QTableWidgetItem(_de(v["erstellt_am"]))
            it.setData(Qt.UserRole, v["id"])
            self.tab.setItem(r, 0, it)
            self.tab.setItem(r, 1, QTableWidgetItem(f"{v['empfaenger']} ({v['rolle_text']})"))
            self.tab.setItem(r, 2, QTableWidgetItem(v["betreff"]))
            self.tab.setItem(r, 3, QTableWidgetItem(str(len(v["dateien"]))))
            st = v["status_text"] + (f" – {v['quelle_text']}" if v["status"] == "versand_bestaetigt" else "")
            si = QTableWidgetItem(st)
            si.setForeground(theme.status_farbe("ok" if v["status"] == "versand_bestaetigt" else "warn"))
            self.tab.setItem(r, 4, si)
            pr_text = v["pruefung"] + ("" if v["gueltig"] else f" · ⚠ veraltet: {v['ungueltig_grund']}")
            self.tab.setItem(r, 5, QTableWidgetItem(pr_text))
        self.tab.resizeColumnsToContents()
        self.tab.horizontalHeader().setSectionResizeMode(2, QHeaderView.Stretch)

    def _gewaehlt(self) -> dict | None:
        r = self.tab.currentRow()
        it = self.tab.item(r, 0) if r >= 0 else None
        if it is None:
            QMessageBox.information(self, "Versand", "Bitte zuerst einen Versandnachweis markieren.")
            return None
        try:
            return self.ctx.versand.eintrag(it.data(Qt.UserRole))
        except OFFLINE as e:
            QMessageBox.warning(self, "Versand", str(e))
            return None

    def details(self):
        v = self._gewaehlt()
        if not v:
            return
        from .posteingang_ui import _de
        zeilen = [f"<h3>{_esc(v['betreff'])}</h3>",
                  f"<p>An: {_esc(v['empfaenger'])} ({_esc(v['rolle_text'])})<br>Erstellt von "
                  f"{_esc(v['erstellt_von_anzeige'])} am {_de(v['erstellt_am'])}<br>Status: <b>{_esc(v['status_text'])}"
                  "</b>" + (f" – {_esc(v['quelle_text'])}: {_esc(v['bestaetigung_text'])} "
                            f"({_esc(v['bestaetigt_von_anzeige'])}, {_de(v['bestaetigt_am'])})"
                            if v["bestaetigt_am"] else "") + "</p>",
                  f"<p>Prüfung beim Erstellen: {_esc(v['pruefung'])}"
                  + ("" if v["gueltig"] else f"<br><b>Nicht mehr gültig:</b> {_esc(v['ungueltig_grund'])}") + "</p>",
                  "<table cellpadding=3><tr><th>#</th><th>Datei</th><th>Rolle</th><th>SHA-256</th><th>bereinigt</th>"
                  "</tr>"]
        for d in v["dateien"]:
            rolle = _esc(d["bezeichnung"] or d["rolle"])
            zeilen.append(f"<tr><td>{d['position'] + 1}</td><td>{_esc(d['name'])}</td><td>{rolle}</td>"
                          f"<td><code>{d['sha256'][:16]}…</code></td><td>{'ja' if d['bereinigt'] else '–'}</td></tr>")
        zeilen.append("</table><p>Feste Versandkopien (unverändert, auch wenn das Original später bearbeitet wird):<br>"
                      + "<br>".join(_esc(d["kopie_pfad"]) for d in v["dateien"]) + "</p>")
        if v["akzeptiert"]:
            zeilen.append("<p><b>Bestätigte Hinweise:</b><ul>" + "".join(
                f"<li>{_esc(a['text'])} – „{_esc(a['begruendung'])}“ ({_esc(a['benutzer'])}, {_de(a['zeit'])})</li>"
                for a in v["akzeptiert"]) + "</ul></p>")
        dlg = QDialog(self)
        dlg.setWindowTitle(f"Versandnachweis Nr. {v['id']}")
        dlg.resize(820, 520)
        l = QVBoxLayout(dlg)
        t = QTextBrowser()
        t.setHtml("".join(zeilen))
        l.addWidget(t)
        bb = QDialogButtonBox(QDialogButtonBox.Close)
        bb.button(QDialogButtonBox.Close).setText("Schließen")
        bb.rejected.connect(dlg.reject)
        l.addWidget(bb)
        dlg.exec()

    def gesendet_pruefen(self):
        v = self._gewaehlt()
        if not v:
            return
        if v["status"] == "versand_bestaetigt":
            QMessageBox.information(self, "Versand", "Dieser Versand ist bereits bestätigt.")
            return
        from core.entwurf import mail_modus
        if mail_modus(self.ctx.cfg) == "eml":
            QMessageBox.information(self, "Versand", "Ohne klassisches Outlook kann der Gesendet-Ordner nicht gelesen "
                                    "werden. Bitte nach dem Senden „Als gesendet bestätigen…“ wählen.")
            return
        from PySide6.QtGui import QGuiApplication
        QGuiApplication.setOverrideCursor(Qt.WaitCursor)
        try:
            text = vs.gesendet_suchen(self.ctx, v)
        except Exception as ex:  # noqa: BLE001
            QGuiApplication.restoreOverrideCursor()
            QMessageBox.warning(self, "Versand", meldung(ex))
            return
        QGuiApplication.restoreOverrideCursor()
        QMessageBox.information(self, "Versand", text)
        self.laden(self.akte)

    def manuell_bestaetigen(self):
        v = self._gewaehlt()
        if not v:
            return
        text, ok = QInputDialog.getText(self, "Als gesendet bestätigen",
                                        "Sie bestätigen, dass diese E-Mail gesendet wurde.\nOptional: wie/wann?",
                                        text="")
        if not ok:
            return
        try:
            self.ctx.versand.bestaetigen(v["id"], "manuell", text)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Versand", meldung(ex))
            return
        self.laden(self.akte)

    def nicht_gesendet(self):
        v = self._gewaehlt()
        if not v:
            return
        grund, ok = QInputDialog.getText(self, "Nicht gesendet", "Grund (optional):", text="Entwurf verworfen")
        if not ok:
            return
        try:
            self.ctx.versand.nicht_bestaetigt(v["id"], grund)
        except Exception as ex:  # noqa: BLE001
            QMessageBox.warning(self, "Versand", meldung(ex))
            return
        self.laden(self.akte)

    def originale_pruefen(self):
        v = self._gewaehlt()
        if not v:
            return
        aend = vs.gueltigkeit_pruefen(self.ctx, v)
        QMessageBox.information(self, "Originale", "\n".join(aend) if aend else
                                "Alle Originale sind unverändert (gleiche Prüfsumme wie beim Entwurf).")
        self.laden(self.akte)

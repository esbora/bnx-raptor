"""Akte → „Offene Unterlagen & Antworten“ (Was fehlt?, 0.5).

Erwartete Unterlagen/Antworten mit Herkunft, Verantwortlichen, angefordert am (nur bestätigt), Nachfassen, Status.
„Erinnerung vorbereiten“ nutzt die Versandkontrolle und den bestehenden Entwurfsweg – nichts wird gesendet, und
ein Entwurf zählt nie als „angefordert“.
"""
from __future__ import annotations

import uuid

from PySide6.QtCore import Qt
from PySide6.QtWidgets import (QAbstractItemView, QComboBox, QDialog, QDialogButtonBox, QFormLayout, QHBoxLayout,
                               QHeaderView, QInputDialog, QLabel, QLineEdit, QListWidget, QListWidgetItem, QMenu,
                               QMessageBox, QPlainTextEdit, QPushButton, QTableWidget, QTableWidgetItem, QVBoxLayout,
                               QWidget)

from core import posteingang as pk
from core import unterlagen as uk

from . import theme
from .posteingang_ui import OFFLINE, _de, _tag, fehler_zeigen


class ErwartungDialog(QDialog):
    def __init__(self, parent, personen: list[dict], e: dict | None = None):
        super().__init__(parent)
        self.setWindowTitle("Erwartete Unterlage / Antwort")
        self.resize(520, 330)
        lay = QVBoxLayout(self)
        f = QFormLayout()
        self.titel = QLineEdit((e or {}).get("titel", ""))
        self.titel.setPlaceholderText("z. B. Vollmacht, Gutachten, Antwort der Versicherung")
        self.von = QComboBox()
        for k, v in uk.VON_ROLLEN.items():
            self.von.addItem(v, k)
        self.von.setCurrentIndex(max(self.von.findData((e or {}).get("von_rolle", "mandant")), 0))
        self.von_name = QLineEdit((e or {}).get("von_name", ""))
        self.von_name.setPlaceholderText("optional, z. B. Name des Sachverständigen")
        self.wer = QComboBox()
        self.wer.addItem("— niemand —", "")
        for p in personen:
            self.wer.addItem(p["anzeige"], p["name"])
        self.wer.setCurrentIndex(max(self.wer.findData((e or {}).get("verantwortlich", "")), 0))
        self.nachfassen = QLineEdit(_tag((e or {}).get("nachfassen", "")))
        self.nachfassen.setPlaceholderText("optional, TT.MM.JJJJ")
        self.beschreibung = QPlainTextEdit((e or {}).get("beschreibung", ""))
        self.beschreibung.setFixedHeight(70)
        f.addRow("Was wird erwartet?", self.titel)
        f.addRow("Von wem?", self.von)
        f.addRow("Name (optional):", self.von_name)
        f.addRow("Wer kümmert sich?", self.wer)
        f.addRow("Nachfassen am:", self.nachfassen)
        f.addRow("Notiz:", self.beschreibung)
        lay.addLayout(f)
        bb = QDialogButtonBox(QDialogButtonBox.Ok | QDialogButtonBox.Cancel)
        bb.button(QDialogButtonBox.Ok).setText("Speichern")
        bb.button(QDialogButtonBox.Cancel).setText("Abbrechen")
        bb.accepted.connect(self.accept)
        bb.rejected.connect(self.reject)
        lay.addWidget(bb)

    def werte(self) -> dict:
        return {"titel": self.titel.text().strip(), "von_rolle": self.von.currentData(),
                "von_name": self.von_name.text().strip(), "verantwortlich": self.wer.currentData() or "",
                "nachfassen": self.nachfassen.text().strip(), "beschreibung": self.beschreibung.toPlainText().strip()}


class UnterlagenWidget(QWidget):
    def __init__(self, ctx, versand_aktualisieren=None):
        super().__init__()
        self.ctx = ctx
        self.akte = ""
        self.versand_aktualisieren = versand_aktualisieren
        lay = QVBoxLayout(self)
        lay.setContentsMargins(0, 4, 0, 0)
        kopf = QHBoxLayout()
        kopf.addWidget(QLabel("Aktenart:"))
        self.akte_art = QComboBox()
        self.akte_art.setEditable(True)
        self.akte_art.setAccessibleName("Aktenart")
        self.akte_art.setMinimumWidth(180)
        self.akte_art.lineEdit().editingFinished.connect(self._art_speichern)
        self.akte_art.activated.connect(lambda *_: self._art_speichern())
        kopf.addWidget(self.akte_art)
        kopf.addStretch(1)
        self.hinweis = theme.rolle(QLabel("Checklisten sind Vorschläge – keine rechtlichen Pflichtlisten."),
                                   "gedimmt")
        kopf.addWidget(self.hinweis)
        lay.addLayout(kopf)
        self.tab = QTableWidget(0, 7)
        self.tab.setHorizontalHeaderLabels(["Unterlage / Antwort", "Von", "Wer kümmert sich", "Angefordert am",
                                            "Nachfassen", "Status", "Verknüpft"])
        self.tab.setSelectionBehavior(QAbstractItemView.SelectRows)
        self.tab.setSelectionMode(QAbstractItemView.ExtendedSelection)
        self.tab.setEditTriggers(QAbstractItemView.NoEditTriggers)
        self.tab.verticalHeader().hide()
        self.tab.setAccessibleName("Offene Unterlagen und Antworten")
        self.tab.cellDoubleClicked.connect(lambda *_: self.bearbeiten())
        lay.addWidget(self.tab, 1)
        reihe = QHBoxLayout()
        self.b_neu = QPushButton(theme.icon("plus", "titel", 16), "  Neu…")
        self.b_neu.clicked.connect(self.neu)
        self.b_vorlage = QPushButton("Checkliste anwenden…")
        self.b_vorlage.clicked.connect(self.vorlage_anwenden)
        self.b_status = QPushButton("Status ▾")
        self.b_status.clicked.connect(self.status_menue)
        self.b_angefordert = QPushButton("Als angefordert eintragen…")
        self.b_angefordert.setToolTip("Nur wenn wirklich angefordert (z. B. Brief, Telefon, gesendete E-Mail)")
        self.b_angefordert.clicked.connect(self.angefordert)
        self.b_erinnerung = QPushButton(theme.icon("mail", "titel", 16), "  Erinnerung vorbereiten…")
        self.b_erinnerung.setToolTip("Outlook-Entwurf mit den fehlenden Punkten – wird nicht gesendet")
        self.b_erinnerung.clicked.connect(self.erinnerung)
        self.b_verwalten = QPushButton("Checklisten verwalten…")
        self.b_verwalten.clicked.connect(self.vorlagen_verwalten)
        self.b_verwalten.setVisible(ctx.rolle in ("admin", "anwalt"))
        for b in (self.b_neu, self.b_vorlage, self.b_status, self.b_angefordert, self.b_erinnerung, self.b_verwalten):
            reihe.addWidget(b)
        reihe.addStretch(1)
        lay.addLayout(reihe)
        self.status = theme.rolle(QLabel(""), "gedimmt")
        self.status.setWordWrap(True)
        lay.addWidget(self.status)
        self._zeilen: list[dict] = []

    def laden(self, akte: str):
        self.akte = akte
        try:
            self._zeilen = self.ctx.unterlagen.liste(akte) if akte else []
            vorlagen = self.ctx.unterlagen.vorlagen()
            a = self.ctx.stammdaten.akte(akte) if akte else None
        except OFFLINE as e:
            theme.status_setzen(self.status, "fehler", str(e))
            return
        arten = sorted({v["akte_art"] for v in vorlagen if v["akte_art"]})
        self.akte_art.blockSignals(True)
        self.akte_art.clear()
        self.akte_art.addItems([""] + arten)
        self.akte_art.setCurrentText((a or {}).get("akte_art") or "")
        self.akte_art.blockSignals(False)
        self.tab.setRowCount(len(self._zeilen))
        for r, e in enumerate(self._zeilen):
            it = QTableWidgetItem(e["titel"] + (f" – {e['beschreibung']}" if e["beschreibung"] else ""))
            it.setData(Qt.UserRole, e["id"])
            it.setToolTip(f"Angelegt von {e['erstellt_von_anzeige']} am {_de(e['erstellt_am'])}"
                          + (f" · aus Checkliste „{e['vorlage']}“" if e["vorlage"] else ""))
            self.tab.setItem(r, 0, it)
            self.tab.setItem(r, 1, QTableWidgetItem(e["von_text"]))
            self.tab.setItem(r, 2, QTableWidgetItem(e["verantwortlich_anzeige"]))
            ang = _tag(e["angefordert_am"])
            if ang:
                ang += " (" + ("Versand bestätigt" if e["angefordert_quelle"] == "versand_bestaetigt" else
                               f"eingetragen von {e['angefordert_von_anzeige']}") + ")"
            self.tab.setItem(r, 3, QTableWidgetItem(ang))
            n = QTableWidgetItem(_tag(e["nachfassen"]) + (" ⚠" if e["nachfassen_faellig"] else ""))
            if e["nachfassen_faellig"]:
                n.setForeground(theme.status_farbe("fehler"))
            self.tab.setItem(r, 4, n)
            s = QTableWidgetItem(e["status_text"] + (f" ({e['geprueft_von_anzeige']})" if e["status"] == "geprueft"
                                                     else ""))
            s.setForeground(theme.status_farbe({"geprueft": "ok", "nicht_erforderlich": "info",
                                                "eingegangen": "warn"}.get(e["status"], "info")))
            self.tab.setItem(r, 5, s)
            links = [l for l in e["links"] if l["art"] in ("eingang", "entwurf", "versand", "anforderung")]
            text = ", ".join({"eingang": "Eingang", "entwurf": "Entwurf (nicht gesendet)", "versand": "Versand",
                              "anforderung": "Anforderung"}[l["art"]] for l in links)
            li = QTableWidgetItem(text)
            li.setToolTip("\n".join(f"{l['art']}: {l['text']} ({_de(l['zeit'])})" for l in links))
            self.tab.setItem(r, 6, li)
        self.tab.resizeColumnsToContents()
        self.tab.horizontalHeader().setSectionResizeMode(0, QHeaderView.Stretch)
        offen = sum(1 for e in self._zeilen if e["status"] in uk.OFFEN)
        self.status.setText(f"{offen} offen · {len(self._zeilen)} insgesamt" if self._zeilen else
                            "Noch keine erwarteten Unterlagen. „Neu…“ oder „Checkliste anwenden…“.")

    def _personen(self) -> list[dict]:
        try:
            return self.ctx.posteingang.personen()
        except OFFLINE:
            return []

    def _gewaehlt(self, mehrere: bool = False):
        ids = sorted({self.tab.item(i.row(), 0).data(Qt.UserRole) for i in self.tab.selectedIndexes()})
        if not ids:
            QMessageBox.information(self, "Unterlagen", "Bitte zuerst eine Zeile markieren.")
            return [] if mehrere else None
        if mehrere:
            return [e for e in self._zeilen if e["id"] in ids]
        return next((e for e in self._zeilen if e["id"] == ids[0]), None)

    def _art_speichern(self):
        if not self.akte:
            return
        try:
            a = self.ctx.stammdaten.akte(self.akte) or {}
            if (a.get("akte_art") or "") != self.akte_art.currentText().strip():
                self.ctx.unterlagen.akte_art_setzen(self.akte, self.akte_art.currentText().strip())
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)

    def neu(self):
        if not self.akte:
            return
        dlg = ErwartungDialog(self, self._personen())
        if dlg.exec() != QDialog.Accepted:
            return
        w = dlg.werte()
        try:
            self.ctx.unterlagen.anlegen(uuid.uuid4().hex, self.akte, **w)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            return
        self.laden(self.akte)

    def bearbeiten(self):
        e = self._gewaehlt()
        if not e:
            return
        dlg = ErwartungDialog(self, self._personen(), e)
        if dlg.exec() != QDialog.Accepted:
            return
        w = dlg.werte()
        basis = {k: e.get(k) for k in w}
        try:
            self.ctx.unterlagen.aendern(e["id"], _basis=basis, **w)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
        self.laden(self.akte)

    def vorlage_anwenden(self):
        if not self.akte:
            return
        try:
            vorlagen = self.ctx.unterlagen.vorlagen(self.akte_art.currentText().strip())
        except OFFLINE as e:
            fehler_zeigen(self, e)
            return
        if not vorlagen:
            QMessageBox.information(self, "Checkliste", "Es gibt keine Checklisten-Vorlage.")
            return
        namen = [f"{v['name']} ({', '.join(p['titel'] for p in v['punkte'])})" for v in vorlagen]
        wahl, ok = QInputDialog.getItem(self, "Checkliste anwenden", "Die Punkte werden in diese Akte übernommen "
                                        "(spätere Änderungen an der Vorlage ändern diese Akte nicht):", namen, 0, False)
        if not ok:
            return
        v = vorlagen[namen.index(wahl)]
        try:
            neu = self.ctx.unterlagen.vorlage_anwenden(uuid.uuid4().hex, self.akte, v["id"])
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            return
        theme.status_setzen(self.status, "ok", f"{len(neu)} Punkt(e) übernommen" + (" – bereits vorhandene wurden "
                                                                                   "nicht doppelt angelegt." if
                                                                                   len(neu) < len(v["punkte"]) else "."))
        self.laden(self.akte)

    def status_menue(self):
        auswahl = self._gewaehlt(mehrere=True)
        if not auswahl:
            return
        m = QMenu(self)
        for k, t in uk.STATUS.items():
            if k == "angefordert":
                continue                                 # nur über „Als angefordert eintragen…“
            a = m.addAction(t)
            a.setData(k)
            if k in uk.NUR_ANWALT_STATUS and self.ctx.rolle not in ("admin", "anwalt"):
                a.setEnabled(False)
                a.setToolTip("entscheidet die Rechtsanwältin / der Rechtsanwalt")
        gewaehlt = m.exec(self.b_status.mapToGlobal(self.b_status.rect().bottomLeft()))
        if not gewaehlt:
            return
        for e in auswahl:
            try:
                self.ctx.unterlagen.aendern(e["id"], _basis={"status": e["status"]}, status=gewaehlt.data())
            except Exception as ex:  # noqa: BLE001
                fehler_zeigen(self, ex)
                break
        self.laden(self.akte)

    def angefordert(self):
        auswahl = self._gewaehlt(mehrere=True)
        if not auswahl:
            return
        datum, ok = QInputDialog.getText(self, "Als angefordert eintragen",
                                         "Wann wurde angefordert? (TT.MM.JJJJ)\n\nNur eintragen, wenn die Anforderung "
                                         "tatsächlich erfolgt ist – ein Entwurf allein genügt nicht.",
                                         text=_tag(pk._heute()))
        if not ok:
            return
        notiz, _ = QInputDialog.getText(self, "Als angefordert eintragen", "Wie? (z. B. Brief, Telefon)", text="")
        for e in auswahl:
            try:
                self.ctx.unterlagen.angefordert_eintragen(e["id"], datum, "manuell", notiz=notiz)
            except Exception as ex:  # noqa: BLE001
                fehler_zeigen(self, ex)
                break
        self.laden(self.akte)

    def erinnerung(self):
        if not self.akte:
            return
        offen = [e for e in self._zeilen if e["status"] in ("nicht_angefordert", "angefordert")]
        if not offen:
            QMessageBox.information(self, "Erinnerung", "Es fehlen keine Unterlagen (alles eingegangen, geprüft oder "
                                    "nicht erforderlich).")
            return
        rollen = sorted({e["von_rolle"] for e in offen})
        rolle = rollen[0]
        if len(rollen) > 1:
            texte = [uk.VON_ROLLEN[r] for r in rollen]
            wahl, ok = QInputDialog.getItem(self, "Erinnerung", "An wen?", texte, 0, False)
            if not ok:
                return
            rolle = rollen[texte.index(wahl)]
        punkte = [e for e in offen if e["von_rolle"] == rolle]
        try:
            akte = self.ctx.stammdaten.akte(self.akte) or {}
        except OFFLINE as ex:
            fehler_zeigen(self, ex)
            return
        betreff, html = uk.erinnerung_text(akte, punkte, rolle)
        empf = {"mandant": akte.get("mandant_email") or "", "versicherung": akte.get("versicherer_email") or ""}.get(
            rolle, "")
        from .versand_ui import versand_vorbereiten
        ergebnis = versand_vorbereiten(self, self.ctx, [], "Erinnerung – Entwurf", betreff, html, akte=self.akte,
                                       akte_fest=True, empfaenger=empf, erwartungen=[e["id"] for e in punkte])
        if ergebnis is not None:
            theme.status_setzen(self.status, "ok", "Erinnerungs-Entwurf erstellt – NICHT gesendet. Der Status bleibt "
                                "unverändert, bis der Versand bestätigt oder die Anforderung eingetragen ist.")
        self.laden(self.akte)
        if self.versand_aktualisieren:
            self.versand_aktualisieren()

    def vorlagen_verwalten(self):
        VorlagenDialog(self, self.ctx).exec()
        if self.akte:
            self.laden(self.akte)


class VorlagenDialog(QDialog):
    """Checklisten-Vorlagen pflegen (Rechtsanwalt/Administrator). Bestehende Akten bleiben unverändert."""

    def __init__(self, parent, ctx):
        super().__init__(parent)
        self.ctx = ctx
        self.setWindowTitle("Checklisten-Vorlagen")
        self.resize(720, 460)
        lay = QHBoxLayout(self)
        self.liste = QListWidget()
        self.liste.currentRowChanged.connect(self._zeigen)
        links = QVBoxLayout()
        links.addWidget(self.liste, 1)
        b_neu = QPushButton("Neue Vorlage")
        b_neu.clicked.connect(lambda: self._fuellen(None))
        b_weg = QPushButton("Vorlage löschen")
        b_weg.clicked.connect(self._loeschen)
        links.addWidget(b_neu)
        links.addWidget(b_weg)
        lay.addLayout(links, 1)
        rechts = QVBoxLayout()
        f = QFormLayout()
        self.name = QLineEdit()
        self.art = QLineEdit()
        self.art.setPlaceholderText("z. B. Verkehrsunfall")
        self.beschreibung = QLineEdit()
        f.addRow("Name:", self.name)
        f.addRow("Aktenart:", self.art)
        f.addRow("Hinweis:", self.beschreibung)
        rechts.addLayout(f)
        rechts.addWidget(QLabel("Punkte (je Zeile: Titel ; von – Mandant/Versicherung/Gegenseite/Gericht/"
                                "Sachverständiger/Sonstige):"))
        self.punkte = QPlainTextEdit()
        rechts.addWidget(self.punkte, 1)
        rechts.addWidget(theme.rolle(QLabel("Änderungen gelten nur für künftig angewendete Checklisten."), "gedimmt"))
        bb = QDialogButtonBox()
        sp = bb.addButton("Speichern", QDialogButtonBox.AcceptRole)
        bb.addButton("Schließen", QDialogButtonBox.RejectRole)
        sp.clicked.connect(self._speichern)
        bb.rejected.connect(self.reject)
        rechts.addWidget(bb)
        lay.addLayout(rechts, 2)
        self._vid = None
        self._laden()

    def _laden(self):
        try:
            self.vorlagen = self.ctx.unterlagen.vorlagen()
        except OFFLINE as e:
            fehler_zeigen(self, e)
            self.vorlagen = []
        self.liste.clear()
        for v in self.vorlagen:
            self.liste.addItem(v["name"])
        if self.vorlagen:
            self.liste.setCurrentRow(0)

    def _zeigen(self, i: int):
        self._fuellen(self.vorlagen[i] if 0 <= i < len(self.vorlagen) else None)

    def _fuellen(self, v: dict | None):
        self._vid = v["id"] if v else None
        self.name.setText(v["name"] if v else "")
        self.art.setText(v["akte_art"] if v else "")
        self.beschreibung.setText(v["beschreibung"] if v else "")
        self.punkte.setPlainText("\n".join(f"{p['titel']} ; {uk.VON_ROLLEN.get(p['von_rolle'], p['von_rolle'])}"
                                           for p in (v["punkte"] if v else [])))

    def _speichern(self):
        rueck = {v.lower(): k for k, v in uk.VON_ROLLEN.items()}
        punkte = []
        for zeile in self.punkte.toPlainText().splitlines():
            if not zeile.strip():
                continue
            titel, _, von = zeile.partition(";")
            punkte.append({"titel": titel.strip(), "von_rolle": rueck.get(von.strip().lower(), "mandant")})
        try:
            self.ctx.unterlagen.vorlage_speichern(self._vid, self.name.text(), self.art.text(),
                                                  self.beschreibung.text(), punkte)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
            return
        self._laden()

    def _loeschen(self):
        if self._vid is None:
            return
        if QMessageBox.question(self, "Vorlage löschen", "Vorlage löschen? Bestehende Akten bleiben unverändert.") \
                != QMessageBox.Yes:
            return
        try:
            self.ctx.unterlagen.vorlage_loeschen(self._vid)
        except Exception as ex:  # noqa: BLE001
            fehler_zeigen(self, ex)
        self._laden()

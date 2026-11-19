"""„Sicherung erstellen…“ / „Sicherung wiederherstellen…“ (0.4.2) – Bedienung über der Mandanten-Liste.

Erstellen: Das Programm sammelt selbst Datenbank, Datenordner, verknüpfte Dokumente und Einstellungen, prüft das
Paket und fragt erst am Ende mit „Sicherung speichern unter…“ nach dem Ziel (USB-Stick oder Ordner).
Wiederherstellen: Datei wählen → Prüfung → Datum und Anzahl der Datensätze, deutliche Rückfrage → automatische
Sicherheitskopie → Wiederherstellung → Neustart.
"""
from __future__ import annotations

import logging
import sys
from pathlib import Path

from PySide6.QtCore import QEventLoop, QThread, Signal
from PySide6.QtWidgets import QApplication, QFileDialog, QMessageBox, QProgressDialog

from core import sicherung as s
from core.config import app_dir, einstellung_speichern
from core.fehlertexte import meldung
from version import __version__

LOG = logging.getLogger(__name__)
FILTER = "BnX-Raptor-Sicherung (*.zip)"


class _Arbeit(QThread):
    fortschritt = Signal(int, str)
    fertig = Signal(object)
    fehler = Signal(str)

    def __init__(self, fn):
        super().__init__()
        self.fn = fn
        self.abbrechen = False

    def run(self):
        try:
            self.fertig.emit(self.fn(lambda p, t: self.fortschritt.emit(int(p), str(t)), lambda: self.abbrechen))
        except s.Abgebrochen:
            self.fehler.emit("")
        except s.SicherungFehler as e:
            self.fehler.emit(str(e))
        except Exception as e:  # noqa: BLE001
            LOG.exception("Sicherung/Wiederherstellung")
            self.fehler.emit(meldung(e, "Sicherung"))


def _ausfuehren(parent, titel: str, fn, abbrechbar: bool = True):
    """fn im Hintergrund mit Fortschrittsfenster. → ("ok", ergebnis) | ("fehler", text) | ("abgebrochen", None)"""
    dlg = QProgressDialog(titel, "Abbrechen" if abbrechbar else None, 0, 100, parent)
    dlg.setWindowTitle(titel)
    dlg.setMinimumDuration(0)
    dlg.setMinimumWidth(460)
    dlg.setAutoClose(False)
    dlg.setAutoReset(False)
    if not abbrechbar:
        dlg.setCancelButton(None)
    dlg.setValue(0)
    arbeit = _Arbeit(fn)
    ergebnis: dict = {}
    schleife = QEventLoop()
    arbeit.fortschritt.connect(lambda p, t: (dlg.setValue(min(p, 99)), dlg.setLabelText(t)))
    arbeit.fertig.connect(lambda r: (ergebnis.update(art="ok", wert=r), schleife.quit()))
    arbeit.fehler.connect(lambda m: (ergebnis.update(art="fehler" if m else "abgebrochen", wert=m), schleife.quit()))
    dlg.canceled.connect(lambda: (setattr(arbeit, "abbrechen", True), dlg.setLabelText("Wird abgebrochen …")))
    dlg.show()
    arbeit.start()
    schleife.exec()
    arbeit.wait()
    dlg.close()
    return ergebnis.get("art", "fehler"), ergebnis.get("wert")


def _orte(ctx) -> tuple[Path, Path]:
    return s.db_pfad_von(ctx.journal.con), Path(ctx.kanzlei_store.ordner)


def _startordner(ctx) -> Path:
    """Zuletzt erfolgreich benutzter Sicherungsordner (z. B. USB-Stick) – sonst der Datenbankordner
    (im Mehrbenutzerbetrieb: der lokale Datenordner dieses Rechners)."""
    letzter = ctx.cfg.get("sicherung_letzter_ordner") or ""
    if letzter and Path(letzter).is_dir():
        return Path(letzter)
    if ctx.mehrbenutzer:
        from core.config import data_dir
        return data_dir(ctx.cfg)
    return _orte(ctx)[0].parent


def _paket_vom_server(ctx, fort, _abbr) -> s.Paket:
    """Mehrbenutzer: Der Server stellt die Sicherung aller Benutzer zusammen und prüft sie; sie wird hierher
    übertragen, damit sie auf einen USB-Stick an DIESEM Rechner gespeichert werden kann."""
    import tempfile
    fort(5, "Der Server stellt die Sicherung zusammen und prüft sie …")
    daten, info = ctx.verbindung.sicherung_erstellen()
    fort(80, "Sicherung wird übertragen und geprüft …")
    tmp = Path(tempfile.mkdtemp(prefix="bnx-sicherung-"))
    z = tmp / info["name"]
    z.write_bytes(daten)
    try:
        geprueft = s.pruefen(z, __version__)
    except s.SicherungFehler:
        s.verwerfen(s.Paket(z, tmp, {}))
        raise
    manifest = dict(geprueft.manifest)
    return s.Paket(z, tmp, manifest, list(info.get("fehlend") or []))


def _mb(n: int) -> str:
    return f"{n / 1024 / 1024:.1f} MB".replace(".", ",")


def sicherung_erstellen(parent, ctx, speichern_dialog=None) -> Path | None:
    if ctx.mehrbenutzer:
        art, paket = _ausfuehren(parent, "Sicherung wird vorbereitet …",
                                 lambda fort, abbr: _paket_vom_server(ctx, fort, abbr), abbrechbar=False)
    else:
        db, daten = _orte(ctx)
        art, paket = _ausfuehren(parent, "Sicherung wird vorbereitet …",
                                 lambda fort, abbr: s.paket_erstellen(db, daten, app_dir(), __version__, fort, abbr))
    if art == "abgebrochen":
        return None
    if art != "ok":
        QMessageBox.warning(parent, "Sicherung erstellen", f"Die Sicherung konnte nicht erstellt werden.\n\n{paket}")
        return None
    try:
        vorschlag = _startordner(ctx) / paket.zip_pfad.name
        frage = speichern_dialog or (lambda: QFileDialog.getSaveFileName(
            parent, "Sicherung speichern unter…", str(vorschlag), FILTER)[0])
        ziel = frage()
        if not ziel:
            return None                                       # abgebrochen → temporäres Paket wird gelöscht
        art, gespeichert = _ausfuehren(parent, "Sicherung wird gespeichert …",
                                       lambda fort, _a: s.speichern(paket, Path(ziel), fort), abbrechbar=False)
        if art != "ok":
            QMessageBox.warning(parent, "Sicherung erstellen", str(gespeichert))
            return None
        ctx.cfg["sicherung_letzter_ordner"] = str(gespeichert.parent)
        einstellung_speichern("sicherung_letzter_ordner", str(gespeichert.parent))
        a = paket.manifest["anzahl"]
        dokumente = sum(1 for e in paket.manifest["dateien"] if e.get("art") == "datei")
        text = (f"Die Sicherung wurde gespeichert und geprüft:\n{gespeichert}\n\n"
                f"Größe: {_mb(gespeichert.stat().st_size)} · {dokumente} Dateien\n"
                + " · ".join(f"{k}: {v}" for k, v in a.items()))
        box = QMessageBox(QMessageBox.Information if not paket.fehlend else QMessageBox.Warning,
                          "Sicherung erstellt", text, parent=parent)
        if paket.fehlend:
            box.setInformativeText(f"{len(paket.fehlend)} verknüpfte Datei(en) fehlen oder sind nicht lesbar und "
                                   "sind NICHT in der Sicherung (Einzelheiten anzeigen).")
            box.setDetailedText("\n".join(f"{f['pfad']} – {f['grund']}" for f in paket.fehlend))
        box.exec()
        return gespeichert
    finally:
        s.verwerfen(paket)


def neu_starten():
    from PySide6.QtCore import QProcess
    from core.config import _CONFIG_PFAD
    extra = ["--config", str(_CONFIG_PFAD[0])] if _CONFIG_PFAD else []
    if getattr(sys, "frozen", False):
        QProcess.startDetached(sys.executable, extra)
    else:
        QProcess.startDetached(sys.executable, [str(app_dir() / "main.py"), *extra])
    QApplication.quit()


def _bestaetigen(parent, bestaetigen, text: str, infotext: str) -> bool:
    if bestaetigen is not None:
        return bestaetigen(text, infotext)
    box = QMessageBox(QMessageBox.Warning, "Sicherung wiederherstellen", text, parent=parent)
    box.setInformativeText(infotext)
    ja = box.addButton("Wiederherstellen", QMessageBox.DestructiveRole)
    nein = box.addButton("Abbrechen", QMessageBox.RejectRole)
    box.setDefaultButton(nein)
    box.setEscapeButton(nein)
    box.exec()
    return box.clickedButton() is ja


def _datum(t: str) -> str:
    try:
        from datetime import datetime
        return datetime.strptime(t, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y, %H:%M Uhr")
    except ValueError:
        return t


def _zentral_wiederherstellen(parent, ctx, datei: str, bestaetigen) -> bool:
    art, info = _ausfuehren(parent, "Sicherung wird zum Server übertragen und geprüft …",
                            lambda fort, _a: ctx.verbindung.sicherung_pruefen(Path(datei).read_bytes()),
                            abbrechbar=False)
    if art != "ok":
        QMessageBox.warning(parent, "Sicherung wiederherstellen",
                            f"Diese Sicherung kann nicht wiederhergestellt werden.\n\n{info}")
        return False
    zeilen = "\n".join(f"  {k}: {v}   (aktuell: {info['aktuell'].get(k, 0)})" for k, v in info["anzahl"].items())
    text = f"Sicherung vom {_datum(info['erstellt'])} (BnX-Raptor {info['programm_version']}) wiederherstellen?"
    infotext = (f"Enthalten:\n{zeilen}\n  Dateien: {info['dateien']}\n\n"
                "ACHTUNG: Die gemeinsamen Daten ALLER Benutzer (Mandanten, Akten/Mandate, Versicherungen, Adressbuch, "
                "Verlauf, Dokumente, Benutzer und Einstellungen des Servers) werden durch den Stand dieser Sicherung "
                "ERSETZT. Während der Wiederherstellung können an keinem Arbeitsplatz Daten geändert werden.\n\n"
                f"Vorher legt der Server automatisch eine Sicherheitskopie an:\n{info['sicherheitskopien']}")
    if not _bestaetigen(parent, bestaetigen, text, infotext):
        return False
    art, erg = _ausfuehren(parent, "Sicherung wird auf dem Server wiederhergestellt – bitte nichts ändern …",
                           lambda fort, _a: ctx.verbindung.sicherung_wiederherstellen(info["token"]),
                           abbrechbar=False)
    if art != "ok":
        QMessageBox.warning(parent, "Sicherung wiederherstellen", str(erg))
        return False
    QMessageBox.information(parent, "Sicherung wiederhergestellt",
                            f"Die Sicherung wurde auf dem Server wiederhergestellt ({erg['dateien']} Dateien).\n\n"
                            f"Sicherheitskopie des vorherigen Stands (auf dem Server):\n{erg['sicherheitskopie']}\n\n"
                            "Alle Arbeitsplätze laden die Daten jetzt neu.")
    return True


def sicherung_wiederherstellen(parent, ctx, oeffnen_dialog=None, bestaetigen=None, neustart=neu_starten) -> bool:
    frage = oeffnen_dialog or (lambda: QFileDialog.getOpenFileName(
        parent, "Sicherung wiederherstellen – Datei wählen", str(_startordner(ctx)), FILTER)[0])
    datei = frage()
    if not datei:
        return False
    if ctx.mehrbenutzer:
        return _zentral_wiederherstellen(parent, ctx, datei, bestaetigen)
    db, daten = _orte(ctx)
    art, info = _ausfuehren(parent, "Sicherung wird geprüft …",
                            lambda fort, _a: s.pruefen(Path(datei), __version__), abbrechbar=False)
    if art != "ok":
        QMessageBox.warning(parent, "Sicherung wiederherstellen",
                            f"Diese Sicherung kann nicht wiederhergestellt werden.\n\n{info}")
        return False
    import sqlite3
    con = sqlite3.connect(db)
    try:
        aktuell = s._zaehlen(con)
    finally:
        con.close()
    zeilen = "\n".join(f"  {k}: {v}   (aktuell: {aktuell.get(k, 0)})" for k, v in info.anzahl.items())
    datum = info.erstellt
    try:
        from datetime import datetime
        datum = datetime.strptime(info.erstellt, "%Y-%m-%d %H:%M:%S").strftime("%d.%m.%Y, %H:%M Uhr")
    except ValueError:
        pass
    text = f"Sicherung vom {datum} (BnX-Raptor {info.programm_version}) wiederherstellen?"
    infotext = (f"Enthalten:\n{zeilen}\n  Dateien: {info.dateien}\n\n"
                "ACHTUNG: Alle aktuellen Mandanten, Akten/Mandate, Versicherungen, Adressbuch-Einträge, der "
                "Verlauf, das Dokumentenarchiv und die Einstellungen werden durch den Stand dieser Sicherung "
                "ERSETZT. Gesicherte Dokumente überschreiben die aktuellen Dateien gleichen Namens.\n\n"
                f"Vorher wird automatisch eine Sicherheitskopie des aktuellen Stands angelegt:\n"
                f"{daten / s.SICHERHEITSKOPIEN}\n\nBnX-Raptor startet danach neu.")
    if bestaetigen is not None:
        ok = bestaetigen(text, infotext)
    else:
        box = QMessageBox(QMessageBox.Warning, "Sicherung wiederherstellen", text, parent=parent)
        box.setInformativeText(infotext)
        ja = box.addButton("Wiederherstellen", QMessageBox.DestructiveRole)
        nein = box.addButton("Abbrechen", QMessageBox.RejectRole)
        box.setDefaultButton(nein)
        box.setEscapeButton(nein)
        box.exec()
        ok = box.clickedButton() is ja
    if not ok:
        return False
    art, erg = _ausfuehren(parent, "Sicherung wird wiederhergestellt – bitte nichts ändern …",
                           lambda fort, _a: s.wiederherstellen(Path(datei), db, daten, app_dir(), __version__, fort),
                           abbrechbar=False)
    if art != "ok":
        QMessageBox.warning(parent, "Sicherung wiederherstellen", str(erg))
        return False
    umzug = ""
    if erg.umgezogen:
        umzug = "\n\nOrdner des anderen Rechners wurden hierher übernommen:\n" + "\n".join(
            f"{alt}\n  → {neu}" for alt, neu in list(erg.umgezogen.items())[:8])
    QMessageBox.information(parent, "Sicherung wiederhergestellt",
                            f"Die Sicherung wurde wiederhergestellt ({erg.dateien} Dateien).\n\n"
                            f"Sicherheitskopie des vorherigen Stands:\n{erg.sicherheitskopie}{umzug}\n\n"
                            "BnX-Raptor wird jetzt neu gestartet.")
    neustart()
    return True

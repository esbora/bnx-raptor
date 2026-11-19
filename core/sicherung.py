"""Sicherung und Wiederherstellung (0.4.2) – z. B. auf einen USB-Stick.

Eine Sicherung ist EINE ZIP-Datei „BnX-Raptor_Backup_JJJJ-MM-TT_HH-mm-ss.zip“ mit
- datenbank/verlauf.sqlite   konsistente Kopie über die SQLite-Online-Backup-API (auch bei geöffnetem Programm):
                             Mandanten, Akten/Mandate, Versicherungen, Adressbuch, Verlauf, Dokumentenarchiv
- dateien/<wurzel>/…         alle Dateien des Datenordners (kanzlei.json, Logo …) und alle Dokumente, auf die
                             die Datenbank verweist (Archiv, Verlauf, Aktenordner) – auch aus anderen Ordnern
- einstellungen/config.json  Programmeinstellungen
- manifest.json              Format, Version, Datum, Anzahl der Datensätze, SHA-256 jeder Datei, fehlende Dateien

Wiederherstellung: Prüfung (ZIP, Prüfsummen, Datenbank-Integrität, Format/Version) → automatische
Sicherheitskopie des aktuellen Stands → Dateien und Datenbank gemeinsam ersetzen. Jeder Schritt wird vorher in
<Datenordner>/.wiederherstellung/aktionen.json protokolliert; bei einem Fehler (oder nach einem Absturz beim
nächsten Start) wird der vorherige Stand zurückgeschrieben. Pfade eines anderen Rechners werden auf den neuen
Datenordner umgeschrieben.
"""
from __future__ import annotations

import errno
import hashlib
import json
import os
import re
import shutil
import sqlite3
import tempfile
import zipfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path
from typing import Callable

FORMAT = "BnX-Raptor-Sicherung"
FORMAT_VERSION = 1
NAME_MUSTER = re.compile(r"^BnX-Raptor_Backup_.*\.zip(\.part)?$", re.IGNORECASE)
SICHERHEITSKOPIEN = "Sicherheitskopien"
ARBEIT = ".wiederherstellung"
WIEDERHERGESTELLT = "Wiederhergestellt"
AUSSCHLUSS_ORDNER = {SICHERHEITSKOPIEN.lower(), ARBEIT.lower()}
# Spalten mit Datei-/Ordnerpfaden (werden bei der Wiederherstellung angepasst)
PFAD_SPALTEN = [("dokumente", "pfad"), ("vorgaenge", "dokument"), ("vorgaenge", "ergebnis"), ("akten", "ordner")]
ZAEHL_TABELLEN = [("mandanten", "Mandanten"), ("akten", "Akten/Mandate"), ("versicherungen", "Versicherungen"),
                  ("versicherer", "Adressbuch-Einträge"), ("dokumente", "Dokumente im Archiv"),
                  ("vorgaenge", "Verlaufseinträge")]
PFLICHT_TABELLEN = {"vorgaenge", "akten"}
BLOCK = 1024 * 1024

Fortschritt = Callable[[int, str], None]


class SicherungFehler(Exception):
    """Verständliche deutsche Meldung für die Oberfläche."""


class Abgebrochen(SicherungFehler):
    pass


class _SimulierterAbsturz(BaseException):
    """Nur für Tests: Programmabbruch mitten in der Wiederherstellung (ohne Aufräumen)."""


# --------------------------------------------------------------------------- Hilfen
def dateiname(jetzt: datetime | None = None, zusatz: str = "") -> str:
    return f"BnX-Raptor_Backup_{(jetzt or datetime.now()).strftime('%Y-%m-%d_%H-%M-%S')}{zusatz}.zip"


def _nc(p) -> str:
    return os.path.normcase(os.path.normpath(str(p)))


def _unter(pfad: str, wurzel: str) -> bool:
    a, w = _nc(pfad), _nc(wurzel)
    return a == w or a.startswith(w.rstrip("\\/") + os.sep)


def _sha_datei(p: Path) -> str:
    h = hashlib.sha256()
    with open(p, "rb") as f:
        for b in iter(lambda: f.read(BLOCK), b""):
            h.update(b)
    return h.hexdigest()


def _ausgeschlossen(p: Path) -> bool:
    if NAME_MUSTER.match(p.name):
        return True                                   # Sicherungen nie in neue Sicherungen aufnehmen
    return any(teil.lower() in AUSSCHLUSS_ORDNER for teil in p.parts)


def _ist_pfad(text: str) -> bool:
    return bool(re.match(r"^([A-Za-z]:[\\/]|\\\\)", text or ""))


def _os_meldung(e: OSError, ziel: Path | None = None) -> str:
    win = getattr(e, "winerror", None)
    if e.errno == errno.ENOSPC or win in (39, 112):
        return "Nicht genug freier Speicherplatz am Ziel. Bitte einen anderen Speicherort oder einen größeren " \
               "USB-Stick wählen."
    if win in (2, 3, 15, 21, 53, 55, 433, 1167, 1006) or isinstance(e, FileNotFoundError):
        return "Das Ziel ist nicht mehr erreichbar – wurde der USB-Stick entfernt? Bitte erneut einstecken und " \
               "die Sicherung wiederholen."
    if isinstance(e, PermissionError) or win in (5, 19, 32, 33):
        return "Keine Schreibberechtigung am Ziel oder die Datei ist schreibgeschützt/geöffnet."
    return f"Schreib-/Lesefehler ({e.strerror or e})."


def db_pfad_von(con: sqlite3.Connection) -> Path:
    for r in con.execute("PRAGMA database_list"):
        if r[1] == "main" and r[2]:
            return Path(r[2])
    raise SicherungFehler("Datenbankdatei nicht gefunden.")


def _tabellen(con) -> dict[str, set[str]]:
    out = {}
    for (n,) in con.execute("SELECT name FROM sqlite_master WHERE type = 'table'").fetchall():
        out[n] = {r[1] for r in con.execute(f"PRAGMA table_info([{n}])")}
    return out


def _zaehlen(con) -> dict[str, int]:
    t = _tabellen(con)
    return {name: (con.execute(f"SELECT COUNT(*) FROM [{tab}]").fetchone()[0] if tab in t else 0)
            for tab, name in ZAEHL_TABELLEN}


def _integritaet(db: Path) -> None:
    try:
        con = sqlite3.connect(db)
        try:
            ok = con.execute("PRAGMA integrity_check").fetchone()[0]
            tab = _tabellen(con)
        finally:
            con.close()
    except sqlite3.DatabaseError as e:
        raise SicherungFehler(f"Die Datenbank in der Sicherung ist beschädigt ({e}).") from e
    if ok != "ok":
        raise SicherungFehler("Die Datenbank in der Sicherung ist beschädigt (Integritätsprüfung fehlgeschlagen).")
    fehlt = PFLICHT_TABELLEN - set(tab)
    if fehlt:
        raise SicherungFehler("Die Datenbank in der Sicherung ist unvollständig (es fehlen: "
                              f"{', '.join(sorted(fehlt))}).")


def _db_kopie(quelle: Path, ziel: Path) -> None:
    """Konsistente Kopie über die SQLite-Online-Backup-API (andere Verbindungen dürfen offen sein)."""
    src = sqlite3.connect(quelle, timeout=30)
    dst = sqlite3.connect(ziel)
    try:
        src.backup(dst)
    finally:
        dst.close()
        src.close()


# --------------------------------------------------------------------------- Dokumente einsammeln
def _referenzen(con) -> tuple[list[str], list[str]]:
    """(alle Pfade aus der Datenbank, Aktenordner)."""
    t = _tabellen(con)
    pfade, ordner = [], []
    for tab, sp in PFAD_SPALTEN:
        if tab in t and sp in t[tab]:
            for (v,) in con.execute(f"SELECT [{sp}] FROM [{tab}] WHERE COALESCE([{sp}], '') != ''"):
                if _ist_pfad(str(v)):
                    pfade.append(str(v))
                    if (tab, sp) == ("akten", "ordner"):
                        ordner.append(str(v))
    return pfade, ordner


def _wurzeln(pfade: list[str], akten_ordner: list[str], daten_ordner: Path) -> list[dict]:
    """Oberste Ordner, unter denen alle Dateien liegen (Datenordner, Aktenordner, Ordner einzelner Dokumente)."""
    kand = {_nc(daten_ordner): ("daten", str(daten_ordner))}
    for o in akten_ordner:
        kand.setdefault(_nc(o), ("ordner", o))
    for p in pfade:
        pp = Path(p)
        o = str(pp) if pp.is_dir() else str(pp.parent)
        kand.setdefault(_nc(o), ("ordner", o))
    behalten: list[tuple[str, str, str]] = []
    for nc in sorted(kand, key=len):
        art, pfad = kand[nc]
        if any(_unter(nc, w[0]) for w in behalten):
            continue
        behalten.append((nc, art, pfad))
    out = [{"id": "daten", "art": "daten", "pfad": str(daten_ordner)}]
    n = 0
    for nc, art, pfad in behalten:
        if art == "daten":
            continue
        n += 1
        out.append({"id": f"w{n}", "art": "ordner", "pfad": pfad})
    # Datenordner, der unter einem anderen Ordner liegt: trotzdem eigene Wurzel (wird immer neu zugeordnet)
    return out


def _wurzel_von(pfad: str, wurzeln: list[dict]) -> dict | None:
    beste = None
    for w in wurzeln:
        if _unter(pfad, w["pfad"]) and (beste is None or len(w["pfad"]) > len(beste["pfad"])):
            beste = w
    return beste


def _dateien_sammeln(con, daten_ordner: Path, db_datei: Path, app_ordner: Path | None) \
        -> tuple[list[dict], list[tuple[Path, dict]], list[dict]]:
    """→ (Wurzeln, [(Datei, Wurzel)], fehlende [{pfad, grund}])."""
    pfade, akten_ordner = _referenzen(con)
    wurzeln = _wurzeln(pfade, akten_ordner, daten_ordner)
    gesehen: set[str] = set()
    dateien: list[tuple[Path, dict]] = []
    fehlend: list[dict] = []
    nicht = {_nc(db_datei), _nc(str(db_datei) + "-journal"), _nc(str(db_datei) + "-wal"),
             _nc(str(db_datei) + "-shm")}
    if app_ordner:
        nicht.add(_nc(Path(app_ordner) / "config.json"))

    def nehmen(p: Path):
        k = _nc(p)
        if k in gesehen or k in nicht or _ausgeschlossen(p) or p.name.lower().startswith("bnx-raptor.log"):
            return
        gesehen.add(k)
        w = _wurzel_von(str(p), wurzeln)
        if w is not None:
            dateien.append((p, w))

    def ordner_durchlaufen(o: Path):
        for wurzel, dirs, files in os.walk(o):
            dirs[:] = [d for d in dirs if d.lower() not in AUSSCHLUSS_ORDNER]
            for f in files:
                nehmen(Path(wurzel) / f)

    if daten_ordner.is_dir():
        ordner_durchlaufen(daten_ordner)
    for o in akten_ordner:
        if Path(o).is_dir():
            ordner_durchlaufen(Path(o))
        else:
            fehlend.append({"pfad": o, "grund": "Aktenordner nicht gefunden"})
    for p in pfade:
        pp = Path(p)
        if pp.is_dir():
            ordner_durchlaufen(pp)
        elif pp.is_file():
            nehmen(pp)
        elif _nc(p) not in gesehen and p not in akten_ordner:
            gesehen.add(_nc(p))
            fehlend.append({"pfad": p, "grund": "Datei nicht gefunden"})
    return wurzeln, dateien, fehlend


# --------------------------------------------------------------------------- Sicherung erstellen
@dataclass
class Paket:
    zip_pfad: Path
    arbeitsordner: Path
    manifest: dict
    fehlend: list[dict] = field(default_factory=list)

    @property
    def groesse(self) -> int:
        return self.zip_pfad.stat().st_size


def paket_erstellen(db_datei: Path, daten_ordner: Path, app_ordner: Path | None, version: str,
                    fortschritt: Fortschritt | None = None, abbrechen: Callable[[], bool] | None = None) -> Paket:
    """Sicherungspaket im lokalen Temp-Ordner erstellen und vollständig prüfen. Quelle = Datenordner der
    aktiven Datenbank + alle verknüpften Dokumente; nichts muss ausgewählt werden."""
    fort = fortschritt or (lambda *_: None)
    abbr = abbrechen or (lambda: False)
    arbeit = Path(tempfile.mkdtemp(prefix="bnx-sicherung-"))
    try:
        fort(2, "Datenbank wird gesichert …")
        db_kopie = arbeit / "verlauf.sqlite"
        _db_kopie(Path(db_datei), db_kopie)
        _integritaet(db_kopie)
        con = sqlite3.connect(db_kopie)
        try:
            zaehler = _zaehlen(con)
            fort(6, "Dokumente werden gesucht …")
            wurzeln, dateien, fehlend = _dateien_sammeln(con, Path(daten_ordner), Path(db_datei), app_ordner)
        finally:
            con.close()
        gesamt = sum((p.stat().st_size if p.exists() else 0) for p, _ in dateien) + db_kopie.stat().st_size
        frei = shutil.disk_usage(arbeit).free
        if frei < gesamt + 50 * BLOCK:
            raise SicherungFehler("Nicht genug freier Speicherplatz für die Vorbereitung der Sicherung "
                                  f"(benötigt ca. {gesamt // BLOCK + 50} MB im Temp-Ordner).")
        jetzt = datetime.now()
        zip_pfad = arbeit / dateiname(jetzt)
        eintraege = []
        erledigt = 0
        with zipfile.ZipFile(zip_pfad, "w", compression=zipfile.ZIP_DEFLATED, compresslevel=6,
                             allowZip64=True) as zf:
            zf.write(db_kopie, "datenbank/verlauf.sqlite")
            eintraege.append({"zip": "datenbank/verlauf.sqlite", "sha256": _sha_datei(db_kopie),
                              "groesse": db_kopie.stat().st_size, "art": "datenbank"})
            cfg = Path(app_ordner) / "config.json" if app_ordner else None
            if cfg and cfg.is_file():
                zf.write(cfg, "einstellungen/config.json")
                eintraege.append({"zip": "einstellungen/config.json", "sha256": _sha_datei(cfg),
                                  "groesse": cfg.stat().st_size, "art": "einstellungen"})
            namen: set[str] = set()
            for i, (p, w) in enumerate(dateien):
                if abbr():
                    raise Abgebrochen("Sicherung abgebrochen.")
                rel = os.path.relpath(p, w["pfad"]).replace("\\", "/")
                name = f"dateien/{w['id']}/{rel}"
                if name.lower() in namen:
                    continue
                namen.add(name.lower())
                fort(8 + int(80 * i / max(len(dateien), 1)), f"Dokument {i + 1} von {len(dateien)}: {p.name}")
                h = hashlib.sha256()
                try:
                    groesse = 0
                    zi = zipfile.ZipInfo.from_file(p, name, strict_timestamps=False)
                    zi.compress_type = zipfile.ZIP_DEFLATED
                    with open(p, "rb") as quelle, zf.open(zi, "w", force_zip64=True) as z:
                        for b in iter(lambda: quelle.read(BLOCK), b""):
                            h.update(b)
                            z.write(b)
                            groesse += len(b)
                except OSError as e:
                    fehlend.append({"pfad": str(p), "grund": f"nicht lesbar ({e.strerror or e})"})
                    continue
                erledigt += groesse
                eintraege.append({"zip": name, "pfad": str(p), "wurzel": w["id"], "sha256": h.hexdigest(),
                                  "groesse": groesse, "art": "datei"})
            manifest = {
                "format": FORMAT, "format_version": FORMAT_VERSION, "programm_version": version,
                "erstellt": jetzt.strftime("%Y-%m-%d %H:%M:%S"),
                "daten_ordner": str(daten_ordner), "datenbank": Path(db_datei).name,
                "anzahl": zaehler, "wurzeln": wurzeln, "dateien": eintraege, "fehlend": fehlend,
            }
            zf.writestr("manifest.json", json.dumps(manifest, ensure_ascii=False, indent=1))
        fort(92, "Sicherung wird geprüft …")
        pruefen(zip_pfad, version)
        fort(100, "Sicherung vorbereitet")
        return Paket(zip_pfad, arbeit, manifest, fehlend)
    except BaseException:
        shutil.rmtree(arbeit, ignore_errors=True)
        raise


def verwerfen(paket: Paket | None) -> None:
    """Temporäres Paket löschen (z. B. wenn „Speichern unter“ abgebrochen wurde)."""
    if paket is not None:
        shutil.rmtree(paket.arbeitsordner, ignore_errors=True)


def speichern(paket: Paket, ziel: Path, fortschritt: Fortschritt | None = None) -> Path:
    """Geprüftes Paket an das Ziel (USB-Stick …) schreiben und dort erneut prüfen. Vorhandene Sicherungen werden
    nie überschrieben. Erfolg nur, wenn die Datei am Ziel vollständig und unverändert ist."""
    fort = fortschritt or (lambda *_: None)
    ziel = Path(ziel)
    if ziel.suffix.lower() != ".zip":
        ziel = ziel.with_name(ziel.name + ".zip")
    n = 2
    basis = ziel
    while ziel.exists():                              # ältere Sicherungen bleiben erhalten
        ziel = basis.with_name(f"{basis.stem}_{n}.zip")
        n += 1
    teil = ziel.with_name(ziel.name + ".part")
    groesse = paket.groesse
    try:
        if not ziel.parent.is_dir():
            raise FileNotFoundError(errno.ENOENT, "Zielordner fehlt", str(ziel.parent))
        if shutil.disk_usage(ziel.parent).free < groesse + BLOCK:
            raise OSError(errno.ENOSPC, "Kein Speicherplatz")
        soll = _sha_datei(paket.zip_pfad)
        geschrieben = 0
        with open(paket.zip_pfad, "rb") as q, open(teil, "wb") as z:
            for b in iter(lambda: q.read(4 * BLOCK), b""):
                z.write(b)
                geschrieben += len(b)
                fort(int(90 * geschrieben / max(groesse, 1)), "Sicherung wird gespeichert …")
            z.flush()
            os.fsync(z.fileno())
        fort(93, "Gespeicherte Datei wird geprüft …")
        if teil.stat().st_size != groesse or _sha_datei(teil) != soll:
            raise SicherungFehler("Die gespeicherte Datei weicht vom Original ab – die Sicherung ist NICHT "
                                  "gültig. Bitte erneut versuchen (anderer USB-Stick?).")
        try:
            with zipfile.ZipFile(teil) as zf:
                kaputt = zf.testzip()
        except zipfile.BadZipFile:
            kaputt = "?"
        if kaputt is not None:
            raise SicherungFehler("Die gespeicherte Sicherung ist beschädigt – bitte erneut versuchen.")
        os.replace(teil, ziel)
        fort(100, "Gespeichert")
        return ziel
    except SicherungFehler:
        _weg(teil)
        raise
    except OSError as e:
        _weg(teil)
        raise SicherungFehler("Die Sicherung wurde NICHT gespeichert. " + _os_meldung(e, ziel)) from e


def _weg(p: Path) -> None:
    try:
        p.unlink()
    except OSError:
        pass


def sicherung_erstellen(db_datei: Path, daten_ordner: Path, app_ordner: Path | None, version: str, ziel: Path,
                        fortschritt: Fortschritt | None = None) -> tuple[Path, list[dict]]:
    """Komplett in einem Schritt (Sicherheitskopie, Tests)."""
    paket = paket_erstellen(db_datei, daten_ordner, app_ordner, version, fortschritt)
    try:
        return speichern(paket, ziel), paket.fehlend
    finally:
        verwerfen(paket)


# --------------------------------------------------------------------------- Prüfen
@dataclass
class Info:
    pfad: Path
    erstellt: str
    programm_version: str
    anzahl: dict
    dateien: int
    fehlend: list[dict]
    daten_ordner: str
    manifest: dict


def _version_tupel(v: str) -> tuple:
    return tuple(int(x) for x in re.findall(r"\d+", v or "")[:3]) or (0,)


def pruefen(zip_pfad: Path, aktuelle_version: str) -> Info:
    """Vollständige Prüfung: ZIP lesbar, Prüfsummen, Manifest, Format/Version, Datenbank-Integrität."""
    zip_pfad = Path(zip_pfad)
    try:
        zf = zipfile.ZipFile(zip_pfad)
    except (zipfile.BadZipFile, OSError) as e:
        raise SicherungFehler("Die Datei ist keine gültige BnX-Raptor-Sicherung oder sie ist beschädigt.") from e
    with zf:
        try:
            m = json.loads(zf.read("manifest.json").decode("utf-8"))
        except KeyError as e:
            raise SicherungFehler("Diese ZIP-Datei ist keine BnX-Raptor-Sicherung (manifest.json fehlt).") from e
        except (ValueError, zipfile.BadZipFile, OSError) as e:
            raise SicherungFehler("Die Sicherung ist beschädigt (Inhaltsverzeichnis nicht lesbar).") from e
        if m.get("format") != FORMAT:
            raise SicherungFehler("Diese ZIP-Datei ist keine BnX-Raptor-Sicherung.")
        if int(m.get("format_version", 0)) > FORMAT_VERSION:
            raise SicherungFehler("Diese Sicherung wurde mit einer neueren BnX-Raptor-Version erstellt "
                                  f"({m.get('programm_version')}). Bitte zuerst BnX-Raptor aktualisieren.")
        if _version_tupel(m.get("programm_version", "")) > _version_tupel(aktuelle_version):
            raise SicherungFehler(f"Diese Sicherung stammt von BnX-Raptor {m.get('programm_version')} – installiert "
                                  f"ist {aktuelle_version}. Bitte zuerst BnX-Raptor aktualisieren.")
        namen = set(zf.namelist())
        for e in m.get("dateien", []):
            if e["zip"] not in namen:
                raise SicherungFehler(f"Die Sicherung ist unvollständig – es fehlt „{e['zip']}“.")
            h = hashlib.sha256()
            try:
                with zf.open(e["zip"]) as f:
                    for b in iter(lambda: f.read(BLOCK), b""):
                        h.update(b)
            except (zipfile.BadZipFile, OSError, EOFError) as ex:
                raise SicherungFehler(f"Die Sicherung ist beschädigt („{e['zip']}“ nicht lesbar).") from ex
            if h.hexdigest() != e["sha256"]:
                raise SicherungFehler(f"Die Sicherung ist beschädigt (Prüfsumme von „{e['zip']}“ stimmt nicht).")
        if "datenbank/verlauf.sqlite" not in namen:
            raise SicherungFehler("Die Sicherung enthält keine Datenbank.")
        tmp = Path(tempfile.mkdtemp(prefix="bnx-pruefen-"))
        try:
            zf.extract("datenbank/verlauf.sqlite", tmp)
            _integritaet(tmp / "datenbank" / "verlauf.sqlite")
        finally:
            shutil.rmtree(tmp, ignore_errors=True)
    return Info(zip_pfad, m.get("erstellt", ""), m.get("programm_version", ""), m.get("anzahl", {}),
                sum(1 for e in m.get("dateien", []) if e.get("art") == "datei"), m.get("fehlend", []),
                m.get("daten_ordner", ""), m)


# --------------------------------------------------------------------------- Wiederherstellen
def ziel_ordner_zuordnen(wurzeln: list[dict], daten_ordner: Path) -> dict[str, Path]:
    """Wurzel → Ordner auf diesem Rechner. Datenordner → aktueller Datenordner. Andere Ordner bleiben, wo sie
    waren, wenn es den Ordner (oder seinen übergeordneten Ordner) hier gibt; sonst → Datenordner\\Wiederhergestellt."""
    out: dict[str, Path] = {}
    belegt: set[str] = set()
    for w in wurzeln:
        if w["art"] == "daten":
            out[w["id"]] = Path(daten_ordner)
            continue
        p = Path(w["pfad"])
        if p.is_dir() or (p.parent != p and p.parent.is_dir()):
            out[w["id"]] = p
            continue
        basis = Path(daten_ordner) / WIEDERHERGESTELLT / (p.name or w["id"])
        ziel, n = basis, 2
        while _nc(ziel) in belegt:
            ziel = basis.with_name(f"{basis.name}_{n}")
            n += 1
        belegt.add(_nc(ziel))
        out[w["id"]] = ziel
    return out


def _abbilden(wurzeln: list[dict], zuordnung: dict[str, Path]) -> Callable[[str], str]:
    def f(alt: str) -> str:
        if not _ist_pfad(alt):
            return alt
        w = _wurzel_von(alt, wurzeln)
        if w is None:
            return alt
        rel = os.path.relpath(alt, w["pfad"])
        neu = zuordnung[w["id"]] if rel == "." else zuordnung[w["id"]] / rel
        return str(neu)
    return f


def _pfade_umschreiben(db: Path, abbild: Callable[[str], str]) -> None:
    con = sqlite3.connect(db)
    try:
        t = _tabellen(con)
        for tab, sp in PFAD_SPALTEN:
            if tab not in t or sp not in t[tab]:
                continue
            for rowid, v in con.execute(f"SELECT rowid, [{sp}] FROM [{tab}]").fetchall():
                if v and _ist_pfad(str(v)):
                    neu = abbild(str(v))
                    if neu != v:
                        con.execute(f"UPDATE [{tab}] SET [{sp}] = ? WHERE rowid = ?", (neu, rowid))
                        if tab == "dokumente" and "schluessel" in t[tab]:
                            from core.archiv import _schluessel
                            con.execute("UPDATE dokumente SET schluessel = ? WHERE rowid = ?",
                                        (_schluessel(Path(neu)), rowid))
        con.commit()
    finally:
        con.close()


class _Transaktion:
    """Ersetzt Dateien und Datenbank mit Rückweg. Jede Aktion wird VOR der Ausführung protokolliert."""

    def __init__(self, daten_ordner: Path):
        self.ordner = Path(daten_ordner) / ARBEIT
        if self.ordner.exists():
            shutil.rmtree(self.ordner, ignore_errors=True)
        (self.ordner / "alt").mkdir(parents=True)
        self.log = self.ordner / "aktionen.json"
        self.aktionen: list[dict] = []
        self._schreiben()

    def _schreiben(self):
        tmp = self.log.with_suffix(".tmp")
        tmp.write_text(json.dumps({"aktionen": self.aktionen}, ensure_ascii=False), encoding="utf-8")
        os.replace(tmp, self.log)

    def datei(self, ziel: Path, quelle: Path):
        ziel = Path(ziel)
        a = {"art": "datei", "ziel": str(ziel), "alt": "", "ordner": []}
        if ziel.exists():
            a["alt"] = str(self.ordner / "alt" / f"{len(self.aktionen)}")
        fehlende = []
        p = ziel.parent
        while not p.exists():
            fehlende.append(str(p))
            p = p.parent
        a["ordner"] = fehlende
        self.aktionen.append(a)
        self._schreiben()
        if a["alt"]:
            shutil.move(str(ziel), a["alt"])
        ziel.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(quelle, ziel)

    def datenbank(self, db: Path, neu: Path):
        alt = self.ordner / "alt" / "verlauf.sqlite"
        _db_kopie(db, alt)
        self.aktionen.append({"art": "datenbank", "ziel": str(db), "alt": str(alt)})
        self._schreiben()
        _db_kopie(neu, db)                            # Backup-API schreibt atomar in die aktive Datenbank

    def zuruecksetzen(self):
        _zuruecksetzen(self.aktionen)
        shutil.rmtree(self.ordner, ignore_errors=True)

    def abschliessen(self):
        shutil.rmtree(self.ordner, ignore_errors=True)


def _zuruecksetzen(aktionen: list[dict]) -> None:
    for a in reversed(aktionen):
        try:
            if a["art"] == "datenbank":
                if Path(a["alt"]).exists():
                    _db_kopie(Path(a["alt"]), Path(a["ziel"]))
                continue
            ziel = Path(a["ziel"])
            if a["alt"]:
                if Path(a["alt"]).exists():
                    if ziel.exists():
                        ziel.unlink()
                    shutil.move(a["alt"], str(ziel))
            elif ziel.exists():
                ziel.unlink()
            for o in a.get("ordner", []):
                try:
                    Path(o).rmdir()
                except OSError:
                    pass
        except OSError:
            continue


def offene_wiederherstellung_zuruecksetzen(daten_ordner: Path) -> bool:
    """Beim Programmstart: wurde eine Wiederherstellung unterbrochen (Absturz, Stromausfall), den vorherigen
    Stand zurückschreiben. True, wenn etwas zurückgesetzt wurde."""
    ordner = Path(daten_ordner) / ARBEIT
    log = ordner / "aktionen.json"
    if not log.exists():
        if ordner.exists():
            shutil.rmtree(ordner, ignore_errors=True)
        return False
    try:
        aktionen = json.loads(log.read_text(encoding="utf-8")).get("aktionen", [])
    except (OSError, ValueError):
        aktionen = []
    _zuruecksetzen(aktionen)
    shutil.rmtree(ordner, ignore_errors=True)
    return True


@dataclass
class Ergebnis:
    sicherheitskopie: Path
    umgezogen: dict[str, str]           # alter Ordner → neuer Ordner (nur bei geänderten Orten)
    dateien: int


def wiederherstellen(zip_pfad: Path, db_datei: Path, daten_ordner: Path, app_ordner: Path | None, version: str,
                     fortschritt: Fortschritt | None = None, _test_absturz_nach: int | None = None,
                     _test_fehler_nach: int | None = None) -> Ergebnis:
    fort = fortschritt or (lambda *_: None)
    fort(2, "Sicherung wird geprüft …")
    info = pruefen(zip_pfad, version)
    m = info.manifest
    # 1) Sicherheitskopie des aktuellen Stands
    fort(10, "Sicherheitskopie des aktuellen Stands …")
    sk_ordner = Path(daten_ordner) / SICHERHEITSKOPIEN
    sk_ordner.mkdir(parents=True, exist_ok=True)
    sicherheitskopie, _ = sicherung_erstellen(
        db_datei, daten_ordner, app_ordner, version,
        sk_ordner / dateiname(zusatz="_vor_Wiederherstellung"),
        lambda p, t: fort(10 + p * 3 // 10, "Sicherheitskopie: " + t))
    # 2) Sicherung entpacken und Pfade anpassen
    fort(42, "Sicherung wird entpackt …")
    stufe = Path(tempfile.mkdtemp(prefix="bnx-wiederherstellen-"))
    try:
        with zipfile.ZipFile(zip_pfad) as zf:
            zf.extractall(stufe)
        zuordnung = ziel_ordner_zuordnen(m["wurzeln"], daten_ordner)
        abbild = _abbilden(m["wurzeln"], zuordnung)
        neue_db = stufe / "datenbank" / "verlauf.sqlite"
        _pfade_umschreiben(neue_db, abbild)
        _integritaet(neue_db)
        dateien = [e for e in m["dateien"] if e.get("art") == "datei"]
        gesamt = sum(e["groesse"] for e in dateien)
        for o in {str(zuordnung[w["id"]]) for w in m["wurzeln"]}:
            p = Path(o)
            while not p.exists() and p.parent != p:
                p = p.parent
            if p.exists() and shutil.disk_usage(p).free < gesamt + 20 * BLOCK:
                raise SicherungFehler("Nicht genug freier Speicherplatz für die Wiederherstellung.")
        # 3) Ersetzen – mit Rückweg
        tx = _Transaktion(daten_ordner)
        try:
            for i, e in enumerate(dateien):
                if _test_absturz_nach is not None and i == _test_absturz_nach:
                    raise _SimulierterAbsturz()
                if _test_fehler_nach is not None and i == _test_fehler_nach:
                    raise OSError(errno.EIO, "simulierter Schreibfehler")
                ziel = Path(abbild(e["pfad"]))
                fort(45 + int(45 * i / max(len(dateien), 1)), f"Dokument {i + 1} von {len(dateien)}: {ziel.name}")
                tx.datei(ziel, stufe / e["zip"])
            cfg_neu = stufe / "einstellungen" / "config.json"
            if app_ordner and cfg_neu.is_file():
                tx.datei(Path(app_ordner) / "config.json", _config_anpassen(cfg_neu, Path(app_ordner), abbild))
            fort(93, "Datenbank wird wiederhergestellt …")
            tx.datenbank(Path(db_datei), neue_db)
        except _SimulierterAbsturz:
            raise                                     # Test: wie ein Programmabbruch – kein Aufräumen
        except BaseException as ex:
            tx.zuruecksetzen()
            if isinstance(ex, SicherungFehler):
                raise SicherungFehler(str(ex) + " Der vorherige Stand wurde wiederhergestellt.") from ex
            if isinstance(ex, OSError):
                raise SicherungFehler("Wiederherstellung fehlgeschlagen – der vorherige Stand wurde "
                                      "wiederhergestellt. " + _os_meldung(ex)) from ex
            raise
        tx.abschliessen()
        umgezogen = {w["pfad"]: str(zuordnung[w["id"]]) for w in m["wurzeln"]
                     if _nc(w["pfad"]) != _nc(zuordnung[w["id"]])}
        fort(100, "Wiederherstellung abgeschlossen")
        return Ergebnis(sicherheitskopie, umgezogen, len(dateien))
    finally:
        shutil.rmtree(stufe, ignore_errors=True)


def _config_anpassen(cfg_datei: Path, app_ordner: Path, abbild: Callable[[str], str]) -> Path:
    """Einstellungen aus der Sicherung übernehmen, aber den Datenordner DIESES Rechners behalten und alte
    Ordnerpfade anpassen (nicht vorhandene → leer = Standard)."""
    try:
        neu = json.loads(cfg_datei.read_text(encoding="utf-8-sig"))
    except (OSError, ValueError):
        neu = {}
    aktuell_datei = app_ordner / "config.json"
    try:
        aktuell = json.loads(aktuell_datei.read_text(encoding="utf-8-sig")) if aktuell_datei.exists() else {}
    except (OSError, ValueError):
        aktuell = {}
    for k in ("daten_ordner",):
        if k in aktuell:
            neu[k] = aktuell[k]
        else:
            neu.pop(k, None)
    for k in ("pdf_ordner", "sicherung_letzter_ordner"):
        v = neu.get(k)
        if v and _ist_pfad(v):
            v2 = abbild(v)
            neu[k] = v2 if Path(v2).is_dir() else ""
    if "sicherung_letzter_ordner" in aktuell:
        neu["sicherung_letzter_ordner"] = aktuell["sicherung_letzter_ordner"]
    ziel = cfg_datei.with_name("config_angepasst.json")
    ziel.write_text(json.dumps(neu, ensure_ascii=False, indent=2), encoding="utf-8")
    return ziel

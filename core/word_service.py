"""Word otomasyonu (COM). Sadece Windows + Microsoft Word ile çalışır.

Zaman sınırı (0.3.0): görünmez Word bazen gizli bir soru penceresinde bekler
("Datei in Verwendung", "schwerwiegender Fehler beim letzten Öffnen" …) ve COM çağrısı
hiç dönmez. Bu durumda süre dolunca SADECE bu programın başlattığı Word süreci kapatılır;
avukatın açık Word pencereleri ve belgeleri etkilenmez.
"""
from __future__ import annotations

import subprocess
import threading
import time
from contextlib import contextmanager
from pathlib import Path

WD_EXPORT_PDF = 17


class WordError(Exception):
    pass


def zeitlimit_meldung(sekunden: float, beendet: bool) -> str:
    text = (f"Microsoft Word hat nicht innerhalb von {int(sekunden)} Sekunden reagiert.\n"
            "Wahrscheinlich wartet Word auf eine Rückfrage (z. B. „Datei in Verwendung“).\n")
    if beendet:
        text += ("Die von BnX-Raptor gestartete Word-Sitzung wurde beendet. "
                 "Ihre geöffneten Word-Dokumente sind davon nicht betroffen.\n")
    else:
        text += "Die Word-Sitzung konnte nicht automatisch beendet werden.\n"
    return text + "Bitte das Dokument in Word schließen und erneut versuchen."


def word_pids() -> set[int]:
    """Çalışan WINWORD.EXE süreçlerinin numaraları (Windows tasklist)."""
    try:
        roh = subprocess.run(
            ["tasklist", "/fo", "csv", "/nh", "/fi", "IMAGENAME eq WINWORD.EXE"],
            capture_output=True, timeout=15,
            creationflags=getattr(subprocess, "CREATE_NO_WINDOW", 0)).stdout
    except Exception:  # noqa: BLE001
        return set()
    return _pids_aus_tasklist(roh or b"")


def _pids_aus_tasklist(roh: bytes) -> set[int]:
    # Bayt olarak okunur: Word yoksa tasklist yerel dilde (ü, ö …, OEM kod sayfası) mesaj yazar
    out = roh.decode("ascii", errors="ignore")
    pids = set()
    for zeile in out.splitlines():
        teile = zeile.strip().strip('"').split('","')
        if len(teile) > 1 and teile[0].lower() == "winword.exe" and teile[1].isdigit():
            pids.add(int(teile[1]))
    return pids


def _prozess_beenden(pid: int) -> bool:
    import ctypes
    k32 = ctypes.windll.kernel32  # type: ignore[attr-defined]
    h = k32.OpenProcess(0x0001 | 0x00100000, False, pid)   # PROCESS_TERMINATE | SYNCHRONIZE
    if not h:
        return False
    try:
        ok = bool(k32.TerminateProcess(h, 1))
        if ok:
            k32.WaitForSingleObject(h, 10000)       # dosya kilitleri bırakılsın (en çok 10 s)
        return ok
    finally:
        k32.CloseHandle(h)


def eintrag_betrifft(daten: bytes, path: Path) -> bool:
    """Word'ün 'Resiliency' kaydı bu belgeye mi ait? (değer UTF-16 metin içerir)"""
    if not isinstance(daten, (bytes, bytearray)):
        return False
    text = bytes(daten).decode("utf-16-le", errors="ignore").lower()
    return str(path).lower() in text


def resiliency_bereinigen(version: str, path: Path) -> int:
    """Word'ün bu belge için tuttuğu 'son açılışta ciddi hata' kayıtlarını siler.
    Yalnızca tam olarak bu dosya yolunu içeren değerler silinir. Silinen sayısını döndürür."""
    try:
        import winreg
    except ImportError:
        return 0
    basis = rf"Software\Microsoft\Office\{version}\Word\Resiliency"
    geloescht = 0

    def durchgehen(pfad: str) -> None:
        nonlocal geloescht
        try:
            key = winreg.OpenKey(winreg.HKEY_CURRENT_USER, pfad, 0,
                                 winreg.KEY_READ | winreg.KEY_SET_VALUE)
        except OSError:
            return
        with key:
            unter, loeschen, i = [], [], 0
            while True:
                try:
                    unter.append(winreg.EnumKey(key, i))
                    i += 1
                except OSError:
                    break
            i = 0
            while True:
                try:
                    name, daten, _typ = winreg.EnumValue(key, i)
                    i += 1
                except OSError:
                    break
                if eintrag_betrifft(daten, path):
                    loeschen.append(name)
            for name in loeschen:
                try:
                    winreg.DeleteValue(key, name)
                    geloescht += 1
                except OSError:
                    pass
        for u in unter:
            durchgehen(pfad + "\\" + u)

    durchgehen(basis)
    return geloescht


def sperrdatei_entfernen(dokument: Path, seit: float) -> list[str]:
    """Kapatılan Word'ün bıraktığı kilit dosyasını ("~$…") siler.

    Word kilit dosyası adında baştaki 0–2 harfi atar ("Brief.docx" -> "~$ief.docx").
    Sadece `seit` anından SONRA oluşturulmuş olanlar silinir: avukatın kendi Word'ünün
    daha önce oluşturduğu kilit dosyasına dokunulmaz.
    """
    name = dokument.name
    adaylar = {f"~${name}", f"~${name[1:]}", f"~${name[2:]}"}
    geloescht = []
    for kandidat in adaylar:
        f = dokument.with_name(kandidat)
        try:
            st = f.stat()
            # Windows "tunneling" yeniden oluşturulan dosyada eski ctime'ı koruyabilir -> mtime da
            if f.is_file() and max(st.st_ctime, st.st_mtime) >= seit and st.st_size < 4096:
                f.unlink()
                geloescht.append(f.name)
        except OSError:
            pass
    return geloescht


class WordService:
    """Ayrı, görünmez bir Word örneği açar; avukatın açık Word penceresine dokunmaz."""

    def __init__(self, zeitlimit: float = 90):
        self.zeitlimit = zeitlimit
        self.pid: int | None = None          # bu programın başlattığı WINWORD.EXE
        self.version = "16.0"
        self._abgelaufen = False
        self._beendet = False
        self._dokument: Path | None = None
        self._start = time.time()

    def __enter__(self) -> "WordService":
        import pythoncom
        import win32com.client as win32
        pythoncom.CoInitialize()
        self._start = time.time() - 1                # dosya zaman damgası hassasiyeti için pay
        vorher = word_pids()
        try:
            self.app = win32.DispatchEx("Word.Application")
        except Exception as e:  # noqa: BLE001
            # Microsoft 365: görünmez başlatma, Word lisansını yenileyene kadar başarısız olabiliyor
            raise WordError(
                "Microsoft Word konnte nicht gestartet werden.\n"
                "Bitte Word einmal normal öffnen (ggf. anmelden), wieder schließen und erneut versuchen."
            ) from e
        neu = word_pids() - vorher
        # Tam olarak bir yeni süreç varsa o bizimdir; emin değilsek hiçbir süreci kapatmayız
        self.pid = neu.pop() if len(neu) == 1 else None
        try:
            self.version = str(self.app.Version) or self.version
        except Exception:  # noqa: BLE001
            pass
        self.app.Visible = False
        self.app.DisplayAlerts = 0
        return self

    def __exit__(self, *exc) -> None:
        if self._beendet:
            return
        try:
            self.app.Quit(SaveChanges=0)
        except Exception:  # noqa: BLE001
            pass

    # --- zaman sınırı ---------------------------------------------------------
    def _notabbruch(self) -> None:
        """Zamanlayıcı iş parçacığında çalışır: sadece kendi Word sürecimizi kapatır."""
        self._abgelaufen = True
        if self.pid and self.pid in word_pids():
            self._beendet = _prozess_beenden(self.pid)
        if self._beendet and self._dokument:
            resiliency_bereinigen(self.version, self._dokument)
            sperrdatei_entfernen(self._dokument, self._start)

    @contextmanager
    def _waechter(self, dokument: Path):
        self._dokument = dokument
        timer = threading.Timer(self.zeitlimit, self._notabbruch)
        timer.daemon = True
        timer.start()
        try:
            yield
        except Exception as e:  # noqa: BLE001
            if self._abgelaufen:
                raise WordError(zeitlimit_meldung(self.zeitlimit, self._beendet)) from e
            raise
        finally:
            timer.cancel()
        if self._abgelaufen:
            raise WordError(zeitlimit_meldung(self.zeitlimit, self._beendet))

    @staticmethod
    def unsaved_in_running_word(path: Path) -> bool:
        """Belge avukatın Word'ünde açık ve kaydedilmemiş mi?"""
        try:
            import win32com.client as win32
            app = win32.GetActiveObject("Word.Application")
            for doc in app.Documents:
                if Path(doc.FullName).resolve() == path.resolve():
                    return not doc.Saved
        except Exception:  # noqa: BLE001
            pass
        return False

    def _open(self, path: Path):
        # Önceki bir zaman aşımından kalan "ciddi hata" kaydı gizli bir soru açar -> önce temizle
        resiliency_bereinigen(self.version, path)
        try:
            return self.app.Documents.Open(
                str(path), ReadOnly=True, AddToRecentFiles=False, Visible=False
            )
        except Exception as e:  # noqa: BLE001
            if self._abgelaufen:
                raise
            raise WordError(f"Dokument konnte nicht geöffnet werden: {path.name}") from e

    def read(self, path: Path) -> tuple[str, dict[str, str]]:
        """Tüm metni (başlık/altbilgi/metin kutuları dahil) ve içerik denetimlerini okur."""
        with self._waechter(path):
            doc = self._open(path)
            texts: list[str] = []
            controls: dict[str, str] = {}
            try:
                for story in doc.StoryRanges:
                    while story is not None:
                        texts.append(story.Text)
                        for cc in story.ContentControls:
                            if cc.ShowingPlaceholderText:
                                continue
                            value = cc.Range.Text.replace("\r", " ").strip()
                            for key in (cc.Tag, cc.Title):
                                if key and key not in controls:
                                    controls[key] = value
                        story = story.NextStoryRange
            finally:
                if not self._abgelaufen:
                    doc.Close(SaveChanges=0)
        return "\r".join(texts), controls

    def export_pdf(self, path: Path, pdf_path: Path, pdfa: bool = True) -> None:
        with self._waechter(path):
            doc = self._open(path)
            try:
                doc.ExportAsFixedFormat(
                    OutputFileName=str(pdf_path), ExportFormat=WD_EXPORT_PDF,
                    OpenAfterExport=False, OptimizeFor=0, Range=0,
                    IncludeDocProps=True, DocStructureTags=True,
                    CreateBookmarks=0, UseISO19005_1=pdfa,
                )
            finally:
                if not self._abgelaufen:
                    doc.Close(SaveChanges=0)

"""Word otomasyonu (COM). Sadece Windows + Microsoft Word ile çalışır."""
from __future__ import annotations

from pathlib import Path

WD_EXPORT_PDF = 17


class WordError(Exception):
    pass


class WordService:
    """Ayrı, görünmez bir Word örneği açar; avukatın açık Word penceresine dokunmaz."""

    def __enter__(self) -> "WordService":
        import pythoncom
        import win32com.client as win32
        pythoncom.CoInitialize()
        try:
            self.app = win32.DispatchEx("Word.Application")
        except Exception as e:  # noqa: BLE001
            # Microsoft 365: görünmez başlatma, Word lisansını yenileyene kadar başarısız olabiliyor
            raise WordError(
                "Microsoft Word konnte nicht gestartet werden.\n"
                "Bitte Word einmal normal öffnen (ggf. anmelden), wieder schließen und erneut versuchen."
            ) from e
        self.app.Visible = False
        self.app.DisplayAlerts = 0
        return self

    def __exit__(self, *exc) -> None:
        try:
            self.app.Quit(SaveChanges=0)
        except Exception:  # noqa: BLE001
            pass

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
        try:
            return self.app.Documents.Open(
                str(path), ReadOnly=True, AddToRecentFiles=False, Visible=False
            )
        except Exception as e:  # noqa: BLE001
            raise WordError(f"Dokument konnte nicht geöffnet werden: {path.name}") from e

    def read(self, path: Path) -> tuple[str, dict[str, str]]:
        """Tüm metni (başlık/altbilgi/metin kutuları dahil) ve içerik denetimlerini okur."""
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
            doc.Close(SaveChanges=0)
        return "\r".join(texts), controls

    def export_pdf(self, path: Path, pdf_path: Path, pdfa: bool = True) -> None:
        doc = self._open(path)
        try:
            doc.ExportAsFixedFormat(
                OutputFileName=str(pdf_path), ExportFormat=WD_EXPORT_PDF,
                OpenAfterExport=False, OptimizeFor=0, Range=0,
                IncludeDocProps=True, DocStructureTags=True,
                CreateBookmarks=0, UseISO19005_1=pdfa,
            )
        finally:
            doc.Close(SaveChanges=0)

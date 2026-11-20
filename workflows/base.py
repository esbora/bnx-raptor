"""Her iş akışı bu sınıftan türetilir. Yeni bir iş = workflows/ altında yeni bir dosya."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Callable

from core.kanzlei import Kanzlei, KanzleiStore


class AppContext:
    """İş akışlarının ortak eriştiği her şey: ayarlar, büro bilgileri, veritabanı."""

    def __init__(self, cfg: dict, kanzlei_store: KanzleiStore, journal, verbindung=None, kopien=None):
        self.cfg = cfg
        self.kanzlei_store = kanzlei_store
        self.journal = journal
        self._adressbuch = None
        # 0.4.2 Mehrbenutzer: verbindung = core.netz.Verbindung (Client/Server-Oberfläche), sonst Einzelplatz
        self.verbindung = verbindung
        from core import netz
        self.dateien = netz.FernDateien(verbindung, kopien) if verbindung else netz.LokaleDateien()
        self._kopien = kopien
        # Word işi bunun üzerinden çalışır. Arayüz bunu "arka planda, zaman sınırlı" bir
        # çağrıyla değiştirir; testlerde ve varsayılan olarak doğrudan çağrılır.
        # Not: SQLite (journal/adres defteri) sadece ana iş parçacığında kullanılabilir.
        self.im_hintergrund = lambda fn, frist=None: fn()
        # 0.4: oluşturulan PDF taslağa eklenmeden önce PDF-Editor'de kontrol/düzenleme.
        # Varsayılan: değişiklik yok. Arayüz, kullanıcı isterse editörü açan bir fonksiyon koyar;
        # dönen yol taslağa eklenecek (önizlemede onaylanmış) dosyadır.
        self.pdf_nachbearbeiten = lambda pdf: pdf

    @property
    def adressbuch(self):
        """Versicherer-Adressbuch – Journal ile aynı SQLite dosyasında (ilk kullanımda açılır)."""
        if self._adressbuch is None and self.verbindung is not None:
            from core.netz import _Fern
            self._adressbuch = _Fern(self.verbindung, "adressbuch")
        if self._adressbuch is None:
            from core.adressbuch import Adressbuch
            self._adressbuch = Adressbuch(self.journal.con,
                                          self.cfg.get("versicherer_abkuerzungen", {}))
        return self._adressbuch

    @property
    def archiv(self):
        """Dokumentenarchiv (0.4.1) – gleiche SQLite-Datei wie Verlauf/Akten."""
        if getattr(self, "_archiv", None) is None and self.verbindung is not None:
            from core.netz import FernArchiv
            self._archiv = FernArchiv(self.verbindung, self._kopien)
        if getattr(self, "_archiv", None) is None:
            from core.archiv import Archiv
            self._archiv = Archiv(self.journal.con)
        return self._archiv

    @property
    def stammdaten(self):
        """Mandanten und Versicherungen (0.4.1); Versicherer-E-Mails bleiben im Adressbuch."""
        if getattr(self, "_stammdaten", None) is None and self.verbindung is not None:
            from core.netz import _Fern
            self._stammdaten = _Fern(self.verbindung, "stammdaten")
        if getattr(self, "_stammdaten", None) is None:
            from core.stammdaten import Stammdaten
            self._stammdaten = Stammdaten(self.journal.con, self.adressbuch)
        return self._stammdaten

    @property
    def kanzlei(self) -> Kanzlei:
        return self.kanzlei_store.laden()          # her seferinde güncel hali

    @property
    def nachrichten(self):
        """Büro-Nachrichten (nur Mehrbenutzerbetrieb)."""
        if self.verbindung is None:
            return None
        if getattr(self, "_nachrichten", None) is None:
            from core.netz import _Fern
            self._nachrichten = _Fern(self.verbindung, "nachrichten")
        return self._nachrichten

    @property
    def mehrbenutzer(self) -> bool:
        return self.verbindung is not None

    @property
    def rolle(self) -> str:
        """admin | sekretariat | anwalt (Einzelplatz: admin)."""
        return (self.verbindung.benutzer or {}).get("rolle", "admin") if self.verbindung else "admin"

    def darf(self, objekt: str, methode: str) -> bool:
        from core.benutzer import erlaubt
        return erlaubt(self.rolle, objekt, methode)

    def aenderungsverlauf(self, art: str, objekt) -> list[dict]:
        if self.verbindung is not None:
            return self.stammdaten.aenderungsverlauf(art, objekt)
        from core.protokoll import Protokoll
        return Protokoll(self.journal.con).fuer(art, objekt)

    def eigene_domains(self) -> list[str]:
        d = list(self.cfg.get("eigene_domains", []))
        if self.kanzlei.domain and self.kanzlei.domain not in d:
            d.append(self.kanzlei.domain)
        return d


@dataclass
class Field:
    key: str
    label: str
    value: str = ""
    choices: list[str] = field(default_factory=list)   # seçenek varsa açılır liste
    required: bool = True
    kind: str = "text"                                 # "text" | "email"
    hint: str = ""                                     # ör. "Vorlage" / "erkannt" / "bitte prüfen"
    # Seçenek -> kaynağı ("aus Brief", "aus Adressbuch …"); seçim değişince ipucu da değişir
    choice_hints: dict[str, str] = field(default_factory=dict)
    must_choose: bool = False                          # True: önceden seçili değer yok, kullanıcı seçer
    # Bu alan değişince diğer alanların yeni hali: fn(yeni_değer) -> list[Field]
    on_change: Callable[[str], list["Field"]] | None = None


@dataclass
class Result:
    ok: bool
    message: str
    output: str = ""
    recipient: str = ""
    reference: str = ""


class Workflow:
    id: str = ""
    name: str = ""
    description: str = ""
    file_types: tuple[str, ...] = (".docx", ".doc")

    def __init__(self, ctx: AppContext):
        self.ctx = ctx
        self.cfg = ctx.cfg

    def accepts(self, path: Path) -> bool:
        return path.suffix.lower() in self.file_types and not path.name.startswith("~$")

    def prepare(self, path: Path) -> list[Field]:
        """Belgeyi okuyup kontrol penceresinde gösterilecek alanları döndürür."""
        raise NotImplementedError

    def execute(self, path: Path, values: dict[str, str]) -> Result:
        """Onaylanan değerlerle işi yapar."""
        raise NotImplementedError

"""Her iş akışı bu sınıftan türetilir. Yeni bir iş = workflows/ altında yeni bir dosya."""
from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path

from core.kanzlei import Kanzlei, KanzleiStore


class AppContext:
    """İş akışlarının ortak eriştiği her şey: ayarlar, büro bilgileri, veritabanı."""

    def __init__(self, cfg: dict, kanzlei_store: KanzleiStore, journal):
        self.cfg = cfg
        self.kanzlei_store = kanzlei_store
        self.journal = journal

    @property
    def kanzlei(self) -> Kanzlei:
        return self.kanzlei_store.laden()          # her seferinde güncel hali

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

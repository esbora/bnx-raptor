"""Güncelleme kontrolü: GitHub'daki en son Release ile kurulu sürümü karşılaştırır.

Sadece okuma yapar (GET), hiçbir büro/müvekkil verisi gönderilmez.
Güncellemeyi kullanıcı kendisi indirir ve kurar (otomatik kurulum YOK).
"""
from __future__ import annotations

import json
import re
import ssl
import urllib.request
from dataclasses import dataclass

API = "https://api.github.com/repos/{repo}/releases/latest"


@dataclass
class ReleaseInfo:
    version: str
    url: str           # Release sayfası (tarayıcıda açılır)
    notizen: str
    download: str      # ilk .zip eki, yoksa boş


def version_tuple(v: str) -> tuple[int, ...]:
    """'v1.2.10' -> (1, 2, 10). Ön ekler/son ekler ('-beta') yok sayılır."""
    zahlen = re.findall(r"\d+", v.split("-", 1)[0])
    return tuple(int(z) for z in zahlen[:3]) + (0,) * (3 - min(3, len(zahlen)))


def ist_neuer(remote: str, lokal: str) -> bool:
    return version_tuple(remote) > version_tuple(lokal)


def release_parsen(daten: dict) -> ReleaseInfo:
    zip_url = next((a.get("browser_download_url", "") for a in daten.get("assets", [])
                    if a.get("name", "").lower().endswith(".zip")), "")
    return ReleaseInfo(
        version=daten.get("tag_name", "").lstrip("vV"),
        url=daten.get("html_url", ""),
        notizen=daten.get("body", "") or "",
        download=zip_url,
    )


def neueste_release(repo: str, timeout: float = 6.0) -> ReleaseInfo | None:
    """Ağ hatası, repo yok vb. durumlarda None – program asla bu yüzden bozulmaz."""
    if not repo or "/" not in repo:
        return None
    req = urllib.request.Request(API.format(repo=repo), headers={
        "Accept": "application/vnd.github+json", "User-Agent": "BnX-Raptor"})
    try:
        with urllib.request.urlopen(req, timeout=timeout, context=ssl.create_default_context()) as r:
            return release_parsen(json.loads(r.read().decode("utf-8")))
    except Exception:  # noqa: BLE001
        return None

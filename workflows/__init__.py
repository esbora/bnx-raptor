"""Kayıtlı iş akışları. Yeni bir modül eklendiğinde buraya bir satır eklenir."""
from .versicherung_brief import VersicherungBrief

ALL_WORKFLOWS = [
    VersicherungBrief,
    # GerichtSchriftsatz,      # örnek: ileride eklenecek
    # MandantenAnschreiben,
]

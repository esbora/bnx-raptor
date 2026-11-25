"""Selbst erzeugtes TLS-Zertifikat für den BnX-Raptor-Server (0.4.3) – nur Python-Standardbibliothek.

Erzeugt beim ersten Bereitstellen der Daten ein RSA-2048-Schlüsselpaar (Zufall aus `secrets`, Miller-Rabin-
Primzahltest) und ein selbst signiertes X.509-v3-Zertifikat (SHA-256, SAN mit Rechnername/IP-Adressen).
Verschlüsselung und Zertifikatsprüfung der Verbindung übernimmt OpenSSL (Python-Modul `ssl`); vertraut wird
ausschließlich genau diesem Zertifikat (Fingerabdruck), nachdem es mit dem Verbindungscode bestätigt wurde.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import ipaddress
import secrets
import socket
from datetime import datetime, timedelta, timezone
from pathlib import Path

# ----------------------------------------------------------------------------- RSA
_KLEINE_PRIMZAHLEN = [p for p in range(3, 2000) if all(p % q for q in range(2, int(p ** 0.5) + 1))]


def _ist_primzahl(n: int, runden: int = 40) -> bool:
    if n < 2:
        return False
    for p in _KLEINE_PRIMZAHLEN:
        if n % p == 0:
            return n == p
    d, r = n - 1, 0
    while d % 2 == 0:
        d //= 2
        r += 1
    for _ in range(runden):
        a = secrets.randbelow(n - 3) + 2
        x = pow(a, d, n)
        if x in (1, n - 1):
            continue
        for _ in range(r - 1):
            x = pow(x, 2, n)
            if x == n - 1:
                break
        else:
            return False
    return True


def _primzahl(bits: int, e: int) -> int:
    while True:
        k = secrets.randbits(bits) | (1 << (bits - 1)) | (1 << (bits - 2)) | 1
        if k % e != 1 and _ist_primzahl(k):
            return k


def rsa_schluessel(bits: int = 2048) -> dict:
    e = 65537
    while True:
        p, q = _primzahl(bits // 2, e), _primzahl(bits // 2, e)
        if p == q:
            continue
        n = p * q
        if n.bit_length() != bits:
            continue
        lam = (p - 1) * (q - 1) // _ggt(p - 1, q - 1)
        d = pow(e, -1, lam)
        return {"n": n, "e": e, "d": d, "p": p, "q": q, "dp": d % (p - 1), "dq": d % (q - 1),
                "qi": pow(q, -1, p)}


def _ggt(a: int, b: int) -> int:
    while b:
        a, b = b, a % b
    return a


def _signieren(k: dict, daten: bytes) -> bytes:
    """RSASSA-PKCS1-v1_5 mit SHA-256."""
    digest_info = bytes.fromhex("3031300d060960864801650304020105000420") + hashlib.sha256(daten).digest()
    laenge = (k["n"].bit_length() + 7) // 8
    em = b"\x00\x01" + b"\xff" * (laenge - len(digest_info) - 3) + b"\x00" + digest_info
    m = int.from_bytes(em, "big")
    m1, m2 = pow(m, k["dp"], k["p"]), pow(m, k["dq"], k["q"])        # CRT
    s = m2 + k["q"] * ((k["qi"] * (m1 - m2)) % k["p"])
    assert pow(s, k["e"], k["n"]) == m                              # Selbstprüfung
    return s.to_bytes(laenge, "big")


# ----------------------------------------------------------------------------- DER
def _len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _tlv(tag: int, inhalt: bytes) -> bytes:
    return bytes([tag]) + _len(len(inhalt)) + inhalt


def _int(n: int) -> bytes:
    b = n.to_bytes(max(1, (n.bit_length() + 8) // 8), "big")      # führendes 0-Byte bei gesetztem Bit
    return _tlv(0x02, b)


def _seq(*teile: bytes) -> bytes:
    return _tlv(0x30, b"".join(teile))


def _set(*teile: bytes) -> bytes:
    return _tlv(0x31, b"".join(teile))


def _oid(text: str) -> bytes:
    z = [int(x) for x in text.split(".")]
    out = bytes([40 * z[0] + z[1]])
    for v in z[2:]:
        teil = [v & 0x7F]
        v >>= 7
        while v:
            teil.append(0x80 | (v & 0x7F))
            v >>= 7
        out += bytes(reversed(teil))
    return _tlv(0x06, out)


def _zeit(t: datetime) -> bytes:
    if t.year < 2050:
        return _tlv(0x17, t.strftime("%y%m%d%H%M%SZ").encode())
    return _tlv(0x18, t.strftime("%Y%m%d%H%M%SZ").encode())


def _name(cn: str) -> bytes:
    return _seq(_set(_seq(_oid("2.5.4.10"), _tlv(0x0C, b"BnX-Raptor"))),
                _set(_seq(_oid("2.5.4.3"), _tlv(0x0C, cn.encode("utf-8")))))


def _ext(oid: str, wert: bytes, kritisch: bool = False) -> bytes:
    return _seq(_oid(oid), *([_tlv(0x01, b"\xff")] if kritisch else []), _tlv(0x04, wert))


def zertifikat_erzeugen(rechner: str | None = None, ips: list[str] | None = None, jahre: int = 10) \
        -> tuple[bytes, bytes]:
    """→ (Zertifikat PEM, privater Schlüssel PEM)."""
    rechner = rechner or socket.gethostname()
    ips = ips or []
    k = rsa_schluessel()
    rsa_alg = _seq(_oid("1.2.840.113549.1.1.1"), b"\x05\x00")
    pub = _seq(_int(k["n"]), _int(k["e"]))
    spki = _seq(rsa_alg, _tlv(0x03, b"\x00" + pub))
    ski = hashlib.sha1(pub).digest()
    sig_alg = _seq(_oid("1.2.840.113549.1.1.11"), b"\x05\x00")
    jetzt = datetime.now(timezone.utc).replace(microsecond=0)
    namen = [_tlv(0x82, n.encode()) for n in dict.fromkeys([rechner, rechner.lower(), "localhost"])]
    for ip in dict.fromkeys(["127.0.0.1", *ips]):
        try:
            namen.append(_tlv(0x87, ipaddress.ip_address(ip).packed))
        except ValueError:
            pass
    erweiterungen = _tlv(0xA3, _seq(
        _ext("2.5.29.19", _seq(_tlv(0x01, b"\xff")), kritisch=True),                 # CA: ja (eigener Anker)
        _ext("2.5.29.15", _tlv(0x03, b"\x02\xa4"), kritisch=True),   # digitalSignature, keyEncipherment, keyCertSign
        _ext("2.5.29.37", _seq(_oid("1.3.6.1.5.5.7.3.1"))),                           # serverAuth
        _ext("2.5.29.17", _seq(*namen)),                                              # SAN
        _ext("2.5.29.14", _tlv(0x04, ski)),                                           # SKI
        _ext("2.5.29.35", _seq(_tlv(0x80, ski))),                                     # AKI
    ))
    name = _name(f"BnX-Raptor Server {rechner}")
    tbs = _seq(
        _tlv(0xA0, _int(2)),
        _int(int.from_bytes(secrets.token_bytes(16), "big") >> 1),
        sig_alg, name,
        _seq(_zeit(jetzt - timedelta(days=1)), _zeit(jetzt + timedelta(days=365 * jahre))),
        name, spki, erweiterungen)
    der = _seq(tbs, sig_alg, _tlv(0x03, b"\x00" + _signieren(k, tbs)))
    schluessel = _seq(*(_int(v) for v in (0, k["n"], k["e"], k["d"], k["p"], k["q"], k["dp"], k["dq"], k["qi"])))
    return _pem("CERTIFICATE", der), _pem("RSA PRIVATE KEY", schluessel)


def _pem(art: str, der: bytes) -> bytes:
    b = base64.encodebytes(der).replace(b"\n", b"")
    zeilen = [b[i:i + 64] for i in range(0, len(b), 64)]
    return b"-----BEGIN " + art.encode() + b"-----\n" + b"\n".join(zeilen) + b"\n-----END " + art.encode() + b"-----\n"


def der_aus_pem(pem: bytes | str) -> bytes:
    if isinstance(pem, str):
        pem = pem.encode()
    inhalt = pem.split(b"-----")[2]
    return base64.b64decode(b"".join(inhalt.split()))


def fingerabdruck(cert_der_oder_pem) -> str:
    der = cert_der_oder_pem if isinstance(cert_der_oder_pem, bytes) and not cert_der_oder_pem.startswith(b"-----") \
        else der_aus_pem(cert_der_oder_pem)
    h = hashlib.sha256(der).hexdigest().upper()
    return ":".join(h[i:i + 2] for i in range(0, len(h), 2))


def kurz(fp: str) -> str:
    """Lesbare Kurzform (erste 8 Bytes) für die Anzeige."""
    return " ".join(fp.replace(":", "")[i:i + 4] for i in range(0, 16, 4))


def bestaetigung_passt(fp: str, eingabe: str) -> bool:
    """El ile yazılan kontrol kodu sunucunun parmak iziyle eşleşiyor mu?

    Boşluk, iki nokta, tire ve küçük harf önemsenmez. Kabul edilen: ana bilgisayarda gösterilen kısa kontrol
    kodu (`kurz`, ilk 16 onaltılık hane = 64 bit) ya da tam SHA-256 parmak izi (64 hane). Bağlantının kendisi
    her zaman onaylanan tam sertifikayla doğrulanır; burada yalnızca kullanıcının karşılaştırması kontrol edilir.
    """
    hedef = "".join(c for c in (fp or "").upper() if c in "0123456789ABCDEF")
    yazilan = "".join(c for c in (eingabe or "").upper() if c in "0123456789ABCDEF")
    if len(hedef) != 64 or len(yazilan) not in (16, 64):
        return False
    return hmac.compare_digest(hedef[:len(yazilan)], yazilan)


def sicherstellen(ordner: Path, ips: list[str] | None = None) -> tuple[Path, Path, bool]:
    """Zertifikat + Schlüssel im Ordner `tls` bereitstellen (einmalig erzeugen). → (cert, key, neu?)"""
    o = Path(ordner) / "tls"
    o.mkdir(parents=True, exist_ok=True)
    cert, key = o / "server.pem", o / "server.key"
    if cert.exists() and key.exists():
        return cert, key, False
    c, s = zertifikat_erzeugen(ips=ips)
    key.write_bytes(s)
    cert.write_bytes(c)
    return cert, key, True


SCANNER_MUSTER = [("Avast", r"avast"), ("AVG", r"\bavg\b"), ("Kaspersky", r"kaspersky"), ("ESET", r"\beset\b"),
                  ("Bitdefender", r"bitdefender"), ("Norton", r"norton|symantec"), ("McAfee", r"mcafee"),
                  ("Sophos", r"sophos"), ("G DATA", r"g ?data"), ("Avira", r"avira"), ("Trend Micro", r"trend ?micro"),
                  ("Fortinet", r"fortinet|fortigate"), ("einem Virenscanner", r"web/mail shield|ssl filter|"
                                                                          r"ssl scanning|https scanning")]


def aussteller(cert_pem: bytes | str) -> str:
    """Aussteller (Issuer) als Text – nur zur Anzeige/Erkennung."""
    import re as _re
    import ssl
    import tempfile
    with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as f:
        f.write(cert_pem if isinstance(cert_pem, bytes) else cert_pem.encode())
        name = f.name
    try:
        d = ssl._ssl._test_decode_cert(name)                       # noqa: SLF001 – nur Anzeige
    except Exception:  # noqa: BLE001
        d = {}
    finally:
        Path(name).unlink(missing_ok=True)
    _ = _re
    return ", ".join("=".join(x) for r in d.get("issuer", ()) for x in r)


def scanner(cert_pem: bytes | str) -> str:
    """Name des Virenscanners/Filters, der die verschlüsselte Verbindung aufbricht und ein eigenes Zertifikat
    vorlegt – oder ''. (Ein solches Zertifikat wird NIE akzeptiert.)"""
    import re as _re
    text = aussteller(cert_pem).lower()
    for name, muster in SCANNER_MUSTER:
        if _re.search(muster, text):
            return name
    return ""


def scanner_text(name: str) -> str:
    return (f"{name} prüft die verschlüsselte Verbindung zum Hauptrechner und legt dabei ein eigenes Zertifikat vor. "
            "BnX-Raptor akzeptiert das aus Sicherheitsgründen nicht – es wurden keine Daten übertragen. Bitte im "
            "Virenscanner eine Ausnahme für BnX-Raptor einrichten (z. B. „HTTPS-Prüfung/Web-Schutz: Ausnahme für "
            "BnX-Raptor.exe“ oder für den Hauptrechner, Port 47310), dann erneut verbinden.")


def details(cert_pem: bytes | str) -> dict:
    """Technische Angaben für „Details“ (über ssl._ssl._test_decode_cert, ohne Netzwerk)."""
    import ssl
    import tempfile
    with tempfile.NamedTemporaryFile("wb", suffix=".pem", delete=False) as f:
        f.write(cert_pem if isinstance(cert_pem, bytes) else cert_pem.encode())
        name = f.name
    try:
        d = ssl._ssl._test_decode_cert(name)                       # noqa: SLF001 – nur Anzeige
    except Exception:  # noqa: BLE001
        d = {}
    finally:
        Path(name).unlink(missing_ok=True)
    return {"inhaber": ", ".join("=".join(x) for r in d.get("subject", ()) for x in r),
            "gueltig_ab": d.get("notBefore", ""), "gueltig_bis": d.get("notAfter", ""),
            "namen": ", ".join(v for _, v in d.get("subjectAltName", ())),
            "fingerabdruck": fingerabdruck(cert_pem), "seriennummer": d.get("serialNumber", "")}

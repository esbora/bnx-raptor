"""45-s-Trailer (Deutsch): echte Programmbilder (fiktive Daten) + Titelkarten im BnX-Design + lokale Stimme
„Microsoft Stefan“ + eingebrannte Untertitel. Ausgabe: docs/marketing/BnX-Raptor_Trailer_DE_45s.mp4 (Aufruf aus dem Projektordner) (1920×1080, 30 fps)."""
import json, re, subprocess, sys, wave
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from PySide6.QtCore import QRectF, Qt  # noqa: E402
from PySide6.QtGui import QColor, QFont, QGuiApplication, QImage, QPainter, QPainterPath  # noqa: E402

QUELLE = Path(__file__).resolve().parent
import tempfile  # noqa: E402
HIER = Path(tempfile.gettempdir()) / "bnx_trailer"
HIER.mkdir(exist_ok=True)
FOTO = QUELLE.parent / "handbuch" / "bilder"
ZIEL = QUELLE / "BnX-Raptor_Trailer_DE_45s.mp4"
B, H, FPS, LAENGE = 1920, 1080, 30, 45.0
app = QGuiApplication(sys.argv)
QGuiApplication.styleHints().setColorScheme(Qt.ColorScheme.Light)
from ui import theme  # noqa: E402
theme.F.update(theme.HELL)
F = theme.F
BILD = HIER / "bilder"; BILD.mkdir(exist_ok=True)


def run(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True, encoding="utf-8", errors="replace")
    if r.returncode:
        raise SystemExit(r.stderr[-1500:])
    return r.stdout


# ------------------------------------------------------------------ Ton: Rate wählen, Sätze planen
SAETZE = [z for z in (QUELLE / "Sprechertext_SSML.txt").read_text(encoding="utf-8").splitlines() if z.strip()]
ZIELSTART = {0: 0.3, 2: 11.0, 4: 18.9, 6: 27.4, 8: 38.9}       # Szenenanker (s) aus dem Ablaufplan


def dauer(p):
    with wave.open(str(p)) as w:
        return w.getnframes() / w.getframerate()


def ton(rate):
    roh, kurz = HIER / f"ton_{rate}", HIER / f"tonk_{rate}"
    if not kurz.exists():
        run(["powershell.exe", "-NoProfile", "-ExecutionPolicy", "Bypass", "-File", str(QUELLE / "tts_stefan.ps1"),
             str(QUELLE / "Sprechertext_SSML.txt"), str(roh), str(rate)])
        kurz.mkdir()
        for f in sorted(roh.glob("*.wav")):
            run(["ffmpeg", "-v", "error", "-y", "-i", str(f), "-af",
                 "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.05,areverse,"
                 "silenceremove=start_periods=1:start_threshold=-45dB:start_silence=0.08,areverse",
                 "-ar", "48000", "-ac", "1", str(kurz / f.name)])
    return sorted(kurz.glob("*.wav"))


def planen(dateien):
    t, plan = 0.0, []
    for i, f in enumerate(dateien):
        start = max(t + (0.22 if i else 0), ZIELSTART.get(i, 0))
        plan.append((start, start + dauer(f), f))
        t = start + dauer(f)
    return plan


for rate in (1.0, 1.03, 1.05, 1.08, 1.1, 1.12, 1.15):
    plan = planen(ton(rate))
    if plan[-1][1] <= LAENGE - 0.35:
        break
print("Sprechrate", rate, "Ende Sprache", round(plan[-1][1], 2))


def klar(s):
    s = re.sub(r"<sub alias='[^']*'>([^<]*)</sub>", r"\1", s)
    return re.sub(r"<[^>]+>", "", s).strip()


# ------------------------------------------------------------------ Bilder
def leinwand():
    img = QImage(B, H, QImage.Format_RGB32)
    img.fill(QColor(F["grund"]))
    return img


def schrift(px, gewicht=QFont.Normal):
    f = QFont("Segoe UI")
    f.setPixelSize(px)
    f.setWeight(gewicht)
    return f


def marke(g, x, y, s):
    g.setPen(Qt.NoPen)
    g.setBrush(QColor(F["primaer"]))
    g.drawRoundedRect(QRectF(x, y, s, s), s * .28, s * .28)
    g.setBrush(QColor("#FFFFFF"))
    g.drawRoundedRect(QRectF(x + s * .27, y + s * .2, s * .46, s * .6), s * .06, s * .06)
    g.setBrush(QColor(F["pfirsich_stark"]))
    g.drawRoundedRect(QRectF(x + s * .52, y + s * .52, s * .34, s * .34), s * .1, s * .1)


def chip(g, x, y, text, px=34):
    g.setFont(schrift(px, QFont.DemiBold))
    w = g.fontMetrics().horizontalAdvance(text) + 2 * px * .8
    g.setPen(Qt.NoPen)
    g.setBrush(QColor(F["pfirsich"]))
    g.drawRoundedRect(QRectF(x, y, w, px * 1.9), px * .7, px * .7)
    g.setPen(QColor(F["pfirsich_text"]))
    g.drawText(QRectF(x, y, w, px * 1.9), Qt.AlignCenter, text)


def szene(name, foto, titel, ausschnitt=None):
    """Programmbild auf warmem Grund, abgerundet mit Schatten, Titel-Chip oben links."""
    img = leinwand()
    g = QPainter(img)
    g.setRenderHint(QPainter.Antialiasing)
    g.setRenderHint(QPainter.SmoothPixmapTransform)
    q = QImage(str(foto))
    if ausschnitt:
        q = q.copy(*ausschnitt)
    maxb, maxh = B - 220, H - 250
    f = min(maxb / q.width(), maxh / q.height())
    w, h = q.width() * f, q.height() * f
    x, y = (B - w) / 2, 170 + (maxh - h) / 2
    for i in range(14, 0, -2):
        g.setPen(Qt.NoPen)
        g.setBrush(QColor(58, 42, 26, 6))
        g.drawRoundedRect(QRectF(x - i, y - i + 8, w + 2 * i, h + 2 * i), 22, 22)
    pfad = QPainterPath()
    pfad.addRoundedRect(QRectF(x, y, w, h), 16, 16)
    g.setClipPath(pfad)
    g.drawImage(QRectF(x, y, w, h), q)
    g.setClipping(False)
    g.setPen(QColor(F["rand"]))
    g.setBrush(Qt.NoBrush)
    g.drawRoundedRect(QRectF(x, y, w, h), 16, 16)
    marke(g, 110, 58, 64)
    g.setFont(schrift(40, QFont.Bold))
    g.setPen(QColor(F["titel"]))
    g.drawText(QRectF(190, 58, 700, 64), Qt.AlignVCenter, "BnX-Raptor")
    chip(g, B - 110 - (len(titel) * 19 + 60), 66, titel, 30)
    g.end()
    p = BILD / f"{name}.png"
    img.save(str(p))
    return p


def karte(name, oben, gross, unten, grafik=False):
    img = leinwand()
    g = QPainter(img)
    g.setRenderHint(QPainter.Antialiasing)
    g.setPen(Qt.NoPen)
    g.setBrush(QColor(F["karte"]))
    g.drawRoundedRect(QRectF(140, 150, B - 280, H - 300), 40, 40)
    marke(g, 240, 300, 110)
    chip(g, 240, 450, oben, 30)
    g.setPen(QColor(F["titel"]))
    g.setFont(schrift(96, QFont.Bold))
    g.drawText(QRectF(240, 530, B - 480, 140), Qt.AlignVCenter, gross)
    g.setPen(QColor(F["gedimmt"]))
    g.setFont(schrift(46))
    g.drawText(QRectF(240, 680, B - 480, 140), Qt.AlignTop | Qt.TextWordWrap, unten)
    g.setBrush(QColor(F["primaer"]))
    g.setPen(Qt.NoPen)
    g.drawRoundedRect(QRectF(240, 255, 120, 10), 5, 5)
    g.end()
    p = BILD / f"{name}.png"
    img.save(str(p))
    return p


s = [p[0] for p in plan]
SZENEN = [  # (Bild, Start, Ende)
    (szene("01_start", FOTO / "00_start.png", "Ein Schriftsatz, viele Anlagen"), 0.0, 3.6),
    (karte("02_name", "Für Anwaltskanzleien", "BnX-Raptor",
           "Entwickelt für Rechtsanwältinnen, Rechtsanwälte und ihre Kanzleiteams."), 3.6, s[2]),
    (szene("03_hineinziehen", FOTO / "10_anlagen_hineingezogen.png", "Word, Scans und PDFs hineinziehen"), s[2], s[3] - 0.1),
    (szene("04_ordnen", FOTO / "11_anlagen_geordnet.png", "Ordnen und nummerieren"), s[3] - 0.1, s[4]),
    (szene("05_ocr", FOTO / "07_editor_scan_ocr.png", "Lokale Texterkennung (OCR)"), s[4], s[4] + 2.7),
    (szene("06_text", FOTO / "06_text_aendern.png", "PDF-Text bearbeiten"), s[4] + 2.7, s[4] + 4.7),
    (szene("07_vorgemerkt", FOTO / "09_schwaerzen_vorgemerkt.png", "Vertrauliches dauerhaft schwärzen"), s[4] + 4.7, s[4] + 6.6),
    (szene("08_geschwaerzt", FOTO / "09c_geschwaerzt.png", "Geschwärzt und geprüft"), s[4] + 6.6, s[6]),
    (szene("09_verzeichnis", FOTO / "13b_anlagenverzeichnis_word.png", "Anlagenverzeichnis in Word"), s[6], s[6] + 3.3),
    (szene("10_pakete", FOTO / "13_paket_erstellt.png", "Paket erstellen: Schriftsatz, Anlage K1 …"), s[6] + 3.3, s[7]),
    (szene("11_outlook", FOTO / "15_outlook_ausschnitt.png", "Anhänge im klassischen Outlook-Entwurf"), s[7], s[8]),
    (karte("12_ende", "Jetzt im Pilotbetrieb", "BnX-Raptor", "Entwickelt für Anwaltskanzleien. "
           "Jetzt im Pilotbetrieb kennenlernen."), s[8], LAENGE),
]

# ------------------------------------------------------------------ Video: Szenen mit sanftem Zoom + Überblendung
teile = []
for i, (bild, a, e) in enumerate(SZENEN):
    d = e - a
    n = int(round(d * FPS))
    zoom = "1+0.035*on/{}".format(max(n, 1)) if "karte" not in bild.name else "1"
    out = HIER / f"teil_{i:02d}.mp4"
    vf = (f"scale={B * 2}:{H * 2},zoompan=z='{zoom}':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':d={n}:s={B}x{H}:fps={FPS},"
          f"fade=t=in:st=0:d=0.25,fade=t=out:st={max(d - 0.25, 0):.2f}:d=0.25,format=yuv420p")
    run(["ffmpeg", "-v", "error", "-y", "-loop", "1", "-i", str(bild), "-vf", vf, "-frames:v", str(n), "-r", str(FPS),
         "-c:v", "libx264", "-preset", "medium", "-crf", "18", str(out)])
    teile.append(out)
(HIER / "teile.txt").write_text("".join(f"file '{p.as_posix()}'\n" for p in teile), encoding="utf-8")
run(["ffmpeg", "-v", "error", "-y", "-f", "concat", "-safe", "0", "-i", str(HIER / "teile.txt"), "-c", "copy", str(HIER / "bild.mp4")])

# Ton: Sätze an ihre Startzeiten legen
eing, filt = [], []
for i, (a, e, f) in enumerate(plan):
    eing += ["-i", str(f)]
    filt.append(f"[{i}:a]adelay={int(a * 1000)}|{int(a * 1000)}[a{i}]")
filt.append("".join(f"[a{i}]" for i in range(len(plan))) + f"amix=inputs={len(plan)}:normalize=0,apad,atrim=0:{LAENGE},"
            "loudnorm=I=-16:TP=-1.5:LRA=11[ton]")
run(["ffmpeg", "-v", "error", "-y", *eing, "-filter_complex", ";".join(filt), "-map", "[ton]", "-ar", "48000",
     str(HIER / "ton.wav")])


# Untertitel (SRT, ein Satz je Eintrag)
def ts(x):
    return f"{int(x // 3600):02d}:{int(x % 3600 // 60):02d}:{int(x % 60):02d},{int(round(x % 1 * 1000)):03d}"


srt = "".join(f"{i + 1}\n{ts(a)} --> {ts(min(e + 0.25, LAENGE))}\n{klar(SAETZE[i])}\n\n" for i, (a, e, _) in enumerate(plan))
(HIER / "untertitel_DE.srt").write_text(srt, encoding="utf-8")
ZIEL.parent.mkdir(parents=True, exist_ok=True)
stil = ("FontName=Segoe UI,FontSize=11,PrimaryColour=&H00FFFFFF,BorderStyle=4,OutlineColour=&H40261A16,"
        "BackColour=&H40261A16,Outline=0,Shadow=0,MarginV=10,MarginL=40,MarginR=40,Bold=0")
sub = (HIER / "untertitel_DE.srt").as_posix().replace(":", "\\:")
run(["ffmpeg", "-v", "error", "-y", "-i", str(HIER / "bild.mp4"), "-i", str(HIER / "ton.wav"),
     "-vf", f"subtitles='{sub}':force_style='{stil}'", "-c:v", "libx264", "-preset", "slow", "-crf", "18",
     "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-t", str(LAENGE), "-movflags", "+faststart", str(ZIEL)])
(HIER / "plan.json").write_text(json.dumps({"rate": rate, "saetze": [(round(a, 2), round(e, 2), klar(SAETZE[i]))
                                                                     for i, (a, e, _) in enumerate(plan)],
                                           "szenen": [(b.name, round(a, 2), round(e, 2)) for b, a, e in SZENEN]},
                                          ensure_ascii=False, indent=1), encoding="utf-8")
print("fertig", ZIEL)

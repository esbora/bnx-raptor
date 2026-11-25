"""Erzeugt die kurze Einrichtungsanleitung „Mehrere Arbeitsplätze“: docs/Mehrbenutzer_Einrichtung_DE.pdf

Bilder: docs/handbuch/bilder/netz_*.png – Bildschirmfotos des echten Programms mit fiktiven Daten.
Aufruf: python docs/handbuch/einrichtung.py
"""
from __future__ import annotations

import io
import sys
from pathlib import Path

import pymupdf

HIER = Path(__file__).resolve().parent
KOK = HIER.parent.parent
BILDER = HIER / "bilder"
ZIEL = KOK / "docs" / "Mehrbenutzer_Einrichtung_DE.pdf"
sys.path.insert(0, str(KOK))
from version import __version__ as VERSION  # noqa: E402

CSS = """
body { font-family: sans-serif; font-size: 10.5pt; line-height: 1.4; color: #283040; }
h1 { font-size: 19pt; color: #16264A; margin: 0 0 4pt 0; }
h2 { font-size: 13.5pt; color: #16264A; margin: 14pt 0 4pt 0; }
p { margin: 0 0 6pt 0; }
ol, ul { margin: 0 0 6pt 0; }
li { margin: 0 0 3pt 0; }
.k { font-size: 8.5pt; color: #6B7280; }
.ui { font-weight: bold; color: #1D4ED8; }
.wichtig { background-color: #FDECEA; border: 1pt solid #B42318; padding: 6pt; margin: 4pt 0 8pt 0; }
.hinweis { background-color: #FFF3D6; border: 1pt solid #C98A1B; padding: 6pt; margin: 4pt 0 8pt 0; }
img { border: 0.6pt solid #D1D5DB; }
"""


def ui(t: str) -> str:
    return f"<span class='ui'>{t}</span>"


def bild(datei: str, text: str, breite: int = 330) -> str:
    if not (BILDER / datei).exists():
        return ""
    return f"<p><img src='{datei}' width='{breite}'/><br/><span class='k'>{text}</span></p>"


INHALT = f"""
<h1>BnX-Raptor – mehrere Arbeitsplätze</h1>
<p class='k'>Kurzanleitung, Version {VERSION} · Bildschirmfotos mit fiktiven Daten</p>

<div class='wichtig'><b>Wichtig:</b> Der <b>Hauptrechner</b> stellt die gemeinsamen Daten bereit. Er muss eingeschaltet
sein und BnX-Raptor muss dort geöffnet sein, solange an den anderen PCs gearbeitet wird.</div>

<h2>A) Hauptrechner (einmalig)</h2>
<ol><li>BnX-Raptor öffnen → {ui('Einstellungen')} → Netzwerk → {ui('Daten auf diesem PC bereitstellen')} →
{ui('Bereitstellen und neu starten')}. Die vorhandenen Daten bleiben erhalten.</li>
<li>Den ersten Administrator anlegen (Benutzername, Passwort mit mindestens 8 Zeichen).</li>
<li><b>Windows-Firewall:</b> Fragt Windows, ob BnX-Raptor im Netzwerk kommunizieren darf: „Private Netzwerke“
anhaken → {ui('Zugriff zulassen')}. Wurde die Frage weggeklickt: Start → „Windows-Sicherheit“ → „Firewall- &amp;
Netzwerkschutz“ → „Zugriff von App durch Firewall zulassen“ → „Einstellungen ändern“ → bei „BnX-Raptor“ den Haken
unter „Privat“ setzen.</li>
<li><b>Kontrollcode:</b> {ui('Einstellungen')} → Netzwerk zeigt einen <b>Kontrollcode</b> (16 Zeichen, z. B. <span class='k'>1A2B 3C4D 5E6F 7A8B</span>). Diesen Code braucht jeder neue Arbeitsplatz einmalig.</li>
<li>{ui('Einstellungen')} → {ui('Benutzer verwalten…')} → für jede Person {ui('Neuer Benutzer…')} (Rolle Sekretariat
oder Rechtsanwalt).</li></ol>
{bild('netz_server.png', 'Hauptrechner: Verbindungsadresse mit „Kopieren“ – nur nötig, wenn die automatische Suche '
      'nichts findet.', 400)}

<h2>B) Jeder weitere PC – drei Schritte</h2>
<ol><li><b>Programm öffnen.</b> Beim ersten Start fragt BnX-Raptor, wie der PC arbeiten soll.</li>
<li><b>Mit der Kanzlei verbinden:</b> {ui('Mit bestehender Kanzlei verbinden')} → die Kanzlei wird im Büronetz
automatisch gefunden → {ui('Verbinden')} → den <b>Kontrollcode vom Hauptrechner</b> abtippen (nicht aus einer E-Mail oder Nachricht übernehmen; Leerzeichen und Groß-/Kleinschreibung sind egal).</li>
<li><b>Anmelden</b> mit eigenem Benutzernamen und Passwort.</li></ol>
{bild('netz_willkommen.png', 'Schritt 1: erster Start auf dem neuen PC.', 300)}
{bild('netz_gefunden.png', 'Schritt 2: Kanzlei gefunden – „Verbinden“.', 300)}
{bild('netz_anmelden.png', 'Schritt 3: anmelden.', 260)}
<p>Danach merkt sich der PC die Kanzlei und verbindet sich bei jedem Start von selbst – nur noch anmelden.
Ändert sich die Adresse des Hauptrechners, findet BnX-Raptor ihn automatisch wieder.</p>
<div class='hinweis'>Wird nichts gefunden: {ui('Verbindungsadresse eingeben…')} und die Adresse vom Hauptrechner
(Einstellungen → Netzwerk → {ui('Kopieren')}) eintragen.</div>

<h2>Wenn etwas nicht klappt</h2>
<ul><li><b>„Server nicht erreichbar“</b>: Hauptrechner einschalten, BnX-Raptor dort öffnen, dann
{ui('Erneut versuchen')}. Hilft das nicht: Windows-Firewall am Hauptrechner (siehe A3).</li>
<li><b>„Keine Verbindung zum Server“</b> links unten während der Arbeit: Eingaben bleiben im Formular und sind
<b>nicht gespeichert</b>. Sobald der Hauptrechner wieder da ist, wird automatisch gespeichert. Hat jemand dasselbe
Feld inzwischen geändert, zeigt BnX-Raptor beide Fassungen zum Vergleich.</li>
<li><b>„… prüft die verschlüsselte Verbindung …“</b>: Ein Virenscanner (z. B. Avast-Web-Schutz) bricht die Verbindung auf. Es wird nichts übertragen. Im Virenscanner eine Ausnahme für BnX-Raptor.exe bzw. den Hauptrechner (Port 47310) einrichten – am Hauptrechner und an jedem Arbeitsplatz.</li>
<li>Outlook-Entwürfe, Word-Umwandlung und Texterkennung laufen an dem PC, an dem gearbeitet wird.</li></ul>
<div class='hinweis'>Die Verbindung im Büronetz ist mit TLS <b>verschlüsselt</b>. Der Hauptrechner erzeugt dafür einmalig ein eigenes Zertifikat. Beim ersten Verbinden eines Arbeitsplatzes wird der <b>Kontrollcode</b> vom Hauptrechner abgetippt; ändert sich das Zertifikat später, hält BnX-Raptor die Verbindung an und überträgt nichts. Nur im eigenen Büronetz verwenden – nicht über das Internet. Server und alle Arbeitsplätze müssen dieselbe Programmversion verwenden: für ein Update zuerst alle Arbeitsplätze schließen, Daten sichern, dann Hauptrechner und Arbeitsplätze gemeinsam aktualisieren.</div>
"""


def main():
    story = pymupdf.Story(html=INHALT, user_css=CSS, archive=pymupdf.Archive(str(BILDER)))
    puffer = io.BytesIO()
    w = pymupdf.DocumentWriter(puffer)
    seite = pymupdf.paper_rect("a4")
    rand = seite + (50, 50, -50, -50)
    mehr = True
    while mehr:
        dev = w.begin_page(seite)
        mehr, _ = story.place(rand)
        story.draw(dev)
        w.end_page()
    w.close()
    doc = pymupdf.open("pdf", puffer.getvalue())
    doc.set_metadata({"title": "BnX-Raptor – mehrere Arbeitsplätze einrichten", "author": "BnX-Raptor"})
    doc.save(ZIEL, garbage=3, deflate=True)
    print(f"erstellt: {ZIEL.name} {doc.page_count} Seiten")


if __name__ == "__main__":
    main()

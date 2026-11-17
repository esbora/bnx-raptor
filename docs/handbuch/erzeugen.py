"""Erzeugt das deutsche Benutzerhandbuch: docs/Benutzerhandbuch_BnX-Raptor_0.4.0_DE.pdf

Bilder: docs/handbuch/bilder/ – Bildschirmfotos des echten Programms mit fiktiven Daten (Testakte Mustermann,
„Kanzlei Muster & Partner (fiktiv)“). Aufruf: python docs/handbuch/erzeugen.py
"""
from __future__ import annotations

import html
import io
import json
from pathlib import Path

import pymupdf

HIER = Path(__file__).resolve().parent
KOK = HIER.parent.parent
BILDER = HIER / "bilder"
ZIEL = KOK / "docs" / "Benutzerhandbuch_BnX-Raptor_0.4.0_DE.pdf"
H = json.loads((KOK / "docs" / "CRA" / "hersteller.json").read_text(encoding="utf-8"))
VERSION = "0.4.0"

CSS = """
body { font-family: sans-serif; font-size: 10pt; line-height: 1.38; color: #283040; }
h1 { font-size: 21pt; color: #16264A; margin: 0 0 4pt 0; }
h2 { font-size: 14.5pt; color: #16264A; margin: 16pt 0 5pt 0; }
h3 { font-size: 11.5pt; color: #16264A; margin: 10pt 0 3pt 0; }
p { margin: 0 0 6pt 0; }
ol, ul { margin: 0 0 6pt 0; }
li { margin: 0 0 2pt 0; }
.k { font-size: 8.5pt; color: #6B7280; }
.box { background-color: #FFF3E9; border: 1pt solid #F28C5B; padding: 7pt; margin: 4pt 0 9pt 0; }
.hinweis { background-color: #FFF3D6; border: 1pt solid #C98A1B; padding: 6pt; margin: 4pt 0 8pt 0; }
.ok { color: #157F3B; font-weight: bold; } .warn { color: #9A5B00; font-weight: bold; } .fehler { color: #B42318; font-weight: bold; }
table { border-collapse: collapse; width: 100%; margin: 3pt 0 9pt 0; }
th { background-color: #F3EDE6; text-align: left; border: 0.5pt solid #C9BEB1; padding: 3pt 4pt; font-size: 9pt; }
td { border: 0.5pt solid #D9CEC1; padding: 3pt 4pt; vertical-align: top; font-size: 9pt; }
code, .t { font-family: monospace; font-size: 9pt; }
b.ui { color: #16264A; }
.bild { margin: 4pt 0 2pt 0; text-align: center; }
.bu { font-size: 8.5pt; color: #6B7280; text-align: center; margin: 0 0 9pt 0; }
"""


def e(t: str) -> str:
    return html.escape(t)


def ui(t: str) -> str:
    """Bezeichnung aus dem Programm (Menü, Knopf, Feld) hervorheben."""
    return f"<b class='ui'>„{e(t)}“</b>"


def bild(datei: str, unterschrift: str, breite: int = 470) -> str:
    return (f"<div class='bild'><img src='{datei}' width='{breite}'/></div>"
            f"<p class='bu'>{e(unterschrift)}</p>")


def tab(kopf, zeilen, breiten=None) -> str:
    cols = "".join(f'<col width="{b}%">' for b in breiten) if breiten else ""
    k = "".join(f"<th>{e(x)}</th>" for x in kopf)
    z = "".join("<tr>" + "".join(f"<td>{x}</td>" for x in r) + "</tr>" for r in zeilen)
    return f"<table>{cols}<tr>{k}</tr>{z}</table>"


SATZ_MELDUNG = (f"Bitte melden Sie mögliche Sicherheitslücken oder Sicherheitsvorfälle per E-Mail an "
                f"{H['sicherheitskontakt']}. Verwenden Sie nach Möglichkeit den Betreff ‚{H['betreff_sicherheitsmeldung']}‘ "
                "und senden Sie keine vertraulichen Mandantendaten mit.")

INHALT = f"""
<h1>BnX-Raptor {VERSION} – Benutzerhandbuch</h1>
<p class='k'>Für Rechtsanwältinnen, Rechtsanwälte und Kanzleimitarbeitende · Testversion für den Pilotbetrieb ·
Alle Abbildungen zeigen das Programm mit fiktiven Daten.</p>

<div class='box'><h3>Schnellstart in 5 Minuten</h3><ol>
<li><b>Entpacken:</b> ZIP-Datei mit Rechtsklick → {ui('Alle extrahieren…')} vollständig entpacken und
<span class='t'>BnX-Raptor\\BnX-Raptor.exe</span> starten (nicht direkt aus der ZIP).</li>
<li><b>Kanzleidaten:</b> Beim ersten Start Name und E-Mail-Adresse der Kanzlei eintragen und speichern.</li>
<li><b>Anlagenpaket:</b> Auf der Startseite {ui('Anlagenpaket erstellen')} wählen und Schriftsatz (Word) sowie
alle Anlagen aus dem Explorer in die {ui('Anlagenliste')} ziehen.</li>
<li><b>Prüfen und erstellen:</b> Hinweise beachten (<span class='fehler'>✖</span> stoppt, <span class='warn'>⚠</span> bitte prüfen),
Reihenfolge und Bezeichnungen kontrollieren, dann {ui('Paket prüfen und erstellen…')} → {ui('Erstellen')}.</li>
<li><b>Entwurf:</b> {ui('Outlook-Entwurf erstellen…')} → Anhänge prüfen → der Entwurf öffnet sich im klassischen
Outlook. <b>Es wird nichts gesendet</b> – Sie prüfen und senden selbst.</li></ol></div>
{bild('00_start.png', 'Startseite: links die Navigation, oben der Anlagen-Assistent, darunter weitere Aufgaben.', 330)}
@@INHALT@@

<h2>1. Voraussetzungen und Installation</h2>
{tab(['Bereich', 'Voraussetzung'], [
    ['Windows', 'Windows 10 oder 11, 64 Bit, ca. 250 MB freier Speicher. Keine Administratorrechte nötig.'],
    ['Word', 'Microsoft Word muss installiert sein (für Word-Schriftsätze, Word-Anlagen und Schreiben an Versicherungen). Geprüft mit Microsoft 365.'],
    ['Outlook', 'Klassisches Outlook (Desktop) für Entwürfe. Ist es nicht vorhanden, erstellt BnX-Raptor eine .eml-Entwurfsdatei. Das neue Outlook wurde nicht geprüft.'],
    ['Texterkennung', 'Ist enthalten (Ordner <span class="t">ocr</span>); Deutsch, Türkisch, Englisch. Keine Internetverbindung nötig.']], [22, 78])}
<ol><li>Prüfsumme der ZIP-Datei vergleichen (PowerShell: <span class='t'>Get-FileHash .\\&lt;ZIP-Datei&gt;</span>) mit dem
mitgeteilten SHA-256-Wert. Bei Abweichung nicht verwenden.</li>
<li>ZIP vollständig entpacken – in einen Ordner, auf den nur berechtigte Personen Zugriff haben. Die Ordner
<span class='t'>ocr</span> und <span class='t'>lizenzen</span> nicht löschen.</li>
<li><span class='t'>BnX-Raptor.exe</span> starten. Windows SmartScreen kann warnen, weil die Datei nicht signiert ist:
nur starten, wenn die Prüfsumme stimmt.</li>
<li>Beim ersten Start öffnet sich {ui('Kanzleidaten')}: Name, Anwältinnen/Anwälte, Anschrift, Telefon, E-Mail,
Kammer und optional ein Logo. Diese Angaben erscheinen in Signatur und Dateinamen. Später änderbar über
{ui('Einstellungen')} → {ui('Kanzleidaten…')}.</li></ol>
{bild('01_kanzleidaten.png', 'Kanzleidaten beim ersten Start (fiktive Angaben).', 300)}
<p><b>Einstellungsdatei:</b> <span class='t'>config.json</span> liegt neben der EXE (Vorlage:
<span class='t'>config.example.json</span>). Daten wie Verlauf und Adressbuch liegen in
<span class='t'>%APPDATA%\\BnX-Raptor</span> bzw. im Ordner aus <span class='t'>daten_ordner</span>.</p>

<h2>2. Die Oberfläche</h2>
<p>Links die Navigation: {ui('Start')}, {ui('Anlagen')}, {ui('PDF-Editor')}, {ui('Akten')}, {ui('Einstellungen')}
(per Tastatur: <span class='t'>Strg+1</span> bis <span class='t'>Strg+5</span>). Oben bleiben die Menüs {ui('Einstellungen')},
{ui('Werkzeuge')} und {ui('Hilfe')}. Rückmeldungen erscheinen immer mit Farbe <b>und</b> Zeichen:</p>
{tab(['Zeichen', 'Bedeutung'], [
    ["<span class='ok'>✓ Erledigt</span>", 'Vorgang abgeschlossen bzw. in Ordnung.'],
    ["<span class='warn'>⚠ Bitte prüfen</span>", 'Kein Fehler, aber bitte ansehen (z. B. doppelte Datei, gedrehte Seite).'],
    ["<span class='fehler'>✖ Gestoppt</span>", 'Der Vorgang kann so nicht fortgesetzt werden (z. B. beschädigte Datei).']], [25, 75])}

<h2>3. Schreiben an eine Versicherung: PDF und Outlook-Entwurf</h2>
<ol><li>Auf der Startseite {ui('Versicherungsschreiben vorbereiten')} wählen und das Word-Schreiben auswählen –
oder die Word-Datei in die Liste ziehen.</li>
<li>Optional {ui('PDF vor dem Entwurf im PDF-Editor prüfen/bearbeiten')} ankreuzen.</li>
<li>{ui('Starten')} (<span class='t'>Alt+S</span>). Word liest das Dokument unsichtbar.</li>
<li>Im Fenster {ui('Prüfen – …')} die gefundenen Werte kontrollieren. Neben jedem Feld steht, woher der Wert stammt
(z. B. „aus Vorlage“, „erkannt – bitte prüfen“, „aus Adressbuch“).</li></ol>
{tab(['Feld', 'Inhalt'], [
    [ui('Versicherer'), 'Name der Versicherung aus dem Schreiben. Ändern Sie ihn, schlägt BnX-Raptor passende Adressen aus dem Adressbuch vor.'],
    [ui('Empfänger-E-Mail'), 'Adresse der Versicherung. Gibt es mehrere Möglichkeiten, bitte aus der Liste wählen. Steht nur die eigene Kanzlei-Adresse im Brief, bleibt das Feld leer und wird von Hand eingetragen.'],
    [ui('Nummer (Betreff)'), 'Versicherungsnummer oder Schaden-Nr. (z. B. „Versicherungsnummer: FV-4711-2026-0815“ oder „Schaden-Nr.: …“) – wird zum Betreff. Alle gefundenen Nummern stehen zur Auswahl.'],
    [ui('Kopie an Mandant (optional)'), 'E-Mail-Adresse der Mandantschaft, falls eine Kopie vorbereitet werden soll.']], [28, 72])}
{bild('03_pruefen_dialog.png', 'Prüfen-Dialog mit erkannten Werten (fiktives Schreiben).', 330)}
<ol start='5'><li>{ui('PDF + Entwurf erstellen')}: Das PDF (PDF/A-Einstellung von Word) wird neben der Word-Datei gespeichert,
Dateiname <span class='t'>Datum_Nummer_Dokument.pdf</span>. Danach öffnet sich der Entwurf im klassischen Outlook.</li>
<li>Entwurf prüfen und selbst senden – oder schließen. BnX-Raptor sendet nie.</li></ol>
<h3>Versicherer-Adressbuch</h3>
<p>{ui('Einstellungen')} → {ui('Versicherer-Adressbuch…')}: E-Mail-Adressen der Versicherer anlegen, ändern oder löschen.
Neue Adressen aus bestätigten Schreiben werden vorgeschlagen.</p>
{bild('04_adressbuch.png', 'Versicherer-Adressbuch (fiktive Einträge).', 360)}

<h2>4. PDF bearbeiten</h2>
<p>{ui('PDF-Editor')} → {ui('PDF öffnen…')} (oder Startseite → {ui('PDF bearbeiten')}). Der Editor arbeitet immer an einer
Kopie im Speicher: <b>Das Original wird nie überschrieben.</b> Gespeichert wird mit {ui('Speichern unter…')}
(<span class='t'>Strg+Umschalt+S</span>) in eine neue Datei.</p>
{bild('05_editor_digital.png', 'PDF-Editor: oben Datei und Suche, darunter die Werkzeuge mit Symbol und Beschriftung.', 470)}
{tab(['Werkzeug', 'Verwendung'], [
    [ui('Seiten'), 'Menü: Links/Rechts drehen, Löschen, Duplizieren, PDF/Bild einfügen…, Auswahl als PDF…, Aufteilen…. Seiten links markieren; Reihenfolge per Ziehen ändern.'],
    [ui('Text bearbeiten'), 'Absatz in einem digitalen PDF anklicken, Text ändern (Schrift, Größe, Farbe, Ausrichtung), Vorschau prüfen. Der alte Text wird entfernt, nicht überdeckt.'],
    [ui('Text einfügen'), 'Stelle anklicken und neuen Text eingeben.'],
    [ui('Wort korrigieren (Scan)'), 'Nach der Texterkennung ein falsch erkanntes Wort anklicken und korrigieren – sichtbare Seite und Suchtext werden gemeinsam geändert.'],
    [ui('OCR'), 'Texterkennung starten. Über den Pfeil bzw. {ui("Umfang")} wählen: Diese Seite, Ausgewählte Seiten, Alle Seiten. Deutsch, Türkisch und Englisch werden lokal erkannt.'.replace('{ui("Umfang")}', ui('Umfang'))],
    [ui('Schwärzen'), 'Bereich aufziehen oder Suchtreffer vormerken; erst {ui("Schwärzungen anwenden")} entfernt Text und Bild endgültig.'.replace('{ui("Schwärzungen anwenden")}', ui('Schwärzungen anwenden'))],
    [ui('Zuschneiden'), 'Seitenbereich aufziehen, der übrig bleiben soll.']], [24, 76])}
<h3>Mit einem Scan arbeiten</h3>
<ol><li>Scan öffnen – oder Startseite → {ui('Scan durchsuchbar machen')} (startet die Texterkennung für alle Seiten).</li>
<li>Nach der Erkennung erscheinen rechts unter {ui('Hinweise / zu prüfen')} unsicher erkannte Wörter und geschützte
Angaben (Aktenzeichen, E-Mail, IBAN, Nummern). Diese werden nie automatisch geändert.</li>
<li>Falsches Wort: Werkzeug {ui('Wort korrigieren (Scan)')}, Wort anklicken, richtiges Wort eingeben, Vorschau prüfen.</li></ol>
{bild('07_editor_scan_ocr.png', 'Scan nach der Texterkennung: unsichere Wörter blau markiert und rechts aufgelistet.', 470)}
{bild('08_wort_korrigieren.png', 'Wort im Scan korrigieren (Vorschau vor dem Übernehmen).', 330)}
<h3>Endgültig schwärzen</h3>
<ol><li>Text suchen (<span class='t'>Strg+F</span>, Enter) und {ui('Suchtreffer zum Schwärzen vormerken')} (<span class='t'>Alt+M</span>) –
oder Werkzeug {ui('Schwärzen')} und Bereich mit der Maus aufziehen.</li>
<li>Vorgemerkte Bereiche sind rot schraffiert mit „WIRD GESCHWÄRZT“ markiert; rechts erscheint
<span class='warn'>⚠ Bitte prüfen: … vorgemerkt – noch nicht geschwärzt</span>.</li>
<li>{ui('Schwärzungen anwenden')} (<span class='t'>Alt+A</span>) und bestätigen. Text, OCR-Text und Bildpunkte werden entfernt.</li>
<li>{ui('Speichern unter…')}: Beim Speichern werden zusätzlich eingebettete Dateien, Metadaten und Vorschaubilder
entfernt; die gespeicherte Datei wird automatisch neu geöffnet und geprüft.</li></ol>
{bild('09_schwaerzen_vorgemerkt.png', 'Vorgemerkte Schwärzung (IBAN, fiktiv): deutlich markiert, noch nicht angewendet.', 470)}
<div class='hinweis'>Ein schwarzes Rechteck aus einem anderen Programm ist keine Schwärzung. Nur
{ui('Schwärzungen anwenden')} und anschließendes Speichern entfernen die Information wirklich.</div>
<p><b>Digital signierte PDFs</b> werden erkannt; Änderungen werden nur als Kopie gespeichert, die Signatur gilt für die
Kopie nicht. Rückgängig/Wiederholen: <span class='t'>Strg+Z</span> / <span class='t'>Strg+Y</span>.</p>

<h2>5. Anlagen-Assistent – Beispiel von Anfang bis Ende</h2>
<p>Beispiel: Klageschrift (Word) mit elf Anlagen – darunter eine Word-Vollmacht, digitale PDFs, Scans, ein Foto
und ein Bildschirmfoto (fiktive „Testakte Mustermann“).</p>
<ol><li><b>Hineinziehen:</b> {ui('Anlagen')} öffnen und alle Dateien in die {ui('Anlagenliste')} ziehen – oder
{ui('Dateien hinzufügen…')} (<span class='t'>Alt+H</span>). Die Word-Datei mit Schriftsatz-typischem Namen wird automatisch
{ui('Schriftsatz')}; ändern mit {ui('Auswahl als Schriftsatz')}. Word-Anlagen werden automatisch in PDF umgewandelt –
warten, bis „bitte warten …“ im Fenstertitel verschwindet.</li>
<li><b>Hinweise lesen:</b> Unten erscheinen beschädigte Dateien (<span class='fehler'>✖ Gestoppt</span>), identische
und inhaltlich ähnliche Dateien sowie gedrehte Seiten (<span class='warn'>⚠ Bitte prüfen</span>). Was entfernt wird,
entscheiden Sie: Anlage wählen → {ui('Entfernen')} (<span class='t'>Entf</span>); gedrehte Seiten → {ui('Ausrichtung korrigieren')}.</li></ol>
{bild('10_anlagen_hineingezogen.png', 'Nach dem Hineinziehen: Liste links, Vorschau in der Mitte, ausgewählte Anlage rechts, Hinweise unten.', 470)}
<ol start='3'><li><b>Ordnen und nummerieren:</b> Reihenfolge per Ziehen oder <span class='t'>Alt+↑/↓</span>. Die Nummern
(„Anlage K1“, „K2“ …) folgen automatisch. Präfix und Startnummer stehen rechts unter {ui('Paket')}
(z. B. „Anlage B“ für die Beklagtenseite).</li>
<li><b>Bezeichnung:</b> In der Liste <span class='t'>F2</span> drücken oder rechts unter {ui('Bezeichnung')} ändern.</li>
<li><b>Seiten:</b> In der {ui('Vorschau')} Seiten markieren und {ui('Drehen')}, {ui('Seite löschen')} oder
{ui('Als eigene Anlage')} wählen. Für Scans {ui('Texterkennung (OCR)')}; für Schwärzungen {ui('Im PDF-Editor öffnen…')}
und dort {ui('In Anlage übernehmen')} (<span class='t'>Strg+Enter</span>). Die Originaldateien bleiben unverändert.</li></ol>
{bild('11_anlagen_geordnet.png', 'Geordnet, nummeriert, bereinigt: keine Hinweise mehr.', 470)}
<ol start='6'><li><b>Prüfen und erstellen:</b> Zielordner wählen, dann {ui('Paket prüfen und erstellen…')} (<span class='t'>Alt+P</span>).
Die Kontrollansicht zeigt Schriftsatz, Reihenfolge, Ausgabedateien und Seitenzahlen. {ui('Erstellen')} oder {ui('Zurück')}.</li></ol>
{bild('12_kontrolle.png', 'Kontrollansicht vor dem Erstellen: Dateinamen und Seitenzahlen prüfen.', 420)}
<p>Ergebnis im Zielordner: <span class='t'>Schriftsatz.pdf</span>, <span class='t'>Anlage_K1.pdf</span>,
<span class='t'>Anlage_K2.pdf</span> … und das bearbeitbare <span class='t'>Anlagenverzeichnis.docx</span> (Anlage, Bezeichnung,
Seiten). Optional {ui('Gesamt-PDF (intern)')} zur internen Prüfung. Vorhandene Dateien werden nicht überschrieben
(Rückfrage, dann „_2“). Bricht das Erstellen ab, bleiben keine halbfertigen Dateien zurück.</p>
{bild('13b_anlagenverzeichnis_word.png', 'Anlagenverzeichnis in Word (bearbeitbar).', 300)}
<ol start='7'><li><b>Outlook-Entwurf:</b> {ui('Outlook-Entwurf erstellen…')} (<span class='t'>Alt+O</span>) zeigt die Anhänge
mit Reihenfolge, Größe und Prüfsumme. Nach dem Bestätigen öffnet sich der Entwurf im klassischen Outlook; BnX-Raptor
prüft, dass die Anhänge genau den bestätigten Dateien entsprechen. Es wird nichts gesendet.</li></ol>
{bild('14_anhaenge_pruefen.png', 'Anhänge vor dem Entwurf prüfen.', 360)}
{bild('15_outlook_ausschnitt.png', 'Ausschnitt des Outlook-Entwurfs: Anhänge in der richtigen Reihenfolge, Text mit Anlagenliste.', 470)}

<h2>6. Häufige Probleme und Lösungen</h2>
{tab(['Problem', 'Ursache und Lösung'], [
    ['„… ist in Word geöffnet und nicht gespeichert“', 'Die Datei ist in Word offen und hat ungespeicherte Änderungen. In Word speichern (oder schließen) und erneut starten. Ihr geöffnetes Word wird von BnX-Raptor nicht angefasst.'],
    ['Word reagiert nicht', 'BnX-Raptor bricht nach dem Zeitlimit (Standard 90 s, <span class="t">word_zeitlimit_sekunden</span>) ab und beendet nur das eigene, unsichtbare Word. Häufige Ursache: kennwortgeschütztes Dokument oder offener Word-Dialog.'],
    ['OCR-Text ist fehlerhaft', 'Scanqualität prüfen (300 dpi, gerade, kontrastreich). Unsichere Wörter stehen unter „Hinweise / zu prüfen“; mit „Wort korrigieren (Scan)“ verbessern. Geschützte Angaben (IBAN, Aktenzeichen) nie ungeprüft übernehmen. Schräg gescannte Seiten werden nicht begradigt.'],
    ['Anlage kann nicht geöffnet werden', 'Rot markiert (✖): Datei beschädigt, kein PDF (z. B. gespeicherte HTML-Seite) oder kennwortgeschützt. Original beim Absender neu anfordern bzw. Kennwort entfernen; die Datei aus der Liste entfernen, sonst wird das Paket nicht erstellt.'],
    ['Outlook-Entwurf erscheint nicht', 'Nur das klassische Outlook wird gesteuert. Ist es nicht installiert oder nicht Standard, entsteht eine .eml-Datei, die sich per Doppelklick öffnet. Outlook ggf. einmal normal starten und erneut versuchen. Entwürfe stehen auch im Ordner „Entwürfe“.'],
    ['Windows-Warnung beim Start', 'SmartScreen warnt bei unsignierten Programmen. Prüfsumme vergleichen; bei Übereinstimmung „Weitere Informationen“ → „Trotzdem ausführen“ (Regeln der Kanzlei-IT beachten).'],
    ['Texterkennung fehlt', 'Ordner <span class="t">ocr</span> neben <span class="t">BnX-Raptor.exe</span> fehlt – ZIP vollständig neu entpacken.']], [30, 70])}

<h2>7. Bekannte Grenzen dieser Testversion</h2>
<ul><li><b>Neues Outlook</b> wurde nicht geprüft; unterstützt wird das klassische Outlook (sonst .eml-Datei).</li>
<li><b>Bearbeitete Anlagen gelten nicht automatisch als PDF/A.</b> PDF/A-Einstellung gilt nur für PDFs, die Word erzeugt
(Schreiben an Versicherungen, Schriftsatz aus Word). Diese Dateien sind als PDF/A gekennzeichnet; eine Prüfung mit
einem unabhängigen PDF/A-Prüfprogramm wurde nicht durchgeführt.</li>
<li>Keine Schräglagenkorrektur bei Scans; Texterkennung nur Deutsch, Türkisch, Englisch.</li>
<li>Keine eigene Verschlüsselung der gespeicherten Daten – bitte Laufwerksverschlüsselung (z. B. BitLocker) und eigene
Windows-Konten verwenden. Löschen: Programmordner und Datenordner (<span class='t'>%APPDATA%\\BnX-Raptor</span>) entfernen.</li>
<li>E-Mails werden nie automatisch gesendet.</li></ul>

<h2>8. Tastenkürzel</h2>
{tab(['Bereich', 'Kürzel'], [
    ['Navigation', '<span class="t">Strg+1</span> Start · <span class="t">Strg+2</span> Anlagen · <span class="t">Strg+3</span> PDF-Editor · <span class="t">Strg+4</span> Akten · <span class="t">Strg+5</span> Einstellungen'],
    ['Versicherungsschreiben', '<span class="t">Alt+S</span> Starten'],
    ['Anlagen-Assistent', '<span class="t">Alt+H</span> Dateien hinzufügen · <span class="t">Alt+L</span> Liste · <span class="t">Alt+↑/↓</span> verschieben · <span class="t">F2</span> Bezeichnung · <span class="t">Entf</span> entfernen · <span class="t">Alt+V</span> Vorschau · <span class="t">Alt+D</span> drehen · <span class="t">Alt+Ö</span> Seite löschen · <span class="t">Alt+G</span> eigene Anlage · <span class="t">Alt+T</span> OCR · <span class="t">Alt+E</span> PDF-Editor · <span class="t">Alt+R</span> Ausrichtung · <span class="t">Alt+P</span> Paket · <span class="t">Alt+O</span> Outlook · <span class="t">Alt+S</span> Schriftsatz · <span class="t">Alt+N</span> Neu'],
    ['PDF-Editor', '<span class="t">Strg+O</span> Öffnen · <span class="t">Strg+Umschalt+S</span> Speichern unter · <span class="t">Strg+Z/Y</span> Rückgängig/Wiederholen · <span class="t">Strg+F</span> Suchen · <span class="t">F3</span> Weiter · <span class="t">Strg++/−</span> Zoom · <span class="t">Alt+M</span> vormerken · <span class="t">Alt+A</span> Schwärzungen anwenden · <span class="t">Strg+Enter</span> In Anlage übernehmen']], [24, 76])}

<h2>9. Hersteller und Sicherheitsmeldungen</h2>
<p>Hersteller: {e(H['name'])}{'' if H['postanschrift'] == 'OFFEN' else ', ' + e(H['postanschrift'])} · E-Mail: {e(H['email'])}</p>
<p><b>{e(SATZ_MELDUNG)}</b></p>
<p class='k'>Drittanbieter-Hinweise und Lizenztexte: Ordner <span class='t'>BnX-Raptor\\lizenzen</span>.</p>
"""


KAPITEL = ["1. Voraussetzungen und Installation", "2. Die Oberfläche", "3. Schreiben an eine Versicherung: PDF und Outlook-Entwurf",
           "4. PDF bearbeiten", "5. Anlagen-Assistent – Beispiel von Anfang bis Ende", "6. Häufige Probleme und Lösungen",
           "7. Bekannte Grenzen dieser Testversion", "8. Tastenkürzel", "9. Hersteller und Sicherheitsmeldungen"]


def setzen(seiten: dict[str, int]) -> pymupdf.Document:
    verz = "<h3>Inhalt</h3>" + tab(["Kapitel", "Seite"], [[e(k), str(seiten.get(k, "–"))] for k in KAPITEL], [88, 12])
    story = pymupdf.Story(html=INHALT.replace("@@INHALT@@", verz), user_css=CSS, archive=pymupdf.Archive(str(BILDER)))
    puffer = io.BytesIO()
    w = pymupdf.DocumentWriter(puffer)
    seite = pymupdf.paper_rect("a4")
    mehr = True
    while mehr:
        dev = w.begin_page(seite)
        mehr, _ = story.place(seite + (54, 50, -54, -58))
        story.draw(dev)
        w.end_page()
    w.close()
    return pymupdf.open("pdf", puffer.getvalue())


def kapitelseiten(doc) -> dict[str, int]:
    """Seite je Kapitel: erste Seite (ab Seite 2) mit großer Überschrift, die mit der Kapitelnummer beginnt."""
    out = {}
    for k in KAPITEL:
        for i, p in enumerate(doc):
            if i == 0:
                continue
            gross = [s["text"].strip() for b in p.get_text("dict")["blocks"] for z in b.get("lines", [])
                     for s in z["spans"] if s["size"] > 13.5]
            if any(g.startswith(k[:2]) for g in gross):
                out[k] = i + 1
                break
    return out


def main() -> None:
    doc = setzen({})
    seiten = kapitelseiten(doc)
    doc = setzen(seiten)
    seiten = kapitelseiten(doc)
    n = doc.page_count
    seite = pymupdf.paper_rect("a4")
    for i, p in enumerate(doc):
        p.insert_text((54, seite.height - 30), f"BnX-Raptor {VERSION} – Benutzerhandbuch · Testversion · Seite {i + 1} von {n}",
                      fontsize=7.5, color=(0.42, 0.45, 0.5))
    doc.set_toc([[1, "Schnellstart", 1]] + [[1, k, seiten[k]] for k in KAPITEL if k in seiten])
    doc.set_metadata({"title": f"BnX-Raptor {VERSION} – Benutzerhandbuch", "author": H["name"],
                      "subject": "Benutzerhandbuch (Testversion)", "creator": "docs/handbuch/erzeugen.py"})
    ZIEL.parent.mkdir(parents=True, exist_ok=True)
    doc.save(ZIEL, garbage=3, deflate=True)
    print("erstellt:", ZIEL.name, n, "Seiten; Kapitel:", seiten)


if __name__ == "__main__":
    main()

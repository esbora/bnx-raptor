"""Erzeugt das deutsche Benutzerhandbuch: docs/Benutzerhandbuch_BnX-Raptor_0.4.2_DE.pdf

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
ZIEL = KOK / "docs" / "Benutzerhandbuch_BnX-Raptor_0.4.2_DE.pdf"
H = json.loads((KOK / "docs" / "CRA" / "hersteller.json").read_text(encoding="utf-8"))
VERSION = "0.4.2"

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
<li><b>Anlagenpaket:</b> Auf der Startseite {ui('Anlagenpaket erstellen')} wählen und Schriftsatz sowie alle Anlagen aus
dem Explorer in die {ui('Anlagenliste')} ziehen. Ein Hauptdokument ist optional.</li>
<li><b>Erstellen:</b> Reihenfolge und Bezeichnungen kontrollieren, dann {ui('Paket erstellen')} – ohne Zwischenfenster.
Ist kein Zielordner gewählt, öffnet sich direkt die Ordnerauswahl.</li>
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
<li>ZIP vollständig entpacken – in einen Ordner, auf den nur berechtigte Personen Zugriff haben (auch OneDrive ist möglich).
Die Ordner <span class='t'>ocr</span> und <span class='t'>lizenzen</span> nicht löschen.</li>
<li><span class='t'>BnX-Raptor.exe</span> starten. Windows SmartScreen kann warnen, weil die Datei nicht signiert ist:
nur starten, wenn die Prüfsumme stimmt.</li>
<li>Beim ersten Start öffnet sich {ui('Kanzleidaten')}: Name, Anwältinnen/Anwälte, Anschrift, Telefon, E-Mail,
Kammer und optional ein Logo. Später änderbar über {ui('Einstellungen')} → {ui('Kanzleidaten…')}.</li></ol>
{bild('01_kanzleidaten.png', 'Kanzleidaten beim ersten Start (fiktive Angaben).', 300)}
<p><b>Einstellungsdatei:</b> <span class='t'>config.json</span> liegt neben der EXE (Vorlage:
<span class='t'>config.example.json</span>). Verlauf, Akten, Mandanten, Versicherungen und Dokumentenarchiv liegen in
<span class='t'>%APPDATA%\\BnX-Raptor</span> bzw. im Ordner aus <span class='t'>daten_ordner</span>.</p>

<h2>2. Die Oberfläche</h2>
<p>Links die Navigation: {ui('Start')}, {ui('Anlagen')}, {ui('PDF-Editor')}, {ui('Akten')}, {ui('Mandanten')},
{ui('Versicherungen')}, {ui('Einstellungen')} (per Tastatur: <span class='t'>Strg+1</span> bis <span class='t'>Strg+7</span>).
Die Oberfläche ist immer hell – auch wenn Windows auf „Dunkel“ steht. Eingaben in Akten, Mandanten und Versicherungen
werden automatisch gespeichert. Rückmeldungen erscheinen immer mit Farbe <b>und</b> Zeichen:</p>
{tab(['Zeichen', 'Bedeutung'], [
    ["<span class='ok'>✓ Erledigt</span>", 'Vorgang abgeschlossen bzw. in Ordnung.'],
    ["<span class='warn'>⚠ Bitte prüfen</span>", 'Kein Fehler, aber bitte ansehen (z. B. gedrehte Seite, Original übernommen).'],
    ["ℹ Hinweis", 'Nur zur Information (z. B. gleiche oder ähnliche Dateien) – nichts wird automatisch entfernt.'],
    ["<span class='fehler'>✖ Gestoppt</span>", 'Der Vorgang konnte nicht ausgeführt werden; die Meldung nennt die Datei und den Grund.']], [25, 75])}

<h2>3. Schreiben an eine Versicherung: PDF und Outlook-Entwurf</h2>
<ol><li>Auf der Startseite {ui('Versicherungsschreiben vorbereiten')} → {ui('Schreiben wählen…')} – Word- oder PDF-Datei –
oder die Datei in die Liste links ziehen.</li>
<li>Das Schreiben erscheint im Programm als Vorschau, so wie Word es druckt. Ändern mit {ui('In Word bearbeiten')}:
BnX-Raptor prüft zuerst, ob das Dokument geschützt ist, legt eine datierte <b>Kopie</b> an (z. B.
<span class='t'>Schreiben_2026-11-18.docx</span>) und öffnet sie im normalen Word. Dort bearbeiten, speichern und schließen –
die Vorschau aktualisiert sich dann selbst, und die Liste verwendet ab jetzt die Kopie. Das Original bleibt unverändert.</li>
<li><b>PDF statt Word:</b> BnX-Raptor erzeugt daneben eine Word-Arbeitskopie <span class='t'>„Name (Word).docx“</span>
(Textebene des PDF bzw. Texterkennung bei Scans). Das Layout kann vereinfacht sein; der Reiter {ui('Original-PDF')}
zeigt das Original zum Vergleich. Arbeitskopie und PDF bleiben im Dokumentenarchiv verknüpft.</li>
<li>{ui('Starten')} (<span class='t'>Alt+S</span>) verwendet die in Word gespeicherte Fassung. Ist das Dokument noch in
Word geöffnet, bitte dort zuerst speichern und schließen.</li>
<li>Im Fenster {ui('Prüfen – …')} die gefundenen Werte kontrollieren. Neben jedem Feld steht, woher der Wert stammt.</li></ol>
{bild('02_hauptfenster_schreiben.png', 'Versicherungsschreiben: Vorschau und „In Word bearbeiten“ (fiktives Schreiben).', 470)}
{tab(['Feld', 'Inhalt'], [
    [ui('Versicherer'), 'Name der Versicherung aus dem Schreiben. Ändern Sie ihn, schlägt BnX-Raptor passende Adressen vor.'],
    [ui('Empfänger-E-Mail'), 'Adresse der Versicherung. Gibt es mehrere Möglichkeiten, bitte aus der Liste wählen.'],
    [ui('Nummer (Betreff)'), 'Versicherungsnummer oder Schaden-Nr. – wird zum Betreff. Alle gefundenen Nummern stehen zur Auswahl.'],
    [ui('Kopie an Mandant (optional)'), 'E-Mail-Adresse der Mandantschaft, falls eine Kopie vorbereitet werden soll.']], [28, 72])}
{bild('03_pruefen_dialog.png', 'Prüfen-Dialog mit erkannten Werten (fiktives Schreiben).', 330)}
<ol start='6'><li>{ui('PDF + Entwurf erstellen')}: Das PDF (PDF/A-Einstellung von Word) wird neben der Word-Datei gespeichert.
Danach öffnet sich der Entwurf im klassischen Outlook. Optional vorher {ui('PDF vor dem Entwurf im PDF-Editor prüfen/bearbeiten')}.</li>
<li>Entwurf prüfen und selbst senden – oder schließen. BnX-Raptor sendet nie.</li></ol>

<h2>4. PDF bearbeiten</h2>
<p>{ui('PDF-Editor')} → {ui('PDF öffnen…')} (oder Startseite → {ui('PDF bearbeiten')}). {ui('Speichern')}
(<span class='t'>Strg+S</span>) speichert in <b>dieselbe Datei</b> – sicher über eine geprüfte Zwischendatei. Wurde die Datei
inzwischen von einem anderen Programm geändert oder ist sie gesperrt (z. B. geöffnet oder in OneDrive-Synchronisierung),
wird nichts überschrieben und Ihre Änderungen bleiben offen. {ui('Speichern unter…')} (<span class='t'>Strg+Umschalt+S</span>)
speichert eine neue Datei. {ui('OK – Änderungen speichern')} (<span class='t'>Strg+Enter</span>) speichert und schließt.</p>
{bild('05_editor_digital.png', 'PDF-Editor: oben Datei und Suche, darunter die Werkzeuge, unten „OK – Änderungen speichern“.', 470)}
{tab(['Werkzeug', 'Verwendung'], [
    [ui('Seiten'), 'Menü: Links/Rechts drehen, Löschen, Duplizieren, PDF/Bild einfügen…, Auswahl als PDF…, Aufteilen…. Seiten links markieren; Reihenfolge per Ziehen ändern.'],
    [ui('Text bearbeiten'), 'Absatz anklicken. Im Fenster jeden anderen Absatz in der Vorschau anklicken oder mit ◀/▶ Absatz für Absatz weitergehen (auch auf Folgeseiten); der gewählte Absatz ist markiert, die Vorschau aktualisiert sich selbst. In Scans werden die erkannten Absätze bearbeitet (fehlt der Text noch, läuft die Texterkennung automatisch).'],
    [ui('Text einfügen'), 'Stelle anklicken und neuen Text eingeben.'],
    [ui('Wort korrigieren (Scan)'), 'Nach der Texterkennung ein falsch erkanntes Wort anklicken und korrigieren – sichtbare Seite und Suchtext werden gemeinsam geändert.'],
    [ui('OCR'), 'Texterkennung starten; Umfang: Diese Seite, Ausgewählte Seiten, Alle Seiten. Deutsch, Türkisch und Englisch werden lokal erkannt.'],
    [ui('Schwärzen'), 'Bereich aufziehen oder Suchtreffer vormerken; erst „Schwärzungen anwenden“ entfernt Text und Bild endgültig.'],
    [ui('Zuschneiden'), 'Seitenbereich aufziehen, der übrig bleiben soll.']], [24, 76])}
{bild('06_text_aendern.png', 'Text bearbeiten: gewählter Absatz markiert, ◀/▶ für weitere Absätze, Vorschau aktualisiert sich selbst.', 420)}
<h3>Mit einem Scan arbeiten</h3>
<ol><li>Scan öffnen – oder Startseite → {ui('Scan durchsuchbar machen')} (startet die Texterkennung für alle Seiten).</li>
<li>Rechts unter {ui('Hinweise / zu prüfen')} stehen unsicher erkannte Wörter und geschützte Angaben (Aktenzeichen,
E-Mail, IBAN, Nummern). Diese werden nie automatisch geändert.</li>
<li>Ganzer Absatz: {ui('Text bearbeiten')}; einzelnes Wort: {ui('Wort korrigieren (Scan)')}.</li></ol>
{bild('07_editor_scan_ocr.png', 'Scan nach der Texterkennung: unsichere Wörter blau markiert und rechts aufgelistet.', 470)}
<h3>Endgültig schwärzen</h3>
<ol><li>Text suchen (<span class='t'>Strg+F</span>, Enter) und {ui('Suchtreffer zum Schwärzen vormerken')} (<span class='t'>Alt+M</span>) –
oder Werkzeug {ui('Schwärzen')} und Bereich mit der Maus aufziehen.</li>
<li>Vorgemerkte Bereiche sind rot schraffiert mit „WIRD GESCHWÄRZT“ markiert.</li>
<li>{ui('Schwärzungen anwenden')} (<span class='t'>Alt+A</span>) und bestätigen. Text, OCR-Text und Bildpunkte werden entfernt.</li>
<li>Speichern ({ui('Speichern')}, {ui('Speichern unter…')} oder {ui('OK – Änderungen speichern')}): eingebettete Dateien,
Metadaten und Vorschaubilder werden entfernt; die Datei wird vor dem Ablegen geprüft (Ergebnis in der Statuszeile).</li></ol>
{bild('09_schwaerzen_vorgemerkt.png', 'Vorgemerkte Schwärzung (IBAN, fiktiv): deutlich markiert, noch nicht angewendet.', 470)}
<div class='hinweis'>Ein schwarzes Rechteck aus einem anderen Programm ist keine Schwärzung. Nur
{ui('Schwärzungen anwenden')} und anschließendes Speichern entfernen die Information wirklich.</div>

<h2>5. Anlagen-Assistent – Beispiel von Anfang bis Ende</h2>
<p>Beispiel: Klageschrift (Word) mit elf Anlagen – darunter eine Word-Vollmacht, digitale PDFs, Scans, ein Foto
und ein Bildschirmfoto (fiktive „Testakte Mustermann“).</p>
<ol><li><b>Hineinziehen:</b> {ui('Anlagen')} öffnen und alle Dateien in die {ui('Anlagenliste')} ziehen – oder
{ui('Dateien hinzufügen…')} (<span class='t'>Alt+H</span>). Warten, bis „bitte warten …“ im Fenstertitel verschwindet.</li>
<li><b>Hauptdokument (optional):</b> Eine Word-Datei mit Schriftsatz-typischem Namen wird vorgeschlagen.
{ui('Als Hauptdokument festlegen')} (<span class='t'>Alt+S</span>): Dieses Dokument wird als Schriftsatz vor den Anlagen
ausgegeben. {ui('Kein Hauptdokument')}: nur Anlagen.</li>
<li><b>Hinweise lesen:</b> Dateien, die nicht geöffnet oder umgewandelt werden können, bleiben in der Liste
(<span class='warn'>⚠ Original übernommen – Vorschau nicht verfügbar</span>) und kommen mit Originalname und Inhalt ins Paket.
Gleiche und ähnliche Dateien zeigen nur einen Hinweis (ℹ). Was entfernt wird, entscheiden Sie: Anlage wählen →
{ui('Entfernen')} (<span class='t'>Entf</span>); gedrehte Seiten → {ui('Ausrichtung korrigieren')}.</li></ol>
{bild('10_anlagen_hineingezogen.png', 'Nach dem Hineinziehen: Liste links, Vorschau in der Mitte, ausgewählte Anlage rechts, Hinweise unten.', 470)}
<ol start='4'><li><b>Ordnen und nummerieren:</b> Reihenfolge per Ziehen oder <span class='t'>Alt+↑/↓</span>. Die Nummern
(„Anlage K1“, „K2“ …) folgen automatisch. Präfix und Startnummer rechts unter {ui('Paket')}.</li>
<li><b>Bezeichnung:</b> In der Liste <span class='t'>F2</span> drücken oder rechts unter {ui('Bezeichnung')} ändern.</li>
<li><b>Seiten bearbeiten:</b> <b>Doppelklick auf eine Seite in der {ui('Vorschau')}</b> öffnet die Anlage genau dort im
Werkzeug {ui('Text bearbeiten')}. {ui('OK – Änderungen speichern')} übernimmt die Änderung sofort in die Anlage
(Vorschau und Angaben werden aktualisiert). Außerdem: {ui('Links drehen')} / {ui('Rechts drehen')} (jeder Klick 90°, auch mehrere Seiten gleichzeitig), {ui('Löschen')}, {ui('Als eigene Anlage')},
{ui('Texterkennung (OCR)')}. Die Originaldateien bleiben unverändert.</li></ol>
{bild('11_anlagen_geordnet.png', 'Geordnet und nummeriert; das Hauptdokument steht oben.', 470)}
<div class='hinweis'><b>Große Vorschau:</b> Maus kurz über eine Seite in der {ui('Vorschau')} (bzw. über das Vorschaubild bei den Anhängen) halten – eine große, gut lesbare Vorschau öffnet sich (Mausrad oder ←/→ blättert, Esc schließt). Abschaltbar unter {ui('Einstellungen')} → {ui('Große Vorschau beim Darüberfahren')}.</div>
<ol start='7'><li><b>Erstellen:</b> {ui('Paket erstellen')} (<span class='t'>Alt+P</span>) – ohne Zwischenfenster. Ohne Zielordner
öffnet sich die Ordnerauswahl.</li></ol>
{bild('13_paket_erstellt.png', 'Paket erstellt: Ergebnis und Hinweise unten in der Statuszeile.', 470)}
<p>Ergebnis im Zielordner: <span class='t'>Schriftsatz.pdf</span>, <span class='t'>Anlage_K1.pdf</span>,
<span class='t'>Anlage_K2.pdf</span> …, übernommene Originale mit ihrem Namen und das bearbeitbare
<span class='t'>Anlagenverzeichnis.docx</span>. Optional {ui('Gesamt-PDF (intern)')}. Vorhandene Dateien werden nicht
überschrieben (Rückfrage, dann „_2“). Das Paket wird zuerst lokal gebaut und dann abgelegt; ist eine Datei kurz gesperrt
(OneDrive, Virenscanner), wartet BnX-Raptor und versucht es erneut. Bleibt sie gesperrt, nennt die Meldung die Datei,
{ui('Erneut versuchen')} ist möglich, und es bleiben keine halbfertigen Dateien zurück.</p>
{bild('13b_anlagenverzeichnis_word.png', 'Anlagenverzeichnis in Word (bearbeitbar).', 300)}
<ol start='8'><li><b>Outlook-Entwurf:</b> {ui('Outlook-Entwurf erstellen…')} (<span class='t'>Alt+O</span>) zeigt die Anhänge
mit Reihenfolge, Größe und Prüfsumme → {ui('In Outlook-Entwurf übernehmen')}. Der Entwurf öffnet sich im klassischen
Outlook; BnX-Raptor prüft, dass die Anhänge genau den bestätigten Dateien entsprechen. Es wird nichts gesendet.</li></ol>
{bild('14_anhaenge_pruefen.png', 'Anhänge vor dem Entwurf prüfen.', 360)}
{bild('15_outlook_ausschnitt.png', 'Ausschnitt des Outlook-Entwurfs: Anhänge in der richtigen Reihenfolge, Text mit Anlagenliste.', 470)}

<h2>6. Akten, Mandanten und Versicherungen</h2>
<ul><li><b>{ui('Mandanten')}:</b> {ui('Neuer Mandant')} – Person oder Firma mit Anschrift, Telefon, E-Mail und Notiz.
{ui('Neue Akte')} legt eine Akte für diesen Mandanten an; ein Mandant kann mehrere Akten haben. Jeder Mandant erhält automatisch eine feste <b>Mandats-Nr.</b> (M01, M02 …). Aktenzeichen, Versicherungsnummer und Schaden-Nr. tragen Sie direkt im Formular ein – ohne Akte wird beim Eintragen automatisch eine angelegt. Unter {ui('Akten / Mandate')} stehen Aktenzeichen, Versicherungsnummer, Schaden-Nr. und Versicherung jeder Akte; ein markiertes Feld anklicken (oder F2) ändert es direkt, Doppelklick öffnet die Akte. Die Suche findet auch M-Nr., Aktenzeichen, Versicherungs- und Schaden-Nr. <b>Löschen:</b> Rechtsklick auf den Mandanten → {ui('Mandant löschen …')} (oder Entf) – Akten und Dokumente bleiben erhalten.</li>
<li><b>{ui('Versicherungen')}:</b> Versicherer mit Anschrift, Kontakt, Notiz und mehreren E-Mail-Adressen. Die E-Mail-Adressen
sind das bisherige Versicherer-Adressbuch – es gibt nur eine Stelle dafür.</li>
<li><b>{ui('Akten')}:</b> {ui('Neue Akte')}; Felder Aktenzeichen, Mandant, Versicherung, Versicherungsnummer und Schaden-Nr.
{ui('Aktenordner öffnen')} zeigt den Ordner im Explorer; {ui('Dateien aus Ordner hinzufügen…')} fügt Dateien der Akte hinzu –
sie erscheinen sofort im Verlauf.</li>
<li><b>Verlauf:</b> Doppelklick öffnet PDFs im PDF-Editor (nach dem Speichern zeigt derselbe Eintrag „✎ bearbeitet …“) und
Word-Dateien in der Vorschau mit {ui('In Word bearbeiten')}: Die datierte Kopie wird im echten Word bearbeitet und als neuer
Eintrag in den Verlauf der Akte übernommen; das Original bleibt unverändert.</li>
<li><b>{ui('Dokumentenordner öffnen')}</b> (in {ui('Mandanten')} und {ui('Versicherungen')}): öffnet die Ordner der bisherigen
Dokumente aus allen verknüpften Akten – bei mehreren Ordnern mit kurzer Auswahl.</li>
<li><b>Dokumentenarchiv:</b> Bearbeitete und erstellte Dateien werden mit Akte, Typ, Datum und Herkunft gemerkt.
{ui('📄 Dokumente ohne Akte')}: markieren → {ui('Akte zuordnen…')}.</li></ul>
{bild('16_akten.png', 'Akte mit Mandant, Versicherung, Nummern und Verlauf (fiktiv).', 470)}
{bild('19_word_bearbeiten.png', 'Word-Datei aus dem Verlauf: Vorschau und „In Word bearbeiten“ (Kopie).', 420)}
{bild('17_mandanten.png', 'Mandanten mit ihren Akten.', 420)}
{bild('04_versicherungen.png', 'Versicherungen mit E-Mail-Adressen (= Versicherer-Adressbuch).', 420)}

<h2>7. Häufige Probleme und Lösungen</h2>
{tab(['Problem', 'Ursache und Lösung'], [
    ['„… ist in Word geöffnet und nicht gespeichert“', 'Die Datei ist in Word offen und hat ungespeicherte Änderungen. In Word speichern (oder schließen) und erneut starten.'],
    ['Word reagiert nicht', 'BnX-Raptor bricht nach dem Zeitlimit (Standard 90 s) ab und beendet nur das eigene, unsichtbare Word.'],
    ['„… ist gesperrt“ / „Zugriff verweigert“', 'Die Datei ist in einem anderen Programm geöffnet oder wird gerade synchronisiert. Schließen bzw. kurz warten und erneut speichern / {ui("Erneut versuchen")}. Es wurde nichts überschrieben.'.replace('{ui("Erneut versuchen")}', ui('Erneut versuchen'))],
    ['„… von einem anderen Programm geändert“', 'Die Datei wurde während der Bearbeitung von außen geändert. Nichts wurde überschrieben – mit „Speichern unter…“ als neue Datei sichern.'],
    ['OCR-Text ist fehlerhaft', 'Scanqualität prüfen (300 dpi, gerade, kontrastreich). Unsichere Wörter stehen unter „Hinweise / zu prüfen“. Schräg gescannte Seiten werden nicht begradigt.'],
    ['Anlage kann nicht geöffnet werden', '„Original übernommen – Vorschau nicht verfügbar“: Die Datei kommt unverändert ins Paket, aber nicht ins Gesamt-PDF. Original ggf. neu anfordern.'],
    ['Outlook-Entwurf erscheint nicht', 'Nur das klassische Outlook wird gesteuert; sonst entsteht eine .eml-Datei. Outlook einmal normal starten und erneut versuchen.'],
    ['Word-Dokument ist geschützt', 'Vor dem Bearbeiten meldet BnX-Raptor Bearbeitungseinschränkungen und gesperrte Inhaltssteuerelemente. In Word unter „Überprüfen → Bearbeitung einschränken“ den Schutz aufheben bzw. die Vorlage freigeben lassen.'],
    ['Fehlermeldung von Word/Outlook', 'Die Meldung nennt die Ursache in Klartext. Technische Einzelheiten für den Support stehen in <span class="t">bnx-raptor.log</span> im Datenordner (ohne Dokumentinhalte).'],
    ['Windows-Warnung beim Start', 'SmartScreen warnt bei unsignierten Programmen. Prüfsumme vergleichen (Regeln der Kanzlei-IT beachten).'],
    ['Texterkennung fehlt', 'Ordner <span class="t">ocr</span> neben <span class="t">BnX-Raptor.exe</span> fehlt – ZIP vollständig neu entpacken.']], [30, 70])}

<h2>8. Bekannte Grenzen dieser Testversion</h2>
<ul><li><b>Neues Outlook</b> wurde nicht geprüft; unterstützt wird das klassische Outlook (sonst .eml-Datei).</li>
<li><b>Bearbeitete Anlagen gelten nicht automatisch als PDF/A.</b> PDF/A-Einstellung gilt nur für PDFs, die Word erzeugt.
Eine Prüfung mit einem unabhängigen PDF/A-Prüfprogramm wurde nicht durchgeführt.</li>
<li>PDF → Word: Das Layout wird vereinfacht (Absätze). Word-Dateien werden im echten Word bearbeitet (als Kopie).</li>
<li>Keine Schräglagenkorrektur bei Scans; Texterkennung nur Deutsch, Türkisch, Englisch.</li>
<li>Keine eigene Verschlüsselung der gespeicherten Daten – bitte Laufwerksverschlüsselung (z. B. BitLocker) und eigene
Windows-Konten verwenden. Löschen: Programmordner und Datenordner (<span class='t'>%APPDATA%\\BnX-Raptor</span>) entfernen.</li>
<li>E-Mails werden nie automatisch gesendet.</li></ul>

<h2>9. Tastenkürzel</h2>
{tab(['Bereich', 'Kürzel'], [
    ['Navigation', '<span class="t">Strg+1</span> Start · <span class="t">Strg+2</span> Anlagen · <span class="t">Strg+3</span> PDF-Editor · <span class="t">Strg+4</span> Akten · <span class="t">Strg+5</span> Mandanten · <span class="t">Strg+6</span> Versicherungen · <span class="t">Strg+7</span> Einstellungen'],
    ['Versicherungsschreiben', '<span class="t">Alt+S</span> Starten'],
    ['Anlagen-Assistent', '<span class="t">Alt+H</span> Dateien hinzufügen · <span class="t">Alt+L</span> Liste · <span class="t">Alt+↑/↓</span> verschieben · <span class="t">F2</span> Bezeichnung · <span class="t">Entf</span> entfernen · <span class="t">Alt+V</span> Vorschau · Doppelklick Seite bearbeiten · <span class="t">Alt+D</span> drehen · <span class="t">Alt+Ö</span> Seite löschen · <span class="t">Alt+G</span> eigene Anlage · <span class="t">Alt+T</span> OCR · <span class="t">Alt+E</span> PDF-Editor · <span class="t">Alt+R</span> Ausrichtung · <span class="t">Alt+P</span> Paket erstellen · <span class="t">Alt+O</span> Outlook · <span class="t">Alt+S</span> Hauptdokument · <span class="t">Alt+N</span> Neu'],
    ['PDF-Editor', '<span class="t">Strg+S</span> Speichern · <span class="t">Strg+Umschalt+S</span> Speichern unter · <span class="t">Strg+Enter</span> OK – Änderungen speichern · <span class="t">Strg+O</span> Öffnen · <span class="t">Strg+Z/Y</span> Rückgängig/Wiederholen · <span class="t">Strg+F</span> Suchen · <span class="t">F3</span> Weiter · <span class="t">Strg++/−</span> Zoom · <span class="t">Alt+M</span> vormerken · <span class="t">Alt+A</span> Schwärzungen anwenden']], [24, 76])}

<h2>10. Hersteller und Sicherheitsmeldungen</h2>
<p>Hersteller: {e(H['name'])}{'' if H['postanschrift'] == 'OFFEN' else ', ' + e(H['postanschrift'])} · E-Mail: {e(H['email'])}</p>
<p><b>{e(SATZ_MELDUNG)}</b></p>
<p class='k'>Drittanbieter-Hinweise und Lizenztexte: Ordner <span class='t'>BnX-Raptor\\lizenzen</span>.</p>
"""


KAPITEL = ["1. Voraussetzungen und Installation", "2. Die Oberfläche", "3. Schreiben an eine Versicherung: PDF und Outlook-Entwurf",
           "4. PDF bearbeiten", "5. Anlagen-Assistent – Beispiel von Anfang bis Ende", "6. Akten, Mandanten und Versicherungen",
           "7. Häufige Probleme und Lösungen", "8. Bekannte Grenzen dieser Testversion", "9. Tastenkürzel",
           "10. Hersteller und Sicherheitsmeldungen"]


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

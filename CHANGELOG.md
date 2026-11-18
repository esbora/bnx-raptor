## BnX-Raptor 0.4.0

- Neu: **Anlagen-Assistent** (Reiter „Anlagen“). Schriftsatz (Word oder PDF) und Anlagen (PDF, JPG, PNG, TIFF) hineinziehen – die Word-Datei wird automatisch als Schriftsatz erkannt (änderbar mit „Auswahl als Schriftsatz“).
- Anlagen werden automatisch nummeriert („Anlage K1“, „Anlage K2“ …). Präfix, Startnummer und die Bezeichnung jeder Anlage (F2) sind änderbar. Reihenfolge per Ziehen oder Alt+↑/↓ – Nummern, Dateinamen, Anlagenverzeichnis und Outlook-Anhänge folgen immer derselben Reihenfolge.
- Vorschau jeder Anlage mit Seiten: drehen, Seite löschen, Seiten als eigene Anlage herauslösen, Texterkennung (OCR) für Scans, „Im PDF-Editor öffnen…“. Die Originaldateien werden nie verändert.
- Hinweise vor dem Erstellen: beschädigte oder unlesbare Dateien (mit Dateiname – das Paket kann dann nicht erstellt werden), Byte für Byte identische Dateien, Dateien mit ähnlichem Inhalt (z. B. PDF und Scan derselben Rechnung) und auf dem Kopf stehende Scan-Seiten („Ausrichtung korrigieren“). Was entfernt wird, entscheiden Sie.
- „Paket prüfen und erstellen…“: eine Kontrollansicht mit Schriftsatz, Reihenfolge, Ausgabedateien, Seitenzahlen und Hinweisen. Ergebnis im gewählten Ordner: Schriftsatz.pdf (PDF/A wie bisher), Anlage_K1.pdf, Anlage_K2.pdf … und ein bearbeitbares Anlagenverzeichnis.docx (Anlage, Bezeichnung, Seiten). Optional ein Gesamt-PDF zur internen Prüfung.
- Vorhandene Dateien werden nicht überschrieben (Rückfrage, dann „_2“). Bricht das Erstellen ab, bleiben keine halbfertigen Dateien zurück – das Paket gilt dann nicht als fertig.
- „Outlook-Entwurf erstellen…“: Vorschau der Anhänge (Reihenfolge, Größe, Prüfsumme), danach Entwurf im klassischen Outlook bzw. als .eml. BnX-Raptor prüft, dass die Anhänge im Entwurf genau den bestätigten Dateien entsprechen. Es wird nichts gesendet.
- Neu: **PDF bearbeiten** (Menü „Werkzeuge“). Seiten ansehen, suchen, Text markieren und kopieren; Seiten per Ziehen sortieren, drehen, löschen, duplizieren, zuschneiden; PDF/Bild einfügen, Seiten als eigenes PDF speichern, aufteilen.
- Echter Textaustausch in digitalen PDFs: Absatz anklicken, Text ändern (Schrift, Größe, Farbe, Ausrichtung). Der alte Text wird aus der Datei entfernt, nicht überdeckt. Vor dem Übernehmen zeigt eine Vorschau Hinweise, z. B. wenn ein Absatz mit gemischter Formatierung vereinheitlicht wird, eine Ersatzschrift nötig ist oder der Text nicht passt. Neuer Text kann an beliebiger Stelle eingefügt werden.
- Texterkennung (OCR) auf dem eigenen Rechner für Deutsch, Türkisch und Englisch – für eine Seite, ausgewählte Seiten oder das ganze Dokument. Gescannte Seiten werden durchsuchbar; unsicher erkannte Wörter und geschützte Angaben (Aktenzeichen, E-Mail, IBAN, Nummern) werden zur Prüfung aufgelistet und nie automatisch geändert. Auf dem Kopf stehende Seiten werden erkannt. Eine Schräglagenkorrektur gibt es noch nicht.
- Wort im Scan korrigieren: sichtbare Seite und Suchtext werden gemeinsam geändert.
- Endgültig schwärzen (Bereiche markieren oder Suchtreffer): Text, OCR-Text und Bildpunkte werden entfernt; beim Speichern außerdem eingebettete Dateien, Metadaten und Vorschaubilder. Die gespeicherte Datei wird danach automatisch neu geöffnet und geprüft.
- Rückgängig/Wiederholen, „Speichern unter…“ in eine neue Datei (das Original bleibt immer unverändert), Warnung bei ungespeicherten Änderungen. Digital signierte PDFs werden erkannt; Änderungen werden nur als Kopie gespeichert.
- Versicherungsschreiben: neue Option „PDF vor dem Entwurf im PDF-Editor prüfen/bearbeiten“; anschließend wird angezeigt, welche Fassung angehängt wird.
- Beschädigte PDFs mit fehlerhaftem Seitenverzeichnis führen jetzt zu einer verständlichen Meldung statt zu einem technischen Fehler.
- Texterkennung auf Tesseract 5.5.4 aktualisiert (behebt mehrere Sicherheitsprobleme der Vorversion, u. a. einen möglichen Absturz bei mehreren Sprachen). Das Erkennungsergebnis bleibt gleich; die Erkennung dauert etwas länger.
- Programmpaket: nicht benötigte Qt-Netzwerk-, Verschlüsselungs- und Bildformat-Bibliotheken entfernt. Lizenzhinweise der mitgelieferten Komponenten vervollständigt; der Quellcode der mitgelieferten GPL/LGPL-Bibliotheken der Texterkennung liegt im Ordner „quellcode-drittanbieter“ bei.

### Nachbesserungen aus dem Pilottest (0.4.0, Stand 18.11.2026)

- Anlagenpaket in OneDrive-Ordnern: Das Paket wird zuerst lokal gebaut und erst am Ende in den Zielordner gelegt. Ist eine Datei kurz gesperrt (OneDrive-Synchronisierung, Virenscanner, geöffnetes Programm), wartet BnX-Raptor einige Sekunden und versucht es erneut. Bleibt sie gesperrt, nennt die Meldung die Datei; Auswahl und vorhandene Dateien bleiben unverändert, „Erneut versuchen“ ist möglich. Es bleiben keine „.bnx-paket-…“-Ordner mehr zurück.
- „Paket erstellen“ statt „Paket prüfen und erstellen…“: kein Zwischenfenster mehr. Ohne Zielordner öffnet sich direkt die Ordnerauswahl. Ein Hauptdokument ist optional („Als Hauptdokument festlegen“ – das Dokument wird als Schriftsatz vor den Anlagen ausgegeben; „Kein Hauptdokument“). Gleiche/ähnliche Dateien sind nur noch ein Hinweis.
- Dateien, die nicht geöffnet oder umgewandelt werden können, bleiben in der Liste („Original übernommen – Vorschau nicht verfügbar“) und kommen mit Originalname, Endung und Inhalt ins Paket. Nicht lesbare Quelldateien werden im Ergebnis ausdrücklich als „nicht kopiert“ genannt.
- Text bearbeiten: In der Vorschau des Dialogs jeden Absatz anklicken (auch ganz unten) oder mit ◀/▶ Absatz für Absatz weitergehen, auch auf Folgeseiten; der gewählte Absatz ist markiert, die Vorschau aktualisiert sich selbst. Gleich lautende Absätze werden getrennt bearbeitet. In Scans werden die erkannten Absätze bearbeitbar (sichtbarer Text und Suchtext werden gemeinsam ersetzt, andere Absätze bleiben unverändert).
- PDF-Editor: „Speichern“ (Strg+S) speichert in dieselbe Datei – sicher über eine geprüfte Zwischendatei; wurde die Datei zwischenzeitlich von außen geändert oder ist sie gesperrt, wird nichts überschrieben und die Bearbeitung bleibt offen. „Speichern unter…“ bleibt. Neuer Knopf „OK – Änderungen speichern“ speichert und führt zurück; im Anlagen-Assistenten werden Vorschau und Angaben sofort aktualisiert.
- Anlagen-Assistent: Doppelklick auf eine Vorschauseite öffnet die Anlage genau dort zum Bearbeiten (Scan ohne Text: Texterkennung läuft automatisch).
- Versicherungsschreiben vorbereiten: Das gewählte Schreiben wird im Programm angezeigt und kann bearbeitet werden (Word: Änderungen über Word, Briefkopf und Formatierung bleiben erhalten; PDF: wird in eine Word-Arbeitskopie neben dem PDF umgewandelt – Textebene bzw. Texterkennung –, Original-PDF zum Vergleich in der Vorschau). „Starten“ speichert offene Änderungen und verwendet den letzten gespeicherten Text.
- Akten: „Aktenordner öffnen“ und „Dateien aus Ordner hinzufügen…“ (Dateien erscheinen sofort im Verlauf). Doppelklick im Verlauf öffnet Word-Dateien zur Bearbeitung im Programm und PDFs im PDF-Editor; danach werden derselbe Verlaufseintrag und die Vorschau aktualisiert. Neue Akte direkt anlegen; Felder werden automatisch gespeichert.
- Dokumentenarchiv in der vorhandenen Datenbank: Akte, Dateiname, Typ, hinzugefügt, zuletzt bearbeitet, Herkunft (z. B. Word-Arbeitskopie ← PDF). „Dokumente ohne Akte“ lassen sich später einer Akte zuordnen.
- Neu: Seiten „Mandanten“ (Person/Firma, Anschrift, Telefon, E-Mail, Notiz, mehrere Akten) und „Versicherungen“ (Anschrift, Kontakt, mehrere E-Mail-Adressen, Notiz). Die E-Mail-Adressen sind das bisherige Versicherer-Adressbuch – eine Stelle für alles. Akten haben jetzt getrennte Felder für Aktenzeichen, Mandant, Versicherung, Versicherungsnummer und Schaden-Nr.; bestehende Akten und Adressen funktionieren weiter.
- Oberfläche immer hell (auch wenn Windows auf „Dunkel“ steht), auch Datei- und Ordnerauswahl; Knöpfe rund und lebendiger (Verlauf, Hover, Druckzustand). Standarddialoge auf Deutsch („Ja/Nein“, „Öffnen“, „Abbrechen“). Akten-Formular zweispaltig, damit der Verlauf mehr Platz hat; auf kleinen Bildschirmen bzw. bei 150 % wird gescrollt statt abgeschnitten.
- Behoben: Nach dem ersten Speichern im PDF-Editor konnten weitere Textänderungen im selben Dokument als nicht durchsuchbarer Text gespeichert werden.
- Akten: Bei Auswahl von Mandant bzw. Versicherung erscheinen Anschrift, Telefon und E-Mail aus den gespeicherten Daten; die E-Mail-Felder füllen sich automatisch (mehrere Versicherungsadressen: Standardadresse – in „Versicherungen“ mit „★ Als Standard“ festlegbar – sonst Auswahlliste). Eine von Hand eingetragene Adresse gilt nur für diese Akte und bleibt erhalten; „E-Mail an Mandant…“ und „E-Mail an Versicherung…“ verwenden die angezeigte Adresse.

## BnX-Raptor 0.3.0

- Neu: **Versicherer-Adressbuch.** Der Name des Versicherers wird aus dem Anschriftenfeld des Schreibens gelesen (oder aus dem Vorlagenfeld „Versicherer“) und im Prüfen-Fenster mit Quelle angezeigt; er kann dort korrigiert werden.
- Enthält das Schreiben keine E-Mail-Adresse, wird die gespeicherte Adresse vorgeschlagen („aus Adressbuch – bitte prüfen“).
- Weicht die Adresse im Schreiben von der gespeicherten ab oder gibt es mehrere Adressen, werden alle mit ihrer Quelle angezeigt – der Entwurf wird erst erstellt, wenn Sie eine Adresse ausgewählt haben.
- Ein Versicherer kann mehrere E-Mail-Adressen haben. Schreibweisen und bekannte Abkürzungen („Vers.“, „Versicherungs-AG“, Umlaute) werden erkannt; ähnlich klingende, aber verschiedene Gesellschaften werden nicht zusammengeführt.
- Gespeichert wird nur, was Sie bestätigt haben – und erst, nachdem PDF und Entwurf erfolgreich erstellt wurden. Abbruch oder Fehler ändern das Adressbuch nicht.
- Einstellungen → „Versicherer-Adressbuch…“: Einträge ansehen, suchen, korrigieren, hinzufügen und löschen.
- Neu: **Versicherungs- oder Schaden-Nr. wählbar.** Alle im Schreiben gefundenen Nummern stehen im Prüfen-Fenster in einer Auswahlliste – jeweils mit ihrer Bezeichnung aus dem Schreiben (z. B. „aus ‚RS Schaden-Nr.‘“). Vorausgewählt ist die Versicherungsnummer; gibt es keine, steht dort „aus ‚RS Schaden-Nr.‘ – keine Versicherungsnummer gefunden“.
- Der E-Mail-Betreff richtet sich nach der gewählten Nummer: „Versicherungsnummer: …“ oder „Schaden-Nr.: …“. Gilt auch für die Kopie an den Mandanten und für Schreiben aus dem Akten-Bereich.
- Die eigene Kanzlei-Adresse wird nicht mehr als Empfänger vorgeschlagen. Die Kanzlei-Domain wird automatisch aus der E-Mail-Adresse unter „Büro-Informationen“ übernommen (zusätzlich zur Einstellung „eigene_domains“). Steht im Schreiben nur die Kanzlei-Adresse, bleibt das Feld leer: „nur Kanzlei-Adresse im Brief – bitte manuell eintragen“.
- Mehr Sicherheit bei Word: Wartet das unsichtbare Word auf eine versteckte Rückfrage (z. B. „Datei in Verwendung“), bricht BnX-Raptor nach 90 Sekunden mit einer verständlichen Meldung ab (einstellbar: „word_zeitlimit_sekunden“). Dabei wird nur die von BnX-Raptor gestartete Word-Sitzung beendet – Ihre geöffneten Word-Dokumente bleiben unberührt. Das Programmfenster reagiert während der Word-Arbeit weiter.
- Kann Word nicht gestartet werden, erscheint ein Hinweis, was zu tun ist.
- Robusterer Programmstart: Eine mit dem Windows-Editor gespeicherte config.json (mit BOM) wird jetzt gelesen; ist die Datei fehlerhaft, erscheint eine verständliche Meldung mit Zeilenangabe statt eines Absturzes.
- Korrektur: Die Mandanten-E-Mail aus dem Vorlagenfeld wird jetzt als „aus Vorlage“ (statt „aus Akte“) gekennzeichnet.

## BnX-Raptor 0.2.0

- Kanzleidaten: Name, Anschrift, Steuernummer, USt-IdNr., Bankverbindung, Logo
- E-Mail-Signatur aus den Kanzleidaten (optional statt Outlook-Signatur)
- Kopie des Schreibens an den Mandanten (optional, als zweiter Entwurf)
- Reiter „Akten“: Verlauf je Versicherungsnummer, E-Mails an Mandant/Versicherung mit Anlagen
- Antworten der Versicherung aus Outlook abrufen oder als .eml/.msg hineinziehen; Ablage im Aktenordner
- E-Mail-Modus wird automatisch erkannt (klassisches Outlook oder .eml-Entwurf für das neue Outlook)
- Hinweis auf neue Versionen beim Start (Update wird manuell installiert)

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
- Korrektur: Die Mandanten-E-Mail aus dem Vorlagenfeld wird jetzt als „aus Vorlage“ (statt „aus Akte“) gekennzeichnet.

## BnX-Raptor 0.2.0

- Kanzleidaten: Name, Anschrift, Steuernummer, USt-IdNr., Bankverbindung, Logo
- E-Mail-Signatur aus den Kanzleidaten (optional statt Outlook-Signatur)
- Kopie des Schreibens an den Mandanten (optional, als zweiter Entwurf)
- Reiter „Akten“: Verlauf je Versicherungsnummer, E-Mails an Mandant/Versicherung mit Anlagen
- Antworten der Versicherung aus Outlook abrufen oder als .eml/.msg hineinziehen; Ablage im Aktenordner
- E-Mail-Modus wird automatisch erkannt (klassisches Outlook oder .eml-Entwurf für das neue Outlook)
- Hinweis auf neue Versionen beim Start (Update wird manuell installiert)

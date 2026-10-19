# Echtlauf M15: zehn Originale mit Signalen, Urteil und Klassifikator

Datum: 2026-10-14. Dieselben zehn Originale wie in M13 (`M13-lanes.md`), diesmal nicht in eine leere
Umgebung, sondern in eine Kopie der Devinstanz mit dem übernommenen Bestand, normal per API
hochgeladen (Kanal `web`, ohne Metadaten). Die Paperless-Werte sind das Soll. Keine Titel und keine
Personennamen in diesem Bericht; die Auswahl steht als Paperless-IDs, Gründe mit maskierten Namen.

## Aufbau

- **Kopie der Devinstanz:** Datenbank `papiq_m15` (Vorlage `papiq_live`), Bucket `papiq-m15` (7644
  Objekte serverseitig kopiert), Webhooks abgeschaltet (es gab keine), eigener Index
  `papiq-m15-documents`, API auf Port 8001.
- **Migration 0011 → 0016 auf echten Daten:** ohne Fehler, 5 s. Die Rückfüllung von `confirmed_at`
  markierte 1525 von 1527 Dokumenten als bestätigt (die übernommenen).
- **Felder:** Die drei globalen Felder (ASN, Notizen, Text) wurden optional den Typen zugeordnet,
  deren Dokumente in Paperless einen Wert tragen (ASN 11 Typen). LA_Brutto und LA_Netto hingen
  schon an Lohnabrechnung (Pflicht, wie vor M15).
- **Die Originale:** Neun der zehn lagen in der Kopie und wurden gelöscht; das zehnte (1980) war
  nicht darin.
- **Training:** `train`, 42 s auf der CPU, aus 1516 bestätigten Dokumenten: 73 Kontakte,
  15 Dokumenttypen, 5 Tags. An einem zurückgehaltenen Fünftel (304 Dokumente) nennt das Modell
  den Kontakt in 90 % und den Typ in 90 % richtig. Es lernte 169 Kennungen.
- **Index:** Die Einträge mit Vektoren kamen aus dem Index der Devinstanz (nur lesend kopiert);
  der Indexer erkannte unveränderten Text am Stempel und schrieb nur die Metadaten mit
  `confirmed` neu, ohne Embedding-Aufrufe.
- **Modell:** Groq `qwen/qwen3.8-27b` über Open WebUI (Tobis Wahl), `json_schema`,
  `LEKTO_LLM_INPUT_BUDGET=6000`, `LEKTO_NODE_RETRY_DELAY=70`. Ein Modellaufruf je Dokument,
  0,8 s im Median.

## Zwei Durchgänge

Der erste Durchgang lief versehentlich unter dem Admin der Kopie, der kein bestätigtes Dokument
besitzt: Die Nachbarn suchen nur in dem, was der Besitzer lesen darf, und enthielten sich bei
allen zehn. Er zeigt damit den Stand mit Klassifikator, aber ohne Nachbarn. Im zweiten Durchgang
gehörten die zehn dem Hauptnutzer des Bestands (Upload im Auftrag), wie im Betrieb.

| | M13 (ein Signal) | M15, Klassifikator ohne Nachbarn | M15, Klassifikator und Nachbarn |
| --- | --- | --- | --- |
| grün | 1 | 3 | 1 |
| gelb | 9 | 7 | 9 |
| rot | 0 | 0 | 0 (einmal vorübergehend: Groq 429) |
| falsch grün | 0 | 0 | 0 |

## Je Feld (Wert, sonst Vorschlag, gegen Paperless)

| Feld | M13 | ohne Nachbarn: richtig / grün / grün und falsch | mit Nachbarn: richtig / grün / grün und falsch |
| --- | --- | --- | --- |
| Kontakt | 2 von 10 | 10 / 7 / 0 | 10 / 7 / 0 |
| Dokumenttyp | 8 von 10 | 8 / 6 / 0 | 9 / 5 / 0 |
| Dokumentdatum | 5 von 10 | 5 / 9 / 4 | 5 / 9 / 4 |
| Tags | 1 von 3 | 8 / – / – | 8 / – / – |

Tags machen nie gelb; „richtig“ heißt hier: gesetzte gleich Paperless (auch beide leer).

**Datum:** Die vier grünen Abweichungen sind keine falschen Werte. Papiq nimmt das Ausstellungsdatum,
wie der Prompt es verlangt, und es steht jeweils im Text; Paperless' „erstellt“ folgt einer anderen
Gewohnheit: ein Kontoauszug mit dem Tag seiner Erstellung statt dem Ende des Zeitraums (+8 Tage),
ein Spendennachweis mit dem Briefdatum statt dem Tag der Zuwendung (+366 Tage), zweimal +1 Tag
(einmal steht Paperless' Datum gar nicht im Text, der aus M13 bekannte Versatz).

**Kontakt:** Der größte Fortschritt. In M13 scheiterte er an buchstabengenauen Namen; jetzt ist er
zehnmal richtig (als Wert oder Vorschlag), siebenmal grün, davon einmal allein über Kennungen
(drei Mail-Domains des Kontakts) und die Nachbarn, ohne dass das Modell ihn nannte.

## Gründe für Gelb (mit Nachbarn, Namen maskiert)

| Paperless-ID | Knoten | Grund | Bewertung |
| --- | --- | --- | --- |
| 1059 | judge | Typ: die Signale widersprechen sich (Modell gegen 3 von 5 Nachbarn) | Paperless beschriftet ähnliche Briefe uneinheitlich; vertretbar |
| 1275 | judge | Typ: die Signale widersprechen sich (Modell gegen 5 von 5 Nachbarn) | Paperless führt den Kontoauszug als „Dokument“, die Nachbarn folgen der Gewohnheit, das Modell sagt „Kontoauszug“; richtig gelb |
| 1548 | judge | Kontakt: die Signale widersprechen sich (Modell und Name im Text gegen 5 von 5 Nachbarn) | Gleichförmiges Formular: die ähnlichen Dokumente sind Bescheinigungen eines anderen Absenders. Die Nachbarn sagen hier etwas über das Formular, nicht über den Absender; unnötiges Gelb |
| 1827 | judge | Kontakt: der Empfänger ist der Kontakt; Typ: nur ein Signal; kein Datum | Das Modell nannte den Empfänger als Absender; richtig gelb |
| 1877 | judge | Typ: nur ein Signal nennt ihn (Klassifikator kennt ihn, 0,77 für einen anderen) | Schwelle 0,8 knapp verfehlt; Kalibrierung (M18) |
| 1961 | fields | ASN: kein gültiger Wert (Zahl) | Das Modell schrieb eine andere Nummer der Rechnung ins optionale Feld; nach der Regel gelb. ASN ist Paperless' Archivnummer und steht nie im Text |
| 1980 | judge | Kontakt: der Absender des Modells ist kein Kontakt, nur andere Signale zeigen auf einen | richtig gelb (Vorschlag stimmt) |
| 384 | fields | Lohnbeträge: die Währung EUR steht nicht im Text | Die Abrechnung druckt Beträge ganz ohne Währung; der Betrag selbst stimmt |
| 620 | judge | Typ: die Signale widersprechen sich (Modell gegen 4 von 5 Nachbarn) | wie 1059 |

Ohne Nachbarn waren 1548 und 1877 grün; 1059 und 620 waren dort gelb, weil nur ein Signal den Typ
nannte.

## Lernregel der Kennungen

Die Regel „in mindestens zwei bestätigten Dokumenten, alle eines Kontakts“ lernt auch Fremdes:
Gegenkonten auf Kontoauszügen (eine Bank mit 10, eine mit 5 IBANs) und verlinkte Domains. Eine
zusätzliche Anteilsregel hätte das eingeschränkt:

| Regel | gelernt | davon IBANs |
| --- | --- | --- |
| heute | 169 | 37 |
| und in mindestens ¼ der Dokumente des Kontakts | 98 | 20 |
| und in mindestens ½ | 59 | 7 |

Gemessen an den zehn: Jede Kennung, die die Fakten fanden, gehörte zum richtigen Kontakt; keine
falsch gelernte erzeugte einen Widerspruch. Die Anteilsregel hätte dagegen genau die Belege
gestrichen, die halfen (die drei Domains, über die ein Kontakt grün wurde, stehen in 4 bis 6 % der
Dokumente ihres Kontakts). Empfehlung: die heutige Regel behalten; ein Admin verwirft falsch
gelernte im Kontaktdialog.

## Befunde für den Betrieb

- **Der Worker bedient die Indexierung vor der Pipeline.** Nach einem großen Abgleich (hier 1200
  Index-Jobs, über den NUC 0,4 je Sekunde) warten neue Uploads, bis der Index durch ist.
- **Groq-Limit:** 7000 Eingabe-Token je Minute; zehn Uploads auf einmal überschreiten es, ein
  Dokument wurde nach drei Versuchen rot und beim Wiederholen gelb.
- **Nachbarn ohne Mindestähnlichkeit:** Die fünf ähnlichsten Dokumente stimmen ab, auch wenn sie
  nur das Formular teilen (Ähnlichkeit um 0,7).

## Entscheidungen (Tobi, 14.10.2026)

- **Nachbarn:** bleiben, wie sie sind (ein Widerspruch ist gelb); wie stark ähnliche Dokumente
  widersprechen dürfen (Mindestähnlichkeit, gleichförmige Formulare), kalibriert M18 am
  Rückkopplungsmaß.
- **Beträge ohne jede Währung im Text:** in der Standardwährung (`LEKTO_DEFAULT_CURRENCY`, EUR).
  Umgesetzt; die Lohnabrechnung (384), ab `fields` neu verarbeitet ohne Modellaufruf, ist jetzt
  grün. Mit Nachbarn stehen damit 2 grün und 8 gelb.
- **Felder „nur von Hand“** (wie die Archivnummer): als Idee vorgemerkt, Issue #52.
- **Lernregel der Kennungen:** bleibt.

## Fertig-Kriterium

„Über neun von zehn Gelb hinaus, ohne ein falsches Grün“: mit Klassifikator ohne Nachbarn erfüllt
(3 grün, kein falsches Grün), mit Klassifikator und Nachbarn nicht (1 grün, wie M13), weil die
Nachbarn dreimal dem Modell widersprechen und einmal einen Typ abdecken, ohne ihn zu nennen. Falsch
grün wurde in keinem Durchgang etwas. Offene Entscheidungen: wie stark ähnliche Dokumente
widersprechen dürfen (etwa nicht gegen den Namen im Text und das Modell beim Kontakt, oder erst ab
einer Mindestähnlichkeit), Beträge ohne jede Währung im Text, und Felder, die das Modell nie lesen
soll (wie die Archivnummer).

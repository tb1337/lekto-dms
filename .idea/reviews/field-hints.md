# Felder mit Beschreibung: Messung an der Devinstanz

Datum: 2026-10-14. Branch `feature/field-hints-0.2.0`. Keine Titel, Namen oder Beträge in diesem Bericht; die Dokumente stehen als laufende Nummer der Liste unten (1–37), Gründe ohne Werte.

## Anlass

Tobi: Dokumente werden oft gelb, weil die Feldnamen (`LA_Brutto`, `LA_Netto`) intern sind und so auf keinem Dokument stehen. In der Devinstanz (52 Dokumente, alle bestätigt) waren 37 Lohnabrechnungen mit 74 Feldprüfungen betroffen. Kein Prüfschritt sucht den Feldnamen im Text. 70 der 74 Prüfungen scheiterten am Zitat („the quoted passage does not appear in the text“):
- Das Modell setzte Beschriftung und Wert aus verschiedenen Stellen zusammen (auf Formularen mit Kästen steht der Betrag Zeilen unter der Beschriftung).
- Es schrieb Beträge im Zitat um (Punkt statt Komma).

## Aufbau

- **Kopie der Devinstanz:** Datenbank `papiq_measure` (Dump von `papiq_live`, auf Revision 0017 gebracht), Texte aus dem Bucket nur gelesen. In der Devinstanz wurde nichts geändert.
- **Skript im Scratchpad:**
  - Es fragt das Modell wie der Sprachmodell-Knoten (`propose_message`, `propose_schema`, `parse_propose`) und prüft wie der Felder-Knoten (`_check_field`, ab Lauf C auch `_readable`).
  - Verglichen wird mit den bestätigten Werten.
  - Es schreibt nichts, weder Protokoll noch Modellanfragen.
- **Beschreibungen** (Entwurf, von Tobi anzupassen):
  - LA_Brutto: das Gesamtbrutto des Monats, bei Auszubildenden die Ausbildungsvergütung, nicht das Grundgehalt und nicht Steuer- oder SV-Brutto.
  - LA_Netto: das gesetzliche Netto des Monats, nicht der überwiesene Betrag, wo er abweicht.
- **Modelle:**
  - Groq `qwen/qwen3.8-27b`, bis das Tageskontingent (200.000 Token, derselbe Schlüssel wie die Devinstanz) nach 45 Dokumenten verbraucht war.
  - Danach `anthropic.claude-sonnet-5-5` über Open WebUI, höchstens 15 Dokumente je Lauf (Tobi).

## Läufe

| | A: alter Stand | B: neuer Prompt, Prüfungen A und B | C: dazu eigene OCR und schwach gelesene Seiten |
| --- | --- | --- | --- |
| Modell | Groq | Sonnet 5.5 | Sonnet 5.5 |
| Prompt | `propose-1`, ohne Beschreibung | `propose-2`, mit Beschreibung | `propose-2`, mit Beschreibung |
| Text | alte OCR-Schicht (ecoDMS) | alte OCR-Schicht | eigene OCR (`--redo-ocr`) |
| Dokumente grün | 0 von 15 | 10 von 15 | 10 von 15 |
| Felder grün | 1 von 30 | 24 von 30 | 20 von 30 |
| Wert wie bestätigt | 22 von 30 | 24 von 30 | 25 von 30 |
| grün, anders als bestätigt | 1 | 3 | 2 |
| gelb: Zitat nicht im Text | 27 | 0 | 0 |
| gelb: Zitat zeigt den Wert nicht | – | 3 | 1 |
| gelb: Wert nicht gefunden | 2 | 3 | 0 |
| gelb: Seite schwach gelesen | – | – | 9 |

Die 15 Dokumente:
- die drei zerfallenen Scans (4, 5, 8);
- die drei mit fraglicher Bestätigung (2, 13, 32);
- zwei Fehllesungen des alten Laufs (19, 27);
- sieben unauffällige (1, 3, 6, 7, 10, 20, 25).

Lauf A mit allen 37 Dokumenten: 0 grün, 70 von 74 Feldern am Zitat gescheitert, 60 Werte wie bestätigt. Der Modellwechsel zwischen A und B macht den Vergleich unrein. Im Teillauf mit Groq und neuem Prompt (8 Dokumente, vor Prüfung A und B) waren alle 16 Felder grün.

**„Grün, anders als bestätigt“** sind in B und C nur die fraglichen Bestätigungen:
- zweimal Netto, wo die Bestätigung den Bruttobetrag trägt;
- einmal Brutto aus der Reihe der fünf Korrekturen, die Brutto auf den Nettobetrag setzten.

Das Modell las dort das, was auf dem Dokument steht. Tobi prüft diese Bestätigungen.

## Befunde

1. **Falsches Grün im Teillauf mit Groq (Dokument 8, zerfallener Scan):** Das Modell zitierte nur die Beschriftung und machte aus einer einzelnen Zahl zehn Zeilen tiefer den Betrag. Die Prüfung verlangte nur, dass das Zitat irgendwo im Text steht und der Wert irgendwo sonst.
   - Prüfung A (das Zitat muss den Wert zeigen) und B (ein Betrag zählt nur als Betrag, mit Nachkommastellen oder Währung) schließen das.
   - In Lauf B fingen sie zweimal ein Zitat aus der bloßen Beschriftung ab, und einmal einen Betrag, dessen Komma die alte OCR verloren hatte. Der Wert war jeweils richtig, die Person bestätigt.
2. **Fremde OCR:** Die Lohnabrechnungen tragen die Textschicht von ecoDMS („pdf to searchable pdf“, 2020). `--skip-text` behielt sie, Tesseract las diese Seiten nie, und deshalb gab es keine Lesung je Seite. Dokument 8 stammt mit seinem zerfallenen Text aus dieser Schicht. Mit `--redo-ocr` liest Papiq solche PDFs selbst (Tobi). Die Lesungen der 37 Dokumente:
   - 32 haben 2–7 % unsichere Wörter;
   - 5 haben 8–15 % (die drei zerfallenen Scans, Dokument 27 mit 8,2 %, Dokument 32).
3. **Schwach gelesene Seiten (Lauf C):** Die fünf Dokumente ab 8 % werden gelb.
   - Auf Dokument 5 las die eigene OCR „£“ statt „€“: Die Prüfung allein hätte den Betrag in Pfund grün gemacht.
   - Auf den anderen vier war der Wert richtig: Das kostet die Person eine Bestätigung je Dokument.
   - Auf Dokument 27 las die alte Schicht „39,25“, wo „239,25“ steht; die eigene OCR liest es richtig.
4. **Die Sicherheit je Wort hilft nicht:** Tesseract war sich bei der Fehllesung zu 96 % sicher. Darum zählt die Seite.
5. **Lange Zeilen im Layout-Text:** Mit der Zeile des Werts zitiert das Modell auch fremde Beschriftungen derselben Zeile. Dass die Beschriftung beim Wert steht, prüft niemand: Issue #55.
6. **Sonnet 5.5 und die Schnittstelle:**
   - Es lehnt `temperature` ab (jetzt `PAPIQ_LLM_TEMPERATURE=none`).
   - Es lehnt `enum` unter einer Typliste mit `null` ab, und `maxItems`. Die Schemas schreiben jetzt `anyOf`, ohne Grenzen für Listen.

## Grenzen

- **Schwellwert:** Die Vorgabe von 8 % beruht auf 37 Lohnabrechnungen zweier Layouts; zwischen 7,4 % (gut) und 8,2 % (Dokument 27) liegt wenig. Die Kalibrierung gehört zu M18.
- **Beschreibungen:** Es sind Entwürfe. Tobi setzt die eigenen in der Feldverwaltung.
- **Bestand:** Er profitiert von der eigenen OCR erst nach „ab OCR neu verarbeiten“. Das fragt das Modell erneut und kann bestätigte Werte ersetzen, darum nur gezielt.

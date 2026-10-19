# Ingest-Neuauflage: Zielbild und Entscheidungen

Stand: 13.10.2026 · Tobi (Entscheidungen) und Creamy (Vorschlag)

Dieses Dokument beschreibt, wie die Verarbeitung eines Dokuments nach 0.1 aussehen soll. Phase 1
(M14) und Phase 2 (M15) sind umgesetzt; ihren Stand beschreibt der Abschnitt „Ingest-Workflow“ in
`architektur.md`, der dafür gilt. Die Entscheidungen am Ende hat Tobi am 12.10.2026 getroffen,
die Lesarten am 13.10.2026 bestätigt oder ersetzt (siehe dort).

## Ist-Stand und Befund

Sieben feste Schritte, streng linear, je ein Job mit Wiederholung: Empfangen → OCR (OCRmyPDF,
Archiv-PDF/A) → Parsen (Docling auf der Textschicht) → Klassifizieren (ein LLM-Aufruf, nur
Text) → Felder (zweiter Aufruf, nur Text) → Regeln → Ablegen. Die Lane ist das schlechteste
Schrittergebnis (`core/domain/pipeline.py`, `core/services/classification/steps.py`).

Was bleibt:

- Konfidenz aus prüfbaren Fakten statt Selbsteinschätzung des Modells, Belegzitate, Schutz vor
  Anweisungen im Text, alles im Verarbeitungsprotokoll nachvollziehbar.
- Die Job-Mechanik: Idempotenz, Leihe, Wiederholung, „ab Schritt X neu“, ein Ergebnis je
  Transaktion.
- Das Archiv-PDF/A mit Textschicht.

Wo es hakt (`reviews/M13-lanes.md`, zehn Originale):

- Neun von zehn Dokumenten gelb. Kontakt 2 von 10, Typ 8 von 10, Datum 5 von 10. Hauptgrund: ein
  einziges Signal, der vom Modell gelesene Name, muss buchstabengenau gegen Stammdaten und Text
  bestehen.
- Kein Lernen aus Bestätigungen außer Kontakt-Aliasen; 1500 übernommene Dokumente mit
  Paperless-Metadaten liegen als Wissen brach.
- OCR ist reines Tesseract; die Layoutanalyse sieht nur die Textschicht. Das Modell sieht nie die
  Seite, nur gekürzten Text (12 000 Zeichen): Stempel, Logos, Handschrift, Formulare gehen
  verloren.
- Globale Felder werden aus jedem Dokument gezogen (Befund 1 in M13). Deutsche Beträge wie
  `2.111,68` scheitern an der Prüfung.
- Zwei Modellaufrufe je Dokument, lokal 3 bis 10 Minuten.
- Die Docling-Struktur (Seite und Box je Textblock) wird gespeichert und von niemandem gelesen.

## Zielbild: ein Graph aus Knoten

Die Verarbeitung ist ein gerichteter azyklischer Graph (DAG). Jeder Knoten ist ein Job mit der
heutigen Mechanik; Knoten ohne Abhängigkeit voneinander laufen parallel. Die Lane bleibt das
schlechteste Ergebnis der entscheidenden Knoten.

```
receive ─┬─► pages ──────────┐
         └─► archive ──► read ├─► signal.llm ────────┐
                              ├─► signal.classifier ─┤
                              ├─► signal.neighbours ─┼─► judge ─► fields ─► rules ─► file
                              └─► signal.facts ──────┘
```

| Knoten | Aufgabe | Eingabe | Ergebnis |
| --- | --- | --- | --- |
| `receive` | Hash, Dublette, Original in den Objektspeicher (wie heute) | Datei | Dokument, Original |
| `pages` | Seitenbilder rendern (PDFium, WebP, etwa 100 KB je Seite) | Original | Derivat `pages/<n>.webp` |
| `archive` | OCRmyPDF: PDF/A mit Textschicht (wie heute) | Original | Derivat Archiv |
| `read` | Lesung: Markdown und Struktur mit Provenienz (Seite, Box) | Archiv, Seitenbilder | Derivate Markdown, Struktur; Qualitätsmaß |
| `signal.llm` | Vorschlag des Sprachmodells mit Zitaten: Kontakt mit Rolle, Typ, Tags, Datum, Titel, Sprache; bei sicherem Typ dessen Felder gleich mit | Text, erste zwei und letzte Seite als Bild (wenn das Modell Bilder nimmt) | Kandidaten je Feld |
| `signal.classifier` | Klassischer Klassifikator wie in Paperless-ngx (Wort-n-Gramme, lineares Modell je Ziel) | Text, trainiertes Modell | Wahrscheinlichkeit je Klasse |
| `signal.neighbours` | Die k ähnlichsten bestätigten Dokumente über den Vektor; ihr Kontakt, Typ und ihre Tags stimmen ab | Text, Embeddings, Suchindex | Kandidaten mit Stimmen |
| `signal.facts` | Harte Beweise im Text: Namen und Aliase (heute), neu Kennungen je Kontakt (IBAN, USt-IdNr, Kundennummer, E-Mail-Domain) | Text, Stammdaten | Treffer je Kontakt |
| `judge` | Urteil je Feld aus allen Kandidaten mit Quellen; Grün-Regel unten | die vier Signale | Metadaten, Lane-Beitrag, gereihte Kandidaten mit Begründung |
| `fields` | Felder des entschiedenen Typs: Schema, Prüfung, Normalisierung, Zitat → Box | Text, Struktur, Typ | Werte mit Beleg |
| `rules` | Regeln (wie heute) | Metadaten | Änderungen, Schublade |
| `file` | Ablegen (wie heute) | | Lane |

Dazu ein Job außerhalb des Graphen: `train` trainiert den Klassifikator neu, nach N neuen
Bestätigungen, und legt das Modell versioniert im Objektspeicher ab.

**Lesung (`read`)** hat drei Betriebsarten per Konfiguration: `ocr` (Textschicht des Archivs,
wie heute), `vlm` (Docling-VLM-Pipeline: Seitenbilder → DocTags → Layout, Tabellen und Text in
einem Durchgang; lokal `granite-docling-258M` auf der CPU, oder entfernt über einen
OpenAI-kompatiblen Vision-Endpunkt) und `auto` (VLM nur bei schwacher Tesseract-Lesung: kein
Text, Bildseiten, hoher Müllanteil). Jede Lesung schreibt ein Qualitätsmaß ins Protokoll (Zeichen,
Wortanteil, Seiten ohne Text), damit `auto` und die Bewertung etwas zu messen haben. Keine
LLM-Nachkorrektur des Tesseract-Textes: sie erfindet Text und bricht die Belegprüfung.

**Urteil (`judge`)**: Kandidaten je Feld mit ihren Quellen werden zusammengeführt. Die Begründung
steht im Protokoll und in der Prüfansicht, etwa „Modell: Beispielbank AG (Zitat); Klassifikator
0,94; 3 von 3 ähnliche Dokumente“. Ohne trainiertes Modell (Kaltstart) gilt die heutige Regel.
Optional eine Eskalation: bei Widerspruch ein zweiter Aufruf mit den Kandidaten an ein stärkeres
Modell (Phase 5).

**Rückkopplung**: Jede Entscheidung einer Person (Posteingang, spätere Änderung) ist ein
Trainingsbeispiel, lernt Aliase (heute) und Kennungen (neu). Ein Maß je Feld, der Anteil der
automatisch grünen Werte, die später korrigiert wurden, steht im Bericht und hebt die Schwelle,
wenn es zu hoch liegt.

## Sichtbarkeit in der Web-UI (Tobi, 12.10.2026)

Die UI zeigt genau, wo im Graphen gearbeitet wird, und jedes Zwischenergebnis, sobald es
vorliegt:

- Der Graph des Dokuments mit dem Zustand je Knoten: wartet, läuft, fertig (ok, unsicher,
  fehlgeschlagen), mit Dauer. Nicht nur der nächste Schritt wie heute.
- Erkannter Text sofort nach `read`, Seitenbilder sofort nach `pages`, auch während die
  Signale noch laufen.
- Je Signal seine Kandidaten mit Quelle, sobald es fertig ist; nach `judge` die Entscheidung
  je Feld mit Begründung; nach `fields` jeder Wert mit Zitat und Box auf der Seite.
- Das Hochladefenster zeigt den Fortschritt nach Knoten, nicht nur „wird verarbeitet“.

Dafür braucht es im Backend: Zustand je Knoten am Dokument (`GET /documents/{id}`), Ereignisse
`document.node_started` und `document.node_completed` über SSE, Zwischenergebnisse als
abrufbare Ressourcen (Text und Seiten) und die Kandidaten der Signale in der Prüfansicht. Die
Idee „Live-Verarbeitungsstand beim Upload“ aus `umsetzungsplan.md` geht hierin auf.

## Grün-Regel (Lesart von Entscheidung 4, bestätigt 13.10.2026)

Tobi: nicht hundertprozentig sicher heißt kein Grün; Kontaktnamen auf Dokumenten weichen vom
Stammdatennamen ab, der Abgleich ist nicht wörtlich.

- **Kontakt** ist grün, wenn (a) ein harter Beweis vorliegt, eine Kennung des Kontakts oder
  sein Name oder Alias im Text, und (b) kein vorhandenes Signal widerspricht. Ohne harten Beweis
  reicht ein Namensabgleich mit Normalisierung (Rechtsform, Satzzeichen, Groß- und
  Kleinschreibung, Wortanteil ab Schwelle) **plus** ein zweites unabhängiges Signal, das denselben
  Kontakt nennt (Klassifikator über Schwelle oder Mehrheit der Nachbarn). Nur ein Signal, auch ein
  starkes, bleibt gelb mit gereihten Kandidaten.
- **Typ und Tags** sind grün, wenn mindestens zwei unabhängige Signale denselben Wert nennen
  und keines widerspricht; der Typ nur aus der bestehenden Liste (wie heute). Kaltstart je Wert:
  Deckt außer dem Modell kein Signal den Wert ab (der Klassifikator kennt ihn nicht, kein
  bestätigtes Dokument trägt ihn), genügt das Modell. Tags machen nie gelb: Nennt nur ein Signal
  einen Tag, den ein anderes abdeckt, ist er ein Vorschlag (Tobi, 13.10.2026).
- **Datum und Felder** wie heute: der Wert muss im Text stehen und gültig sein; neu die
  Normalisierung deutscher Zahlen und Daten vor der Prüfung.
- **Widerspruch** zwischen Signalen ist immer gelb, mit allen Kandidaten und ihren Quellen, auch
  gegen einen Wert, den das widersprechende Signal nicht kennt (sonst bliebe der Lohnnachweis
  grün, dessen Angestellten das Modell für den Absender hält).
- Ein automatisch grüner Kontakt lernt **keinen** Alias; Aliase lernen weiterhin nur aus
  Bestätigungen einer Person (Entscheidung vom 10.10.2026). Bestätigt 13.10.2026.
- Kaltstart ohne Klassifikator und ohne Nachbarn: die heutige Regel (Name oder Alias im Text).

## Entscheidungen (Tobi, 12.10.2026)

1. **Modelle und Endpunkte:** `chat.tbsch.me` ist OpenWebUI mit Ollama auf dem NUC, Groq und
   Claude dahinter. Folge: Lekto spricht einen OpenAI-kompatiblen Endpunkt, der Modellname wählt
   den Anbieter; Text- und Vision-Modell werden getrennt konfiguriert
   (`LEKTO_LLM_MODEL`, `LEKTO_LLM_VISION_MODEL`), die Lesung ihr eigenes (`LEKTO_READ_VLM_MODEL`).
   Zu prüfen in Phase 3: ob OpenWebUIs API Bilder an Claude und Groq durchreicht, und wie schnell
   `granite-docling-258M` auf dem NUC ist.
2. **scikit-learn:** ja, als Abhängigkeit eines Adapters hinter einem neuen Port `Classifier`;
   der Kern bleibt reines Python.
3. **Trainingsdaten:** übernommene Dokumente (Kanal `migration`) zählen als bestätigt und
   trainieren von Anfang an. Lesart: Trainingsbeispiele sind Dokumente, deren Metadaten eine
   Person gesetzt oder bestätigt hat, die Übernahme eingeschlossen; automatisch grüne Dokumente
   trainieren nicht, sonst verstärkt der Klassifikator seine eigenen Fehler. Bestätigt
   13.10.2026.
4. **Grün-Regel:** siehe oben.
5. **Globale Felder:** Lesart von „ja“: Ein Feld wird nur extrahiert, wenn der entschiedene Typ
   es führt. Globale Felder werden nicht mehr aus jedem Dokument gezogen; sie bleiben für Hand
   und Regeln. **Ersetzt (Tobi, 13.10.2026):** Felder sind Pflicht oder optional, je Zuordnung zu
   einem Typ, globale mit eigenem Schalter, nach der Übernahme alle optional. Pflichtfelder
   müssen erkannt werden; optionale sollten, müssen aber nicht. Auch ein optionales Feld muss,
   wenn das Modell einen Wert nennt, richtig gelesen sein, sonst gelb; wird nichts gefunden,
   bleibt es leer.
6. **Schublade:** Der Klassifikator schlägt keine Schublade vor. Schubladen tragen Rechte; sie
   sind kein Speicherpfad wie in Paperless. Ablegen bleibt bei Regeln und Personen.
7. **Titel:** Das Modell schlägt den Titel vor, wenn keine Regel ihn setzt (heute der
   Dateiname). Neu je Dokumenttyp ein optionales **Titelmuster**, etwa `{datum:YYYY}/{datum:MM}`
   für Lohnnachweise, mit Platzhaltern für Datum, Kontakt und Felder des Typs. Vorschlag: Hat
   der Typ ein Muster, wird der Titel daraus gerendert und nicht vom Modell vorgeschlagen; das
   Modell liefert nur die Werte. Bestätigt 13.10.2026; Regeln können den Titel weiter setzen.
   Die Platzhalter sind englisch wie bei der Regel „Titel setzen“, etwa
   `{document_date:YYYY}/{document_date:MM}`.
8. **Struktur:** ein Graph mit einem Job je Knoten (DAG), dazu die Sichtbarkeit in der UI wie
   oben.
9. **Reihenfolge der Phasen:** Empfehlung unten.

## Was sich ändert

**Kern**

- `Step` (sieben Werte in fester Reihenfolge) wird zu `Node` mit Kanten (`PIPELINE_GRAPH`);
  `Processing` hält den Zustand je Knoten (wartet, läuft, Ergebnis) statt `current_step`.
  „Ab Knoten X neu“ setzt X und alle Nachfolger zurück. Lanes und `Outcome` bleiben.
- Protokoll je Knoten, wie heute je Schritt; die Signale schreiben ihre Kandidaten als Ausgabe.
- Neue Services: Signale, Urteil, Training; die Klassifizierung von heute geht im Modell-Signal
  auf.
- Stammdaten: Kennungen je Kontakt (Art, Wert; eindeutig über alle Kontakte), Titelmuster je
  Dokumenttyp.

**Ports und Adapter**

| Port | Änderung | Adapter |
| --- | --- | --- |
| `DocumentParser` | Betriebsart `vlm`, Struktur mit Provenienz als Ergebnis | `docling` (VLM-Pipeline, entferntes Modell) |
| `PreviewRenderer` → `PageRenderer` | alle Seiten statt nur der ersten | `pdfium` |
| `LanguageModel` | Bilder in der Anfrage | `openai_compat` |
| `Classifier` (neu) | `train(examples) -> model`, `predict(model, text) -> Wahrscheinlichkeiten` | neu `sklearn`; In-Memory-Adapter und Vertragstest |
| `SearchIndex` | ähnliche Dokumente zu einem Vektor | `meilisearch` (`/similar`), `memory` |

**API und UI**

- `GET /documents/{id}`: Zustand je Knoten; `GET /documents/{id}/pages/{n}`: Seitenbild;
  `GET /documents/{id}/review`: Kandidaten je Signal mit Quellen und Begründung.
- Ereignisse `document.node_started`, `document.node_completed`.
- Stammdaten: Kennungen am Kontakt, Titelmuster am Typ. Verwaltung: Stand des Klassifikators,
  Training anstoßen.
- Prüfansicht: Graph, Zwischenergebnisse, Zitat → Box auf der Seite.

**Einstellungen (neu):** `LEKTO_READ_MODE` (`ocr`, `vlm`, `auto`), `LEKTO_READ_VLM_MODEL`,
`LEKTO_LLM_VISION_MODEL`, `LEKTO_LLM_PAGES` (Seitenbilder je Anfrage), `LEKTO_PAGE_WIDTH`,
`LEKTO_CLASSIFIER_MIN_EXAMPLES`, `LEKTO_CLASSIFIER_RETRAIN_AFTER`, `LEKTO_CLASSIFIER_THRESHOLD`,
`LEKTO_NEIGHBOURS`.

**Daten:** neue Derivate (Seitenbilder), Tabellen `contact_identifiers` und
`classifier_models` (Version, Zeitpunkt, Anzahl Beispiele, Objektschlüssel), Spalte
`title_pattern` an `document_types`; Alembic-Revisionen dazu.

**Dokumente:** `architektur.md` nimmt „Kein maschinelles Lernen wie in Paperless“ (10.10.2026)
zurück; der Abschnitt „Ingest-Workflow“ wird nach der Umsetzung durch dieses Zielbild ersetzt.
Der Bewertungssatz bekommt Seitenbilder und einen Trainingskorpus; der Bericht zählt Lanes je
Feld und das Rückkopplungsmaß.

## Phasen und Empfehlung zur Reihenfolge (Entscheidung 9)

Empfehlung: zuerst der Graph, dann die Signale. Die Sichtbarkeit in der UI hängt am Zustand je
Knoten; Signale erst als Stufe zu bauen und später in Knoten zu zerlegen wäre doppelte Arbeit.
Der Umbau auf den Graphen ändert kein Verhalten, nur die Form, und ist mit dem heutigen
Bewertungssatz prüfbar.

| Phase | Meilenstein | Inhalt | Nutzen für sich |
| --- | --- | --- | --- |
| 1 | M14 | Graph: Knoten, Kanten, Zustand je Knoten, Ereignisse, „ab Knoten X neu“; die sieben Schritte werden Knoten ohne neue Logik; UI zeigt Graph und Text sofort nach der Lesung; Hochladefenster nach Knoten | Sichtbarkeit; Grundlage für alles Weitere |
| 2 | M15 | Verstehen: Kennungen, Klassifikator (scikit-learn, Training aus Übernahme und Bestätigungen), Nachbarn, ein Modellaufruf; Urteil mit der Grün-Regel; Titelmuster; Felder nur je Typ; Normalisierung deutscher Zahlen; Bericht je Feld | greift das Neun-von-zehn-Gelb direkt an |
| 3 | M16 | Lesen: Seitenbilder, Betriebsart `vlm` und `auto`, Qualitätsmaß, Bilder im Modellaufruf; Messung von granite-docling auf dem NUC und der Vision-Modelle über OpenWebUI | bessere Lesung von Scans, Stempeln, Formularen |
| 4 | M17 | Grounding: Zitat → Box auf der Seite in der Prüfansicht, Seitenansicht mit Hervorhebung | schnellere Prüfung |
| 5 | M18 | Eskalation bei Widerspruch an ein stärkeres Modell; Kalibrierung der Schwellen am Rückkopplungsmaß | weniger Gelb ohne mehr Falsch-Grün |

Die Meilensteine stehen im `umsetzungsplan.md`; jeder beginnt mit einem Plan und endet mit einem
Review durch einen separaten Agenten.

## Offen

- OpenWebUI: Bilder über die API an Claude und Groq (Phase 3 misst es).
- `granite-docling-258M` auf der CPU des NUC: Laufzeit je Seite (Phase 3 misst es).
- Kennungen in der Übernahme aus Paperless: dort gibt es sie nicht; sie entstehen aus
  Bestätigungen oder von Hand.

## Quellen

- Paperless-ngx-Klassifikator: https://github.com/paperless-ngx/paperless-ngx/blob/dev/src/documents/classifier.py, https://docs.paperless-ngx.com/usage/#automatic-matching
- Docling VLM-Pipeline und entfernte Modelle: https://docling-project.github.io/docling/usage/vision_models/, https://docling-project.github.io/docling/examples/vlm_pipeline_api_model/
- granite-docling: https://huggingface.co/ibm-granite/granite-docling-258M
- Docling-Provenienz: https://docling-project.github.io/docling/concepts/docling_document/
- Meilisearch, ähnliche Dokumente: https://www.meilisearch.com/docs/reference/api/similar
- OpenWebUI-API: https://docs.openwebui.com/getting-started/api-endpoints/
- Bilder über Ollamas OpenAI-kompatible API: https://github.com/ollama/ollama/blob/main/docs/openai.md
- scikit-learn: https://scikit-learn.org/stable/

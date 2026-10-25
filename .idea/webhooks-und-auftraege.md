# Webhooks und Aufträge: Zielbild und Entscheidungen

Stand: 25.10.2026 · Tobi (Entscheidungen) und Creamy (Vorschlag)

Dieses Dokument beschreibt, wie Lekto mit Systemen außerhalb spricht: Webhooks, die mehr
können als heute, Regeln, die Webhooks senden und fragen, und Modellaufrufe, die ein externer
Dienst übernimmt. Nichts davon ist umgesetzt; die Phasen stehen am Ende und im
`umsetzungsplan.md` (M19–M21). Bis zur Umsetzung gelten `architektur.md` und der Code; die
Abschnitte dort, die sich ändern, verweisen hierher. Die Entscheidungen hat Tobi am 25.10.2026
im Gespräch getroffen (Liste am Ende).

## Anlass

1. Wer etwas Besseres bauen will als Lekto, soll die Schritte selbst übernehmen können, die an
   ein Sprachmodell gehen: den Vorschlag (`signal_llm`) und das Lesen der Felder (`fields`).
2. Home Assistant oder Node-RED sollen mit Lekto arbeiten können: über Ereignisse, die sie
   ohne zweiten API-Aufruf verstehen, und über Regeln, die gezielt melden und nachfragen.

Beides bildet Lekto über ein Konzept ab: den Webhook.

## Ist-Stand

Webhooks (M8, `core/domain/webhooks.py`, `core/services/webhooks/`):

- Jeder Nutzer legt eigene an; sie melden nur Dokumente in seiner Reichweite (auch bei Admins).
- Acht Dokumentereignisse: `document.received`, `node_started`, `node_deferred`,
  `node_completed`, `lane_changed`, `filed`, `updated`, `deleted`.
- Schlanker Body (`id`, `type`, `occurred_at`, `document_id`); Details holt der Empfänger per
  API mit eigenem Token.
- Signiert nach Standard Webhooks (HMAC-SHA256), Wiederholung mit wachsendem Abstand,
  Zustellprotokoll, Abschalten nach wiederholten Fehlern, „Test senden“. Die Antwort des
  Empfängers wird nicht gelesen.

Was fehlt: Home Assistant prüft keine Signatur und liest den Body als `trigger.json`; Node-RED
legt ihn in `msg.payload`. Mit dem schlanken Body haben beide nichts in der Hand (kein Titel,
kein Betrag), filtern lässt sich nur nach Ereignistyp, und eine Antwort kann Lekto nicht
verwenden.

## Zielbild

### Webhook: ein Endpunkt

Ein Webhook ist die Konfiguration eines Endpunkts; ob er meldet oder fragt, entscheidet, wer ihn
verwendet.

| Eigenschaft | Inhalt |
| --- | --- |
| Name, URL | wie heute (`http`/`https`, keine Zugangsdaten in der URL) |
| Header | frei wählbar, Name und Wert (`Authorization: Bearer …`, `X-Tenant`); verschlüsselt gespeichert wie das Geheimnis, nach dem Speichern nur die Namen sichtbar. Gesperrt: `webhook-*`, `lekto-*`, `content-type`, `content-length`, `host`, dazu `connection` und `transfer-encoding` (setzt HTTP selbst); Namen nach RFC 9110, Werte druckbares ASCII ohne Steuerzeichen, Leerzeichen nur innen |
| Geheimnis | optional; ist eines gesetzt, signiert Lekto nach Standard Webhooks wie heute |
| Body | `thin` (schlank, wie heute), `full` (voll, festes JSON) oder `template` (Liquid erzeugt JSON) |
| Ereignistypen | optional; ohne Ereignistyp dient der Webhook nur Regeln und Aufträgen |
| Offene Aufträge | höchstens N gleichzeitig (Vorgabe 4, 1 bis 64); weitere warten in Lekto, ihre Frist beginnt beim Versand |
| Modellaufruf | nur an Webhooks von Admins: dient als `propose` oder `extract`; je Art höchstens einer aktiv |

Verwendungen:

| Verwendung | Art | Wer |
| --- | --- | --- |
| Ereignisse abonnieren | Benachrichtigung | jeder Nutzer, für Dokumente in seiner Reichweite |
| Regelschritt „Webhook senden“ | Benachrichtigung | der Autor der Regel |
| Regelschritt „Webhook fragen“ | Auftrag | der Autor der Regel |
| Modellaufruf `propose`, `extract` | Auftrag mit festem Vertrag | ein Admin; sieht jedes Dokument |

**Body `full`:** Ereignis (`id`, `type`, `occurred_at`, `document_id`) und das Dokument, wie es
bei der Zustellung ist: Titel, Kontakt, Typ, Thema, Tags, Datum, Space, Lane, Felder (Schlüssel
→ Wert in ihrer JSON-Form) und `link` (`LEKTO_PUBLIC_URL` + `/ui/documents/{id}`, ohne
`LEKTO_PUBLIC_URL` fehlt er). Bei `document.deleted` nur die ID.

**Body `template`:** ein Liquid-Template, das JSON ergibt (Renderer und Template-Editor der
Regeln). Es sieht, was Templates der Regeln sehen (`contact`, `document_type`, `field.<key>` …),
dazu `event` (`type`, `id`, `occurred_at`), `document_id`, `lane`, `link`, in Regeln `rule` und
`steps`, bei Aufträgen `task`. Werte werden mit einem Filter `json` sicher eingebettet. Ergibt
das Template kein gültiges JSON oder fehlt ein Wert, den es schreibt, ist die Zustellung
gescheitert (im Protokoll mit Grund, ohne Wiederholung).

**Zustellung:** wie heute über Jobs, mit Prüfung der Rechte vor jedem Versuch. Benachrichtigungen
schalten sich nach wiederholten Fehlern ab (wie heute); Webhooks, die Aufträge annehmen, nie:
Ihre Fehler wirken am Dokument (rot, gelb oder weiter, siehe unten). Globale Grenzen bleiben
Umgebungsvariablen mit dem Präfix `LEKTO_WEBHOOK_` (Zeitlimit, Wiederholungen, Anzahl je
Nutzer); neue globale Grenzen bekommen dasselbe Präfix.

### Ereignisse

Zu den acht von heute kommen:

| Ereignis | Wann |
| --- | --- |
| `document.review_required` | das Dokument wartet im Posteingang (gelb oder rot) |
| `document.confirmed` | eine Person hat es im Posteingang bestätigt |
| `document.moved` | es liegt in einem anderen Space (verschoben, übergeben, durch eine Regel); `handed_over` sagt, ob es übergeben wurde |
| `document.node_delegated` | ein Knoten wartet auf Aufträge („Läuft extern“), mit Knoten, Lauf und Frist; abonnierbar wie `node_started` und `node_deferred` (Tobi, 25.10.2026) |

### Regeln: Schritte statt Aktionen

Eine Regel behält Auslöser, Bedingungen und Priorität. Ihre Aktionen werden eine geordnete
Folge von Schritten (höchstens 20, wie heute die Aktionen):

| Schritt | Aufgabe | Ergebnis |
| --- | --- | --- |
| Aktion | wie heute: Space, Kontakt, Typ, Thema, Titel, Tags, Feld setzen, Prüfung erzwingen | – |
| Webhook senden | Benachrichtigung über einen Webhook des Autors | – |
| Webhook fragen | Auftrag über einen Webhook des Autors; wartet auf die Antwort | `steps.<name>`: das JSON der Antwort |
| Bedingung | Bedingungen wie im Kopf der Regel, dazu Werte aus `steps`; ist sie falsch, endet die Regel hier | – |

Die Liste der Aktionen ist schon heute geordnet; bestehende Regeln bleiben gültig, ihre
Aktionen sind die ersten Schritte. Der Ablauf ist linear, ohne Verzweigung: Ein „sonst“ ist eine
zweite Regel.

```
Regel „Rechnung abgleichen“   Auslöser: Eingang · Bedingung: Typ ist Rechnung
 1. Webhook fragen „buchhaltung“   → Antwort {"bezahlt": true, "beleg": "B-4711"}
 2. Bedingung {{ steps.buchhaltung.bezahlt }} ist wahr
 3. Tag hinzufügen „bezahlt“
 4. Feld setzen „Belegnummer“ = {{ steps.buchhaltung.beleg }}
```

**Was ein Schritt sieht (Variante 2):** Jede Regel arbeitet auf einer eigenen Kopie des
Dokuments und sieht dort, was ihre früheren Schritte gesetzt haben (Body eines Auftrags,
Bedingungsschritte); andere Regeln sieht sie nicht. Am Ende werden die Aktionen aller Regeln
zusammengeführt wie heute (`rule_planner`): Konflikte machen gelb. Templates von Aktionen sehen
das Dokument weiter so, wie die Regeln es hinterlassen, dazu `steps`.

**Webhook senden:** beim Eingang und bei Änderungen (Body nach der Variante des Webhooks, Typ
`rule.send`, dazu `rule` mit ID und Namen). Beim Eingang geht die Nachricht erst hinaus, wenn das
Dokument abgelegt wird (Knoten `file`): Ein grünes sofort, ein gelbes erst nach dem Bestätigen,
ein rotes nie, und nichts doppelt, obwohl die Regeln nach dem Bestätigen noch einmal laufen
(Tobi, 25.10.2026). Bei Änderungen und beim rückwirkenden Anwenden geht sie hinaus, sobald das
Ergebnis gespeichert ist; rückwirkend je ausgewähltem Dokument, die Vorschau zeigt „sendet an …“
(Tobi, 25.10.2026). Die Zustellung wird in derselben Transaktion wie das Ergebnis eingereiht:
Home Assistant bekommt nie einen Stand, der danach nicht gilt.

**Webhook fragen:**

- Nur beim Eingang (Auslöser `ingest`); eine Regel mit einem solchen Schritt hat nur diesen
  Auslöser und lässt sich nicht auf bestehende Dokumente anwenden.
- Je Schritt: Name (Schlüssel, eindeutig in der Regel), Webhook, Frist (Vorgabe 5 Minuten),
  ohne Antwort: rot, gelb oder weiter (Vorgabe rot). „Weiter“ heißt: `steps.<name>` fehlt, die
  Regel läuft weiter. „Gelb“: Die Regel endet am Frageschritt, ihre Schritte davor gelten, das
  Dokument wartet im Posteingang. „Rot“: Der Knoten scheitert, keine Regel wirkt, wie bei jedem
  roten Knoten (Tobi, 25.10.2026).
- Bestätigen im Posteingang lässt die Regeln in einem neuen Lauf erneut laufen. Hat das
  Bestätigen nichts am Dokument geändert, fragt kein Schritt neu: Es gilt das Ergebnis des
  vorigen Laufs (die Antwort, oder dass keine kam). Hat es etwas geändert (Metadaten, Felder,
  übernommene Vorschläge, Space, korrigierter Typ), fragen die Schritte neu. Fehlt eine Antwort
  nach dem Bestätigen, wird das nur gemeldet, und die Regel läuft weiter wie bei „weiter“: Das
  Dokument hinge sonst im Posteingang fest. „Neu verarbeiten“ fragt immer neu (Tobi,
  25.10.2026).
- Der Knoten `apply_rules` steht dann auf „Läuft extern“. Fragen mehrere Regeln, gehen die
  Aufträge parallel hinaus; zusammengeführt wird, wenn alle Regeln fertig sind. Kommt das
  Dokument in einen anderen Space, laufen danach dessen Regeln (wie heute), die wieder fragen
  können.
- Die Antwort ist beliebiges JSON; handeln dürfen nur die Schritte der Regel. Verweist ein
  Template auf einen Pfad, den die Antwort nicht hat, tut die Aktion nichts, und das Protokoll
  sagt es (wie beim Titelmuster). Kein Schema für Antworten.
- Aktionen aus einer Antwort lösen keine weiteren Regeln aus (Schleifenschutz wie heute), außer
  dem Einzug in einen anderen Space.

**Rechte:** Eine Regel eines Space verwendet nur Webhooks ihres Autors (des zuletzt
Speichernden), eine globale nur Webhooks eines Admins. Vor jedem Senden und Fragen prüft Lekto,
ob der Besitzer des Webhooks das Dokument lesen darf; wenn nicht, greift der Schritt nicht, und
das Dokument wird gelb (beim Eingang) bzw. es wird gemeldet (bei Änderungen), wie heute bei
einer Regel, deren Autor ein Recht verloren hat. Hat eine Person im Lauf schon bestätigt, wird
ein solcher Schritt nur noch gemeldet (eine Person kann das Recht nicht herbeibestätigen; das
Dokument hinge sonst im Posteingang fest). Wird ein Webhook gelöscht, werden die Regeln, die ihn
verwenden, abgeschaltet, mit Grund, wie bei gelöschten Stammdaten.

**Bedingung:** Bedingungen wie im Kopf der Regel (mit Und/Oder-Gruppen), dazu Bedingungen auf
Werte aus `steps`: Pfad (`buchhaltung.bezahlt`), Operator (ist, enthält, größer, kleiner,
vorhanden, fehlt) und Wert (Tobi, 25.10.2026).

**Probelauf:** zeigt „sendet an …“ und „fragt …“; die Antwort kennt Lekto vorher nicht.

**Protokoll:** jeder Schritt mit Eingabe, Ausgabe und Dauer, wie n8n es je Knoten zeigt.

### Aufträge

Ein Auftrag ist ein Webhook-Aufruf, der eine Antwort erwartet: ein Regelschritt „fragen“ oder
ein Modellaufruf.

```
Knoten fällig → Lekto sendet den Auftrag (signiert, wenn ein Geheimnis gesetzt ist)
             → Knoten „Läuft extern“, der Job endet
Konsument    → POST <callback> mit Authorization: Bearer <token>
Lekto        → prüft Token, Lauf, Hülle und Inhalt → Knoten weiter
Frist um     → je nach Fall rot, gelb oder weiter
```

**Angaben zum Auftrag** stehen immer in den Headern `lekto-task-id`, `lekto-callback`,
`lekto-task-token`, `lekto-deadline`, dazu im Body: bei `thin` und `full` als Objekt `task`, im
Template als `task.id`, `task.callback`, `task.token`, `task.deadline` (für Empfänger, die keine
Header lesen).

**Antwort:** `POST /api/v1/external/tasks/{id}/result`, das Token im Header
`Authorization: Bearer` (nie in der URL: Reverse Proxies schreiben URLs ins Log). Das Token ist
einmalig und an Dokument, Knoten, Lauf und Auftrag gebunden; gespeichert wird nur sein Hash.

```json
{ "status": "ok", "producer": "mein-agent 2.1", "answer": { } }
{ "status": "error", "reason": "Modell nicht erreichbar" }
```

| Code | Wann | Folge |
| --- | --- | --- |
| 204 | angenommen und gültig | der Knoten läuft weiter |
| 422 | angenommen, aber ungültig (Hülle oder Inhalt); der Body nennt den Fehler | wie ohne Antwort, Token verbraucht |
| 413 | größer als 1 MB | wie ohne Antwort, Token verbraucht |
| 409 | Lauf veraltet (neu verarbeitet) oder schon beantwortet | keine Wirkung |
| 401 | Token unbekannt oder abgelaufen | keine Wirkung |

`status: error` wirkt wie eine ausbleibende Antwort; `reason` erscheint als Grund im
Posteingang, gekürzt auf 300 Zeichen und als reiner Text. `producer` (optional) steht im
Protokoll, wo heute das Modell steht.

**Dateien:** `GET /api/v1/external/tasks/{id}/files/{name}` (`content.json`, Seitenbilder);
jeder Link ist signiert (`LEKTO_SECRET_KEY`), an Dokument, Lauf und Datei gebunden und gilt bis
zur Frist. Das Antwort-Token ist davon getrennt.

**Zustand:** neuer Knotenzustand `delegated`, in der UI „Läuft extern“ (englisch „Running
externally“) mit der Restfrist („noch 8 Min.“). Ein Wächter-Job beendet Aufträge, deren Frist
abgelaufen ist. Ist der Endpunkt beim Versand nicht erreichbar, wiederholt Lekto die Zustellung
bis zur Frist. Wird ein Dokument neu verarbeitet oder gelöscht, erfährt der Konsument es nicht;
seine spätere Antwort bekommt 409.

**Voraussetzung:** `LEKTO_PUBLIC_URL` (gibt es für OIDC) wird Pflicht, sobald ein Webhook
Aufträge annimmt; Rückruf und Links brauchen sie.

### Modellaufrufe als Auftrag

Ein Admin bestimmt je Art einen seiner Webhooks; er ersetzt dann den internen Modellaufruf
dieser Art (`LEKTO_LLM_*` bleibt für die andere Art und für alles Übrige).

| Art | Knoten | ersetzt | Antwort |
| --- | --- | --- | --- |
| `propose` | `signal_llm` | Prompt `propose-5` | wie die Antwort des Modells: Absender, Empfänger, Typ, Thema, Tags, Datum, Titel, Sprache, Space, Felder des gewählten Typs |
| `extract` | `fields` | Prompt `extract-5`, nur wenn das Urteil einen anderen Typ entschied | Felder des entschiedenen Typs |

**Kein Prompt, sondern Kontext.** Der Konsument baut seinen Prompt selbst:

```json
{
  "contract": "propose-ext-1",
  "task": { "id": "…", "kind": "propose", "document_id": "…", "run": 3,
            "deadline": "…", "callback": "https://…/api/v1/external/tasks/…/result" },
  "document": { "filename": "…", "media_type": "application/pdf", "pages": 3,
                "received": "2026-10-25", "text": "…",
                "structure": "https://…/files/content.json?…",
                "page_images": ["https://…/files/pages/1.webp?…"] },
  "contacts": [ { "name": "Beispielbank AG", "aliases": ["…"], "topics": ["Girokonto"] } ],
  "document_types": [ { "name": "Rechnung", "description": "…", "fields": ["betrag"] } ],
  "fields": { "betrag": { "name": "LA_Brutto", "type": "amount", "description": "…" } },
  "general_fields": ["…"],
  "tags": ["…"],
  "spaces": [ { "key": "s1", "label": "Haushalt", "description": "…" } ],
  "answer_schema": { }
}
```

- Text ungekürzt; `content.json` (Wörter mit Boxen) und die Seitenbilder als signierte Links.
  Dafür bekommt `signal_llm` die Kante `pages → signal_llm`: Die Bilder sind da, wenn der
  Auftrag hinausgeht (heute läuft `pages` neben der OCR und ist meist vor `parse` fertig).
- Kontakte: die Vorauswahl von 20 wie heute; die Antwort nennt sie mit Namen, das Urteil gleicht
  sie ab wie die des Modells (ab 0,9).
- `answer_schema`: das JSON-Schema, das Lekto schon je Dokument aus den Stammdaten baut
  (`classification/answers.py`); die Regeln des heutigen Systemprompts stehen als
  `description` an seinen Feldern (Zitat wörtlich, Empfänger nie Absender, Betrag mit Währung).
  Der Konsument kann es direkt als Structured Output verwenden.
- `extract`: dieselbe Hülle mit Text, Struktur, Typ, den gesuchten Feldern und eigenem
  Antwortschema. Felder „nur von Hand“ gehen nie hinaus, Profildaten von Nutzern auch nicht.
- Die Antwort durchläuft dieselbe Prüfung wie eine Modellantwort: Zitate müssen wörtlich im
  Text stehen, die Lesesicherheit gilt, ein Kontakt wird erst mit einem zweiten Signal oder
  einem harten Beweis grün. Ein externer Dienst macht kein Dokument allein grün. Was entfällt:
  Lektos Schutz vor Anweisungen im Text und die Kürzung auf ein Budget; beides liegt beim
  Konsumenten.
- Fehler (Frist, `status: error`, ungültige Antwort): rot.
- Übernommene Dokumente (Migration) erzeugen keinen Auftrag; „ab `judge` neu“ behält die
  Antwort wie heute die des Modells.
- Protokoll: Kontext (ohne Bilder) und Antwort liegen beim Dokument wie heute die Modellaufrufe
  (`documents/{id}/exchanges/<knoten>.json`); im Verarbeitungsprotokoll die Vertragsversion
  statt der Prompt-Version und `producer`.

### Vertrag in OpenAPI

`web/openapi.json` (OpenAPI 3.1) beschreibt im Abschnitt `webhooks` die Bodies, die Lekto
sendet (`external.propose`, `external.extract`, `rule.send`, `rule.ask`, die Ereignisse), und
unter `paths` Antwort und Dateien. FastAPI kann das (`app.webhooks`, geprüft mit 0.142.2). Das
Antwortschema eines Modellaufrufs hängt an den Stammdaten; OpenAPI beschreibt seine allgemeine
Form, das genaue Schema steht im Auftrag. Der Test, der bei veraltetem `web/openapi.json`
fehlschlägt, deckt den Vertrag mit ab.

## Fehlerfälle

| Fall | Modellaufruf | Regel fragt | Benachrichtigung |
| --- | --- | --- | --- |
| Endpunkt nicht erreichbar | Zustellung wiederholt bis zur Frist | ebenso | Wiederholung wie heute, Abschalten nach Serie |
| Frist abgelaufen | rot | je Schritt: rot, gelb oder weiter | – |
| `status: error` | rot | wie Frist | – |
| Antwort ungültig (422) | rot | wie Frist | – |
| Template ergibt kein JSON | – | wie Frist | gescheitert, ohne Wiederholung |
| Besitzer darf das Dokument nicht lesen | – (sieht alles) | Schritt greift nicht, gelb | `dropped` wie heute |
| Antwort zu einem alten Lauf | 409, ohne Wirkung | ebenso | – |

## Rechte und Datenschutz

- Benachrichtigungen und Regelschritte melden nur, was der Besitzer des Webhooks lesen darf;
  geprüft vor jedem Versuch.
- Der Webhook eines Modellaufrufs sieht jedes Dokument: eine ausdrückliche Ausnahme vom
  Grundsatz „Rechte erweitern Webhooks nicht, auch bei Admins nicht“ (`architektur.md`).
- Was hinausgeht, entscheiden Admin und Nutzer selbst; Lekto macht keine Vorgaben. Header und
  Geheimnisse liegen verschlüsselt, erscheinen in keinem Log und keinem Protokoll.
- Antworten sind Daten von außen: strenge Prüfung der Hülle, Größe begrenzt, `reason` als
  reiner Text.

## Was sich ändert

**Kern**

- `Webhook`: Header, optionales Geheimnis, Body-Variante und Template, optionale Ereignistypen,
  Grenze offener Aufträge, Rolle als Modellaufruf.
- Ereignisse `document.review_required`, `document.confirmed`, `document.moved`.
- Regeln: Schritte `send_webhook`, `ask_webhook`, `condition`; Bedingungen auf `steps`; ein
  Lauf der Regeln, der auf Antworten wartet und danach weiterläuft.
- Aufträge: Auftrag mit Token-Hash, Frist, Zustand; Wächter-Job; Knotenzustand `delegated`.
- `signal_llm` und `fields`: Kontext statt Prompt, wenn ein Webhook die Art übernimmt; Kante
  `pages → signal_llm`.

**Ports und Adapter**

| Port | Änderung | Adapter |
| --- | --- | --- |
| `WebhookSender` | unverändert (Header gibt es schon) | `httpx2` |
| `TemplateRenderer` | Filter `json`, Werte `event`, `steps`, `task`, `rule` | `liquid` |
| `UnitOfWork` | Repositorien für Aufträge | `sql`, `memory` |

**API und UI**

- Webhooks: Header (Werte nur schreibbar), Geheimnis erzeugen oder entfernen, Body-Variante mit
  Template-Editor, Ereignisse optional, Grenze offener Aufträge; für Admins „dient als
  Modellaufruf“.
- Regeln: Schritte im Baukasten, Reihenfolge änderbar; Probelauf mit „sendet“ und „fragt“.
- Pfade `/api/v1/external/tasks/{id}/result` und `/files/{name}`; OpenAPI `webhooks`.
- Dokument: Knoten „Läuft extern“ mit Restfrist; Protokoll je Schritt.

**Daten:** Spalten an `webhooks`, Tabelle für Aufträge, Regel-JSON mit Schritten (bestehende
gültig); Alembic-Revisionen dazu.

## Abweichungen von `architektur.md`

- Webhooks (Egress): „schlanke Ereignisse, Details per API“ gilt nur noch für den Body `thin`;
  `full` und `template` liefern Inhalte, im Rahmen der Reichweite des Besitzers.
- Webhooks (Egress): Der Webhook eines Modellaufrufs sieht jedes Dokument.
- Regel-Engine: Aktionen werden Schritte; Regeln senden und fragen.
- Ingest-Workflow: Zustand `delegated`; Kante `pages → signal_llm`; Modellaufrufe über einen
  Webhook.

## Phasen

| Phase | Meilenstein | Inhalt | Nutzen für sich |
| --- | --- | --- | --- |
| 1 | M19 | Webhooks ausbauen: Header, optionales Geheimnis, Body `full` und `template`, Ereignisse optional, drei neue Ereignisse, Regelschritt „Webhook senden“ | Home Assistant und Node-RED anbinden |
| 2 | M20 | Aufträge: Rückruf, Token, Frist, `delegated`, Wächter; Regelschritte „Webhook fragen“ und „Bedingung“, `steps`, Reihenfolge im Baukasten | Regeln fragen Node-RED, ein CRM, eine Buchhaltung |
| 3 | M21 | Modellaufrufe über Aufträge: Kontext, Links, Kante `pages → signal_llm`; Vertrag in OpenAPI | eigene Modelle und Agenten statt `LEKTO_LLM_*` |

## Verworfen

- OCR auslagern (etwa Azure Document Intelligence): gestrichen (Tobi, 25.10.2026).
- Konfiguration der Modellaufrufe über `LEKTO_EXTERNAL_*`: ersetzt durch Webhooks in der
  Datenbank.
- Eine Antwort, die selbst Aktionen liefert: ersetzt durch beliebiges JSON und Schritte der Regel.
- Kontext über die ganze Pipeline (`nodes.judge…` in Regeln, Lesart B): vorerst nicht.
- Verzweigungen in Regeln: vorerst nicht, linear.
- Zeitgesteuerte Auslöser („Fälligkeit in N Tagen“): derzeit kein Nutzen.
- Bewertung (`lekto evaluate`) gegen einen externen Endpunkt: kein Mehrwert.
- Pull statt Push (externe Worker holen Aufträge): nicht verfolgt, Webhook reicht.

## Offen

Beim Bauen von M21 entschieden, zur Bestätigung durch Tobi:

1. Ein Webhook dient als genau eine Art (`propose` oder `extract`); für beide Arten zwei
   Webhooks, gern mit derselben URL.
2. Die Frist eines Modellaufrufs steht am Webhook (`model_call.timeout_seconds`), Vorgabe
   5 Minuten, 30 Sekunden bis 24 Stunden.
3. „Je Art höchstens einer aktiv“ zählt die aktiven Webhooks aktiver Admins; ein zweiter: 409
   (`model_call_taken`). Nur ein Admin gibt die Rolle, nur an den Webhook eines Admins;
   entfernen darf sie jeder, der den Webhook verwaltet.
4. Vertragsversionen `propose-ext-1` und `extract-ext-1`; `task.kind` heißt `external.propose`
   und `external.extract`; das Token steht auch im Body (`task.token`), wie bei `thin` und
   `full`. Der Body des Webhooks gilt für Modellaufrufe nicht (immer der Vertrag); Ereignisse
   und Regeln am selben Webhook nutzen ihn weiter.
5. Datei-Links: signiert über `SecretCipher` (AES-GCM mit `LEKTO_SECRET_KEY`, gebunden an
   Auftrag, Dokument, Lauf, Datei und Ablauf); sie gelten bis zur Frist, auch nach der Antwort;
   401 nach Ablauf oder mit falscher Signatur, 409 nach Neuverarbeitung oder Löschen. In
   OpenAPI als Sicherheitsschema `fileSignature`.
6. Die Kante `pages → signal_llm` gilt immer: „Neu verarbeiten ab `pages`“ fragt deshalb das
   Modell (oder den Webhook) neu. Bestätigen nach einem OCR-Fehler rendert die Seiten weiter,
   statt sie zu übernehmen.
7. Kein zweiter Versuch: Eine Antwort, die nicht passt, ist sofort 422 und rot (das interne
   Modell wird nach einer unpassenden Antwort einmal neu gefragt).
8. Im Kontext stehen die Spaces anderer Nutzer mit dem Anzeigenamen als Label, wie im Prompt
   heute; Felder mit `form` (wie der Wert geschrieben wird) und `type`.
9. Protokoll: der Kontext ohne Auftrag und Links als „Nutzer“, die Antwort als „Antwort“, kein
   Systemprompt (die UI blendet den Reiter aus); `model_version` ist `producer`, ohne ihn
   `external`.
10. Das Beispiel liegt unter `examples/model-calls/` (Skript, Compose-Erweiterung, README); ein
    optionales `OLLAMA_API_KEY` erlaubt einen Proxy vor Ollama.
11. Ein Modellaufruf, der noch auf Platz wartet, wird abgebrochen, wenn sein Webhook geht oder
    nicht mehr dient; der Knoten fragt dann neu (einen anderen Webhook oder das Modell), statt
    rot zu werden. Ein schon gesendeter läuft bis zur Frist (Entscheidung 29).
12. Ist der Lauf inzwischen gescheitert (ein anderes Signal rot), geht nichts mehr hinaus; ein
    wartender Auftrag gibt seinen Platz frei.

## Entscheidungen (Tobi, 25.10.2026)

1. Ausgelagert werden nur Schritte, die an ein Sprachmodell gehen: `signal_llm` und `fields`.
   Die OCR auszulagern ist gestrichen.
2. Ein ausgelagerter Schritt ersetzt den internen; Lekto definiert den Vertrag.
3. Was hinausgeht, entscheidet der Betreiber; Lekto macht keine Vorgaben.
4. Ohne Antwort in der Frist wird das Dokument rot; eine ungültige Antwort macht sofort rot, das
   Token ist einmalig.
5. Modellaufrufe richten Admins ein, systemweit.
6. Kein Prompt, sondern Kontext als JSON; der Konsument baut seinen Prompt selbst.
7. Daten: Text ungekürzt, `content.json` und Seitenbilder als Link (signiert, mit Ablaufzeit);
   Kontakte in der Antwort mit Namen; Vorauswahl von 20 Kontakten wie heute; `propose` und
   `extract` getrennt einstellbar.
8. Header konfigurierbar, das Geheimnis optional (signiert wird nur mit Geheimnis); höchstens N
   offene Aufträge je Endpunkt.
9. Protokoll: Kontext und Antwort beim Dokument; Vertragsversion und `producer` im
   Verarbeitungsprotokoll; die Vertragsversion steht im Auftrag.
10. Die Antwort trägt das Token als `Authorization: Bearer`, nicht in der URL; Hülle mit
    `status`, `producer`, `answer` oder `reason`; `status: error` macht rot.
11. Abgebildet wird alles über die Webhooks; sie werden stärker: mehr Anpassung, mehr Auslöser
    (Home Assistant, Node-RED). Die Konfiguration liegt in der Datenbank, nicht in
    Umgebungsvariablen; globale Grenzen bleiben `LEKTO_WEBHOOK_*`.
12. Body-Varianten schlank, voll und Template.
13. Bedingtes Senden über Regeln; ein Regelschritt kann eine Antwort erwarten.
14. Schritte innerhalb einer Regel (Lesart A), linear; spätere Schritte greifen über
    `steps.<name>` auf frühere zu.
15. Jede Regel sieht, was ihre eigenen Schritte gesetzt haben (Variante 2); Konflikte zwischen
    Regeln werden am Ende zusammengeführt.
16. „Webhook fragen“ nur beim Eingang, nicht rückwirkend; ohne Antwort je Regel rot, gelb oder
    weiter (Vorgabe rot), Frist je Schritt (Vorgabe 5 Minuten).
17. Regeln verwenden nur Webhooks ihres Autors (global: eines Admins); der Besitzer muss das
    Dokument lesen dürfen, sonst greift der Schritt nicht und das Dokument wird gelb.
18. Ein Webhook ist ein Endpunkt; die Verwendung bestimmt, ob er meldet oder fragt. Der Webhook
    eines Modellaufrufs sieht jedes Dokument.
19. Angaben zum Auftrag als Header und im Body.
20. Neue Ereignisse: wartet auf Prüfung, bestätigt, verschoben oder übergeben.
21. Webhooks mit Aufträgen schalten sich nie selbst ab; Benachrichtigungen wie heute.
22. Knotenzustand „Läuft extern“ mit Restfrist.
23. Vertrag in OpenAPI 3.1 (`webhooks`); Pfade `/api/v1/external/tasks/{id}/result` und
    `/files/{name}`.
24. Kante `pages → signal_llm`.
25. Zeitgesteuerte Auslöser und die Bewertung gegen externe Endpunkte: nicht jetzt.
26. „Webhook senden“ beim Eingang geht erst beim Ablegen hinaus; rückwirkend angewendet sendet
    eine Regel je Dokument, mit Hinweis in der Vorschau.
27. Bestätigen ohne Änderung fragt nicht neu, mit Änderung schon; eine fehlende Antwort nach dem
    Bestätigen wird nur gemeldet; „Neu verarbeiten“ fragt immer neu.
28. Eine Antwort ist höchstens 1 MB groß; größer: 413, wirkt wie keine Antwort.
29. Wird ein Webhook geändert oder gelöscht, während Aufträge offen sind, laufen sie bis zur
    Frist; eine Antwort mit gültigem Token wird angenommen.
30. Wird der Admin des Modellaufruf-Webhooks gelöscht, gilt wieder der interne Modellaufruf;
    ohne ihn enthält sich `signal_llm`.
31. Ein minimaler Beispiel-Konsument kommt: als Vorlage für Admins und zum Ausprobieren in der
    Devinstanz (M21), nicht für den Betrieb.
32. Ereignis `document.node_delegated`, abonnierbar.
33. Bedingungsschritte prüfen Werte aus `steps` wie Bedingungen (Pfad, Operator, Wert).
34. Ohne Antwort „gelb“: Die Schritte vor dem Frageschritt gelten; „rot“: keine Regel wirkt.
35. Die signierten Datei-Links (`/external/tasks/{id}/files/{name}`) kommen mit M21; erst die
    Modellaufrufe brauchen sie.
36. Die Frist eines Frageschritts liegt zwischen 30 Sekunden und 24 Stunden.
37. Verschiebt eine Person ein Dokument in einen Space, dessen Regeln fragen, wird nicht gefragt:
    Die Regel endet am Frageschritt, ihre Schritte davor gelten.
38. Das Token eines Auftrags liegt bis zur Zustellung verschlüsselt beim Auftrag, danach nur sein
    Hash.
39. Eine Antwort ist höchstens 1.000.000 Bytes groß.
40. Der Template-Editor schlägt in Regeln `steps.<name>` der Frageschritte davor vor.
41. Beispiel-Konsument: ein Python-Skript nur mit der Standardbibliothek in `examples/`, dazu ein
    Compose-Beispiel neben `docker/` mit Ollama.

## Quellen

- Standard Webhooks: https://www.standardwebhooks.com
- OpenAPI 3.1, `webhooks`: https://spec.openapis.org/oas/v3.1.0#openapi-object
- RFC 9110, Header-Namen: https://www.rfc-editor.org/rfc/rfc9110#name-field-names
- Home Assistant, Webhook-Auslöser (Body als `trigger.json`, Methoden):
  https://community.home-assistant.io/t/allow-get-to-trigger-webhook/542140
- Node-RED, JSON per POST in einen Flow: https://cookbook.nodered.org/http/post-json-data-to-a-flow
- n8n, Ergebnisse früherer Knoten: https://docs.n8n.io/data/data-mapping/referencing-other-nodes

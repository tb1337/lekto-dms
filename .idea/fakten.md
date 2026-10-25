# Fakten: Zielbild und Entscheidungen

Stand: 25.10.2026 · Tobi (Entscheidungen) und Creamy (Vorschlag)

Gehört zu [Bezüge, Serien und Stream](bezuege.md): Fakten sind die Grundlage, auf der Lekto
Bezüge und Serien erkennt. Umgesetzt ist davon noch nichts; `architektur.md` bleibt verbindlich
und wird erst mit der Umsetzung ergänzt. Die E-Rechnung als Quelle ist ein mögliches Feature:
[Issue #144](https://github.com/tb1337/lekto-dms/issues/144).

## Ist-Stand

- `signal_facts` findet ohne Sprachmodell, mit Mustern, Prüfziffern und Codes: Namen von
  Kontakten, Kennungen (IBAN, USt-IdNr, Kundennummer, Personalnummer, E-Mail-Domain und
  -Adresse, Steuer-ID, Sozialversicherungs- und Krankenversichertennummer) und den GiroCode
  (Empfänger, IBAN, BIC, Betrag, Verwendungszweck) (`core/domain/facts.py`, `core/domain/codes.py`,
  `core/domain/identifiers/base.py`).
- Fakten sind Beweise für das Urteil. Gespeichert wird nur, welche Kennungen ein Dokument zeigt
  (`document_identifiers`).
- Das Sprachmodell liefert keine Fakten; es bekommt nur Text, keine Codes und keine Seitenbilder
  (`core/services/classification/prompts.py`).
- Regeln und Templates sehen keine Fakten (`core/domain/rule_conditions.py`, `Facts`). Templates
  setzen nur Textfelder (`architektur.md`, Regel-Engine).
- Eine Rechnungsnummer kennt Lekto nicht; die Art `customer_number` deckt Kunden-, Vertrags- und
  Policennummern zugleich ab.

## Fakt und Feld

- **Fakt:** was etwas *kennzeichnet* oder auf etwas *zeigt*: Nummern und Verweise, auch „Ihr
  Schreiben vom 18.06.2026“ als Verweis mit Datum. Ein Fakt steht im Dokument und wird nicht
  konfiguriert; er gilt für jeden Typ, und Lekto vergleicht ihn über Dokumente hinweg.
- **Feld:** was etwas *misst* oder *terminiert*: Beträge, Fristen, Zeiträume. Was eine Person je
  Typ am Dokument festhält.
- **Ausnahme:** Eine maschinenlesbare Quelle (GiroCode, E-Rechnung) ist je *ein* Fakt mit ihren
  Werten; eine Regel bringt einen Wert ins Feld (`{{ facts.girocode.amount }}`).

Ein Fakt hat eine Art, einen Wert (normalisiert: „00012345“ gleich „12345“), seine Fundstellen,
eine Herkunft (Muster, Code, Sprachmodell, Person) und eine Rolle.

Gründe gegen Beträge und Daten als Fakten: Ohne Beschriftung hat ein Betrag keine Rolle (eine
Rechnung hat zehn Beträge), mit Beschriftung ist er ein Feld; Felder haben die Prüfung schon
(Zitat, Beschriftung beim Wert, schwach gelesene Stellen); Bezüge brauchen Identität, keine Menge
(39,99 € steht jeden Monat auf der Rechnung); ein Wert gehört an einen Ort.

## Rollen

| Rolle | Beispiele | Wofür |
| --- | --- | --- |
| zeigt auf den Kontakt | Kundennummer, Personalnummer, Gläubiger-ID, Handelsregisternummer, Steuernummer eines Unternehmens | Kontakt, Thema |
| zeigt auf ein Bezugsziel | Vertrags-, Policen-, Mitglieds-, Zähler-, Darlehensnummer, Mandatsreferenz, Kfz-Kennzeichen | Serie, Bezug zum Vertrag |
| kennzeichnet das Dokument | Rechnungs-, Gutschrift-, Bestell- oder Auftragsnummer, ASN aus Code oder Etikett | Ziel für Bezüge, Feld |
| verbindet einen Strang | Aktenzeichen, „Unser Zeichen“, Schaden-, Ticketnummer | Abzweig im Stream |
| verweist auf ein Dokument | „Ihre Rechnung Nr. …“, „Ihr Schreiben vom …“, „Ihr Zeichen“ | Bezug |
| zeigt auf eine Person | Steuer-ID, Steuernummer, Kindergeldnummer (und die vorhandenen) | Personen, Space |

Beispiel zur Rolle: Die Rechnung vom 04.06. trägt „Rechnungsnummer 4711“, die Mahnung vom 20.07.
schreibt „Ihre Rechnung Nr. 4711 ist noch offen“. Beide zeigen denselben Fakt; die Nummer gehört
der Rechnung, die Mahnung verweist auf sie. Nur so zeigt der Bezug von der Mahnung auf die
Rechnung, und eine zweite Mahnung ebenso auf die Rechnung, nicht auf die erste Mahnung.

## Entscheidungen (Tobi, 25.10.2026)

1. Fakten sind ein Kernthema. Der Katalog der Arten liegt fest im Code und wird dort erweitert;
   Admins legen keine Arten an.
2. Das Sprachmodell wird eine weitere Quelle für Fakten, mit derselben Prüfung wie bei Feldern:
   Zitat, Wert im Text, Beschriftung. Die Laufzeit ist dabei kein Thema.
3. Die Rolle eines Fakts („eigene Nummer“ oder „Verweis“) bestimmt das Sprachmodell; eine
   Faustregel (das älteste Dokument mit der Nummer besitzt sie) gibt es nicht.
4. `customer_number` wird getrennt in Kunden-, Vertrags- und Policennummer.
5. Der Katalog oben ist vorerst vollständig; die Rufnummer entfällt.
6. Fakten werden durchsuchbar und filterbar, auch für Nutzer (etwa „Rechnungsnummer = 4711“).
7. Fakten sind korrigierbar (aus „4661VF“ wird „4661“):
   - Wer das Dokument bearbeiten darf (Bearbeiter des Space, Admins), ergänzt, korrigiert oder
     verwirft einen Fakt am Dokument; Leser nicht.
   - Der Fakt trägt danach die Herkunft „Person“ und übersteht eine neue Verarbeitung: Die Person
     gewinnt, wie bei Feldern. Die Korrektur zählt in die Urteile je Feld (`field_verdicts`).
   - Die Korrektur am Dokument ändert keinen Kontakt. Hat Lekto den falschen Wert als Kennung
     gelernt, bietet Lekto einem Admin beim Korrigieren „auch beim Kontakt korrigieren“ an.
8. Fakten kommen über Regeln in Felder. Dafür sehen Templates die Fakten, und Regeln setzen jedes
   Feld, nicht nur Textfelder („darf so nicht bleiben“).
9. Eine Rechnungsnummer braucht kein Feld. Pflicht je Typ, Kartenfeld in einer Lens und
   Sortieren bleiben Sache der Felder; wer das will, füllt ein Feld per Regel aus dem Fakt.
10. Die E-Rechnung (ZUGFeRD, Factur-X) wird als mögliches Feature aufgenommen
    ([Issue #144](https://github.com/tb1337/lekto-dms/issues/144)); XML liest Lekto dann mit
    `defusedxml`.
11. Die Prompts werden für Prompt-Caching umgebaut („wenn wir damit Prompt-Caching kriegen,
    gern“), gemessen mit dem Bewertungssatz (siehe unten).

## Sprachmodell: mehrere Aufrufe, ein Dokument

Die APIs sind zustandslos; auch ein Chat schickt bei jedem Aufruf den ganzen Verlauf. Sparen
lässt sich die Rechenarbeit: Prompt-Caching hält den berechneten Anfang eines Prompts, und ein
Aufruf, der exakt gleich beginnt, überspringt ihn.

- Ollama: automatisch, solange das Modell geladen bleibt (`keep_alive`)
  ([Leanpub](https://leanpub.com/read/ollama/prompt-caching); Mechanismus aus llama.cpp,
  [ADR](https://llama-cpp-ex.hexdocs.pm/007-prefix-caching.html); Ollamas eigene Doku dazu nicht
  gefunden).
- Groq: automatisch, derzeit nur für die GPT-OSS-Modelle, Ablauf nach zwei Stunden ohne Nutzung
  ([Groq](https://console.groq.com/docs/prompt-caching)).
- Anthropic: Der Anfang muss markiert werden (`cache_control`); über Anthropics OpenAI-kompatible
  Schnittstelle gar nicht ([Anthropic](https://docs.anthropic.com/en/api/openai-sdk)). Über
  LiteLLM setzt der Proxy die Marken: je Modell `cache_control_injection_points` in der
  `config.yaml` (nach Rolle oder Index der Nachricht) oder global
  `enable_anthropic_prompt_caching` (ab v1.94.0: Systemprompt und letzte Nachricht)
  ([LiteLLM](https://docs.litellm.ai/docs/tutorials/prompt_caching)).

Heute teilen zwei Aufrufe nur den Systemprompt: Das Dokument steht am Ende, hinter den Listen
(`prompts.py`, `propose_message`, `extract_message`).

Vorschlag (Creamy):

1. Reihenfolge: Systemprompt (gleich für alle Aufrufe), dann das Dokument als eigene Nachricht,
   dann die Aufgabe. Das Dokument bleibt eine Nachricht des Nutzers in seinem Marker, nie im
   Systemprompt: Es ist fremder Inhalt.
2. Port: `StructuredRequest` trennt Dokument und Aufgabe. Der OpenAI-kompatible Adapter schickt
   drei Nachrichten; Lekto bleibt neutral gegenüber dem Anbieter.
3. Getrennte Aufrufe mit gleichem Anfang statt Chatverlauf: Jede Antwort wird für sich geprüft,
   keine falsche färbt die nächste. Ein Verlauf nur, wo eine Frage auf einer früheren Antwort
   aufbaut.
4. `propose-5` lässt sich dann in kleine Themen teilen: Klassifizierung, Felder des Typs, Fakten
   mit Rolle, Verweise. Ob kleine Modelle damit besser werden, misst der Bewertungssatz.
5. Ob der Cache trifft, steht im Bericht des Endpunkts (`StructuredAnswer.usage`), den Lekto schon
   ins Protokoll schreibt.

## Was fehlt

- Fakten als gespeicherte Werte am Dokument mit Art, Wert, Fundstellen, Herkunft und Rolle; heute
  nur die Kennungen ohne Rolle (`document_identifiers`).
- Neue Arten aus dem Katalog; die Trennung von `customer_number`.
- Fakten vom Sprachmodell (Prompt, Schema, Prüfung).
- Korrigieren in API und Web-UI.
- Fakten in Suche, Filter, Regelbedingungen und Templates; Regeln, die jedes Feld setzen.

## Offene Punkte

- LiteLLM: Marken für Anthropic im Proxy konfigurieren (nach Index auf die Nachricht mit dem
  Dokument) oder von Lekto mitschicken; Vorschlag Creamy: im Proxy, Lekto bleibt neutral.
- Sichtbarkeit: Eine Nummer, die eine Person nennt, bleibt privat (`architektur.md`,
  Berechtigungen; Issue #82). Den Wert sehen die Leser des Dokuments im Text, nicht, wem er
  gehört; gilt so auch für Suche und Filter.
- E-Rechnung: Widerspruch zwischen XML und sichtbarem Text (Vorschlag: gelb); die kleinen
  Profile; Priorität des Issues.

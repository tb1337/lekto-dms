# Bezüge, Serien und Stream: Zielbild und Entscheidungen

Stand: 25.10.2026 · Tobi (Entscheidungen) und Creamy (Vorschlag)

Dieses Dokument hält die Vision fest, die Tobi und Creamy am 25.10.2026 im Gespräch entwickelt
haben. Umgesetzt ist davon noch nichts; `architektur.md` bleibt verbindlich und wird erst mit der
Umsetzung ergänzt. Mock: Canvas „Lekto Stream“ (Desktop und Handy, hell und dunkel),
<https://claude.ai/artifact/Q6SnMvjuLZEGBV5YuVQfGR>.

Gehört zu [Fakten](fakten.md): Die Nummern und Verweise, aus denen Lekto Bezüge und Serien
erkennt, sind Fakten am Dokument; dort stehen ihre Arten, Rollen und Quellen.

## Anlass

- Dokumente gehören zusammen, ohne einander zu ersetzen: Im Juni kommt eine Korrektur zur
  Lohnabrechnung für Januar 2026; sie trägt ein Junidatum, gehört aber zum Original.
- Viele Dokumente kommen regelmäßig, etwa die Rechnung von Vodafone jeden Monat. Lekto soll
  zeigen, wann die nächste voraussichtlich kommt.
- Für einen Kontakt, eine Kontaktgruppe oder ein Thema soll eine zeitliche Abfolge sichtbar sein,
  wie Branches auf GitHub: eine Hauptspur, davon abzweigend ein paralleler Strang (eine
  Reklamation zur Rechnung).

Lekto bleibt dabei, was es ist: eine smarte Ablage, spezialisiert auf das Erkennen von Inhalten
und von Bezügen zwischen Dokumenten (Tobi).

## Begriffe

| Begriff | Bedeutung |
| --- | --- |
| Bezug | gerichtete Verbindung vom neueren zum älteren Dokument, angezeigt als „bezieht sich auf“ |
| Serie | gleichartige Dokumente in festem Abstand, abgeleitet, nicht gespeichert |
| Bezugsziel | ein Dokumenttyp, auf den eine gemeinsame Nummer verweist (Vertrag, Police) |
| Stream | Darstellung der gefilterten Dokumente als Zeitachse mit Spuren |
| Erwartet | Ansicht der Dokumente, die nach ihrer Serie als Nächstes kommen sollten |

- „Korrespondenz“ fällt aus: In Paperless-ngx ist der Korrespondent unser Kontakt
  (`architektur.md`, Datenmodell).
- „Lane“ bleibt grün, gelb und rot. Die Bahnen im Stream heißen anders; im Mock „Spuren“ (offen).
- „Vorgang“ ist der Fachbegriff der Schriftgutverwaltung für Dokumente zu einem abgrenzbaren
  Sachverhalt ([Erzbistum München](https://www.erzbistum-muenchen.de/cms-media/media-23056320.pdf),
  [BMG, Aktenplan](https://www.bundesgesundheitsministerium.de/ministerium/aufgaben-und-organisation/aktenplan)).
  Lekto führt ihn nicht (siehe Entscheidungen).

## Entscheidungen (Tobi, 25.10.2026)

**Bezug**

1. Zwei Dokumente bleiben zwei Dokumente; keines ersetzt das andere. Die Korrektur zeigt ihren
   Bezug auf das Original, das Original zeigt, dass es eine Korrektur gibt.
2. Bezüge sind n:m: ein Dokument kann sich auf mehrere beziehen (eine Gutschrift auf zwei
   Rechnungen), auf eines beziehen sich viele (alle Rechnungen auf den Vertrag).
3. Ein Bezug hat keine eigene Art. Angezeigt wird „bezieht sich auf“; die Dokumenttypen an beiden
   Enden geben den Sinn (Korrekturabrechnung → Lohnabrechnung, Mahnung → Rechnung).
4. Bezüge gehen zwischen beliebigen Typen, auch Rechnung → Vertrag.
5. Sichtbar ist ein Bezug nur, wer beide Dokumente lesen darf.
6. Von Hand setzt einen Bezug, wer das neuere Dokument bearbeiten und das ältere lesen darf.
7. Ein Bezug macht nie gelb. Ein sicherer wird gesetzt, ein unsicherer erscheint als Vorschlag
   am Dokument. Damit die Qualität sichtbar bleibt, kommt der Bezug in die Urteile je Feld
   (`field_verdicts`, `architektur.md`, Ingest-Workflow).

**Erkennen**

8. Eine gemeinsame Vertrags- oder Kundennummer verbindet nur mit Dokumenten eines Typs, den ein
   Admin als Bezugsziel markiert (Schalter am Dokumenttyp; „versuchen wir“). Sonst verbände die
   Kundennummer jede Rechnung mit jeder anderen.
9. Weitere Quellen („klingt erstmal sinnvoll“):
   - gleicher Kontakt, gleicher Typ und gleicher Bezugszeitraum bei anderem Dokumentdatum: die
     Korrektur;
   - eine Nummer im Text, die ein anderes Dokument trägt (Rechnungs-, Gutschrift-, Vorgangsnummer):
     Mahnung, Reklamation, Gutschrift;
   - Verweise, die das Sprachmodell liest („Ihr Schreiben vom 18.06.2026“).

**Serien und Erwartet**

10. Eine Serie: gleicher Kontakt und Typ, dazu die Vertrags- oder Kundennummer, wenn das Dokument
    eine zeigt; mindestens drei Dokumente; der Abstand folgt aus den Dokumentdaten.
11. Serien werden abgeleitet, nicht gespeichert. Nach zwei verpassten Terminen gilt eine Serie
    als beendet. „Beenden“ und „stumm“ von Hand gibt es vorerst nicht.
12. Die Ansicht heißt „Erwartet“, eine eigene Ansicht, vorerst nur zum Ansehen. Backend, API und
    UI ja; ausgehende Ereignisse (Outbox, Webhooks) noch nicht. Der Posteingang bleibt, was er
    ist.

**Stream**

13. Der Stream ist eine dritte Darstellung der Dokumentliste neben Raster und Liste und damit
    auch einer Lens.
14. Wonach er läuft, bestimmt der Filter: Kontakt, Kontaktgruppe oder Thema; der Mensch schaltet
    um.
15. Einstieg per Klick auf einen Kontakt: Die Dokumentliste öffnet sich, gefiltert auf ihn, als
    Stream. Aus der Dokumentansicht führt „Im Stream zeigen“ zum Stream seines Kontakts.
16. Eine Serie ist eine Spur, ihr Bezugsziel (der Vertrag) ihr Anfang. Ein Abzweig ist ein
    Dokument mit Bezug auf ein Serien-Dokument, das selbst nicht zur Serie gehört, mit der Kette
    seiner Bezüge. Erwartete Dokumente stehen als Platzhalter am Ende ihrer Spur.
17. Dokumente ohne Serie und ohne Bezug stehen in einer gemeinsamen Spur „Einzeln“.

**Nicht in Lekto**

18. Vorgänge (Name, Status offen oder erledigt, Gruppen über Kontakte) gehören in einen eigenen
    Service, der später auf Lekto aufsetzt. Fast alles, was ein Vorgang zeigt, ergibt sich aus
    Bezügen; „offen“ decken manuelle Status-Tags ab (`architektur.md`, Tags, Gruppen und Themen).

## Was es schon gibt

- Feldtyp Zeitraum mit Bezugszeitraum (`architektur.md`, Ingest-Workflow; `core/domain/periods.py`).
- Kennungen, die ein Dokument zeigt (`document_identifiers`, `adapters/outbound/sql/tables.py`);
  eine Kennung kann ein Thema belegen.
- Kontakt, Typ, Thema und Dokumentdatum an jedem Dokument.
- Nachbarn über Embeddings und das Sprachmodell mit Zitaten (`signal_neighbours`, `signal_llm`).
- Wiederkehrende Jobs (`core/domain/jobs.py`).
- Lens mit Darstellung Raster oder Liste und Gruppierung nach Monat, Frist, Typ, Kontakt
  (`core/domain/lenses.py`).

## Was fehlt

- Bezüge zwischen Dokumenten: weder Tabelle noch Begriff im Kern.
- Nummern, die ein Dokument kennzeichnen (Rechnungs-, Gutschrift-, Vorgangsnummer), und ihre
  Rolle (eigene Nummer oder Verweis): siehe [Fakten](fakten.md).
- Schalter „Bezugsziel“ am Dokumenttyp.
- Serien und erwartete Dokumente als Begriff im Kern, mit API.
- Filter nach Bezugszeitraum („kommen später“, `architektur.md`).
- Darstellung „Stream“ in Dokumentliste und Lens; Ansicht „Erwartet“.

## Offene Punkte

- Reihenfolge des Eingangs (Vorschlag Creamy): Kommt die Korrektur vor dem Original an, muss das
  Original beim Eingang die Dokumente finden, die sich schon auf es beziehen. Für den Bestand ein
  eigener Lauf, ähnlich `reindex`.
- Kundennummer über mehrere Verträge: Passt eine Nummer auf zwei Bezugsziele, nur vorschlagen
  (Vorschlag Creamy).
- Name der Bahnen im Stream: „Spuren“ oder anders.
- Ein weiter Filter (Kontaktgruppe mit vielen Serien) macht den Stream unlesbar: Grenze („bitte
  enger filtern“) oder zusammengeklappte Spuren.
- Aus dem Mock, nicht entschieden:
  - „Erwartet“ als eigener Menüpunkt neben „Dokumente“.
  - Desktop mit waagerechter Zeitachse (Monate als Spalten), Handy senkrecht wie `git log
    --graph`, neueste oben.
  - Name einer Abzweig-Spur aus dem Typ ihres ersten Dokuments („Reklamation“).
  - Am Dokument drei Gruppen: „Bezieht sich auf“, „Darauf beziehen sich“, „Vorschlag“, jeweils
    mit dem Beleg, aus dem Lekto den Bezug hat.
  - In „Erwartet“: Abschnitte Überfällig, Nächste 30 Tage, Später, Beendet; Streuung je Serie
    („± 2 Tage“); der Bezugszeitraum, wo die Serie einen trägt („für November 2026“).

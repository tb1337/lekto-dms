"""The senders of the household's documents: companies, authorities, practices, clubs, each
with its own look. All made up; domains end in `.example`, register numbers and VAT IDs are
synthetic."""

from synth import ids
from synth.letter import Sender, Style


def _sender(name: str, street: str, city: str, style: Style, **details: str) -> Sender:
    return Sender(name=name, street=street, city=city, style=style, **details)


# Utilities, telecommunication.

STADTWERKE = _sender(
    "Stadtwerke Musterstadt GmbH",
    "Am Wasserturm 3",
    "12345 Musterstadt",
    Style("sans", (0, 112, 120), "bars", "right", "Energie für Musterstadt"),
    short="Stadtwerke Musterstadt",
    phone="Telefon 0800 1234 567",
    email="service@stadtwerke-musterstadt.example",
    web="www.stadtwerke-musterstadt.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000047110815"),
    bic="SPMUDE2MXXX",
    register="Amtsgericht Musterstadt HRB 4711",
    vat_id=ids.vat_id("12345678"),
    managers="Geschäftsführer: Dr. Jan Beispiel",
)
FERNNETZ = _sender(
    "FernNetz Telekommunikation GmbH",
    "Funkstraße 1",
    "40210 Beispielburg",
    Style("sans", (200, 0, 110), "wave", "band", "Mobil · Festnetz · Internet"),
    short="FernNetz",
    phone="Hotline 0800 3376 638",
    email="rechnung@fernnetz.example",
    web="www.fernnetz.example",
    bank="Hansebank AG",
    iban=ids.iban("DE", "300400000987654321"),
    register="Amtsgericht Beispielburg HRB 88231",
    vat_id=ids.vat_id("81234567"),
    managers="Vorstand: Petra Lindner, Omar Haddad",
)
WASSERVERBAND = _sender(
    "Wasser- und Abwasserverband Musterland",
    "Klärwerkstraße 20",
    "12350 Musterstadt",
    Style("serif", (20, 80, 160), "wave", "left", "Körperschaft des öffentlichen Rechts"),
    short="Wasserverband Musterland",
    phone="Telefon 01234 5566-0",
    email="gebuehren@wasserverband-musterland.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000033221100"),
    tax_number="21/400/12345",
)

# Housing.

WOHNBAU = _sender(
    "Wohnbau Musterstadt eG",
    "Genossenschaftsweg 8",
    "12345 Musterstadt",
    Style("sans", (150, 60, 20), "triangle", "left", "Gut wohnen seit 1921"),
    phone="Telefon 01234 7788-0",
    email="vermietung@wohnbau-musterstadt.example",
    web="www.wohnbau-musterstadt.example",
    bank="Volksbank Musterland eG",
    iban=ids.iban("DE", "430600001122334455"),
    register="Amtsgericht Musterstadt GnR 112",
    managers="Vorstand: Ingrid Hoffmann, Paul Wagner",
)
HAUSVERWALTUNG = _sender(
    "Hausverwaltung Klein",
    "Kastanienstraße 14",
    "12347 Musterstadt",
    Style("serif", (60, 60, 60), "none", "center"),
    phone="Telefon 01234 33 21 10",
    email="info@hv-klein.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000099887766"),
    tax_number="21/215/30411",
)
ELEKTRO_KRAUSE = _sender(
    "Elektro Krause GmbH",
    "Werkstraße 7",
    "12349 Musterstadt",
    Style("sans", (230, 160, 0), "diamond", "left", "Elektroinstallation · Smart Home · Notdienst"),
    phone="Telefon 01234 90 90 90",
    email="buero@elektro-krause.example",
    web="www.elektro-krause.example",
    bank="Volksbank Musterland eG",
    iban=ids.iban("DE", "430600004455667788"),
    register="Amtsgericht Musterstadt HRB 2290",
    vat_id=ids.vat_id("29384756"),
    managers="Geschäftsführer: Frank Krause",
)
MALER = _sender(
    "Malerbetrieb Sonnenschein",
    "Am Anger 2",
    "12351 Musterstadt-Süd",
    Style("serif", (210, 120, 0), "circle", "right", "Meisterbetrieb seit 1987"),
    phone="Telefon 01234 41 22 07",
    email="maler.sonnenschein@mail-beispiel.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000055443322"),
    tax_number="21/315/77801",
    managers="Inhaber: Bernd Sonnenschein",
)
UMZUG = _sender(
    "Umzüge Express Nord GmbH",
    "Logistikring 30",
    "12355 Musterstadt",
    Style("sans", (0, 70, 140), "bars", "band", "Ihr Umzug in guten Händen"),
    phone="Telefon 01234 600 700",
    email="angebot@umzuege-express.example",
    bank="Hansebank AG",
    iban=ids.iban("DE", "300400000112233445"),
    register="Amtsgericht Musterstadt HRB 5120",
    vat_id=ids.vat_id("50213847"),
    managers="Geschäftsführerin: Sabine Ortmann",
)

# Shopping.

BERGMANN = _sender(
    "Versandhaus Bergmann GmbH",
    "Versandallee 100",
    "33100 Paketstadt",
    Style("sans", (20, 40, 90), "monogram", "right", "Alles für Haus und Garten"),
    short="Bergmann",
    phone="Kundenservice 0800 777 1234",
    email="kundenservice@bergmann-versand.example",
    web="www.bergmann-versand.example",
    bank="Hansebank AG",
    iban=ids.iban("DE", "300400000777123456"),
    register="Amtsgericht Paketstadt HRB 10077",
    vat_id=ids.vat_id("77123498"),
    managers="Geschäftsführung: Clara Bergmann, Leon Fuchs",
)
TECHNIKWELT = _sender(
    "Technikwelt Online GmbH",
    "Chipstraße 42",
    "80331 Beispielhausen",
    Style("sans", (30, 60, 150), "bars", "band", "Elektronik zum besten Preis"),
    short="TECHNIKWELT",
    phone="Service 089 1234 5000",
    email="service@technikwelt.example",
    web="www.technikwelt.example",
    bank="Hansebank AG",
    iban=ids.iban("DE", "300400000555000111"),
    register="Amtsgericht Beispielhausen HRB 230411",
    vat_id=ids.vat_id("23041188"),
    managers="Geschäftsführer: Tobias Reiter",
)
MOEBEL = _sender(
    "Möbelhaus Wohnfreude GmbH & Co. KG",
    "Gewerbepark 5",
    "12360 Musterstadt-Ost",
    Style("serif", (110, 70, 40), "triangle", "right", "Wohnen mit Freude"),
    short="Wohnfreude",
    phone="Telefon 01234 8800",
    email="service@wohnfreude.example",
    web="www.wohnfreude.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000812345670"),
    register="Amtsgericht Musterstadt HRA 1789",
    vat_id=ids.vat_id("17891234"),
    managers="pers. haftende Ges.: Wohnfreude Verwaltungs GmbH",
)
CLOUDBERRY = _sender(
    "Cloudberry Hosting Inc.",
    "500 Harbor Street, Suite 12",
    "Portsmouth, NH 03801, USA",
    Style("sans", (120, 50, 160), "circle", "left", "Fast hosting for everyone"),
    short="Cloudberry",
    email="billing@cloudberry-hosting.example",
    web="cloudberry-hosting.example",
)
NORTHWIND = _sender(
    "Northwind Software Ltd.",
    "14 Mill Lane",
    "Cambridge CB2 1RX, United Kingdom",
    Style("serif", (0, 90, 70), "rings", "right", "Tools for small offices"),
    short="Northwind Software",
    email="sales@northwind-software.example",
    web="www.northwind-software.example",
    register="Registered in England No. 09876543",
    extra=("VAT Reg. No. GB 123 4567 89",),
)

# Bank and finance.

SPARKASSE = _sender(
    "Sparkasse Musterstadt",
    "Marktplatz 1",
    "12345 Musterstadt",
    Style("sans", (20, 90, 140), "monogram", "right"),
    phone="Telefon 01234 100-0",
    email="service@sparkasse-musterstadt.example",
    web="www.sparkasse-musterstadt.example",
    bic="SPMUDE2MXXX",
    register="Anstalt des öffentlichen Rechts, Amtsgericht Musterstadt HRA 300",
    vat_id=ids.vat_id("30012345"),
    managers="Vorstand: Hans Gruber (Vors.), Mia Klose",
)
HANSEBANK = _sender(
    "Hansebank AG",
    "Kaistraße 9",
    "20457 Hafenstadt",
    Style("serif", (10, 50, 100), "wave", "left", "Ihre Bank im Norden"),
    phone="Telefon 040 555 000",
    email="karten@hansebank.example",
    web="www.hansebank.example",
    register="Amtsgericht Hafenstadt HRB 45678",
    vat_id=ids.vat_id("45678123"),
    managers="Vorstand: Dr. Karin Möller (Vors.), Felix Brandt",
)
DIREKTBANK = _sender(
    "Direktbank Nord AG",
    "Am Kanal 77",
    "24103 Förderstadt",
    Style("sans", (0, 130, 80), "circle", "band", "Banking ohne Umwege"),
    phone="Telefon 0431 999 888",
    email="kontakt@direktbank-nord.example",
    web="www.direktbank-nord.example",
    register="Amtsgericht Förderstadt HRB 7788",
    managers="Vorstand: Jonas Petersen",
)
BAUSPAR = _sender(
    "Bausparkasse Musterland AG",
    "Sparerweg 2",
    "12345 Musterstadt",
    Style("sans", (0, 80, 160), "triangle", "right", "Wir bauen auf Sie"),
    phone="Telefon 01234 222 333",
    email="service@bausparkasse-musterland.example",
    register="Amtsgericht Musterstadt HRB 900",
    vat_id=ids.vat_id("90012233"),
    managers="Vorstand: Ulrike Sommer, Kai Albers",
)
AUTOBANK = _sender(
    "AutoFinanz Bank GmbH",
    "Motorenstraße 11",
    "38440 Werkstadt",
    Style("sans", (40, 40, 40), "bars", "left", "Finanzierung für Ihr Fahrzeug"),
    phone="Telefon 05361 400 400",
    email="kredit@autofinanz.example",
    register="Amtsgericht Werkstadt HRB 1203",
    managers="Geschäftsführer: Nils Becker",
)

# Work.

BRUECKNER = _sender(
    "Brückner Maschinenbau GmbH",
    "Industriestraße 40",
    "12357 Musterstadt",
    Style("sans", (0, 60, 120), "diamond", "right", "Präzision seit 1962"),
    short="BRÜCKNER",
    phone="Telefon 01234 5050-0",
    email="personal@brueckner-maschinenbau.example",
    web="www.brueckner-maschinenbau.example",
    bank="Hansebank AG",
    iban=ids.iban("DE", "300400000123123123"),
    register="Amtsgericht Musterstadt HRB 1962",
    vat_id=ids.vat_id("19621962"),
    managers="Geschäftsführung: Anja Brückner, Ralf Ostendorf",
)
STADT_PERSONAL = _sender(
    "Stadt Musterstadt",
    "Rathausplatz 1",
    "12345 Musterstadt",
    Style("serif", (130, 0, 30), "monogram", "left", "Der Oberbürgermeister · Personalamt"),
    phone="Telefon 01234 115",
    email="personalamt@musterstadt.example",
    web="www.musterstadt.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000000115115"),
)

# Insurance.

HANSE_VERS = _sender(
    "Hanse Versicherung AG",
    "Ankerplatz 4",
    "20459 Hafenstadt",
    Style("serif", (0, 60, 110), "wave", "right", "Sicher wie ein Hafen"),
    short="Hanse Versicherung",
    phone="Telefon 040 300 300",
    email="kundenservice@hanse-versicherung.example",
    web="www.hanse-versicherung.example",
    bank="Hansebank AG",
    iban=ids.iban("DE", "300400000300300300"),
    register="Amtsgericht Hafenstadt HRB 3003",
    managers="Vorstand: Lars Jansen (Vors.), Eva Kruse",
    extra=("Versicherungsteuer-Nr. 807/V90807012345",),
)
GESUNDKASSE = _sender(
    "Gesundkasse BKK",
    "Vitalstraße 12",
    "12345 Musterstadt",
    Style("sans", (0, 140, 110), "circle", "left", "Die Krankenkasse für Musterland"),
    phone="Telefon 01234 800 900",
    email="service@gesundkasse.example",
    web="www.gesundkasse.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000088990011"),
    managers="Vorstand: Dr. Sven Richter",
    extra=("Körperschaft des öffentlichen Rechts",),
)
KRAFTSCHUTZ = _sender(
    "Kraftschutz Versicherung AG",
    "Am Ring 50",
    "50667 Domstadt",
    Style("sans", (230, 100, 0), "triangle", "band", "Kfz-Versicherung"),
    short="KRAFTSCHUTZ",
    phone="Telefon 0221 700 800",
    email="kfz@kraftschutz.example",
    web="www.kraftschutz.example",
    bank="Hansebank AG",
    iban=ids.iban("DE", "300400000700800900"),
    register="Amtsgericht Domstadt HRB 7008",
    managers="Vorstand: Marc Vogel",
)
VORSORGE = _sender(
    "Vorsorge Leben AG",
    "Rentenplatz 3",
    "70173 Schwabenstadt",
    Style("serif", (90, 40, 110), "rings", "right", "Gemeinsam vorsorgen"),
    phone="Telefon 0711 220 330",
    email="service@vorsorge-leben.example",
    register="Amtsgericht Schwabenstadt HRB 2203",
    managers="Vorstand: Dr. Helene Graf",
)

# Authorities.

FINANZAMT = _sender(
    "Finanzamt Musterstadt",
    "Steuerplatz 1",
    "12345 Musterstadt",
    Style("sans", (0, 0, 0), "none", "left"),
    phone="Telefon 01234 9000-0",
    email="poststelle@fa-musterstadt.example",
    bank="Bundesbank, Filiale Musterstadt",
    iban=ids.iban("DE", "120000000012345601"),
    bic="MARKDEF1120",
)
HAUPTZOLLAMT = _sender(
    "Hauptzollamt Musterstadt",
    "Zollhof 2",
    "12345 Musterstadt",
    Style("sans", (0, 0, 0), "none", "left"),
    phone="Telefon 01234 7700-0",
    email="kraftfahrzeugsteuer@hza-musterstadt.example",
    bank="Bundesbank, Filiale Musterstadt",
    iban=ids.iban("DE", "120000000012345602"),
    bic="MARKDEF1120",
)
STADT = _sender(
    "Stadt Musterstadt",
    "Rathausplatz 1",
    "12345 Musterstadt",
    Style("serif", (130, 0, 30), "monogram", "left", "Der Oberbürgermeister"),
    phone="Telefon 01234 115",
    email="buergerservice@musterstadt.example",
    web="www.musterstadt.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000000115116"),
)
FAMILIENKASSE = _sender(
    "Familienkasse Musterland",
    "Kinderweg 1",
    "12340 Musterstadt",
    Style("sans", (0, 70, 130), "none", "left"),
    phone="Telefon 0800 4 5555 30",
    email="familienkasse-musterland@arbeit-beispiel.example",
)
RENTENKASSE = _sender(
    "Rentenkasse Musterland",
    "Ruhestandsallee 10",
    "12340 Musterstadt",
    Style("sans", (0, 60, 130), "bars", "left"),
    phone="Telefon 0800 1000 4800",
    email="info@rentenkasse-musterland.example",
)
BUSSGELD = _sender(
    "Landkreis Musterkreis",
    "Kreishaus, Am Wall 1",
    "12370 Kreisstadt",
    Style("serif", (40, 90, 40), "monogram", "left", "Zentrale Bußgeldstelle"),
    phone="Telefon 01235 600-0",
    email="bussgeldstelle@musterkreis.example",
    bank="Kreissparkasse Musterkreis",
    iban=ids.iban("DE", "250501000060000600"),
)

# Health.

DR_BEISPIEL = _sender(
    "Dr. med. Anna Beispiel",
    "Ärztehaus am Park, Parkstraße 3",
    "12345 Musterstadt",
    Style("serif", (0, 100, 140), "none", "center", "Fachärztin für Allgemeinmedizin"),
    phone="Telefon 01234 45 45 45",
    email="praxis@dr-beispiel.example",
    bank="Deutsche Ärztebank Musterstadt",
    iban=ids.iban("DE", "300606010004545450"),
    tax_number="21/280/45454",
)
ZAHNARZT = _sender(
    "Zahnarztpraxis Dr. Lehmann",
    "Lindenplatz 9",
    "12345 Musterstadt",
    Style("sans", (0, 150, 200), "circle", "center", "Dr. med. dent. Jonas Lehmann · Zahnarzt"),
    phone="Telefon 01234 67 67 67",
    email="praxis@zahnarzt-lehmann.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000067676767"),
)
KLINIKUM = _sender(
    "Klinikum Musterstadt",
    "Krankenhausstraße 1",
    "12345 Musterstadt",
    Style("sans", (0, 90, 150), "diamond", "right", "Klinik für Kinder- und Jugendmedizin"),
    phone="Telefon 01234 300-0",
    email="kinderklinik@klinikum-musterstadt.example",
    register="Amtsgericht Musterstadt HRB 3000",
    managers="Geschäftsführer: Prof. Dr. Uwe Hansen",
)
APOTHEKE = _sender(
    "Apotheke am Markt",
    "Marktplatz 6",
    "12345 Musterstadt",
    Style("sans", (200, 0, 30), "none", "center"),
    phone="Telefon 01234 21 21 21",
)
PHYSIO = _sender(
    "Physiotherapie Bewegung",
    "Sportplatzweg 4",
    "12345 Musterstadt",
    Style("sans", (100, 160, 0), "wave", "left", "Krankengymnastik · Manuelle Therapie"),
    phone="Telefon 01234 78 78 78",
    email="team@physio-bewegung.example",
    bank="Volksbank Musterland eG",
    iban=ids.iban("DE", "430600007878787878"),
    tax_number="21/260/78787",
)

# Everyday life.

TSV = _sender(
    "TSV Musterstadt 1890 e.V.",
    "Sportplatzweg 1",
    "12345 Musterstadt",
    Style("serif", (0, 100, 50), "monogram", "left", "Turnen · Fußball · Schwimmen"),
    short="TSV Musterstadt 1890",
    email="mitglieder@tsv-musterstadt.example",
    web="www.tsv-musterstadt.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000018901890"),
    register="Amtsgericht Musterstadt VR 189",
    managers="1. Vorsitzende: Gisela Brandt",
)
TIERHEIM = _sender(
    "Tierschutzverein Musterstadt e.V.",
    "Am Tierheim 1",
    "12345 Musterstadt",
    Style("sans", (180, 100, 0), "circle", "left", "Tierheim Musterstadt"),
    email="spenden@tierheim-musterstadt.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000044332211"),
    register="Amtsgericht Musterstadt VR 512",
    tax_number="21/250/51200",
)
REGIOBAHN = _sender(
    "RegioBahn Musterland GmbH",
    "Bahnhofsplatz 1",
    "12345 Musterstadt",
    Style("sans", (0, 110, 80), "triangle", "band", "Gut ankommen"),
    short="RegioBahn",
    web="www.regiobahn.example",
    register="Amtsgericht Musterstadt HRB 1001",
    vat_id=ids.vat_id("10011001"),
)
SKYNORD = _sender(
    "SkyNord Airlines",
    "Airport Road 1",
    "Copenhagen, Denmark",
    Style("sans", (0, 50, 120), "triangle", "band", "Fly the north"),
    web="www.skynord.example",
)
AUTOHAUS = _sender(
    "Autohaus Weber GmbH & Co. KG",
    "Ringstraße 88",
    "12359 Musterstadt",
    Style("sans", (60, 60, 60), "monogram", "right", "Service · Verkauf · Teile"),
    short="Autohaus Weber",
    phone="Telefon 01234 4040",
    email="service@autohaus-weber.example",
    web="www.autohaus-weber.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000040404040"),
    register="Amtsgericht Musterstadt HRA 2040",
    vat_id=ids.vat_id("20404040"),
    managers="Geschäftsführer: Michael Weber",
)
PRUEFDIENST = _sender(
    "Prüfdienst Nord e.V.",
    "Prüfweg 2",
    "12359 Musterstadt",
    Style("sans", (0, 80, 160), "diamond", "left", "Fahrzeugprüfung"),
    phone="Telefon 01234 9393",
    web="www.pruefdienst-nord.example",
    register="Amtsgericht Musterstadt VR 77",
    vat_id=ids.vat_id("77001122"),
)
ANWALT = _sender(
    "Meier, Müller & Partner Rechtsanwälte",
    "Justizplatz 4",
    "12345 Musterstadt",
    Style(
        "serif",
        (60, 60, 90),
        "none",
        "center",
        "Rechtsanwälte · Fachanwälte für Miet- und Verkehrsrecht",
    ),
    short="Meier, Müller & Partner",
    phone="Telefon 01234 51 52 53",
    email="kanzlei@mmp-recht.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000051525354"),
    register="Partnerschaftsregister Musterstadt PR 31",
    vat_id=ids.vat_id("51525354"),
)
MUSIKSCHULE = _sender(
    "Musikschule Klangfarbe",
    "Notenweg 7",
    "12345 Musterstadt",
    Style("serif", (150, 0, 90), "circle", "left", "Unterricht für alle Altersstufen"),
    email="info@musikschule-klangfarbe.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000077665544"),
    tax_number="21/290/11223",
)
SCHULE = _sender(
    "Grundschule am Park",
    "Schulstraße 10",
    "12345 Musterstadt",
    Style("sans", (40, 120, 40), "triangle", "left", "Städtische Grundschule"),
    phone="Telefon 01234 55 10 20",
    email="sekretariat@gs-am-park.example",
)
VHS = _sender(
    "Volkshochschule Musterstadt",
    "Bildungszentrum, Lernweg 1",
    "12345 Musterstadt",
    Style("sans", (230, 120, 0), "bars", "right", "Lernen ein Leben lang"),
    phone="Telefon 01234 115-400",
    email="anmeldung@vhs-musterstadt.example",
    web="www.vhs-musterstadt.example",
    bank="Sparkasse Musterstadt",
    iban=ids.iban("DE", "250500000000115400"),
)
SONNENKRAFT = _sender(
    "Sonnenkraft Solar Direkt GmbH",
    "Lichtstraße 1",
    "99084 Sonnental",
    Style("sans", (240, 160, 0), "circle", "band", "Ihr Dach kann mehr!"),
    phone="Gratis-Hotline 0800 765 765",
    web="www.sonnenkraft-solar.example",
    register="Amtsgericht Sonnental HRB 5050",
)
GEWINN = _sender(
    "Glücksbote Verlag GmbH",
    "Postfach 10 20 30",
    "60000 Messestadt",
    Style("serif", (180, 0, 0), "diamond", "center", "Gewinnbenachrichtigung"),
)
PRIVATE_SELLER = _sender(
    "Thomas Schreiber",
    "Ahornweg 21",
    "12346 Musterstadt",
    Style("sans", (0, 0, 0), "none", "left"),
)
HOTEL = _sender(
    "Harbour View Hotel",
    "2 Quay Street",
    "Bristol BS1 4RD, United Kingdom",
    Style("serif", (0, 70, 90), "wave", "center", "Harbour View Hotel · Bristol"),
    phone="+44 117 000 0000",
    email="frontdesk@harbourview-hotel.example",
    register="Registered in England No. 04455667",
    extra=("VAT Reg. No. GB 987 6543 21",),
)

# Shops whose documents are till receipts (their head is the receipt's, not a letterhead).

FRISCHMARKT = _sender(
    "Frischmarkt KG", "Hauptstraße 50", "12345 Musterstadt", Style("sans", (0, 120, 0))
)
BAUMARKT = _sender(
    "Baumarkt Hammer GmbH", "Gewerbestraße 3", "12349 Musterstadt", Style("sans", (220, 100, 0))
)
DROGERIE = _sender(
    "Drogerie Sonne e.K.", "Bahnhofstraße 12", "12345 Musterstadt", Style("sans", (0, 90, 170))
)
TANKSTELLE = _sender(
    "Tankstelle Nord GmbH", "Ringstraße 2", "12359 Musterstadt", Style("sans", (200, 0, 0))
)
BAECKEREI = _sender(
    "Bäckerei Krume", "Kirchplatz 3", "12345 Musterstadt", Style("serif", (140, 80, 20))
)
CAFE = _sender(
    "Café Lindenblüte", "Lindenallee 2", "12345 Musterstadt", Style("serif", (90, 60, 30))
)

BUCHHANDLUNG = _sender(
    "Buchhandlung Seitenweise GmbH",
    "Am Markt 11",
    "12345 Musterstadt",
    Style("serif", (120, 30, 30), "monogram", "center", "Bücher · Zeitschriften · Geschenke"),
    short="Buchhandlung Seitenweise",
    phone="Telefon 01234 30 30 30",
    email="info@seitenweise.example",
    register="Amtsgericht Musterstadt HRB 3131",
    vat_id=ids.vat_id("31313131"),
    managers="Geschäftsführerin: Marlene Kurz",
)

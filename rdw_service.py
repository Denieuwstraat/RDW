"""Logica voor de Streamlit-interface op de RDW OSINT-verkenner.

Alle externe RDW-aanroepen en geografische benaderingen hergebruiken rdw_core.py.
De resultaten zijn RDW-registraties, geen vastgestelde milieubelastende activiteiten.
"""
from __future__ import annotations

import csv
import datetime as dt
import io
import tempfile
import urllib.parse
from collections import Counter, defaultdict
from pathlib import Path
from typing import Any

import rdw_core as rdw


COLUMNS = [
    'Gemeente', 'RDW-volgnummer', 'Bedrijfsnaam', 'Gevelnaam', 'Adres',
    'Postcode', 'RDW-plaats', 'Erkenningen', 'MBA-signaal',
    'Onderzoeksrichting', 'Dubbel adres RDW',
    'Gemeentekoppeling', 'Bron bedrijf', 'Bron erkenningen', 'Peildatum',
]


def lees_rdw_csv(bestandsinhoud: bytes) -> list[dict[str, Any]]:
    """Leest RDW's eigen CSV-export (ook BOM en puntkomma's) zonder schijfgebruik."""
    if not bestandsinhoud:
        raise ValueError('Het CSV-bestand is leeg.')
    try:
        content = bestandsinhoud.decode('utf-8-sig')
    except UnicodeDecodeError as exc:
        raise ValueError('CSV moet als UTF-8 zijn opgeslagen (zoals de RDW-export).') from exc
    try:
        delimiter = csv.Sniffer().sniff(content[:8000], delimiters=',;\t').delimiter
    except csv.Error:
        delimiter = ','
    records = list(csv.DictReader(io.StringIO(content), delimiter=delimiter))
    if not records:
        raise ValueError('Geen gegevensregels in het CSV-bestand.')
    normalized = rdw.normaliseer_bron(records)
    if 'volgnummer' not in normalized[0]:
        raise ValueError('Kolom "Volgnummer" ontbreekt in het RDW-bestand.')
    return normalized


def selecteer_bedrijven(landelijke_bedrijven: list[dict], selectie: list[str],
                        plaatsindex: dict[str, str]) -> tuple[list[dict], Counter]:
    """Neemt alleen de geselecteerde gemeenten op; behoudt matchwaarschuwing."""
    geselecteerd: list[dict] = []
    mogelijke_homoniemen: Counter = Counter()
    for bron in landelijke_bedrijven:
        gemeente, methode = rdw.bepaal_gemeente(bron, plaatsindex)
        if gemeente in selectie:
            item = dict(bron)
            item['_gemeente'] = gemeente
            item['_methode'] = methode
            geselecteerd.append(item)
        elif not gemeente and rdw.standaard(bron.get('plaats')) in plaatsindex:
            mogelijke_homoniemen[str(bron.get('plaats', ''))] += 1
    return geselecteerd, mogelijke_homoniemen


def maak_tabel(bedrijven: list[dict], erkenningen: list[dict], peildatum: str | None = None) -> list[dict]:
    """Vertaal hetzelfde RDW-bronmateriaal naar rijen voor de Streamlit-tabel."""
    per_volgnummer: dict[str, set[str]] = defaultdict(set)
    for regel in erkenningen:
        nummer = str(regel.get('volgnummer', '')).strip()
        if nummer:
            per_volgnummer[nummer].add(str(regel.get('erkenning', '')).strip())
    per_adres = Counter((b['_gemeente'], rdw.postcode(b), str(b.get('huisnummer', '')).strip(),
                         rdw.standaard(b.get('huisnummer_toevoeging'))) for b in bedrijven)
    vandaag = peildatum or dt.date.today().isoformat()
    resultaat = []
    for bedrijf in sorted(bedrijven, key=lambda b: (
        b['_gemeente'], rdw.standaard(b.get('plaats')), rdw.standaard(b.get('straat')),
        str(b.get('huisnummer', '')), str(b.get('volgnummer', ''))
    )):
        volgnummer = str(bedrijf.get('volgnummer', '')).strip()
        typen = sorted(x for x in per_volgnummer.get(volgnummer, set()) if x)
        niveau, reden = rdw.indicatie(bedrijf, typen)
        toevoeging = str(bedrijf.get('huisnummer_toevoeging') or '').strip()
        nummer = str(bedrijf.get('huisnummer') or '').strip()
        straat = str(bedrijf.get('straat') or '').strip()
        adres = f'{straat} {nummer}{(" " + toevoeging) if toevoeging else ""}'.strip()
        is_dubbel = per_adres[(bedrijf['_gemeente'], rdw.postcode(bedrijf), nummer,
                               rdw.standaard(toevoeging))] > 1
        param = urllib.parse.quote(volgnummer, safe='')
        resultaat.append({
            'Gemeente': bedrijf['_gemeente'],
            'RDW-volgnummer': volgnummer,
            'Bedrijfsnaam': str(bedrijf.get('naam_bedrijf') or ''),
            'Gevelnaam': str(bedrijf.get('gevelnaam') or ''),
            'Adres': adres,
            'Postcode': rdw.postcode(bedrijf),
            'RDW-plaats': str(bedrijf.get('plaats') or ''),
            'Erkenningen': '; '.join(typen),
            'MBA-signaal': niveau,
            'Onderzoeksrichting': reden,
            'Dubbel adres RDW': 'Ja' if is_dubbel else 'Nee',
            'Gemeentekoppeling': bedrijf.get('_methode', ''),
            'Bron bedrijf': f'https://opendata.rdw.nl/resource/{rdw.BEDRIJVEN_ID}.json?volgnummer={param}',
            'Bron erkenningen': f'https://opendata.rdw.nl/resource/{rdw.ERKENNINGEN_ID}.json?volgnummer={param}',
            'Peildatum': vandaag,
        })
    return resultaat


def filter_tabel(rijen: list[dict], zoektekst: str = '', niveaus: list[str] | None = None,
                 alleen_dubbele_adressen: bool = False) -> list[dict]:
    delen = zoektekst.casefold().split()
    niveaus_set = set(niveaus) if niveaus is not None else None
    resultaten = []
    for rij in rijen:
        if niveaus_set is not None and rij['MBA-signaal'] not in niveaus_set:
            continue
        if alleen_dubbele_adressen and rij['Dubbel adres RDW'] != 'Ja':
            continue
        tekst = ' '.join(str(rij.get(k, '')) for k in (
            'Gemeente', 'Bedrijfsnaam', 'Gevelnaam', 'Adres', 'Postcode',
            'RDW-plaats', 'Erkenningen', 'RDW-volgnummer'
        )).casefold()
        if all(deel in tekst for deel in delen):
            resultaten.append(rij)
    return resultaten


def samenvatting(rijen: list[dict], gemeenten: list[str]) -> list[dict]:
    per_gemeente = defaultdict(list)
    for rij in rijen:
        per_gemeente[rij['Gemeente']].append(rij)
    return [
        {
            'Gemeente': gemeente,
            'RDW-bedrijven': len(per_gemeente[gemeente]),
            'Sterkere aanwijzing': sum(x['MBA-signaal'] == 'Sterkere aanwijzing'
                                      for x in per_gemeente[gemeente]),
            'Middel': sum(x['MBA-signaal'] == 'Middel' for x in per_gemeente[gemeente]),
            'Laag': sum(x['MBA-signaal'] == 'Laag' for x in per_gemeente[gemeente]),
        }
        for gemeente in gemeenten
    ]


def excel_bytes(bedrijven: list[dict], erkenningen: list[dict], gemeenten: list[str]) -> bytes:
    """Exporteert met de bestaande geteste Excel-functie, in een tijdelijk bestand.

    Alleen de gevraagde selectie wordt meegenomen. Geen RDW-bestanden blijven achter.
    """
    if not bedrijven:
        raise ValueError('Geen bedrijven geselecteerd; er is niets te exporteren.')
    nummers = {str(b.get('volgnummer', '')) for b in bedrijven}
    bijbehorende_erkenningen = [r for r in erkenningen if str(r.get('volgnummer', '')) in nummers]
    with tempfile.TemporaryDirectory(prefix='rdw_export_') as mapnaam:
        bestand = Path(mapnaam) / 'RDW_Export.xlsx'
        rdw.bouw_excel(bedrijven, bijbehorende_erkenningen, gemeenten, bestand)
        return bestand.read_bytes()

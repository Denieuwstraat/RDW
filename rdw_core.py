#!/usr/bin/env python3
"""RDW OSINT-inventarisatie voor één, meerdere of alle geconfigureerde gemeenten.

Python 3.9+, geen aanvullende Python-pakketten.
Gebruik interactief:   python rdw_core.py
Gebruik opdrachtregel: python rdw_core.py --gemeente "Bergen op Zoom" --gemeente "Roosendaal"
                    of python rdw_core.py --alle
Offline CSV-test:    python rdw_core.py --alle --bedrijven-csv bedrijven.csv --erkenningen-csv erkenningen.csv

Bronnen: https://opendata.rdw.nl/d/5k74-3jha en https://opendata.rdw.nl/d/nmwb-dqkz
LET OP: RDW geeft plaatsnamen, GEEN gemeente-indeling; de meegeleverde woonplaatslijst
is bewerkbaar en kan onvolledig zijn. Postcodebeperkingen op een aantal homoniemen.
RDW-erkenningen bewijzen op zichzelf niet dat op een locatie een milieubelastende activiteit plaatsvindt.
"""
from __future__ import annotations
import argparse
import csv
import datetime as dt
import io
import json
import re
import sys
import time
import unicodedata
import urllib.error
import urllib.parse
import urllib.request
import zipfile
from collections import Counter, defaultdict
from pathlib import Path
from xml.sax.saxutils import escape

ROOT = Path(__file__).resolve().parent
CONFIG = ROOT / 'gemeenten.json'
RDW = 'https://opendata.rdw.nl/resource/'
BEDRIJVEN_ID = '5k74-3jha'
ERKENNINGEN_ID = 'nmwb-dqkz'
BATCH = 15000

# Identieke plaatsnamen buiten de meegeleverde regio: laat deze niet onbedoeld door.
# Controleer bij gebruik van deze namen ook de volledige fysieke adreslocatie.
HOMONIEM_POSTCODE = {
    'ALPHEN': lambda pc: pc == '5131',
    'RIJSWIJK': lambda pc: pc == '4284',
    'HEUSDEN': lambda pc: pc == '5256',
    'OOSTERHOUT': lambda pc: pc.startswith('490'),
    'STEENBERGEN': lambda pc: pc.startswith('465'),
    'OUDE MOLEN': lambda pc: pc == '4796',
}


def standaard(tekst):
    tekst = unicodedata.normalize('NFKD', str(tekst or ''))
    return ''.join(c for c in tekst if not unicodedata.combining(c)).strip().upper().replace('’', "'")


def werkgebied():
    data = json.loads(CONFIG.read_text(encoding='utf-8'))
    gebieden = {k: v for k, v in data.items() if not k.startswith('_')}
    if not gebieden:
        raise ValueError('Het configuratiebestand bevat geen gemeenten.')
    for naam, plaatsen in gebieden.items():
        if not isinstance(plaatsen, list) or not plaatsen:
            raise ValueError(f'Geen geldige woonplaatsen voor gemeente {naam!r}.')
    inverse = defaultdict(set)
    for gemeente, plaatsen in gebieden.items():
        for plaats in plaatsen:
            inverse[standaard(plaats)].add(gemeente)
    dubbel = {plaats: sorted(g) for plaats, g in inverse.items() if len(g) > 1}
    if dubbel:
        raise ValueError('Woonplaats gekoppeld aan meerdere gemeenten: ' + str(dubbel))
    return gebieden, {p: next(iter(g)) for p, g in inverse.items()}


def keuzes(args, gebieden):
    if args.alle:
        return list(gebieden)
    if args.gemeente:
        return [naam_zoeken(waarde, gebieden) for waarde in args.gemeente]
    print('\nRDW Milieuverkenner\n')
    for nr, gemeente in enumerate(gebieden, 1):
        print(f'{nr:>2}. {gemeente}')
    print('\nTyp 0 voor ALLE gemeenten, of bijvoorbeeld 4,19,21 voor meerdere gemeenten.')
    antwoord = input('Gemeente(n): ').strip()
    if not antwoord:
        raise ValueError('Geen selectie gemaakt.')
    if antwoord.casefold() in ('0','alle','alles'):
        return list(gebieden)
    uniek = []
    for waarde in antwoord.split(','):
        waarde = waarde.strip()
        keuze = list(gebieden)[int(waarde)-1] if waarde.isdigit() and 1 <= int(waarde) <= len(gebieden) else naam_zoeken(waarde, gebieden)
        if keuze not in uniek:
            uniek.append(keuze)
    return uniek


def naam_zoeken(zoektekst, gebieden):
    resultaat = [naam for naam in gebieden if standaard(naam) == standaard(zoektekst)]
    if not resultaat:
        raise ValueError(f'Onbekende gemeente: {zoektekst!r}')
    return resultaat[0]


def api_lijst(dataset, params=None, retries=3):
    query = urllib.parse.urlencode(params or {})
    url = f'{RDW}{dataset}.json' + ('?' + query if query else '')
    for poging in range(retries):
        try:
            request = urllib.request.Request(url, headers={
                'User-Agent': 'RDW-Milieuverkenner/2.1 (openbare gegevens)',
                'Accept': 'application/json'})
            with urllib.request.urlopen(request, timeout=90) as result:
                data = json.loads(result.read().decode('utf-8-sig'))
            if not isinstance(data, list):
                raise ValueError('API leverde geen JSON-lijst op.')
            return data
        except (OSError, ValueError, json.JSONDecodeError) as exc:
            if poging == retries - 1:
                raise RuntimeError(f'Ophalen RDW mislukt: {url}\n{exc}') from exc
            time.sleep((poging + 1) * 1.2)
    raise RuntimeError('Niet bereikbaar')


def alle_paginas(dataset, max_paginas=200):
    resultaat = []
    for pagina in range(max_paginas):
        batch = api_lijst(dataset, {'$limit': BATCH, '$offset': pagina*BATCH,
                                     '$order': 'volgnummer'})
        resultaat.extend(batch)
        if len(batch) < BATCH:
            return resultaat
    raise RuntimeError('Te veel RDW-records; gestopt om onvolledige landelijke data te vermijden.')


def csv_inlezen(bestand):
    path = Path(bestand)
    content = path.read_text(encoding='utf-8-sig')
    sample = content[:4000]
    try:
        sep = csv.Sniffer().sniff(sample, delimiters=',;\t').delimiter
    except csv.Error:
        sep = ','
    reader = csv.DictReader(io.StringIO(content), delimiter=sep)
    return [dict(row) for row in reader]


def normaliseer_bron(regels):
    """Accepteer RDW CSV-export met displaynamen én RDW API-veldlabels."""
    sleutels = {'Volgnummer':'volgnummer','Naam bedrijf':'naam_bedrijf',
                'Gevelnaam':'gevelnaam', 'Straat':'straat','Huisnummer':'huisnummer',
                'Huisnummer toevoeging':'huisnummer_toevoeging',
                'Postcode numeriek':'postcode_numeriek',
                'Postcode alfanumeriek':'postcode_alfanumeriek',
                'Plaats':'plaats','Erkenning':'erkenning'}
    return [{sleutels.get(k.strip(), k.strip().lower().replace(' ','_')): v
             for k, v in row.items() if k} for row in regels]


def postcode4(record):
    pc = re.sub(r'\D','',str(record.get('postcode_numeriek','')))
    return pc[:4]


def postcode(record):
    post = postcode4(record)
    letters = re.sub(r'[^A-Z]','', standaard(record.get('postcode_alfanumeriek','')))
    return (post + ' ' + letters).strip()


def bepaal_gemeente(record, plaatsindex):
    plaats = standaard(record.get('plaats'))
    gemeente = plaatsindex.get(plaats)
    if not gemeente:
        return None, 'Geen woonplaatsmatch'
    if plaats in HOMONIEM_POSTCODE and not HOMONIEM_POSTCODE[plaats](postcode4(record)):
        return None, 'Homonieme plaats; postcode buiten geconfigureerde regio'
    return gemeente, 'Op basis van RDW-plaatsnaam (benadering)'


def erkenningen_ophalen(ids, csv_pad=None):
    if csv_pad:
        alle = normaliseer_bron(csv_inlezen(csv_pad))
        ids = set(map(str,ids))
        return [r for r in alle if str(r.get('volgnummer','')) in ids]
    ids = sorted({str(n) for n in ids if str(n).isdigit()}, key=int)
    if not ids:
        return []
    # Voor een kleine selectie efficiënt alleen relevante RDW-erkenningen opvragen.
    if len(ids) > 600:
        print('Veel bedrijven geselecteerd; haal één keer het landelijke erkenningenbestand op ...')
        alle = alle_paginas(ERKENNINGEN_ID)
        nummers = set(ids)
        return [r for r in alle if str(r.get('volgnummer','')) in nummers]
    rows = []
    try:
        for i in range(0,len(ids),50):
            subset = ids[i:i+50]
            where = 'volgnummer in(' + ','.join(subset) + ')'
            rows.extend(api_lijst(ERKENNINGEN_ID, {'$where':where,'$limit':50000}))
    except RuntimeError as exc:
        print('Gefilterde erkenningen-query mislukt; probeer landelijke download:',exc)
        alle = alle_paginas(ERKENNINGEN_ID)
        nummers = set(ids)
        rows = [r for r in alle if str(r.get('volgnummer','')) in nummers]
    return rows


def indicatie(bedrijf, erkenningen):
    erken_tekst = ' '.join(erkenningen).lower()
    naam = (str(bedrijf.get('naam_bedrijf',''))+' '+str(bedrijf.get('gevelnaam',''))).lower()
    erken_signaal = any(woord in erken_tekst for woord in
                         ('apk','tachograf','gasinstall','inbouw','ombouw','keuring'))
    naam_signaal = any(woord in naam for woord in
                        ('garage','autoservice','autotechn','reparat','onderhoud','schade',
                         'banden','carrosserie','motorservice','truckservice'))
    if erken_signaal:
        return 'Sterkere aanwijzing','Mogelijke voertuigkeuring of werkplaats; feitelijke werkzaamheden controleren'
    if naam_signaal:
        return 'Middel','Bedrijfsnaam suggereert werkplaats; RDW-erkenning bewijst geen MBA'
    return 'Laag','RDW-registratie op zichzelf bewijst geen garageactiviteiten'


def xml_tekst(waarde):
    tekst = str('' if waarde is None else waarde)
    tekst = ''.join(ch for ch in tekst if ord(ch) >= 32 or ch in '\t\r\n')
    # Geen formule-injectie, want alle cellen worden als letterlijke tekst opgeslagen.
    return escape(tekst, {'"':'&quot;'})


def colnaam(n):
    naam = ''
    while n:
        n,rest = divmod(n-1,26)
        naam = chr(65+rest)+naam
    return naam


def tabblad_xml(data, widths, freeze=True):
    kolommen = ''.join(f'<col min="{i}" max="{i}" width="{breedte}" customWidth="1"/>'
                       for i, breedte in enumerate(widths,1))
    rows = []
    for r, row in enumerate(data,1):
        cells = []
        for c, value in enumerate(row,1):
            if value is None or value == '':
                continue
            stijl = ' s="1"' if r==1 else ''
            cells.append(f'<c r="{colnaam(c)}{r}"{stijl} t="inlineStr"><is><t>{xml_tekst(value)}</t></is></c>')
        rows.append(f'<row r="{r}"{(" ht=\"26\" customHeight=\"1\"" if r==1 else "")}>{"".join(cells)}</row>')
    filter_range = f'A1:{colnaam(len(data[0]))}{len(data)}'
    return ('<?xml version="1.0" encoding="UTF-8" standalone="yes"?>'
            '<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
            '<sheetViews><sheetView workbookViewId="0">'+
            ('<pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/>' if freeze else '')+
            '</sheetView></sheetViews><cols>'+kolommen+'</cols><sheetData>'+
            ''.join(rows)+'</sheetData><autoFilter ref="'+filter_range+'"/></worksheet>')


def schrijf_xlsx(pad, tabs):
    pad.parent.mkdir(parents=True, exist_ok=True)
    n = len(tabs)
    ct = ('<?xml version="1.0" encoding="UTF-8"?>'
          '<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">'
          '<Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>'
          '<Default Extension="xml" ContentType="application/xml"/>'
          '<Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>'
          '<Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>'+
          ''.join(f'<Override PartName="/xl/worksheets/sheet{i}.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>' for i in range(1,n+1))+'</Types>')
    wb_xml = ('<?xml version="1.0" encoding="UTF-8"?>'
              '<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships"><sheets>'+
              ''.join(f'<sheet name="{xml_tekst(naam)}" sheetId="{i}" r:id="rId{i}"/>' for i,(naam,_,_) in enumerate(tabs,1))+'</sheets></workbook>')
    rels = ('<?xml version="1.0" encoding="UTF-8"?>'
            '<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">'+
            ''.join(f'<Relationship Id="rId{i}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet{i}.xml"/>' for i in range(1,n+1))+
            f'<Relationship Id="rId{n+1}" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>'+'</Relationships>')
    style = ('<?xml version="1.0" encoding="UTF-8"?>'
             '<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">'
             '<fonts count="2"><font><sz val="11"/><name val="Aptos"/></font>'
             '<font><b/><sz val="11"/><color rgb="FFFFFFFF"/><name val="Aptos"/></font></fonts>'
             '<fills count="3"><fill><patternFill patternType="none"/></fill><fill><patternFill patternType="gray125"/></fill><fill><patternFill patternType="solid"><fgColor rgb="FF174B65"/></patternFill></fill></fills>'
             '<borders count="1"><border><left/><right/><top/><bottom/><diagonal/></border></borders>'
             '<cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>'
             '<cellXfs count="2"><xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>'
             '<xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyFill="1"/></cellXfs>'
             '</styleSheet>')
    with zipfile.ZipFile(pad,'w',zipfile.ZIP_DEFLATED) as z:
        z.writestr('[Content_Types].xml',ct)
        z.writestr('_rels/.rels','<?xml version="1.0" encoding="UTF-8"?><Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships"><Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/></Relationships>')
        z.writestr('xl/workbook.xml',wb_xml)
        z.writestr('xl/_rels/workbook.xml.rels',rels)
        z.writestr('xl/styles.xml',style)
        for i,(_,matrix,widths) in enumerate(tabs,1):
            z.writestr(f'xl/worksheets/sheet{i}.xml',tabblad_xml(matrix,widths))


def bouw_excel(bedrijven, erkenningen, selectie, pad):
    erken_by_id=defaultdict(set)
    for erk in erkenningen:
        erken_by_id[str(erk.get('volgnummer',''))].add(str(erk.get('erkenning','')))
    adressen = Counter((b['_gemeente'],postcode(b),str(b.get('huisnummer','')).strip(),
                        standaard(b.get('huisnummer_toevoeging',''))) for b in bedrijven)
    datum=dt.date.today().isoformat()
    header=['Gemeente','RDW-volgnummer','Bedrijfsnaam','Gevelnaam','Straat','Huisnr','Toevoeging',
            'Postcode','RDW-plaats','Erkenningen','MBA-signaal','Onderzoeksrichting',
            'Dubbel adres RDW','Gemeentekoppeling','Bron bedrijf',
            'Bron erkenningen','Peildatum']
    regels=[header]
    for b in sorted(bedrijven,key=lambda b:(b['_gemeente'],str(b.get('plaats','')),str(b.get('straat','')),
                                            str(b.get('huisnummer','')),str(b.get('volgnummer','')))):
        idx=str(b.get('volgnummer',''))
        er=sorted(erken_by_id[idx])
        niveau, reden=indicatie(b,er)
        dub = adressen[(b['_gemeente'],postcode(b),str(b.get('huisnummer','')).strip(),
                        standaard(b.get('huisnummer_toevoeging','')))]>1
        regels.append([b['_gemeente'],idx,b.get('naam_bedrijf',''),b.get('gevelnaam',''),
                       b.get('straat',''),b.get('huisnummer',''),b.get('huisnummer_toevoeging',''),
                       postcode(b),b.get('plaats',''),'; '.join(er),niveau,reden,
                       'Ja' if dub else 'Nee',b.get('_methode',''),
                       f'https://opendata.rdw.nl/resource/{BEDRIJVEN_ID}.json?volgnummer={urllib.parse.quote(idx)}',
                       f'https://opendata.rdw.nl/resource/{ERKENNINGEN_ID}.json?volgnummer={urllib.parse.quote(idx)}',datum])
    er_rows=[['Gemeente','RDW-volgnummer','Erkenning','Bron']]
    b_by_id={str(b.get('volgnummer','')):b for b in bedrijven}
    for r in sorted(erkenningen,key=lambda x:(str(x.get('volgnummer','')),str(x.get('erkenning','')))):
        idx=str(r.get('volgnummer',''))
        if idx in b_by_id:
            er_rows.append([b_by_id[idx]['_gemeente'],idx,r.get('erkenning',''),
                            f'https://opendata.rdw.nl/resource/{ERKENNINGEN_ID}.json?volgnummer={urllib.parse.quote(idx)}'])
    overzicht=[['Gemeente','RDW-registraties','Sterkere aanwijzing','Middel','Laag']]
    for gemeente in selectie:
        r=[reg for reg in regels[1:] if reg[0]==gemeente]
        overzicht.append([gemeente,str(len(r))]+[str(sum(1 for item in r if item[10]==cat))
                                             for cat in ('Sterkere aanwijzing','Middel','Laag')])
    toelichting=[['Onderdeel','Toelichting'],
                 ['Geselecteerde gemeenten', ', '.join(selectie)],
                 ['Peildatum',datum],
                 ['Aantal bedrijven',str(len(bedrijven))],
                 ['Aantal erkenningsregels',str(len(erkenningen))],
                 ['RDW bron bedrijven','https://opendata.rdw.nl/d/5k74-3jha'],
                 ['RDW bron erkenningen','https://opendata.rdw.nl/d/nmwb-dqkz'],
                 ['RDW-geografie','RDW geeft plaatsnaam; geen bestuurlijke gemeente. Koppeling via aanpasbare woonplaatsenlijst.'],
                 ['Ambigue plaatsnamen','Voor enkele homoniemen voert het script aanvullende postcodecontrole uit.'],
                 ['Volledigheid','Postadres kan afwijken van fysieke locatie; controleer gemeentenlijst en uitzonderingen.'],
                 ['MBA status','Indicatie voor nader onderzoek; RDW-erkenning toont niet aan dat een Bal-MBA wordt uitgevoerd.'],
                 ['Licentie RDW','CC0; vermeld bron en peildatum.'],
                 ['Bronvalidatie','Controleer actualiteit en werkelijke bedrijfsactiviteiten voordat dossiers worden aangemaakt.']]
    tabs=[('RDW bedrijven',regels,[24,20,37,30,27,12,14,15,24,44,24,67,20,56,62,62,20]),
          ('Erkenningen',er_rows,[25,20,45,65]),
          ('Overzicht',overzicht,[28,20,24,14,14]),
          ('Toelichting',toelichting,[28,110])]
    schrijf_xlsx(pad,tabs)
    return len(bedrijven),len(erkenningen)


def run(args):
    gemeenten, index=werkgebied()
    selectie=keuzes(args,gemeenten)
    print(f'\nGeselecteerd ({len(selectie)}): '+', '.join(selectie))
    if args.bedrijven_csv:
        print('Lees RDW-bedrijven uit lokale CSV ...')
        land=normaliseer_bron(csv_inlezen(args.bedrijven_csv))
    else:
        print('Download RDW-bedrijven (landelijke dataset, eenmalig) ...')
        land=alle_paginas(BEDRIJVEN_ID)
    if not land:
        raise RuntimeError('Lege RDW-bedrijvendataset: controleer bron/bestand.')
    kandidaten=[]
    onbekende_plaatsen=Counter()
    for b in land:
        gemeente, methode=bepaal_gemeente(b,index)
        if gemeente in selectie:
            item=dict(b)
            item['_gemeente']=gemeente
            item['_methode']=methode
            kandidaten.append(item)
        elif not gemeente and standaard(b.get('plaats','')) in index:
            onbekende_plaatsen[str(b.get('plaats'))] += 1
    # Geen data? We weten niet of de selectie terecht leeg is. Markeer dit expliciet.
    if not kandidaten:
        raise RuntimeError('Geen RDW-bedrijven voor deze selectie. Controleer woonplaatsenlijst / bron; geen leeg Excel als betrouwbaar resultaat opslaan.')
    print(f'Geselecteerd uit {len(land)} landelijke RDW-records: {len(kandidaten)}')
    if onbekende_plaatsen:
        print('Let op: homonieme plaatsnamen uitgesloten op postcode:',dict(onbekende_plaatsen))
    erken = erkenningen_ophalen([r['volgnummer'] for r in kandidaten],args.erkenningen_csv)
    print(f'Gekoppelde RDW-erkenningen: {len(erken)}')
    if not erken:
        print('WAARSCHUWING: geen erkenningen gekoppeld; controleer RDW-schema of erkenningenbestand.')
    folder=Path(args.uitvoer).resolve() if args.uitvoer else ROOT
    folder.mkdir(parents=True,exist_ok=True)
    naam = 'RDW_alle_gemeenten.xlsx' if len(selectie)==len(gemeenten) else ('RDW_'+'_'.join(n.replace(' ','_') for n in selectie)[:85]+'.xlsx')
    pad=folder/naam
    n,m=bouw_excel(kandidaten,erken,selectie,pad)
    print(f'\nGereed: {pad}\n{n} RDW-registraties; {m} erkenningen.')
    return pad


def argumenten(argv=None):
    parser=argparse.ArgumentParser(description=__doc__,formatter_class=argparse.RawDescriptionHelpFormatter)
    groep=parser.add_mutually_exclusive_group()
    groep.add_argument('--alle',action='store_true',help='Alle gemeenten uit gemeenten.json')
    groep.add_argument('--gemeente',action='append',help='Herhaal deze optie voor meerdere gemeenten')
    parser.add_argument('--bedrijven-csv',help='Optioneel: lokaal gedownload RDW bedrijven CSV-bestand')
    parser.add_argument('--erkenningen-csv',help='Optioneel: lokaal gedownload RDW erkenningen CSV-bestand')
    parser.add_argument('--uitvoer',help='Optioneel: uitvoermap voor het Excel-bestand')
    return parser.parse_args(argv)

if __name__=='__main__':
    try:
        run(argumenten())
    except (ValueError,RuntimeError,OSError,KeyError) as e:
        print(f'\nFOUT: {e}',file=sys.stderr)
        sys.exit(1)

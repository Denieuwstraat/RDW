"""Offline controles voor RDW Streamlit. Testdata zijn nadrukkelijk FICTIEF."""
from __future__ import annotations

import csv
import io
import json
import sys
import tempfile
import unittest
from unittest import mock
import zipfile
from pathlib import Path
from xml.etree import ElementTree as ET

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import rdw_core as rdw
from rdw_service import (
    COLUMNS, excel_bytes, filter_tabel, lees_rdw_csv, maak_tabel, samenvatting,
    selecteer_bedrijven,
)


BEDRIJVEN = [
    {'volgnummer': '1001', 'naam_bedrijf': 'Garage Test', 'straat': 'Industrieweg',
     'huisnummer': '11', 'postcode_numeriek': '4611', 'postcode_alfanumeriek': 'AA',
     'plaats': 'Bergen op Zoom'},
    {'volgnummer': '1002', 'naam_bedrijf': 'Bandenzaak Test', 'straat': 'Hoofdstraat',
     'huisnummer': '8', 'postcode_numeriek': '4661', 'postcode_alfanumeriek': 'BB',
     'plaats': 'Halsteren'},
    {'volgnummer': '1003', 'naam_bedrijf': 'Garage Roosendaal', 'straat': 'Straat',
     'huisnummer': '2', 'postcode_numeriek': '4701', 'postcode_alfanumeriek': 'CC',
     'plaats': 'Roosendaal'},
    {'volgnummer': '1004', 'naam_bedrijf': 'Garage Buiten', 'straat': 'Straat',
     'huisnummer': '5', 'postcode_numeriek': '2500', 'postcode_alfanumeriek': 'DD',
     'plaats': 'Rijswijk'},
    {'volgnummer': '1005', 'naam_bedrijf': 'Garage Altena', 'straat': 'Kerkweg',
     'huisnummer': '1', 'postcode_numeriek': '4284', 'postcode_alfanumeriek': 'EE',
     'plaats': 'Rijswijk'},
    {'volgnummer': '1006', 'naam_bedrijf': 'Handel Test', 'straat': 'Industrieweg',
     'huisnummer': '11', 'postcode_numeriek': '4611', 'postcode_alfanumeriek': 'AA',
     'plaats': 'Bergen op Zoom'},
]
ERKENNINGEN = [
    {'volgnummer': '1001', 'erkenning': 'APK'},
    {'volgnummer': '1003', 'erkenning': 'Handel'},
    {'volgnummer': '1005', 'erkenning': 'APK'},
    {'volgnummer': '1006', 'erkenning': 'Handel'},
]


class TestsRDWStreamlit(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.gebieden, cls.index = rdw.werkgebied()

    def test_gemeenten_configuratie(self):
        self.assertGreaterEqual(len(self.gebieden), 1)
        self.assertIn('Bergen op Zoom', self.gebieden)
        self.assertIn('Halsteren', self.gebieden['Bergen op Zoom'])

    def test_gebied_is_vrij_aanpasbaar(self):
        with tempfile.TemporaryDirectory() as mapnaam:
            tijdelijk = Path(mapnaam) / 'gemeenten.json'
            tijdelijk.write_text(json.dumps({
                'Voorbeeldstad': ['Nieuwe Plaats'],
                'Nog een gemeente': ['Tweede Plaats']
            }), encoding='utf-8')
            with mock.patch.object(rdw, 'CONFIG', tijdelijk):
                gemeenten, index = rdw.werkgebied()
        self.assertEqual(len(gemeenten), 2)
        self.assertEqual(index['NIEUWE PLAATS'], 'Voorbeeldstad')

    def test_enkele_gemeente_inclusief_kernen(self):
        regels, buiten = selecteer_bedrijven(BEDRIJVEN, ['Bergen op Zoom'], self.index)
        self.assertEqual({r['volgnummer'] for r in regels}, {'1001', '1002', '1006'})
        self.assertEqual(buiten['Rijswijk'], 1)
        tabel = maak_tabel(regels, ERKENNINGEN, peildatum='2026-10-27')
        self.assertEqual(len(tabel), 3)
        self.assertEqual([c for c in COLUMNS if c not in tabel[0]], [])
        self.assertEqual(sum(x['MBA-signaal'] == 'Sterkere aanwijzing' for x in tabel), 1)
        self.assertEqual(sum(x['Dubbel adres RDW'] == 'Ja' for x in tabel), 2)
        self.assertEqual(next(x for x in tabel if x['RDW-volgnummer']=='1001')['Postcode'], '4611 AA')
        self.assertTrue(next(x for x in tabel if x['RDW-volgnummer']=='1001')['Bron bedrijf'].startswith('https://'))
        self.assertFalse(any('match' in key.casefold() for key in tabel[0]))

    def test_meerdere_alle_gemeenten_en_homoniemen(self):
        records, _ = selecteer_bedrijven(BEDRIJVEN, ['Bergen op Zoom', 'Roosendaal'], self.index)
        self.assertEqual(len(records), 4)
        records, _ = selecteer_bedrijven(BEDRIJVEN, list(self.gebieden), self.index)
        self.assertEqual({r['volgnummer'] for r in records}, {'1001','1002','1003','1005','1006'})

    def test_zoekfuncties_en_score(self):
        records, _ = selecteer_bedrijven(BEDRIJVEN, ['Bergen op Zoom'], self.index)
        tabel = maak_tabel(records, ERKENNINGEN)
        gefilterd = filter_tabel(tabel, 'industrieweg 4611', ['Sterkere aanwijzing'])
        self.assertEqual([x['RDW-volgnummer'] for x in gefilterd], ['1001'])
        dubbel = filter_tabel(tabel, alleen_dubbele_adressen=True)
        self.assertEqual(len(dubbel), 2)
        self.assertEqual(len(filter_tabel(tabel, niveaus=[])), 0)
        statistiek = samenvatting(tabel, ['Bergen op Zoom', 'Roosendaal'])
        self.assertEqual(statistiek[0]['RDW-bedrijven'], 3)
        self.assertEqual(statistiek[1]['RDW-bedrijven'], 0)

    def test_csv_import(self):
        csv_bytes = ('Volgnummer;Naam bedrijf;Straat;Huisnummer;Postcode numeriek;'
                     'Postcode alfanumeriek;Plaats\n1001;Garage Test;Industrieweg;11;4611;AA;Bergen op Zoom\n').encode('utf-8-sig')
        rows = lees_rdw_csv(csv_bytes)
        self.assertEqual(rows[0]['plaats'], 'Bergen op Zoom')
        self.assertEqual(rows[0]['volgnummer'], '1001')
        with self.assertRaises(ValueError):
            lees_rdw_csv(b'voornaam,achternaam\nA,B\n')

    def test_excel_biedt_4_tabbladen_en_herkende_regel(self):
        records, _ = selecteer_bedrijven(BEDRIJVEN, ['Bergen op Zoom'], self.index)
        tabel = maak_tabel(records, ERKENNINGEN)
        alleen_apk = filter_tabel(tabel, niveaus=['Sterkere aanwijzing'])
        ids = {row['RDW-volgnummer'] for row in alleen_apk}
        gefilterde_bedrijven = [b for b in records if b['volgnummer'] in ids]
        data = excel_bytes(gefilterde_bedrijven, ERKENNINGEN, ['Bergen op Zoom'])
        self.assertGreater(len(data), 2000)
        with zipfile.ZipFile(io.BytesIO(data)) as z:
            self.assertIsNone(z.testzip())
            wb = ET.fromstring(z.read('xl/workbook.xml'))
            ns = {'x':'http://schemas.openxmlformats.org/spreadsheetml/2006/main'}
            tabs = [el.attrib['name'] for el in wb.findall('.//x:sheet',ns)]
            self.assertEqual(tabs, ['RDW bedrijven','Erkenningen','Overzicht','Toelichting'])
            text = z.read('xl/worksheets/sheet1.xml').decode()
            self.assertIn('Garage Test', text)
            self.assertNotIn('Bandenzaak Test', text)
            assert 'match' not in text.lower()
        with self.assertRaises(ValueError):
            excel_bytes([], ERKENNINGEN, ['Bergen op Zoom'])


if __name__ == '__main__':
    unittest.main()

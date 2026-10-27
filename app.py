"""Streamlit-app voor RDW-erkende bedrijven in geselecteerde gemeenten.

Start met: streamlit run app.py
"""
from __future__ import annotations

import datetime as dt

import streamlit as st

import rdw_core as rdw
from rdw_service import (
    COLUMNS, excel_bytes, filter_tabel, lees_rdw_csv, maak_tabel,
    samenvatting, selecteer_bedrijven,
)

st.set_page_config(page_title='RDW Milieuverkenner', page_icon='🔎',
                   layout='wide', initial_sidebar_state='expanded')


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def laad_rdw_bedrijven():
    """Nationale RDW-set max. 6 uur cachen; gemeente wisselen vereist dan geen nieuwe download."""
    gegevens = rdw.alle_paginas(rdw.BEDRIJVEN_ID)
    if not gegevens:
        raise RuntimeError('De RDW-bedrijvendataset is leeg.')
    return gegevens


@st.cache_data(ttl=6 * 3600, show_spinner=False)
def laad_rdw_erkenningen(volgnummers: tuple[str, ...]):
    return rdw.erkenningen_ophalen(volgnummers)


def bedrijfsgegevens_laden(bron: str, bestand):
    if bron == 'RDW live':
        return laad_rdw_bedrijven()
    if bestand is None:
        raise ValueError('Upload eerst het bestand met RDW-erkende bedrijven.')
    return lees_rdw_csv(bestand.getvalue())


def erkenningen_laden(bron: str, bedrijven: list[dict], bestand):
    if bron == 'RDW live':
        nummers = tuple(sorted({str(x.get('volgnummer', '')) for x in bedrijven}))
        return laad_rdw_erkenningen(nummers)
    if bestand is None:
        raise ValueError('Upload eerst het bestand met RDW-erkenningen.')
    ids = {str(x.get('volgnummer', '')) for x in bedrijven}
    return [e for e in lees_rdw_csv(bestand.getvalue())
            if str(e.get('volgnummer', '')) in ids]


st.title('RDW Milieuverkenner')
st.caption('Openbare RDW-bedrijven en erkenningen · Zonder luchtfoto’s of beeldherkenning')
st.info('Een RDW-erkenning bewijst niet dat er op een locatie daadwerkelijk een milieubelastende activiteit plaatsvindt. '
        'De resultaten zijn **onderzoeksaanwijzingen**, geen vastgestelde feiten.',
        icon='ℹ️')

try:
    gebieden, plaatsindex = rdw.werkgebied()
except (OSError, ValueError) as exc:
    st.error(f'De gemeentelijst kan niet worden geladen: {exc}')
    st.stop()

with st.sidebar:
    st.header('Onderzoeksgebied')
    alle = st.checkbox(f'Alle gemeenten in de lijst ({len(gebieden)})', value=False)
    if alle:
        selectie = list(gebieden)
        st.caption('Alle gemeenten zijn geselecteerd.')
    else:
        selectie = st.multiselect('Selecteer één of meerdere gemeenten',
                                  options=list(gebieden), default=[('Bergen op Zoom' if 'Bergen op Zoom' in gebieden else next(iter(gebieden)))])
    st.divider()
    st.header('Gegevensbron')
    bron = st.radio('Hoe wil je de RDW-gegevens inladen?',
                    ['RDW live', 'Eigen RDW CSV-bestanden'],
                    help='Als een netwerk- of firewallbeleid RDW blokkeert, kun je de bestanden eerst zelf downloaden.')
    csv_bedrijven = None
    csv_erkenningen = None
    if bron != 'RDW live':
        csv_bedrijven = st.file_uploader('RDW Erkende Bedrijven (CSV)', type=['csv'],
                                         key='bedrijvencsv')
        csv_erkenningen = st.file_uploader('RDW Erkenningen (CSV)', type=['csv'],
                                           key='erkenningencsv')
        st.caption('Gebruik de volledige RDW-exportbestanden met de originele kolomnamen.')
    uitvoeren = st.button('Inventarisatie uitvoeren', type='primary',
                           use_container_width=True, disabled=not bool(selectie))
    st.divider()
    st.caption('Geografie: de gemeenteselectie is gebaseerd op RDW-plaatsnamen en '
               'een bewerkbare woonplaatslijst. Dit is geen exacte BAG-gemeentegrens.')

if uitvoeren:
    try:
        with st.spinner('RDW-bedrijven ophalen en gemeenten selecteren...'):
            landelijke_bedrijven = bedrijfsgegevens_laden(bron, csv_bedrijven)
            bedrijven, uitgesloten = selecteer_bedrijven(
                landelijke_bedrijven, selectie, plaatsindex
            )
        if not bedrijven:
            st.session_state.pop('rdw_resultaat', None)
            st.warning('Er zijn geen RDW-bedrijven gevonden. Controleer de woonplaatslijst '
                       'en de gekozen bron voordat je dit als een volledig resultaat beschouwt.')
        else:
            with st.spinner('Erkenningen koppelen en lijst opbouwen...'):
                erkenningen = erkenningen_laden(bron, bedrijven, csv_erkenningen)
                tabel = maak_tabel(bedrijven, erkenningen)
                st.session_state.rdw_resultaat = {
                    'bedrijven': bedrijven,
                    'erkenningen': erkenningen,
                    'tabel': tabel,
                    'gemeenten': list(selectie),
                    'bron': bron,
                    'uitgesloten': dict(uitgesloten),
                    'tijdstip': dt.datetime.now().strftime('%d-%m-%Y %H:%M'),
                }
            st.success(f'Inventarisatie gereed: {len(bedrijven):,} RDW-registraties gevonden.'.replace(',', '.'))
    except (OSError, ValueError, RuntimeError, KeyError) as exc:
        st.session_state.pop('rdw_resultaat', None)
        st.error(f'Inventarisatie mislukt: {exc}')
        if bron == 'RDW live':
            st.info('Alternatief: selecteer **Eigen RDW CSV-bestanden** en upload de '
                    'exportbestanden van de officiële RDW-website. Er wordt geen fictieve '
                    'of onvolledige lijst als eindresultaat weergegeven.')

resultaat = st.session_state.get('rdw_resultaat')
if resultaat is None:
    st.subheader('Begin met een gemeenteselectie')
    st.write('Kies links één of meerdere gemeenten en klik op **Inventarisatie uitvoeren**. '
             'De gevonden RDW-bedrijven verschijnen hieronder in een doorzoekbare lijst.')
    st.markdown('**RDW-bronnen:** [Erkende Bedrijven](https://opendata.rdw.nl/d/5k74-3jha) · '
                '[Erkenningen](https://opendata.rdw.nl/d/nmwb-dqkz)')
    st.stop()

if set(resultaat['gemeenten']) != set(selectie) or resultaat['bron'] != bron:
    st.warning('Je hebt de selectie of bron gewijzigd. De onderstaande resultaten horen nog '
               'bij de vorige inventarisatie; klik opnieuw op **Inventarisatie uitvoeren**.')

st.caption(f"Laatste inventarisatie in deze sessie: {resultaat['tijdstip']} · "
           f"Bron: {resultaat['bron']} · "
           f"Gemeenten: {', '.join(resultaat['gemeenten'])}")

if resultaat['uitgesloten']:
    with st.expander('Uitgesloten homonieme plaatsnamen (postcodecontrole)'):
        st.json(resultaat['uitgesloten'])

st.subheader('Overzicht')
kolom1, kolom2, kolom3, kolom4 = st.columns(4)
volledige_tabel = resultaat['tabel']
kolom1.metric('RDW-registraties', len(volledige_tabel))
kolom2.metric('Geselecteerde gemeenten', len(resultaat['gemeenten']))
kolom3.metric('Sterkere aanwijzing',
              sum(r['MBA-signaal'] == 'Sterkere aanwijzing' for r in volledige_tabel))
kolom4.metric('Gekoppelde erkenningen', len(resultaat['erkenningen']))

st.dataframe(samenvatting(volledige_tabel, resultaat['gemeenten']),
             hide_index=True, use_container_width=True)

st.subheader('Lijst met RDW-bedrijven')
filterlinks, filterrechts = st.columns([2, 1])
zoektekst = filterlinks.text_input(
    'Zoeken', placeholder='Bedrijfsnaam, adres, postcode, plaats of erkenning'
)
niveaus = filterrechts.multiselect('MBA-signaal',
    ['Sterkere aanwijzing', 'Middel', 'Laag'],
    default=['Sterkere aanwijzing', 'Middel', 'Laag'])
alleen_dubbele = st.checkbox('Alleen adressen met meerdere RDW-registraties')
weergave = filter_tabel(volledige_tabel, zoektekst, niveaus, alleen_dubbele)

st.caption(f'{len(weergave)} van {len(volledige_tabel)} registraties zichtbaar. '
           'Het signaal is alleen een prioriteringshulp.')
if weergave:
    tabel_kolommen = [k for k in COLUMNS if k not in ('Bron erkenningen', 'Gemeentekoppeling', 'Peildatum')]
    st.dataframe(
        [{k: r.get(k, '') for k in tabel_kolommen} for r in weergave],
        column_order=tabel_kolommen,
        column_config={
            'Bron bedrijf': st.column_config.LinkColumn('RDW-bron', display_text='Bekijk bron'),
            'Adres': st.column_config.TextColumn('Adres', width='medium'),
            'Bedrijfsnaam': st.column_config.TextColumn('Bedrijfsnaam', width='large'),
            'Erkenningen': st.column_config.TextColumn('Erkenningen', width='large'),
        },
        hide_index=True, use_container_width=True, height=550,
    )
else:
    st.warning('Geen resultaten voor deze filters. Pas de filters aan om verder te gaan.')

st.subheader('Download als Excel')
st.caption('De download bevat **alleen de momenteel gefilterde registraties** plus '
           'bijbehorende erkenningen, gemeenteoverzicht en bron-/statusuitleg.')
if weergave:
    zichtbaar = {r['RDW-volgnummer'] for r in weergave}
    exportbedrijven = [b for b in resultaat['bedrijven']
                       if str(b.get('volgnummer', '')) in zichtbaar]
    try:
        data = excel_bytes(exportbedrijven, resultaat['erkenningen'], resultaat['gemeenten'])
        st.download_button(
            label='⬇️ Download Excel-overzicht (.xlsx)', data=data,
            file_name=f'RDW_Milieuverkenner_{dt.date.today().isoformat()}.xlsx',
            mime='application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
            type='primary', use_container_width=False,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        st.error(f'Excel genereren mislukt: {exc}')

with st.expander('Bronnen en interpretatie'):
    st.markdown('''
- **RDW Erkende Bedrijven:** https://opendata.rdw.nl/d/5k74-3jha
- **RDW Erkenningen:** https://opendata.rdw.nl/d/nmwb-dqkz
- **Geografisch filter:** woonplaats-/postcodebenadering op basis van gemeentelijst. Controleer grensgevallen.
- **MBA-signaal:** indicatief; erkend bedrijf ≠ vastgestelde milieubelastende activiteit.
- **Privacy:** geüploade CSV-bestanden worden binnen de lokale Streamlit-sessie verwerkt. Gebruik de app bij voorkeur lokaal en deel geen vertrouwelijke datasets via publieke hosting.
''')

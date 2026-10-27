# RDW Milieuverkenner — Streamlit

Deze lokale Streamlit-app zoekt RDW-erkende bedrijven in door jou geselecteerde gemeenten. De app heeft **geen koppeling met interne registraties** en gebruikt **geen luchtfoto's of beeldherkenning**.

## Opstarten (Windows)

1. Pak de ZIP volledig uit op een schrijfbare locatie.
2. Installeer zo nodig **Python 3.10 of hoger**.
3. Dubbelklik op `Start_RDW_Milieuverkenner.cmd`. De eerste keer wordt een `.venv` aangemaakt en worden de vereiste pakketten geïnstalleerd.
4. Open `http://localhost:8501` als je browser niet automatisch opent.
5. Kies een of meer gemeenten, kies de gegevensbron en klik op **Inventarisatie uitvoeren**.
6. Gebruik de tabel en filters. Klik op **Download Excel-overzicht (.xlsx)** voor uitsluitend de zichtbare selectie.

Handmatige start in een bestaande Python-omgeving:

```powershell
python -m pip install -r requirements.txt
python -m streamlit run app.py
```

## Gemeenten aanpassen

Het bestand `gemeenten.json` bevat standaard **25 gemeenten in Midden- en West-Brabant** met een lijst van gekoppelde woonplaatsen. Je kunt gemeenten en woonplaatsen verwijderen, toevoegen of wijzigen. Gebruik de bestaande JSON-structuur:

```json
{
  "Bergen op Zoom": ["Bergen op Zoom", "Halsteren", "Lepelstraat"],
  "Roosendaal": ["Roosendaal", "Wouw", "Nispen"]
}
```

Dit is een *voorbeeld* van de structuur, niet een volledige landelijke gemeentelijst. `gemeenten.json` bevat meer plaatsen en de toelichtingssleutel `_toelichting`.

Een woonplaats mag in deze eenvoudige methode slechts aan één gemeente gekoppeld zijn. Bij gelijknamige plaatsen bestaan aanvullende postcodecontroles in `rdw_core.py`. Controleer die regels als je het gebied uitbreidt. De geografische selectie is een benadering op basis van plaatsnaam en postcode, geen officiële gemeentegrensbepaling.

## Gegevens en Excel

- **RDW live:** haalt landelijke RDW-erkende bedrijven op en koppelt erkenningen voor de geselecteerde bedrijven.
- **RDW CSV:** upload eigen CSV-exporten van de twee officiële RDW-datasets. Dit is handig wanneer een netwerk of firewall de API niet doorlaat.
- **Overzicht:** de app toont gegevens per gemeente en een doorzoekbare tabel met RDW-registraties.
- **Excel:** tabbladen `RDW bedrijven`, `Erkenningen`, `Overzicht`, `Toelichting`.
- **Bronnen:** [RDW erkende bedrijven](https://opendata.rdw.nl/d/5k74-3jha) en [RDW erkenningen](https://opendata.rdw.nl/d/nmwb-dqkz).

**Belangrijk:** een RDW-erkenning is geen bewijs dat op de locatie daadwerkelijk een milieubelastende activiteit plaatsvindt. Ook kan het opgegeven adres afwijken van de feitelijke werklocatie. De app levert onderzoeksaanwijzingen en geen gevalideerde lijst van onbekende bedrijven.

## Bestanden

- `app.py`: Streamlit-interface.
- `rdw_core.py`: API, filtering op woonplaatsen, erkenningsanalyse en Excel-generator.
- `rdw_service.py`: CSV-import, tabelvorming, zoeken en exportselectie.
- `gemeenten.json`: aanpasbare gemeentelijst.
- `requirements.txt`: Streamlit-vereiste.
- `Start_RDW_Milieuverkenner.cmd`: Windows-starter.
- `tests/test_app_logic.py`: offline verwerkingstests met fictieve records.

## Tests

```powershell
python -m unittest discover -s tests -v
```

De testset gebruikt fictieve gegevens. De live RDW-verbinding en de grafische Streamlit-weergave zijn niet volledig getoetst in deze omgeving. Start de app lokaal om het live gebruik en netwerktoegang te controleren.

## Privacy

De app is bedoeld voor lokaal gebruik. Beveilig een eventuele publieke installatie en upload daar geen vertrouwelijke gegevens.

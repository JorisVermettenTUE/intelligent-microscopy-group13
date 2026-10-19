# Intelligent Microscopy – Group 13

Automatische scan van een ibidi µ-Slide 8 Well met detectie van **multinucleaire (reuzen)cellen**.

Een XY-gantry, aangestuurd door een Arduino, beweegt de slide onder de microscoop. Python maakt per positie een foto met de Arducam en zoekt direct naar multinucleaire cellen. Foto's met een hit worden apart opgeslagen, samen met een overlay en een overzicht van alle tussenstappen.

```
Python (laptop)  ── "X,800" / "Y,-400" ──▶  Arduino  ──▶  stappenmotoren
                 ◀────────── "DONE" ──────
      │
      └── Arducam (USB) ──▶ foto ──▶ segmentatie ──▶ runs/run_<datum>/
```

---

## Inhoud

| Pad | Wat |
|---|---|
| `arduino/final/final.ino` | Arduino-sketch voor de XY-gantry |
| `arduino/zstage/zstage.ino` | ESP32-sketch (openUC2 V2) voor de Z-stage (focus) |
| `final_segmentatie/final_segmentatie.py` | Hoofdprogramma: scant alle 8 wells en analyseert elke foto |
| `final_segmentatie/multinucleair.py` | Het segmentatie-algoritme (ook los te gebruiken op een map met foto's) |
| `zstage/zstage.py` | Z-stage met het toetsenbord besturen om scherp te stellen |
| `kalibratie/calibratie.py` | Meet `STEPS_PER_MM` en het beeldveld (FOV) van de opstelling |
| `test_1e_run/` | Resultaten van het algoritme op de eerste testopnames |
| `environment.yml` | Conda-omgeving met alle Python-packages |

---

## Installatie

```bash
conda env create -f environment.yml
```

```bash
conda activate microscopy
```

Upload daarna met de Arduino IDE:
- `arduino/final/final.ino` naar de Arduino van de XY-gantry
- `arduino/zstage/zstage.ino` naar de ESP32 (openUC2 V2) van de Z-stage

---

## De scan draaien

1. **Instellingen controleren** bovenin `final_segmentatie.py`:
   - `ARDUINO_PORT`: de COM-poort van de Arduino (bijv. `"COM3"`)
   - `CAMERA_INDEX`: welke camera de Arducam is (`0`, `1`, `2`, …)
   - `FOV_X_MM` / `FOV_Y_MM`: het gemeten beeldveld van de microscoop
   - `STEPS_PER_MM_X` / `STEPS_PER_MM_Y`: kalibratie van de gantry

   De laatste twee haal je uit de [kalibratie](#kalibratie).
2. **Microscoop handmatig in het midden van well 1** zetten en **scherpstellen** met de Z-stage (zie [Z-stage](#z-stage-scherpstellen)).
3. Starten:
   ```bash
   python final_segmentatie/final_segmentatie.py
   ```
4. Druk op **ENTER** om te beginnen. Met **Ctrl+C** stop je de scan; de gantry blijft dan staan waar hij is.

### Scanvolgorde

De wells worden in een slangpatroon gescand, zodat de gantry zo min mogelijk hoeft te rijden:

```
1 → 2 → 3 → 4
            ↓
8 ← 7 ← 6 ← 5
```

Binnen elke well wordt het hele oppervlak (10.0 × 10.7 mm) ook in een slangpatroon afgedekt, met 10% overlap tussen de foto's. Na elke well gaat de gantry terug naar het midden van die well en rijdt dan naar het midden van de volgende.

### Uitvoer

Elke scan krijgt een eigen map `runs/run_<datum>_<tijd>/`:

```
runs/run_2026-10-19_14-30-00/
├── scan_config.json        alle instellingen van deze run
├── scan_metadata.csv       elke foto met positie (mm en steps) en aantal hits
├── multinucleair.csv       elke gevonden cel: well, foto, positie, straal, oppervlakte
├── well_01/
│   ├── well01_x000_y000.png
│   ├── ...
│   └── multinucleair/      alleen foto's met een hit
│       ├── well01_x004_y012.png
│       ├── well01_x004_y012_overlay.png   gevonden cel omlijnd
│       └── well01_x004_y012_stappen.jpg   alle tussenstappen
└── well_02/ ...
```

Zet `SAVE_ALL_PHOTOS = False` om alleen foto's met een hit te bewaren, en `SAVE_STEPS = False` om de stappen-overzichten over te slaan.

---

## Hoe de detectie werkt

Multinucleaire cellen zijn veel groter dan normale cellen en vormen één groot, aaneengesloten donker gebied. Een groepje normale cellen is ook groot, maar heeft lichte randjes tussen de cellen. Daarom kijken we niet naar de **oppervlakte**, maar naar de **dikte** van elk donker gebied.

1. **Schalen** naar 960 px breed, zodat de drempel niet van de camera-resolutie afhangt.
2. **Achtergrond wegdelen**: delen door een sterk vervaagde versie van het beeld, zodat vignettering en kleurverloop verdwijnen.
3. **Drempel**: pixels die donkerder zijn dan 0.85 × de mediane helderheid tellen als cel.
4. **Opschonen**: kleine ruis weghalen en gaten opvullen (de lichtere kern van een reuzencel hoort bij de cel).
5. **Dikte meten** met een *distance transform*: de straal van de grootste cirkel die volledig in het gebied past.
6. **Beslissen**: een straal van **≥ 36 px** telt als multinucleair.

Cellen die door de beeldrand worden afgesneden tellen niet mee. Door de overlap staan ze in een buurfoto wel volledig in beeld.

| | Straal (px) |
|---|---|
| Normale cellen / clusters | ~20 – 33 |
| Multinucleaire cellen | ~36 – 97 |

> ⚠️ `MIN_RADIUS` is gemeten op de webcam-foto's van de eerste run. Kalibreer hem opnieuw als de camera of de vergroting verandert (zie [Kalibratie](#kalibratie)).

---

## Kalibratie

Voordat de scan betrouwbaar werkt, moeten drie dingen kloppen: hoe ver de gantry per motorstap beweegt, hoe groot het beeldveld is, en vanaf welke celgrootte iets multinucleair heet. Herhaal de kalibratie als de camera, het objectief of de vergroting verandert.

### 1. Gantry en beeldveld (`STEPS_PER_MM`, `FOV`)

Met `kalibratie/calibratie.py` meet je deze waarden met de opstelling zelf. Zet eerst `ARDUINO_PORT`, `CAMERA_INDEX` en de resolutie bovenin het script gelijk aan die in `final_segmentatie.py`, en start dan:

```bash
python kalibratie/calibratie.py
```

Er opent een live camerabeeld. Daarin meet je:

| Stap | Toets | Wat er gebeurt |
|---|---|---|
| **A. Pixels per stap** | `M` | De stage beweegt automatisch een stukje in X en in Y. Met *phase correlation* wordt gemeten hoeveel pixels het beeld verschuift. Elke as wordt 3× gemeten en gemiddeld. Werkt op elk scherp preparaat met structuur (cellen of een kalibratieslide). |
| **B. µm per pixel** | `C` | Met een kalibratieslide (schaalverdeling) in beeld: klik twee streepjes aan die ver uit elkaar liggen en vul de echte afstand in µm in. |
| **B'. Alternatief: wand tot wand** | `1` / `2` | Zonder kalibratieslide: rij met de pijltjes naar de ene wand van een well en druk `1`, rij naar de andere wand en druk `2`. Vul de afstand in (ibidi: 10.0 mm in X, 10.7 mm in Y). |
| **Opslaan** | `P` | Print het resultaat en slaat het op in `kalibratie/calibratie.json`. |

Uit A + B (of A + B') wordt de rest berekend:

```
µm per stap   = µm per pixel × pixels per stap
STEPS_PER_MM  = 1000 / µm per stap
FOV           = beeldgrootte (px) × µm per pixel
```

Het script print de waarden die je overneemt in `final_segmentatie.py`, bijvoorbeeld:

```
STEPS_PER_MM_X = 80.00
STEPS_PER_MM_Y = 80.00
FOV_X_MM = 0.7500
FOV_Y_MM = 0.4800
```

Overige toetsen: pijltjes = stage bewegen, `[` / `]` = stapgrootte kleiner/groter, `G` = dradenkruis aan/uit, `Q` / `Esc` = stoppen.

**Tips**
- Stel eerst goed scherp met de Z-stage; bij een onscherp beeld geeft `M` een lage betrouwbaarheid.
- De *terugkeerfout* laat zien hoeveel speling (backlash) de gantry heeft. Het script rijdt elke positie vanaf dezelfde kant aan om die op te vangen.
- De *beeldhoek* laat zien in welke richting het beeld verschuift. Wijkt die voor X of Y een paar graden af van een rechte hoek, dan staat de camera scheef ten opzichte van de gantry.
- De kalibratieslide (B) is nauwkeuriger dan wand tot wand (B'), omdat de wanden van een well lastig precies te zien zijn.

### 2. Segmentatie (`MIN_RADIUS`, `DARK_FACTOR`)

De drempels voor de detectie staan bovenin `final_segmentatie/multinucleair.py`. Maak een paar foto's met de echte camera en vergroting, en open ze in de interactieve viewer:

```bash
python final_segmentatie/multinucleair.py <map met foto's> --interactief
```

- Zet `DARK_FACTOR` zo dat de cellen in stap 3 rood worden en de achtergrond niet.
- Zet `MIN_RADIUS` net boven de grootste straal van normale cellen en clusters, maar onder die van de kleinste reuzencel. In stap 5 staat bij elk gebied de straal.
- Druk `q`; de gekozen waarden worden geprint. Vul ze in bovenin `multinucleair.py`.

### 3. Startpositie

De scan gaat ervan uit dat de microscoop bij het starten **precies in het midden van well 1** staat; alle andere posities worden daarvandaan berekend. De foto's dekken de well precies tot aan de wanden af, dus een afwijking bij het starten schuift het hele scangebied mee: aan de ene kant mis je dan een strook van de well, aan de andere kant fotografeer je de wand. Gebruik het dradenkruis van `calibratie.py` (toets `G`) om het midden van well 1 nauwkeurig op te zoeken.

---

## Segmentatie los gebruiken

`multinucleair.py` kan ook zonder gantry een hele map met foto's doorlopen:

```bash
python final_segmentatie/multinucleair.py <map>
```

```bash
python final_segmentatie/multinucleair.py <map> --debug
```

```bash
python final_segmentatie/multinucleair.py <map> --interactief
```

| Optie | Effect |
|---|---|
| *(geen)* | Foto's met een hit + overlay + `resultaten.csv` in `<map>/multinucleair/` |
| `--debug` | Ook een overzicht met alle tussenstappen per foto in `stappen/` |
| `--out <map>` | Resultaten in een andere map opslaan |
| `--interactief` | Viewer met schuifjes voor `DARK_FACTOR` en `MIN_RADIUS`: blader met `a`/`d`, stop met `q`; de gekozen waarden worden geprint |

De interactieve viewer is de makkelijkste manier om de drempels te kalibreren: zoek een `MIN_RADIUS` die alle reuzencellen pakt en geen clusters normale cellen, en zet die waarde bovenin `multinucleair.py`.

---

## Arduino

`final.ino` wacht op regels via de seriële poort (115200 baud):

| Commando | Betekenis |
|---|---|
| `X,1000` | 1000 steps naar rechts (negatief = links) |
| `Y,500` | 500 steps vooruit (negatief = achteruit) |

Na elke beweging stuurt de Arduino `DONE` terug; Python wacht daarop voordat het de volgende foto maakt.

| Pin | Functie |
|---|---|
| 2 / 5 | step / dir motor 1 |
| 3 / 6 | step / dir motor 2 |
| 8 | enable van de drivers (LOW = aan) |

De gantry is een CoreXY-achtige opstelling: beide motoren draaien bij elke beweging mee, in dezelfde richting voor X en tegengesteld voor Y. Met `disableWhenIdle = true` staan de drivers alleen aan tijdens het bewegen, zodat de motoren niet zoemen of trillen als er een foto wordt gemaakt.

---

## Z-stage (scherpstellen)

De Z-stage wordt los aangestuurd door een ESP32 op een openUC2 V2-board. Zet `PORT` bovenin `zstage/zstage.py` op de juiste COM-poort en start:

```bash
python zstage/zstage.py
```

| Toets | Effect |
|---|---|
| **R** ingedrukt houden | omhoog |
| **F** ingedrukt houden | omlaag |
| loslaten | stop |
| **Shift** ingedrukt houden | snel |
| **Esc** | programma stoppen |

Het script stuurt losse tekens naar de ESP32 (115200 baud):

| Commando | Betekenis |
|---|---|
| `U` / `D` | continu omhoog / omlaag bewegen |
| `S` | stoppen |
| `F` / `N` | snel / normale snelheid |

| Pin | Functie |
|---|---|
| 12 | step |
| 14 | dir |
| 13 | enable (LOW = aan) |

De ESP32 reset soms als de seriële poort opent; `zstage.py` zet daarom DTR/RTS uit en wacht 2 seconden voordat het commando's stuurt.

---

## Testrun

`test_1e_run/` bevat de uitvoer van `multinucleair.py --debug` op de eerste testopnames (webcam, 1920×1080):

- 25 foto's geanalyseerd, in 15 daarvan is een multinucleaire cel gevonden
- `*.png` / `*_overlay.png`: de foto's met een hit en de gevonden cel omlijnd
- `stappen/`: het stappen-overzicht van alle 25 foto's
- `resultaten.csv`: per foto het aantal hits en de positie, straal en oppervlakte van elke cel

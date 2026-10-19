# intelligent-microscopy-group13

Automatische 8-well scan met detectie van multinucleaire cellen.

- `arduino/final/final.ino` – gantry-besturing (Python stuurt `X,<steps>` / `Y,<steps>`, Arduino antwoordt `DONE`)
- `final_segmentatie/final_segmentatie.py` – scant alle wells, maakt foto's en zoekt multinucleaire cellen
- `final_segmentatie/multinucleair.py` – segmentatie (ook los te draaien op een map met foto's)
- `test_1e_run/` – resultaten van de segmentatie op de eerste testrun
- `environment.yml` – Python-omgeving (`conda env create -f environment.yml`)

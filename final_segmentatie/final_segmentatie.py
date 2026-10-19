import serial
import cv2
import time
import csv
import json
import math
import sys

from pathlib import Path
from datetime import datetime


# Segmentatie uit multinucleair.py (zelfde map)
sys.path.insert(
    0,
    str(Path(__file__).resolve().parent)
)

from multinucleair import (
    detect_multinucleated,
    segment,
    steps_image,
)


# ============================================================
#                    INSTELLINGEN
# ============================================================


# ------------------------------------------------------------
# ARDUINO
# ------------------------------------------------------------

ARDUINO_PORT = "COM3"       # <-- AANPASSEN
BAUDRATE = 115200


# ------------------------------------------------------------
# ARDUCAM
# ------------------------------------------------------------

CAMERA_INDEX = 1            # 0, 1, 2 etc.

CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 800


# ------------------------------------------------------------
# GANTRY CALIBRATIE
#
# Deze waarden moeten uiteindelijk exact gekalibreerd worden.
#
# Voorlopig:
# 80 motorsteps per mm
# ------------------------------------------------------------

STEPS_PER_MM_X = 80.0
STEPS_PER_MM_Y = 80.0


# ------------------------------------------------------------
# IBIDI µ-SLIDE 8 WELL
#
# Well:
# 10.0 x 10.7 mm
#
# Hart-op-hart:
# X = 12.9 mm
# Y = 11.5 mm
# ------------------------------------------------------------

WELL_WIDTH_MM = 10.0
WELL_HEIGHT_MM = 10.7

WELL_PITCH_X_MM = 12.9
WELL_PITCH_Y_MM = 11.5


# ------------------------------------------------------------
# FOV VAN JULLIE MICROSCOOP
#
# !!! HIER JULLIE ECHTE GEMETEN FOV INVULLEN !!!
#
# Voorbeeldwaarden:
# ------------------------------------------------------------

FOV_X_MM = 0.75
FOV_Y_MM = 0.48


# ------------------------------------------------------------
# OVERLAP
#
# 0.10 = 10%
# 0.15 = 15%
# 0.20 = 20%
#
# 10% is een prima begin.
# ------------------------------------------------------------

OVERLAP = 0.10


# ------------------------------------------------------------
# WACHTTIJD NA BEWEGING
#
# Zo voorkom je foto's terwijl het systeem nog trilt.
# ------------------------------------------------------------

SETTLE_TIME = 0.4


# ------------------------------------------------------------
# AANTAL OUDE CAMERA-FRAMES WEGGOOIEN
# ------------------------------------------------------------

FRAMES_TO_FLUSH = 3


# ------------------------------------------------------------
# MAXIMALE TIJD WACHTEN OP ARDUINO
# ------------------------------------------------------------

MOTOR_TIMEOUT = 30


# ------------------------------------------------------------
# SEGMENTATIE
#
# SAVE_ALL_PHOTOS:
#   True  = alle foto's opslaan, hits extra in map "multinucleair"
#   False = alleen foto's met een multinucleaire cel opslaan
#
# SAVE_STEPS:
#   bij een hit ook het overzicht met alle tussenstappen opslaan
#
# Drempels staan in multinucleair.py
# (MIN_RADIUS opnieuw kalibreren voor de Arducam!)
# ------------------------------------------------------------

SAVE_ALL_PHOTOS = True
SAVE_STEPS = True


# ============================================================
# WELL POSITIES
#
# Fysieke indeling:
#
#       1   2   3   4
#
#       5   6   7   8
#
# ============================================================

WELL_POSITIONS = {

    1: (0, 0),
    2: (1, 0),
    3: (2, 0),
    4: (3, 0),

    5: (0, 1),
    6: (1, 1),
    7: (2, 1),
    8: (3, 1),
}


# ============================================================
# SCANVOLGORDE
#
# Serpentine:
#
# 1 → 2 → 3 → 4
#             ↓
# 8 ← 7 ← 6 ← 5
#
# Daardoor hoeft de gantry zo weinig mogelijk te bewegen.
# ============================================================

SCAN_ORDER = [
    1,
    2,
    3,
    4,
    8,
    7,
    6,
    5,
]


# ============================================================
# NIEUWE RUN-MAP AANMAKEN
# ============================================================

timestamp = datetime.now().strftime(
    "%Y-%m-%d_%H-%M-%S"
)

RUN_FOLDER = (
    Path("runs") /
    f"run_{timestamp}"
)

RUN_FOLDER.mkdir(
    parents=True,
    exist_ok=False
)


print()
print("==========================================")
print("NIEUWE RUN")
print("==========================================")
print(RUN_FOLDER.resolve())
print()


# ============================================================
# CONFIG OPSLAAN
# ============================================================

config = {

    "date": timestamp,

    "arduino_port": ARDUINO_PORT,

    "steps_per_mm_x": STEPS_PER_MM_X,
    "steps_per_mm_y": STEPS_PER_MM_Y,

    "well_width_mm": WELL_WIDTH_MM,
    "well_height_mm": WELL_HEIGHT_MM,

    "well_pitch_x_mm": WELL_PITCH_X_MM,
    "well_pitch_y_mm": WELL_PITCH_Y_MM,

    "fov_x_mm": FOV_X_MM,
    "fov_y_mm": FOV_Y_MM,

    "overlap": OVERLAP,

    "camera_width": CAMERA_WIDTH,
    "camera_height": CAMERA_HEIGHT,

    "save_all_photos": SAVE_ALL_PHOTOS,
}


with open(
    RUN_FOLDER / "scan_config.json",
    "w"
) as file:

    json.dump(
        config,
        file,
        indent=4
    )


# ============================================================
# METADATA CSV
# ============================================================

metadata_path = (
    RUN_FOLDER /
    "scan_metadata.csv"
)

metadata_file = open(
    metadata_path,
    "w",
    newline=""
)

metadata_writer = csv.writer(
    metadata_file
)


metadata_writer.writerow([

    "well",

    "grid_x",
    "grid_y",

    "x_mm_from_center",
    "y_mm_from_center",

    "x_steps_from_center",
    "y_steps_from_center",

    "filename",

    "multinucleair"
])


# Alle hits van de hele run
hits_path = (
    RUN_FOLDER /
    "multinucleair.csv"
)

hits_file = open(
    hits_path,
    "w",
    newline=""
)

hits_writer = csv.writer(
    hits_file
)

hits_writer.writerow([
    "well",
    "grid_x",
    "grid_y",
    "filename",
    "cell_x_px",
    "cell_y_px",
    "radius_px",
    "area_px"
])

photos_with_hits = 0


# ============================================================
# BEREKEN SCANPOSITIES
# ============================================================

def calculate_scan_positions(
    well_size_mm,
    fov_mm,
    overlap
):

    """
    Berekent automatisch hoeveel foto's nodig zijn
    om de HELE well te bedekken.

    De eerste en laatste foto worden zo geplaatst
    dat de randen van de well precies meegenomen
    worden.
    """

    if fov_mm <= 0:

        raise ValueError(
            "FOV moet groter zijn dan 0."
        )


    # Als één foto al groter is dan de hele well
    if fov_mm >= well_size_mm:

        return [0.0]


    # Maximale stapgrootte met gewenste overlap
    maximum_spacing = (
        fov_mm *
        (1 - overlap)
    )


    # Afstand waarover de centra moeten bewegen
    travel = (
        well_size_mm -
        fov_mm
    )


    # Minimum aantal foto's
    number_of_images = (
        math.ceil(
            travel /
            maximum_spacing
        )
        + 1
    )


    # Eerste en laatste fotocentrum
    start = -travel / 2
    end = travel / 2


    # Als er meer dan één foto is:
    actual_spacing = (
        end - start
    ) / (
        number_of_images - 1
    )


    positions = []

    for i in range(
        number_of_images
    ):

        position = (
            start +
            i * actual_spacing
        )

        positions.append(
            position
        )


    return positions


# ============================================================
# X EN Y SCANPOSITIES
# ============================================================

X_POSITIONS_MM = (
    calculate_scan_positions(
        WELL_WIDTH_MM,
        FOV_X_MM,
        OVERLAP
    )
)

Y_POSITIONS_MM = (
    calculate_scan_positions(
        WELL_HEIGHT_MM,
        FOV_Y_MM,
        OVERLAP
    )
)


NX = len(X_POSITIONS_MM)
NY = len(Y_POSITIONS_MM)

IMAGES_PER_WELL = NX * NY
TOTAL_IMAGES = IMAGES_PER_WELL * 8


print("==========================================")
print("SCAN-INSTELLINGEN")
print("==========================================")

print(
    f"Well: "
    f"{WELL_WIDTH_MM:.2f} x "
    f"{WELL_HEIGHT_MM:.2f} mm"
)

print(
    f"FOV: "
    f"{FOV_X_MM:.3f} x "
    f"{FOV_Y_MM:.3f} mm"
)

print(
    f"Overlap: "
    f"{OVERLAP * 100:.1f}%"
)

print()

print(
    f"Foto's in X: {NX}"
)

print(
    f"Foto's in Y: {NY}"
)

print(
    f"Foto's per well: "
    f"{IMAGES_PER_WELL}"
)

print(
    f"Totaal voor 8 wells: "
    f"{TOTAL_IMAGES}"
)

print()


# ============================================================
# ZET MM-POSITIES OM NAAR ABSOLUTE STEPPOSITIES
#
# Belangrijk:
#
# we rekenen elke gewenste positie vanaf het centrum uit.
# Hierdoor stapelen afrondingsfouten zich niet op.
# ============================================================

X_POSITIONS_STEPS = [

    round(
        position *
        STEPS_PER_MM_X
    )

    for position
    in X_POSITIONS_MM
]


Y_POSITIONS_STEPS = [

    round(
        position *
        STEPS_PER_MM_Y
    )

    for position
    in Y_POSITIONS_MM
]


# ============================================================
# VERBINDEN MET ARDUINO
# ============================================================

print(
    "Verbinden met Arduino..."
)

arduino = serial.Serial(

    ARDUINO_PORT,
    BAUDRATE,

    timeout=0.1
)


# Arduino reset meestal wanneer serial geopend wordt
time.sleep(2)


# Oude data verwijderen
arduino.reset_input_buffer()


print(
    "Arduino verbonden."
)


# ============================================================
# VERBINDEN MET ARDUCAM
# ============================================================

print(
    "Arducam openen..."
)

camera = cv2.VideoCapture(

    CAMERA_INDEX,
    cv2.CAP_DSHOW
)


camera.set(
    cv2.CAP_PROP_FRAME_WIDTH,
    CAMERA_WIDTH
)

camera.set(
    cv2.CAP_PROP_FRAME_HEIGHT,
    CAMERA_HEIGHT
)


if not camera.isOpened():

    arduino.close()

    metadata_file.close()

    hits_file.close()

    raise RuntimeError(
        "Arducam kon niet worden geopend."
    )


print(
    "Arducam verbonden."
)


# ============================================================
# MOTORCOMMANDO
# ============================================================

def send_motor_command(
    axis,
    steps
):

    steps = int(steps)


    if steps == 0:

        return


    command = (
        f"{axis},{steps}\n"
    )


    print(
        f"Motor: {command.strip()}"
    )


    # Oude DONE's verwijderen
    arduino.reset_input_buffer()


    arduino.write(
        command.encode()
    )


    start_time = time.time()


    while True:


        # Timeout beveiliging
        if (
            time.time() -
            start_time
            > MOTOR_TIMEOUT
        ):

            raise TimeoutError(
                "Arduino gaf geen DONE terug."
            )


        line = (
            arduino
            .readline()
            .decode(
                errors="ignore"
            )
            .strip()
        )


        if not line:

            continue


        print(
            "Arduino:",
            line
        )


        if line == "DONE":

            break


# ============================================================
# X / Y STEPS
# ============================================================

def move_x_steps(
    steps
):

    send_motor_command(
        "X",
        steps
    )


def move_y_steps(
    steps
):

    send_motor_command(
        "Y",
        steps
    )


# ============================================================
# FOTO MAKEN
# ============================================================

def take_photo(

    well,

    grid_x,
    grid_y,

    x_mm,
    y_mm,

    x_steps,
    y_steps,

    well_folder
):


    # Oude frames verwijderen
    for _ in range(
        FRAMES_TO_FLUSH
    ):

        camera.read()


    success, frame = (
        camera.read()
    )


    if not success:

        raise RuntimeError(
            "Arducam kon geen foto maken."
        )


    filename = (

        f"well{well:02d}_"

        f"x{grid_x:03d}_"
        f"y{grid_y:03d}.png"
    )


    filepath = (
        well_folder /
        filename
    )


    # -----------------------------------------------
    # Segmentatie
    # -----------------------------------------------

    global photos_with_hits

    cells, overlay = detect_multinucleated(
        frame
    )


    if SAVE_ALL_PHOTOS:

        success = cv2.imwrite(
            str(filepath),
            frame
        )

        if not success:

            raise RuntimeError(
                f"Foto kon niet worden opgeslagen: "
                f"{filepath}"
            )


    if cells:

        photos_with_hits += 1

        hits_folder = (
            well_folder /
            "multinucleair"
        )

        hits_folder.mkdir(
            exist_ok=True
        )

        hit_path = (
            hits_folder /
            filename
        )

        hit_images = [
            (hit_path, frame),
            (
                hits_folder /
                filename.replace(".png", "_overlay.png"),
                overlay
            ),
        ]

        if SAVE_STEPS:

            hit_images.append((
                hits_folder /
                filename.replace(".png", "_stappen.jpg"),
                steps_image(
                    segment(frame),
                    filename
                )
            ))

        # Bij een mislukte hit-foto niet de hele scan stoppen,
        # alleen waarschuwen
        for path, image in hit_images:

            if not cv2.imwrite(str(path), image):

                print(
                    f"WAARSCHUWING: kon niet opslaan: "
                    f"{path}"
                )

        # Zonder SAVE_ALL_PHOTOS is de hit-kopie de enige foto
        if not SAVE_ALL_PHOTOS:

            filepath = hit_path

        for cell in cells:

            hits_writer.writerow([
                well,
                grid_x,
                grid_y,
                str(hit_path),
                cell["x"],
                cell["y"],
                cell["radius_px"],
                cell["area_px"]
            ])

        hits_file.flush()


    # Metadata
    if SAVE_ALL_PHOTOS or cells:

        metadata_writer.writerow([

            well,

            grid_x,
            grid_y,

            round(x_mm, 5),
            round(y_mm, 5),

            x_steps,
            y_steps,

            str(filepath),

            len(cells)
        ])


        metadata_file.flush()


    print(
        f"FOTO: {filename}"
        + (
            f"  ->  {len(cells)} MULTINUCLEAIR"
            if cells else ""
        )
    )


# ============================================================
# ÉÉN COMPLETE WELL SCANNEN
# ============================================================

def scan_well(
    well_number
):


    print()
    print("==========================================")
    print(
        f"START WELL {well_number}"
    )
    print("==========================================")


    # --------------------------------------------------------
    # Map voor deze well
    # --------------------------------------------------------

    well_folder = (

        RUN_FOLDER /
        f"well_{well_number:02d}"
    )


    well_folder.mkdir(
        exist_ok=False
    )


    # --------------------------------------------------------
    # Huidige offset vanaf centrum well
    #
    # We starten altijd in het wellcentrum.
    # --------------------------------------------------------

    current_x_steps = 0
    current_y_steps = 0


    # ========================================================
    # SERPENTINE SCAN
    # ========================================================

    for y_index in range(NY):


        target_y_steps = (
            Y_POSITIONS_STEPS[
                y_index
            ]
        )


        # ----------------------------------------------------
        # Y naar huidige rij
        # ----------------------------------------------------

        delta_y = (
            target_y_steps -
            current_y_steps
        )


        if delta_y != 0:

            move_y_steps(
                delta_y
            )

            current_y_steps = (
                target_y_steps
            )

            time.sleep(
                SETTLE_TIME
            )


        # ----------------------------------------------------
        # Rijrichting
        #
        # EVEN:
        # links -> rechts
        #
        # ONEVEN:
        # rechts -> links
        # ----------------------------------------------------

        if y_index % 2 == 0:

            x_indices = range(
                NX
            )

        else:

            x_indices = range(
                NX - 1,
                -1,
                -1
            )


        # ----------------------------------------------------
        # SCAN DE RIJ
        # ----------------------------------------------------

        for x_index in x_indices:


            target_x_steps = (
                X_POSITIONS_STEPS[
                    x_index
                ]
            )


            delta_x = (
                target_x_steps -
                current_x_steps
            )


            # Bewegen
            if delta_x != 0:

                move_x_steps(
                    delta_x
                )

                current_x_steps = (
                    target_x_steps
                )

                time.sleep(
                    SETTLE_TIME
                )


            # -----------------------------------------------
            # Foto
            # -----------------------------------------------

            take_photo(

                well_number,

                x_index,
                y_index,

                X_POSITIONS_MM[
                    x_index
                ],

                Y_POSITIONS_MM[
                    y_index
                ],

                current_x_steps,
                current_y_steps,

                well_folder
            )


    # ========================================================
    # TERUG NAAR EXACT CENTRUM WELL
    # ========================================================

    print()
    print(
        f"WELL {well_number} klaar."
    )

    print(
        "Terug naar wellcentrum..."
    )


    if current_x_steps != 0:

        move_x_steps(
            -current_x_steps
        )


    if current_y_steps != 0:

        move_y_steps(
            -current_y_steps
        )


    time.sleep(
        SETTLE_TIME
    )


    print(
        f"Terug in centrum WELL {well_number}"
    )


# ============================================================
# BEWEEG VAN WELL-CENTRUM NAAR VOLGENDE WELL-CENTRUM
# ============================================================

def move_between_wells(

    current_well,
    next_well
):


    current_col, current_row = (
        WELL_POSITIONS[
            current_well
        ]
    )


    next_col, next_row = (
        WELL_POSITIONS[
            next_well
        ]
    )


    # --------------------------------------------------------
    # Verschil in well-posities
    # --------------------------------------------------------

    delta_col = (
        next_col -
        current_col
    )

    delta_row = (
        next_row -
        current_row
    )


    # --------------------------------------------------------
    # Naar steps
    # --------------------------------------------------------

    x_steps = round(

        delta_col *
        WELL_PITCH_X_MM *
        STEPS_PER_MM_X
    )


    y_steps = round(

        delta_row *
        WELL_PITCH_Y_MM *
        STEPS_PER_MM_Y
    )


    print()
    print(
        f"WELL {current_well}"
        f" -> "
        f"WELL {next_well}"
    )


    if x_steps != 0:

        move_x_steps(
            x_steps
        )


    if y_steps != 0:

        move_y_steps(
            y_steps
        )


    time.sleep(
        SETTLE_TIME
    )


# ============================================================
# HOOFDPROGRAMMA
# ============================================================

try:


    print()
    print("==========================================")
    print("        AUTOMATISCHE 8-WELL SCAN")
    print("==========================================")
    print()

    print(
        "BELANGRIJK:"
    )

    print(
        "Plaats de microscoop eerst exact "
        "in het CENTRUM van WELL 1."
    )

    print()

    input(
        "Druk ENTER om de scan te starten..."
    )


    # ========================================================
    # ALLE WELLS
    # ========================================================

    for index, well in enumerate(
        SCAN_ORDER
    ):


        # ----------------------------------------------------
        # Complete well scannen
        # ----------------------------------------------------

        scan_well(
            well
        )


        # ----------------------------------------------------
        # Naar volgende well
        # ----------------------------------------------------

        if (
            index <
            len(SCAN_ORDER) - 1
        ):

            next_well = (
                SCAN_ORDER[
                    index + 1
                ]
            )


            move_between_wells(
                well,
                next_well
            )


    # ========================================================
    # KLAAR
    # ========================================================

    print()
    print("==========================================")
    print("SCAN VOLTOOID")
    print("==========================================")
    print()

    print(
        f"Totaal aantal foto's: "
        f"{TOTAL_IMAGES}"
    )

    print(
        f"Foto's met multinucleaire cel: "
        f"{photos_with_hits}"
    )

    print()

    print(
        "Opgeslagen in:"
    )

    print(
        RUN_FOLDER.resolve()
    )


# ============================================================
# CTRL+C
# ============================================================

except KeyboardInterrupt:

    print()
    print()
    print(
        "SCAN HANDMATIG GESTOPT."
    )

    print(
        "De gantry wordt niet automatisch "
        "verplaatst."
    )


# ============================================================
# ALTIJD AFSLUITEN
# ============================================================

finally:

    camera.release()

    arduino.close()

    metadata_file.close()

    hits_file.close()

    cv2.destroyAllWindows()

    print()
    print(
        "Camera en Arduino afgesloten."
    )
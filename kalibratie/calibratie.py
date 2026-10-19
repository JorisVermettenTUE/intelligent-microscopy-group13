"""
KALIBRATIE: STEPS_PER_MM en FOV

Meet drie dingen:

  1. Pixels per motorstap  (automatisch, toets M)
     De stage beweegt een bekend aantal stappen en de software meet
     met phase correlation hoeveel pixels het beeld verschuift.
     Werkt op elk preparaat met structuur (cellen, calibratieslide).

  2. µm per pixel  (toets C, met calibratieslide)
     Klik twee streepjes aan op de schaal en vul de afstand in µm in.

  3. Stappen per mm  (toetsen 1 en 2, zonder slide)
     Rijd naar de ene wand van de well, druk 1, rijd naar de andere
     wand, druk 2 en vul de afstand in (Ibidi: 10.0 mm in X,
     10.7 mm in Y).

  Uit (1) + (2) of (1) + (3) volgt de rest:
      µm per stap   = µm per pixel x pixels per stap
      steps per mm  = 1000 / µm per stap
      FOV           = beeldbreedte x µm per pixel

TOETSEN (in het camera-venster):
  pijltjes        stage bewegen (X links/rechts, Y op/neer)
  [  ]            stapgrootte kleiner / groter
  M               pixels per stap meten (X en Y, automatisch)
  C               µm per pixel meten met calibratieslide
  1 / 2           positie markeren voor wand-tot-wand meting
  G               dradenkruis aan/uit
  P               resultaat printen en opslaan in calibratie.json
  Q / Esc         stoppen
"""

import json
import math
import time
from datetime import datetime
from pathlib import Path

import cv2
import numpy as np
import serial


# ============================================================
#                    INSTELLINGEN
#     (zelfde waarden als in final.py / final_segmentatie.py)
# ============================================================

ARDUINO_PORT = "COM3"       # <-- AANPASSEN
BAUDRATE = 115200

CAMERA_INDEX = 1

CAMERA_WIDTH = 1280
CAMERA_HEIGHT = 800

SETTLE_TIME = 0.5
FRAMES_TO_FLUSH = 3
MOTOR_TIMEOUT = 30

# Automatische meting:
# eerste proefbeweging (in stappen)
PROBE_STEPS = 20

# uiteindelijke beweging = deze fractie van de beeldbreedte
TARGET_SHIFT_FRACTION = 0.3

# nooit verder dan dit in één meting
MAX_MEASURE_STEPS = 3000

# aantal herhalingen per as (gemiddelde)
REPEATS = 3

# Speling (backlash) opvangen: altijd vanuit dezelfde kant
# aanrijden door eerst dit aantal stappen terug te gaan
BACKLASH_STEPS = 40

# Standaard wand-tot-wand afstanden (Ibidi µ-Slide 8 well)
WELL_WIDTH_MM = 10.0
WELL_HEIGHT_MM = 10.7

JOG_SIZES = [1, 5, 10, 50, 100, 500, 1000]

RESULT_PATH = Path(__file__).resolve().parent / "calibratie.json"


# ============================================================
#                    HARDWARE
# ============================================================

class Stage:

    def __init__(self, port, baudrate):

        self.arduino = serial.Serial(port, baudrate, timeout=0.1)

        # Arduino reset bij openen van de poort
        time.sleep(2)
        self.arduino.reset_input_buffer()

        # Positie in stappen t.o.v. startpunt
        self.x = 0
        self.y = 0

    def move(self, axis, steps):

        steps = int(steps)

        if steps == 0:
            return

        self.arduino.reset_input_buffer()
        self.arduino.write(f"{axis},{steps}\n".encode())

        start = time.time()

        while True:

            if time.time() - start > MOTOR_TIMEOUT:
                raise TimeoutError("Arduino gaf geen DONE terug.")

            line = (
                self.arduino.readline()
                .decode(errors="ignore")
                .strip()
            )

            if line == "DONE":
                break

        if axis == "X":
            self.x += steps
        else:
            self.y += steps

    def close(self):
        self.arduino.close()


class Camera:

    def __init__(self, index, width, height):

        self.camera = cv2.VideoCapture(index, cv2.CAP_DSHOW)
        self.camera.set(cv2.CAP_PROP_FRAME_WIDTH, width)
        self.camera.set(cv2.CAP_PROP_FRAME_HEIGHT, height)

        if not self.camera.isOpened():
            raise RuntimeError("Camera kon niet worden geopend.")

    def live(self):

        success, frame = self.camera.read()

        if not success:
            raise RuntimeError("Camera gaf geen beeld.")

        return frame

    def still(self):
        """Verse foto na stilstand (oude frames weggooien)."""

        for _ in range(FRAMES_TO_FLUSH):
            self.camera.read()

        return self.live()

    def close(self):
        self.camera.release()


# ============================================================
#                    BEELDVERSCHUIVING METEN
# ============================================================

def image_shift(image_a, image_b):
    """
    Verschuiving (dx, dy) in pixels van image_b t.o.v. image_a,
    plus een betrouwbaarheid (0..1, hoger = beter).
    """

    a = cv2.cvtColor(image_a, cv2.COLOR_BGR2GRAY).astype(np.float32)
    b = cv2.cvtColor(image_b, cv2.COLOR_BGR2GRAY).astype(np.float32)

    # Vignettering / belichting weg, zodat alleen structuur telt
    a -= cv2.GaussianBlur(a, (0, 0), 30)
    b -= cv2.GaussianBlur(b, (0, 0), 30)

    window = cv2.createHanningWindow(a.shape[::-1], cv2.CV_32F)

    (dx, dy), response = cv2.phaseCorrelate(a, b, window)

    return dx, dy, response


def settle_and_shoot(camera):

    time.sleep(SETTLE_TIME)
    return camera.still()


def measure_move(stage, camera, axis, steps):
    """
    Beweegt `steps` stappen en weer terug.

    Geeft terug:
        (dx, dy)       verschuiving heen
        return_error   hoe ver het beeld na terugkomen afwijkt (px)
        response       betrouwbaarheid van de meting
    """

    # Speling opvangen: altijd in positieve richting aanrijden
    stage.move(axis, -BACKLASH_STEPS)
    stage.move(axis, BACKLASH_STEPS)

    reference = settle_and_shoot(camera)

    stage.move(axis, steps)
    moved = settle_and_shoot(camera)

    stage.move(axis, -steps)
    back = settle_and_shoot(camera)

    dx, dy, response = image_shift(reference, moved)
    rx, ry, _ = image_shift(reference, back)

    return (dx, dy), math.hypot(rx, ry), response


def measure_axis(stage, camera, axis, image_width):
    """
    Meet pixels per stap voor één as.
    """

    print()
    print(f"--- {axis}-as meten ---")

    # 1. Proefbeweging, oplopend tot er een duidelijke verschuiving is
    steps = PROBE_STEPS

    while True:

        (dx, dy), _, response = measure_move(stage, camera, axis, steps)
        shift = math.hypot(dx, dy)

        print(
            f"proef: {steps} stappen -> {shift:.1f} px "
            f"(betrouwbaarheid {response:.2f})"
        )

        if shift >= 5:
            break

        if steps * 4 > MAX_MEASURE_STEPS:
            raise RuntimeError(
                "Geen verschuiving gemeten. Beweegt de stage? "
                "Staat er structuur (cellen) in beeld en is het scherp?"
            )

        steps *= 4

    # 2. Echte meting: verschuiving van ~30% van het beeld
    px_per_step_guess = shift / steps

    steps = round(
        TARGET_SHIFT_FRACTION * image_width / px_per_step_guess
    )

    steps = max(1, min(steps, MAX_MEASURE_STEPS))

    results = []

    for i in range(REPEATS):

        (dx, dy), return_error, response = measure_move(
            stage, camera, axis, steps
        )

        px_per_step = math.hypot(dx, dy) / steps
        angle = math.degrees(math.atan2(dy, dx))

        print(
            f"meting {i + 1}: {steps} stappen -> "
            f"dx={dx:7.1f} dy={dy:7.1f} px  "
            f"= {px_per_step:.4f} px/stap  "
            f"hoek {angle:6.1f}°  "
            f"terugkeerfout {return_error:.1f} px  "
            f"(betr. {response:.2f})"
        )

        if response < 0.05:
            print(
                "  LET OP: lage betrouwbaarheid, "
                "weinig structuur of onscherp beeld"
            )

        results.append((px_per_step, angle, return_error))

    values = np.array([r[0] for r in results])

    return {
        "px_per_step": float(values.mean()),
        "px_per_step_spread_pct": float(
            values.std() / values.mean() * 100
        ),
        "image_angle_deg": float(np.mean([r[1] for r in results])),
        "return_error_px": float(np.mean([r[2] for r in results])),
        "steps_used": steps,
    }


# ============================================================
#                    µm PER PIXEL MET CALIBRATIESLIDE
# ============================================================

def measure_um_per_px(camera):
    """
    Bevroren beeld, gebruiker klikt twee punten op de schaal
    en vult de echte afstand in.
    """

    frame = camera.still()
    points = []

    window = "Calibratieslide - klik 2 punten (Esc = annuleren)"

    def on_mouse(event, x, y, flags, param):
        if event == cv2.EVENT_LBUTTONDOWN and len(points) < 2:
            points.append((x, y))

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.setMouseCallback(window, on_mouse)

    print()
    print("Klik op twee streepjes van de schaal, zo ver mogelijk uit elkaar.")
    print("Tip: zoom in je venster in of maak het groot voor precisie.")

    while len(points) < 2:

        view = frame.copy()

        for p in points:
            cv2.drawMarker(view, p, (0, 0, 255), cv2.MARKER_CROSS, 40, 2)

        cv2.imshow(window, view)

        if cv2.waitKey(20) & 0xFF == 27:
            cv2.destroyWindow(window)
            return None

    view = frame.copy()
    cv2.line(view, points[0], points[1], (0, 0, 255), 2)
    cv2.imshow(window, view)
    cv2.waitKey(300)

    distance_px = math.dist(points[0], points[1])

    print(f"Afstand: {distance_px:.1f} px")

    answer = input(
        "Echte afstand tussen de punten in µm "
        "(bv. 500), leeg = annuleren: "
    ).strip().replace(",", ".")

    cv2.destroyWindow(window)

    if not answer:
        return None

    um_per_px = float(answer) / distance_px

    print(f"-> {um_per_px:.4f} µm per pixel")

    return um_per_px


# ============================================================
#                    RESULTAAT BEREKENEN
# ============================================================

def compute(state, image_width, image_height):
    """
    Combineert alle metingen tot STEPS_PER_MM en FOV.
    """

    px_x = state["axis"].get("X", {}).get("px_per_step")
    px_y = state["axis"].get("Y", {}).get("px_per_step")

    um_per_px = state["um_per_px"]
    source = "calibratieslide"

    # Zonder slide: µm per pixel terugrekenen uit wand-tot-wand
    if um_per_px is None:

        estimates = []

        for axis, px in (("X", px_x), ("Y", px_y)):

            spm = state["wall_steps_per_mm"].get(axis)

            if spm and px:
                estimates.append(1000 / (spm * px))

        if estimates:
            um_per_px = float(np.mean(estimates))
            source = "wand-tot-wand"

    result = {
        "um_per_px": um_per_px,
        "um_per_px_bron": source if um_per_px else None,
    }

    for axis, px in (("X", px_x), ("Y", px_y)):

        if px and um_per_px:
            result[f"STEPS_PER_MM_{axis}"] = 1000 / (um_per_px * px)
        else:
            result[f"STEPS_PER_MM_{axis}"] = (
                state["wall_steps_per_mm"].get(axis)
            )

    if um_per_px:
        result["FOV_X_MM"] = image_width * um_per_px / 1000
        result["FOV_Y_MM"] = image_height * um_per_px / 1000

    return result


def report(state, image_width, image_height):

    result = compute(state, image_width, image_height)

    print()
    print("==========================================")
    print("RESULTAAT")
    print("==========================================")

    for axis in ("X", "Y"):

        info = state["axis"].get(axis)

        if info:
            print(
                f"{axis}: {info['px_per_step']:.4f} px/stap "
                f"(spreiding {info['px_per_step_spread_pct']:.1f}%), "
                f"beeldhoek {info['image_angle_deg']:.1f}°, "
                f"terugkeerfout {info['return_error_px']:.1f} px"
            )

    for axis, spm in state["wall_steps_per_mm"].items():
        print(f"{axis} wand-tot-wand: {spm:.2f} steps/mm")

    if result["um_per_px"]:
        print(
            f"µm per pixel: {result['um_per_px']:.4f} "
            f"(bron: {result['um_per_px_bron']})"
        )

    print()
    print("In final_segmentatie.py invullen:")
    print()

    for key in (
        "STEPS_PER_MM_X", "STEPS_PER_MM_Y",
        "FOV_X_MM", "FOV_Y_MM"
    ):

        value = result.get(key)

        if value is None:
            print(f"# {key} = ?   (nog niet gemeten)")
        elif key.startswith("FOV"):
            print(f"{key} = {value:.4f}")
        else:
            print(f"{key} = {value:.2f}")

    print()

    data = {
        "datum": datetime.now().isoformat(timespec="seconds"),
        "camera_width": image_width,
        "camera_height": image_height,
        "metingen": state,
        "resultaat": result,
    }

    with open(RESULT_PATH, "w") as file:
        json.dump(data, file, indent=4)

    print(f"Opgeslagen: {RESULT_PATH}")


# ============================================================
#                    HOOFDPROGRAMMA
# ============================================================

# Pijltjestoetsen bij cv2.waitKeyEx op Windows
KEY_LEFT = 2424832
KEY_UP = 2490368
KEY_RIGHT = 2555904
KEY_DOWN = 2621440


def draw_overlay(frame, state, jog, crosshair):

    view = frame.copy()
    h, w = view.shape[:2]

    if crosshair:
        cv2.line(view, (w // 2, 0), (w // 2, h), (0, 255, 255), 1)
        cv2.line(view, (0, h // 2), (w, h // 2), (0, 255, 255), 1)

    lines = [
        f"positie X={state['pos'][0]}  Y={state['pos'][1]} stappen",
        f"stapgrootte: {jog}   ( [ ] )",
    ]

    for axis in ("X", "Y"):
        info = state["axis"].get(axis)
        if info:
            lines.append(f"{axis}: {info['px_per_step']:.4f} px/stap")

    if state["um_per_px"]:
        lines.append(f"{state['um_per_px']:.4f} um/px")

    if state["mark"] is not None:
        lines.append(f"markering 1: {state['mark']}")

    lines.append("M=meet px/stap  C=slide  1/2=wand  G=kruis  P=opslaan  Q=stop")

    for i, text in enumerate(lines):

        y = 28 + i * 26

        cv2.putText(view, text, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4)
        cv2.putText(view, text, (10, y),
                    cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 255, 0), 1)

    return view


def wall_measurement(stage, state):
    """
    Tweede markering: aantal stappen tussen markering 1 en nu
    omrekenen naar steps/mm.
    """

    if state["mark"] is None:
        print("Druk eerst 1 bij de eerste wand.")
        return

    dx = stage.x - state["mark"][0]
    dy = stage.y - state["mark"][1]

    axis = "X" if abs(dx) >= abs(dy) else "Y"
    steps = abs(dx if axis == "X" else dy)

    default = WELL_WIDTH_MM if axis == "X" else WELL_HEIGHT_MM

    print()
    print(f"{axis}-as: {steps} stappen tussen de markeringen.")

    answer = input(
        f"Echte afstand in mm [{default}]: "
    ).strip().replace(",", ".")

    distance = float(answer) if answer else default

    if steps == 0:
        print("Geen beweging, meting genegeerd.")
        return

    spm = steps / distance

    state["wall_steps_per_mm"][axis] = spm
    state["mark"] = None

    print(f"-> {spm:.2f} steps/mm in {axis}")


def main():

    print("Verbinden met Arduino...")
    stage = Stage(ARDUINO_PORT, BAUDRATE)

    print("Camera openen...")
    camera = Camera(CAMERA_INDEX, CAMERA_WIDTH, CAMERA_HEIGHT)

    frame = camera.live()
    image_height, image_width = frame.shape[:2]

    print(f"Beeld: {image_width} x {image_height} px")
    print(__doc__.split("TOETSEN")[1])

    state = {
        "axis": {},
        "um_per_px": None,
        "wall_steps_per_mm": {},
        "mark": None,
        "pos": (0, 0),
    }

    jog_index = 3
    crosshair = True

    window = "Kalibratie"
    cv2.namedWindow(window, cv2.WINDOW_NORMAL)

    try:

        while True:

            state["pos"] = (stage.x, stage.y)

            frame = camera.live()

            cv2.imshow(
                window,
                draw_overlay(
                    frame, state,
                    JOG_SIZES[jog_index], crosshair
                )
            )

            key = cv2.waitKeyEx(20)

            if key == -1:
                continue

            jog = JOG_SIZES[jog_index]
            char = chr(key & 0xFF).lower() if key < 256 else ""

            if key == KEY_LEFT:
                stage.move("X", -jog)
            elif key == KEY_RIGHT:
                stage.move("X", jog)
            elif key == KEY_UP:
                stage.move("Y", jog)
            elif key == KEY_DOWN:
                stage.move("Y", -jog)

            elif char == "[":
                jog_index = max(0, jog_index - 1)
            elif char == "]":
                jog_index = min(len(JOG_SIZES) - 1, jog_index + 1)

            elif char == "m":
                try:
                    for axis in ("X", "Y"):
                        state["axis"][axis] = measure_axis(
                            stage, camera, axis, image_width
                        )
                    report(state, image_width, image_height)
                except RuntimeError as error:
                    print(f"MISLUKT: {error}")

            elif char == "c":
                value = measure_um_per_px(camera)
                if value:
                    state["um_per_px"] = value

            elif char == "1":
                state["mark"] = (stage.x, stage.y)
                print(f"Markering 1 op {state['mark']}")

            elif char == "2":
                wall_measurement(stage, state)

            elif char == "g":
                crosshair = not crosshair

            elif char == "p":
                report(state, image_width, image_height)

            elif char == "q" or key == 27:
                break

    except KeyboardInterrupt:
        pass

    finally:

        camera.close()
        stage.close()
        cv2.destroyAllWindows()

        print()
        print(
            f"Stage staat op X={stage.x}, Y={stage.y} stappen "
            f"t.o.v. het startpunt."
        )


if __name__ == "__main__":
    main()

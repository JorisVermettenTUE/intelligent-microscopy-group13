"""
Detectie van multinucleaire (reuzen)cellen.

Idee:
    Multinucleaire cellen zijn veel groter dan normale cellen en vormen
    één groot, aaneengesloten donker blok. Een cluster normale cellen is
    ook groot, maar heeft lichte randjes tussen de cellen.

    Daarom meten we niet de oppervlakte, maar de "dikte" van elk donker
    gebied: de straal van de grootste cirkel die er volledig in past
    (distance transform). Die is groot voor een reuzencel en klein voor
    een cluster normale cellen.

Gebruik:
    python multinucleair.py <map>                 foto's met hit opslaan
    python multinucleair.py <map> --debug         + alle tussenstappen per foto
    python multinucleair.py <map> --out <map>     resultaten ergens anders
    python multinucleair.py <map> --interactief   viewer met schuifjes

Zonder <map> wordt "opnames/1e run" gebruikt.
"""

import argparse
import csv
from pathlib import Path

import cv2
import numpy as np
from scipy.ndimage import binary_fill_holes


# ============================================================
#                    INSTELLINGEN
# ============================================================

# Alle foto's worden eerst naar deze breedte geschaald,
# zodat de drempel niet afhangt van de camera-resolutie.
WORK_WIDTH = 960

# Achtergrond (vignettering / kleurverloop) wegdelen
BACKGROUND_SIGMA = 60

# Ruis wegfilteren
SMOOTH_SIGMA = 4

# Pixel telt als "cel" als hij donkerder is dan
# DARK_FACTOR x de mediane helderheid
DARK_FACTOR = 0.85

# Minimale straal (in pixels op WORK_WIDTH) van de grootste
# ingeschreven cirkel om een gebied multinucleair te noemen.
#
# Gemeten op 1e run (1920x1080 webcam-foto's):
#   normale cellen / clusters:  ~20 - 33
#   multinucleaire cellen:      ~36 - 97
#
# !!! Opnieuw kalibreren als vergroting of camera verandert !!!
MIN_RADIUS = 36

# Gebieden met een kleinere straal worden in de debug-beelden
# niet van een getal voorzien (anders wordt het onleesbaar)
LABEL_RADIUS = 15


# ============================================================
#                    SEGMENTATIE
# ============================================================

def segment(
    image_bgr,
    dark_factor=DARK_FACTOR,
    min_radius=MIN_RADIUS
):
    """
    Voert alle stappen uit en geeft alle tussenresultaten terug
    (op WORK_WIDTH-resolutie), zodat je kunt zien wat er gebeurt.
    """

    height, width = image_bgr.shape[:2]
    scale = WORK_WIDTH / width

    small = cv2.resize(
        image_bgr,
        (WORK_WIDTH, round(height * scale)),
        interpolation=cv2.INTER_AREA
    )

    gray = cv2.cvtColor(
        small,
        cv2.COLOR_BGR2GRAY
    ).astype(np.float32)

    # 1. Achtergrond normaliseren
    background = cv2.GaussianBlur(
        gray, (0, 0), BACKGROUND_SIGMA
    )

    norm = gray / (background + 1e-3)

    norm = cv2.GaussianBlur(
        norm, (0, 0), SMOOTH_SIGMA
    )

    # 2. Donkere gebieden = cellen
    threshold = np.median(norm) * dark_factor

    dark_raw = (norm < threshold).astype(np.uint8)

    # 3. Ruis weg + gaten dichten: de lichtere binnenkant van een
    #    reuzencel hoort bij de cel
    dark = cv2.morphologyEx(
        dark_raw,
        cv2.MORPH_OPEN,
        np.ones((5, 5), np.uint8)
    )

    dark = binary_fill_holes(dark).astype(np.uint8)

    # 4. Dikte van elk gebied.
    #    De beeldrand telt als grens: afgesneden cellen aan de rand
    #    worden zo niet meegeteld (door de overlap staan ze in de
    #    buurfoto wel volledig in beeld).
    framed = dark.copy()
    framed[[0, -1], :] = 0
    framed[:, [0, -1]] = 0

    dist = cv2.distanceTransform(
        framed, cv2.DIST_L2, 5
    )

    # 5. Per gebied de grootste ingeschreven cirkel
    n_labels, labels = cv2.connectedComponents(dark)

    regions = []

    for label in range(1, n_labels):

        region = labels == label
        region_dist = np.where(region, dist, 0)
        radius = float(region_dist.max())

        y, x = np.unravel_index(
            region_dist.argmax(),
            region_dist.shape
        )

        regions.append({
            "label": label,
            "x": int(x),
            "y": int(y),
            "radius": radius,
            "area": int(region.sum()),
            "multinucleair": radius >= min_radius,
        })

    return {
        "scale": scale,
        "small": small,
        "norm": norm,
        "threshold": threshold,
        "dark_raw": dark_raw,
        "dark": dark,
        "dist": dist,
        "labels": labels,
        "regions": regions,
        "min_radius": min_radius,
    }


def detect_multinucleated(image_bgr):
    """
    Zoekt multinucleaire cellen in één foto.

    Geeft terug:
        cells   - lijst met dicts per gevonden cel
                  (centrum, straal en oppervlakte in originele pixels)
        overlay - kopie van de foto met de gevonden cellen omlijnd
    """

    result = segment(image_bgr)

    scale = result["scale"]
    height, width = image_bgr.shape[:2]

    cells = []
    overlay = image_bgr.copy()

    for region in result["regions"]:

        if not region["multinucleair"]:
            continue

        cells.append({
            "x": round(region["x"] / scale),
            "y": round(region["y"] / scale),
            "radius_px": round(region["radius"] / scale),
            "area_px": round(region["area"] / scale ** 2),
        })

        # Contour tekenen op de originele resolutie
        mask = cv2.resize(
            (result["labels"] == region["label"]).astype(np.uint8),
            (width, height),
            interpolation=cv2.INTER_NEAREST
        )

        contours, _ = cv2.findContours(
            mask,
            cv2.RETR_EXTERNAL,
            cv2.CHAIN_APPROX_SIMPLE
        )

        cv2.drawContours(
            overlay, contours, -1, (0, 255, 0), 3
        )

        cv2.circle(
            overlay,
            (round(region["x"] / scale), round(region["y"] / scale)),
            round(region["radius"] / scale),
            (0, 0, 255),
            2
        )

    return cells, overlay


# ============================================================
#                    VISUALISATIE VAN DE STAPPEN
# ============================================================

def _title(image, text):

    cv2.rectangle(image, (0, 0), (image.shape[1], 34), (0, 0, 0), -1)

    cv2.putText(
        image, text, (8, 24),
        cv2.FONT_HERSHEY_SIMPLEX, 0.7, (255, 255, 255), 2
    )

    return image


def _radius_labels(image, regions, min_radius):

    for region in regions:

        if region["radius"] < LABEL_RADIUS:
            continue

        color = (
            (0, 255, 0) if region["multinucleair"]
            else (0, 200, 255)
        )

        cv2.circle(
            image,
            (region["x"], region["y"]),
            round(region["radius"]),
            color,
            2 if region["multinucleair"] else 1
        )

        cv2.putText(
            image, f"{region['radius']:.0f}",
            (region["x"] - 14, region["y"] + 7),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, (0, 0, 0), 4
        )

        cv2.putText(
            image, f"{region['radius']:.0f}",
            (region["x"] - 14, region["y"] + 7),
            cv2.FONT_HERSHEY_SIMPLEX, 0.6, color, 2
        )


def steps_image(result, name=""):
    """
    Maakt één overzichtsbeeld (2 rijen x 3) met alle stappen.
    """

    small = result["small"]
    regions = result["regions"]
    min_radius = result["min_radius"]

    # 1. Origineel
    p1 = _title(small.copy(), f"1. Origineel  {name}")

    # 2. Genormaliseerd + drempel
    norm_vis = np.clip(
        (result["norm"] - 0.5) / 0.8 * 255, 0, 255
    ).astype(np.uint8)

    p2 = _title(
        cv2.cvtColor(norm_vis, cv2.COLOR_GRAY2BGR),
        f"2. Achtergrond weg (drempel {result['threshold']:.2f})"
    )

    # 3. Ruw masker
    p3 = small.copy()
    p3[result["dark_raw"] > 0] = (0, 0, 255)
    p3 = cv2.addWeighted(small, 0.5, p3, 0.5, 0)
    p3 = _title(p3, "3. Donker masker (ruw)")

    # 4. Opgeschoond + gaten gevuld, elk gebied eigen kleur
    rng = np.random.default_rng(0)
    colors = rng.integers(60, 255, (result["labels"].max() + 1, 3))
    colors[0] = 0

    p4 = colors[result["labels"]].astype(np.uint8)
    p4 = _title(p4, f"4. Opgeschoond + gaten gevuld ({len(regions)} gebieden)")

    # 5. Distance transform
    dist_vis = np.clip(
        result["dist"] / max(min_radius * 2, 1) * 255, 0, 255
    ).astype(np.uint8)

    p5 = cv2.applyColorMap(dist_vis, cv2.COLORMAP_INFERNO)
    p5[result["dark"] == 0] = 0
    _radius_labels(p5, regions, min_radius)
    p5 = _title(p5, f"5. Dikte (straal) - drempel {min_radius:.0f}")

    # 6. Resultaat
    p6 = small.copy()
    hits = [r for r in regions if r["multinucleair"]]

    for region in hits:

        mask = (result["labels"] == region["label"]).astype(np.uint8)

        contours, _ = cv2.findContours(
            mask, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE
        )

        cv2.drawContours(p6, contours, -1, (0, 255, 0), 2)

        cv2.circle(
            p6, (region["x"], region["y"]),
            round(region["radius"]), (0, 0, 255), 2
        )

    verdict = (
        f"{len(hits)} MULTINUCLEAIR -> opslaan" if hits
        else "geen multinucleaire cel"
    )

    p6 = _title(p6, f"6. Resultaat: {verdict}")

    return np.vstack([
        np.hstack([p1, p2, p3]),
        np.hstack([p4, p5, p6]),
    ])


# ============================================================
#                    HELE MAP VERWERKEN
# ============================================================

def find_images(input_folder, skip_folder=None):

    return sorted(
        p for p in Path(input_folder).rglob("*")
        if p.suffix.lower() in (".jpg", ".jpeg", ".png")
        and (skip_folder is None or skip_folder not in p.parents)
    )


def process_folder(input_folder, output_folder=None, debug=False):

    input_folder = Path(input_folder)

    output_folder = Path(
        output_folder or input_folder / "multinucleair"
    )

    output_folder.mkdir(parents=True, exist_ok=True)

    debug_folder = output_folder / "stappen"

    if debug:
        debug_folder.mkdir(exist_ok=True)

    summary_path = output_folder / "resultaten.csv"

    with open(summary_path, "w", newline="") as file:

        writer = csv.writer(file)

        writer.writerow([
            "bestand", "aantal",
            "x", "y", "radius_px", "area_px"
        ])

        for path in find_images(input_folder, output_folder):

            image = cv2.imread(str(path))

            if image is None:
                continue

            cells, overlay = detect_multinucleated(image)

            relative = path.relative_to(input_folder)
            name = "_".join(relative.with_suffix("").parts)

            print(
                f"{str(relative):45s} "
                f"{len(cells)} multinucleair"
            )

            if debug:
                cv2.imwrite(
                    str(debug_folder / f"{name}.jpg"),
                    steps_image(segment(image), name)
                )

            for cell in cells:
                writer.writerow([
                    relative, len(cells),
                    cell["x"], cell["y"],
                    cell["radius_px"], cell["area_px"]
                ])

            if not cells:
                writer.writerow([relative, 0, "", "", "", ""])
                continue

            # Alleen opslaan als er minstens één gevonden is
            cv2.imwrite(
                str(output_folder / f"{name}.png"),
                image
            )

            cv2.imwrite(
                str(output_folder / f"{name}_overlay.png"),
                overlay
            )

    print()
    print(f"Resultaten: {output_folder.resolve()}")


# ============================================================
#                    INTERACTIEVE VIEWER
# ============================================================

def interactive(input_folder):
    """
    Bladeren door de foto's met alle stappen in beeld.
    Met de schuifjes pas je DARK_FACTOR en MIN_RADIUS live aan.

    Toetsen:
        d / spatie   volgende foto
        a            vorige foto
        q / Esc      stoppen (de gekozen waarden worden geprint)
    """

    images = find_images(input_folder)

    if not images:
        raise FileNotFoundError(f"Geen foto's in {input_folder}")

    window = "Multinucleair - stappen"

    cv2.namedWindow(window, cv2.WINDOW_NORMAL)
    cv2.resizeWindow(window, 1600, 640)

    cv2.createTrackbar(
        "DARK_FACTOR x100", window, round(DARK_FACTOR * 100), 100,
        lambda v: None
    )

    cv2.createTrackbar(
        "MIN_RADIUS", window, MIN_RADIUS, 150,
        lambda v: None
    )

    index = 0
    cache = {}
    last = None

    while True:

        dark_factor = max(cv2.getTrackbarPos("DARK_FACTOR x100", window), 1) / 100
        min_radius = cv2.getTrackbarPos("MIN_RADIUS", window)

        key_state = (index, dark_factor, min_radius)

        if key_state != last:

            path = images[index]

            if path not in cache:
                cache[path] = cv2.imread(str(path))

            result = segment(cache[path], dark_factor, min_radius)

            name = (
                f"[{index + 1}/{len(images)}] "
                f"{path.parent.name}/{path.stem}"
            )

            cv2.imshow(window, steps_image(result, name))

            last = key_state

        key = cv2.waitKey(50) & 0xFF

        if key in (ord("q"), 27):
            break

        if key in (ord("d"), ord(" ")):
            index = (index + 1) % len(images)

        if key == ord("a"):
            index = (index - 1) % len(images)

        if cv2.getWindowProperty(window, cv2.WND_PROP_VISIBLE) < 1:
            break

    cv2.destroyAllWindows()

    print(f"DARK_FACTOR = {dark_factor}")
    print(f"MIN_RADIUS = {min_radius}")


if __name__ == "__main__":

    default = (
        Path(__file__).resolve().parents[2]
        / "opnames" / "1e run"
    )

    parser = argparse.ArgumentParser()
    parser.add_argument("map", nargs="?", default=default)
    parser.add_argument("--out", default=None)
    parser.add_argument("--debug", action="store_true")
    parser.add_argument("--interactief", action="store_true")
    args = parser.parse_args()

    if args.interactief:
        interactive(args.map)
    else:
        process_folder(args.map, args.out, args.debug)

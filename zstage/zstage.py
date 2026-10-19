import serial
import time
import threading

from pynput import keyboard


# ==========================
# INSTELLINGEN
# ==========================

PORT = "COM4"
BAUDRATE = 115200


# ==========================
# SERIELE VERBINDING
# ==========================

# DTR/RTS uit voordat de poort opent, anders blijft de ESP32
# soms in reset / bootloader hangen
ser = serial.Serial()
ser.port = PORT
ser.baudrate = BAUDRATE
ser.timeout = 1
ser.dtr = False
ser.rts = False
ser.open()

# ESP32 krijgt tijd om op te starten
time.sleep(2)

# opstartberichten van de ESP32 tonen (bv. "Z-STAGE READY")
while ser.in_waiting:
    print("ESP32:", ser.readline().decode(errors="ignore").strip())


# ==========================
# ANTWOORDEN ESP32 TONEN
# ==========================

def read_serial():
    while ser.is_open:
        try:
            line = ser.readline().decode(errors="ignore").strip()
        except serial.SerialException:
            break
        if line:
            print("ESP32:", line)


threading.Thread(target=read_serial, daemon=True).start()


print()
print("==========================")
print("     Z-STAGE CONTROL")
print("==========================")
print()
print("Houd R ingedrukt = omhoog")
print("Houd F ingedrukt = omlaag")
print("Loslaten = STOP")
print("Shift ingedrukt = SNEL")
print()
print("ESC = programma stoppen")
print()


# onthouden welke toets actief is
current_direction = None

# onthouden of shift (snel) actief is
fast_mode = False

SHIFT_KEYS = (keyboard.Key.shift, keyboard.Key.shift_l, keyboard.Key.shift_r)

# toetsen voor omhoog / omlaag
UP_KEY = 'r'
DOWN_KEY = 'f'


# letter van een toets (met SHIFT wordt key.char een hoofdletter,
# daarom kijken we naar de toetscode)
def get_letter(key):

    vk = getattr(key, 'vk', None)

    if vk is not None and 65 <= vk <= 90:
        return chr(vk).lower()

    char = getattr(key, 'char', None)

    if char:
        return char.lower()

    return None


def send(command):
    ser.write((command + "\n").encode())


# ==========================
# TOETS INGEDRUKT
# ==========================

def on_press(key):

    global current_direction, fast_mode

    letter = get_letter(key)

    # SHIFT = SNEL
    if key in SHIFT_KEYS:

        if not fast_mode:

            send("F")

            fast_mode = True

            print("» SNEL")


    # OMHOOG
    elif letter == UP_KEY:

        if current_direction != "up":

            send("U")

            current_direction = "up"

            print("↑ OMHOOG")


    # OMLAAG
    elif letter == DOWN_KEY:

        if current_direction != "down":

            send("D")

            current_direction = "down"

            print("↓ OMLAAG")


# ==========================
# TOETS LOSGELATEN
# ==========================

def on_release(key):

    global current_direction, fast_mode

    letter = get_letter(key)

    # SHIFT LOSGELATEN = NORMAAL
    if key in SHIFT_KEYS:

        if fast_mode:

            send("N")

            fast_mode = False

            print("» NORMAAL")


    elif letter == UP_KEY:

        if current_direction == "up":

            send("S")

            current_direction = None

            print("■ STOP")


    elif letter == DOWN_KEY:

        if current_direction == "down":

            send("S")

            current_direction = None

            print("■ STOP")


    # ESC = programma afsluiten
    elif key == keyboard.Key.esc:

        send("S")

        print()
        print("Programma gestopt.")

        return False


# ==========================
# START
# ==========================

try:

    with keyboard.Listener(
        on_press=on_press,
        on_release=on_release
    ) as listener:

        listener.join()

finally:

    send("S")

    ser.close()
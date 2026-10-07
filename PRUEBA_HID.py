import time
import serial
from serial.tools import list_ports

def find_holotouch():
    for p in list_ports.comports():
        s = None
        try:
            print("Probando", p.device)
            s = serial.Serial(p.device, 115200, timeout=0.15, write_timeout=0.3)
            time.sleep(0.85)
            deadline = time.monotonic() + 2.4
            next_hello = 0
            while time.monotonic() < deadline:
                if time.monotonic() >= next_hello:
                    s.write(b"HELLO\n")
                    s.flush()
                    next_hello = time.monotonic() + 0.45
                line = s.readline().decode("utf-8", errors="ignore").strip()
                if line.startswith("HOLOTOUCH_USB,V7,"):
                    print("Encontrado:", line)
                    return s, p.device
            s.close()
        except Exception:
            try:
                if s: s.close()
            except Exception:
                pass
    return None, None

s, port = find_holotouch()
if not s:
    print("\nERROR: no se encontro el ESP32-S3 HOLOTOUCH.")
    print("Cierra el Monitor Serie y revisa USB CDC On Boot = Enabled.")
    input("Enter para salir...")
    raise SystemExit(1)

print("\nUSB OK en", port)
print("El cursor hara un pequeno cuadrado. No hace clicks.")
commands = [
    ("MOVE,55,0", 0.18),
    ("MOVE,0,55", 0.18),
    ("MOVE,-55,0", 0.18),
    ("MOVE,0,-55", 0.18),
]
for cmd, wait in commands:
    s.write((cmd + "\n").encode("ascii"))
    s.flush()
    time.sleep(wait)

s.close()
print("Prueba terminada.")
input("Enter para salir...")

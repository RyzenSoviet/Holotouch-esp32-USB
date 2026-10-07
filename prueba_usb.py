import time
import serial
from serial.tools import list_ports

for p in list_ports.comports():
    s = None
    try:
        print("Probando", p.device)
        s = serial.Serial(p.device, 115200, timeout=0.2, write_timeout=0.2)
        time.sleep(0.45)
        s.reset_input_buffer()
        s.write(b"HELLO\n")
        s.flush()

        deadline = time.monotonic() + 1.2
        while time.monotonic() < deadline:
            line = s.readline().decode("utf-8", errors="ignore").strip()
            if line.startswith("HOLOTOUCH_USB,V7,"):
                print("OK:", line)
                print("HOLOTOUCH V7 encontrado en", p.device)
                s.close()
                raise SystemExit(0)

        s.close()
    except SystemExit:
        raise
    except Exception:
        try:
            if s:
                s.close()
        except Exception:
            pass

print("No se encontro HOLOTOUCH V7.")
print("Cierra el Monitor Serie de Arduino y vuelve a intentar.")
input("Enter para salir...")

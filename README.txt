IMPORTANTE - V7.1 HOTFIX
La calibracion ya no bloquea el control y ahora existe fallback de una mano.
Para diagnosticar primero ejecuta PRUEBA_HID.bat.

HOLOTOUCH V7 PRO
================

Version USB avanzada:
PC camera -> Python/MediaPipe -> USB CDC -> ESP32-S3 -> USB HID

Incluye:
- 2 manos simultaneas.
- Mano CURSOR y mano ACCIONES intercambiables.
- Calibracion automatica al iniciar.
- Movimiento adaptativo y modo precision.
- Pinzas con histeresis para reducir falsos positivos.
- Proteccion cuando indice/medio parecen pinza a la vez.
- Swipes que exigen distancia + velocidad + direccion dominante.
- Menu radial.
- Perfiles automaticos por aplicacion.
- Gestos y acciones editables en config.json.
- Zoom con dos manos.
- Bloqueo con dos palmas.
- Fail-safe con puno.
- OLED renovado.
- Boton corto / doble / largo.
- Reconexión USB automatica.
- Creacion de EXE y autoarranque opcional.

IMPORTANTE:
Ningun sistema de vision puede prometer cero falsos positivos con toda iluminacion,
fondos y posiciones. V7 esta configurado para exigir gestos deliberados y reducirlos
mucho respecto a una deteccion directa sin filtros.


============================================================
1. CONEXIONES
============================================================

OLED 0.96" 128x64 I2C:
VCC -> 3V3
GND -> GND
SDA -> GPIO 8
SCL -> GPIO 9

BOTON:
GPIO 13 -> boton -> GND

No necesita resistencia externa porque el firmware usa INPUT_PULLUP.

Puedes probar primero con el puro ESP32-S3 por USB.
El firmware sigue funcionando aunque OLED o boton no esten conectados.


============================================================
2. ARDUINO IDE
============================================================

Board Manager:
- esp32 by Espressif Systems

Library Manager:
- Adafruit SSD1306
- Adafruit GFX Library
- Adafruit BusIO (dependencia)

USB/Wire vienen con el core:
- USB.h
- USBHIDMouse.h
- USBHIDKeyboard.h
- USBHIDConsumerControl.h
- Wire.h

Tools recomendados:
Board: ESP32S3 Dev Module
USB Mode: USB-OTG (TinyUSB)
USB CDC On Boot: Enabled
CPU Frequency: 240MHz (WiFi)
Flash Size: 4MB (32Mb)
PSRAM: Disabled
Partition Scheme: Default 4MB with spiffs
Upload Mode: UART0 / Hardware CDC
Upload Speed: 115200
Erase All Flash Before Sketch Upload: Disabled

FLASH MODE:
Conserva QIO o DIO exactamente como lo tienes AHORA que tu placa ya arranca bien.
No cambies ese ajuste sin necesidad.

Firmware:
HOLOTOUCH_ESP32_S3_USB\HOLOTOUCH_ESP32_S3_USB.ino

Despues de subir:
1. Cierra Serial Monitor.
2. Desconecta/conecta o pulsa RESET si hace falta.
3. Ejecuta PRUEBA_USB.bat.


============================================================
3. INSTALAR EN WINDOWS
============================================================

Ejecuta una sola vez:
INSTALAR.bat

Instala:
- opencv-python
- mediapipe
- pyserial
- psutil

El archivo hand_landmarker.task ya viene incluido.

Prueba:
PRUEBA_USB.bat

Uso:
INICIAR.bat


============================================================
4. ROLES DE LAS DOS MANOS
============================================================

Por defecto:
IZQUIERDA = CURSOR
DERECHA = ACCIONES

Tecla X:
intercambia los roles.

Doble toque del boton:
intercambia los roles.

Tambien puedes editar:
"cursor_hand": "Left"
"action_hand": "Right"

Si MediaPipe te muestra izquierda/derecha al reves:
"swap_handedness": true


============================================================
5. GESTOS
============================================================

MANO CURSOR
-----------
Indice solo:
mover cursor.

Indice + medio:
scroll.

Indice visible + pulgar/anular juntos:
modo PRECISION temporal; baja sensibilidad.

MANO ACCIONES
-------------
Pulgar + indice:
accion principal del perfil.

En MOUSE/BROWSER/EDIT:
pinza corta = click.
pinza mantenida = drag.
soltar = termina drag.

Pulgar + medio:
accion secundaria.

3 dedos (indice+medio+anular):
accion especial.
Debe mantenerse hasta completar el aro de confirmacion.

Palma abierta moviendose:
swipe.

Palma abierta quieta:
abre MENU RADIAL.
Luego desplaza la palma hacia una opcion y mantenla un instante.

Puno:
fail-safe.
Suelta botones/teclas y cancela el estado HID mientras mantienes el puno.

DOS MANOS
---------
Pinza pulgar+indice en las dos manos:
separar = zoom +
juntar = zoom -

Dos palmas abiertas mantenidas:
bloquear / desbloquear HOLOTOUCH.


============================================================
6. MODOS Y PERFILES
============================================================

BOTON:
toque corto = siguiente modo
toque doble = intercambiar manos
toque largo = bloquear/desbloquear

Modos:
MOUSE
MEDIA
PRESENT
NAV

Perfiles automaticos, si A / auto_profiles esta activado:
chrome.exe -> BROWSER
msedge.exe -> BROWSER
firefox.exe -> BROWSER
powerpnt.exe -> PRESENT
spotify.exe -> MEDIA
vlc.exe -> MEDIA
code.exe -> EDIT

El OLED muestra:
MODE = modo fisico/manual
APP = perfil efectivo de la aplicacion

Puedes agregar procesos en app_profiles dentro de config.json.


============================================================
7. ACCIONES POR PERFIL
============================================================

MOUSE/BROWSER:
pinza principal = click
pinza secundaria = click derecho
3 dedos = Alt+Tab
swipe izquierda/derecha = atras/adelante
swipe arriba/abajo = Page Up/Page Down

MEDIA:
pinza principal = Play/Pausa
pinza secundaria = Mute
3 dedos = Fullscreen
swipe L/R = pista anterior/siguiente
swipe U/D = volumen +/-

PRESENT:
pinza principal = siguiente
pinza secundaria = anterior
3 dedos = F5
swipe L/R = slides
swipe U/D = Page Up/Page Down

NAV:
pinza principal = Enter
pinza secundaria = Escape
3 dedos = Win+Tab
swipes = flechas

EDIT:
pinza principal = click
pinza secundaria = click derecho
3 dedos = Alt+Tab
swipe L/R = deshacer/rehacer
swipe U/D = Page Up/Page Down


============================================================
8. MENU RADIAL
============================================================

MOUSE:
izquierda = COPIAR
derecha = PEGAR
arriba = ALT+TAB
abajo = ESCRITORIO

BROWSER:
izquierda = ATRAS
derecha = ADELANTE
arriba = NUEVA TAB
abajo = CERRAR TAB

MEDIA:
anterior / siguiente / volumen + / volumen -

PRESENT:
anterior / siguiente / F5 / Escape

NAV:
atras / adelante / Win+Tab / escritorio

EDIT:
deshacer / rehacer / copiar / pegar

Se edita en radial_menu de config.json.


============================================================
9. INTERFAZ DE CAMARA
============================================================

HUD:
- USB
- modo
- perfil de aplicacion
- LIVE/LOCK
- roles L/R
- etiqueta CURSOR/ACCIONES encima de cada mano
- gesto actual
- indicador de precision
- FPS

H = ayuda
D = debug
X = cambiar manos
C = recalibrar
A = activar/desactivar perfiles automaticos
R = reconectar USB
F = pantalla completa

1 = MOUSE
2 = MEDIA
3 = PRESENT
4 = NAV

ESC o Q = salir


============================================================
10. FILTROS DE PRECISION
============================================================

V7 no ejecuta una accion apenas ve una forma.

Usa:
- confianza de deteccion alta
- dos roles separados
- calibracion del tamano visible de mano y jitter
- suavizado adaptativo
- rechazo de saltos grandes de tracking
- dead-zone dinamica
- pinzas con umbral PRESS y RELEASE separados
- exclusividad entre pinza indice y pinza medio
- cooldowns
- gestos de 3 dedos con tiempo de confirmacion
- frames de gracia al perder una mano
- swipes con distancia, velocidad y direccion
- radial solo si la palma se mantiene estable
- proteccion posterior a zoom para no producir click al soltar
- DRAG_END si la mano desaparece
- puno como cancelacion HID


============================================================
11. PERSONALIZAR
============================================================

config.json contiene:
- sensibilidad
- suavizado
- umbrales de pinza
- velocidad de swipe
- tiempo de confirmacion
- perfiles
- programas
- menu radial
- mano cursor / acciones

Si algo te queda demasiado sensible, NO cambies diez valores a la vez.
Empieza por:
pinch_press_ratio
pinch_release_ratio
mouse_gain
swipe_min_px


============================================================
12. USARLO SIN ABRIR EL SCRIPT CADA VEZ
============================================================

La webcam pertenece al PC y MediaPipe tambien corre en el PC.
Por eso el ESP32-S3 solo no puede reconocer estas manos usando la webcam del PC.

Pero puedes dejarlo como una aplicacion normal:

1. Ejecuta CREAR_EXE.bat.
2. Se genera:
   dist\HOLOTOUCH_V7_PRO.exe
3. Ejecuta INSTALAR_AUTOARRANQUE.ps1.
4. Windows iniciara el EXE automaticamente al iniciar sesion.
5. El programa intenta reconectar el ESP32 si lo desconectas/conectas.

Asi ya no tienes que abrir Python o una consola manualmente.

Para quitar el inicio automatico:
DESINSTALAR_AUTOARRANQUE.ps1

Si quieres que funcione con CERO software en el PC, entonces el reconocimiento tendria
que mudarse a hardware propio con camara/procesador capaz de hacer vision; con la
arquitectura actual del ESP32-S3 + webcam del PC, el programa de PC sigue siendo necesario.

============================================================
11. NOTA SOBRE VERSION SIN SCRIPT / EXE
============================================================

Esta entrega V7 se concentra en tracking, gestos, USB HID, OLED, boton y perfiles.
La conversion a EXE/autoarranque se deja para la siguiente etapa, tal como se acordo.

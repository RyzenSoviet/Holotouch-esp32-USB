#include <Wire.h>                    // Comunicación I2C
#include <Adafruit_GFX.h>            // Gráficos y textos
#include <Adafruit_SSD1306.h>        // Pantalla OLED
#include "USB.h"                     // Conexión USB
#include "USBHIDMouse.h"             // Mouse virtual
#include "USBHIDKeyboard.h"          // Teclado virtual
#include "USBHIDConsumerControl.h"   // Controles multimedia

// ============================================================
// HOLOTOUCH V7 PRO - ESP32-S3
// Control del computador mediante comandos enviados por Python
// Incluye mouse, teclado, pantalla OLED y botón físico
// ============================================================

// Pines y configuración
#define OLED_SDA 8                  // Datos de pantalla
#define OLED_SCL 9                  // Reloj de pantalla
#define BUTTON_PIN 13               // Botón físico
#define SCREEN_WIDTH 128            // Ancho OLED
#define SCREEN_HEIGHT 64            // Alto OLED
#define SERIAL_BAUD 115200          // Velocidad serial
#define RX_BUFFER_SIZE 192          // Memoria para comandos

// Creamos los dispositivos
Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
USBHIDMouse Mouse;
USBHIDKeyboard Keyboard;
USBHIDConsumerControl Consumer;

// Estados principales
bool oledOK = false;                // Pantalla detectada
bool locked = false;                // Control bloqueado
bool dragging = false;              // Mouse arrastrando

// Temporizadores
unsigned long lastOLEDRefresh = 0;  // Última actualización OLED
unsigned long lastPcCommand = 0;    // Último mensaje del PC
unsigned long lastAnim = 0;         // Última animación
uint8_t animFrame = 0;              // Fotograma actual

// Información del sistema
String lastAction = "Arrancando";   // Última acción
String activeProfile = "MOUSE";     // Perfil utilizado
String cursorRole = "L";            // Mano del cursor
String actionRole = "R";            // Mano de acciones

// Almacenamiento de comandos USB
char rxBuffer[RX_BUFFER_SIZE];
size_t rxPos = 0;

// Modos disponibles
enum ControlMode : uint8_t {
  MODE_MOUSE = 0,                   // Control del cursor
  MODE_MEDIA = 1,                   // Música y volumen
  MODE_PRESENT = 2,                 // Presentaciones
  MODE_NAV = 3                      // Navegación
};

ControlMode currentMode = MODE_MOUSE;

// Variables para reconocer pulsaciones
bool lastRawButton = HIGH;
bool stableButton = HIGH;
unsigned long lastDebounceTime = 0;
unsigned long buttonPressStart = 0;
bool longPressDone = false;

bool pendingShort = false;
unsigned long firstReleaseAt = 0;

// Tiempos de pulsación
const unsigned long DEBOUNCE_MS = 35;       // Evita rebotes
const unsigned long LONG_PRESS_MS = 900;    // Pulsación larga
const unsigned long DOUBLE_PRESS_MS = 330;  // Doble pulsación

// ============================================================
// FUNCIONES DE ESTADO
// ============================================================

// Obtiene el nombre del modo actual
const char* modeName() {
  switch (currentMode) {
    case MODE_MOUSE: return "MOUSE";
    case MODE_MEDIA: return "MEDIA";
    case MODE_PRESENT: return "PRESENT";
    case MODE_NAV: return "NAV";
  }
  return "?";
}

// Suelta todos los botones y teclas
void releaseEverything() {
  if (dragging) {
    Mouse.release(MOUSE_LEFT);
    dragging = false;
  }

  Mouse.release(MOUSE_LEFT);
  Mouse.release(MOUSE_RIGHT);
  Mouse.release(MOUSE_MIDDLE);
  Keyboard.releaseAll();
  Consumer.release();
}

// Guarda el nombre de la última acción
void setAction(const String &s) {
  lastAction = s;
}

// Cambia el modo de control
void setMode(uint8_t m) {
  if (m > MODE_NAV) return;

  releaseEverything();              // Evita teclas presionadas
  currentMode = (ControlMode)m;      // Guarda el nuevo modo
  setAction(String("Modo ") + modeName());
}

// Avanza al siguiente modo
void nextMode() {
  setMode(((uint8_t)currentMode + 1) % 4);
}

// Bloquea o desbloquea los controles
void toggleLock() {
  locked = !locked;
  releaseEverything();
  setAction(locked ? "BLOQUEADO" : "ACTIVO");
}

// Acorta textos demasiado largos
String oledTrim(String s, uint8_t maxChars) {
  if (s.length() <= maxChars) return s;
  return s.substring(0, maxChars);
}

// ============================================================
// PANTALLA OLED
// ============================================================

// Inicia la pantalla OLED
void initOLED() {
  Wire.begin(OLED_SDA, OLED_SCL);
  delay(60);

  // Prueba las direcciones habituales
  if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    oledOK = true;
  } else if (display.begin(SSD1306_SWITCHCAPVCC, 0x3D)) {
    oledOK = true;
  }

  // Muestra el logo inicial
  if (oledOK) {
    display.clearDisplay();
    display.setTextColor(SSD1306_WHITE);
    display.setTextSize(1);

    display.setCursor(17, 17);
    display.println("HOLOTOUCH V7");

    display.setCursor(29, 34);
    display.println("PRO USB");

    display.display();
    delay(550);
  }
}

// Dibuja la información del sistema
void drawOLED(bool force = false) {
  if (!oledOK) return;

  // Actualiza aproximadamente cada 120 ms
  if (!force && millis() - lastOLEDRefresh < 120) return;
  lastOLEDRefresh = millis();

  // Actualiza la animación
  if (millis() - lastAnim > 220) {
    lastAnim = millis();
    animFrame = (animFrame + 1) % 4;
  }

  // Comprueba si Python envió comandos recientemente
  bool pcOnline = (millis() - lastPcCommand) < 2600UL;

  display.clearDisplay();

  // Cabecera blanca con letras negras
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);

  display.setCursor(3, 2);
  display.print("HOLOTOUCH V7");

  // Indicador de conexión
  display.setCursor(103, 2);
  display.print(pcOnline ? "PC" : "--");

  display.setTextColor(SSD1306_WHITE);

  // Muestra modo y bloqueo
  display.setCursor(2, 16);
  display.print("MODE ");
  display.print(modeName());

  display.setCursor(78, 16);
  display.print(locked ? "LOCK" : "LIVE");

  // Muestra perfil activo
  display.setCursor(2, 28);
  display.print("APP  ");
  display.print(oledTrim(activeProfile, 14));

  // Muestra los roles de las manos
  display.setCursor(2, 40);
  display.print(cursorRole);
  display.print(":CUR ");
  display.print(actionRole);
  display.print(":ACT");

  // Animación de conexión
  const char spinner[4] = {'|', '/', '-', '\\'};
  display.setCursor(115, 40);
  display.print(pcOnline ? spinner[animFrame] : 'x');

  // Línea separadora
  display.drawFastHLine(0, 50, 128, SSD1306_WHITE);

  // Muestra la última acción
  display.setCursor(2, 54);
  display.print("> ");
  display.print(oledTrim(lastAction, 18));

  display.display();                // Actualiza la pantalla
}

// ============================================================
// CONTROL USB HID
// ============================================================

// Presiona y suelta una tecla
void tapKey(uint8_t key, uint16_t holdMs = 35) {
  Keyboard.press(key);
  delay(holdMs);
  Keyboard.release(key);
}

// Ejecuta una combinación de teclas especiales
void hotkey2(uint8_t mod, uint8_t key) {
  Keyboard.press(mod);
  delay(20);
  Keyboard.press(key);
  delay(50);
  Keyboard.release(key);
  Keyboard.release(mod);
}

// Combina una tecla especial con una letra
void hotkeyChar(uint8_t mod, char key) {
  Keyboard.press(mod);
  delay(20);
  Keyboard.press(key);
  delay(50);
  Keyboard.release(key);
  Keyboard.release(mod);
}

// Ejecuta una acción multimedia
void consumerTap(uint16_t code) {
  Consumer.press(code);
  delay(25);
  Consumer.release();
}

// ============================================================
// ACCIONES DEL COMPUTADOR
// ============================================================

// Recibe el nombre de una acción y la ejecuta
void runAction(String a) {
  a.trim();                         // Elimina espacios
  a.toUpperCase();                  // Convierte a mayúsculas

  // Cancela las teclas presionadas
  if (a == "CANCEL") {
    releaseEverything();
    setAction("CANCEL");
    return;
  }

  // Impide acciones si está bloqueado
  if (locked) return;

  if (a == "CLICK") {
    Mouse.click(MOUSE_LEFT);        // Clic izquierdo
    setAction("Click");
  }
  else if (a == "RIGHTCLICK") {
    Mouse.click(MOUSE_RIGHT);       // Clic derecho
    setAction("Click der");
  }
  else if (a == "DOUBLECLICK") {
    Mouse.click(MOUSE_LEFT);        // Primer clic
    delay(85);
    Mouse.click(MOUSE_LEFT);        // Segundo clic
    setAction("Doble click");
  }
  else if (a == "ALT_TAB") {
    hotkey2(KEY_LEFT_ALT, KEY_TAB); // Cambiar ventana
    setAction("Alt+Tab");
  }
  else if (a == "WIN_TAB") {
    hotkey2(KEY_LEFT_GUI, KEY_TAB); // Vista de tareas
    setAction("Win+Tab");
  }
  else if (a == "BACK") {
    hotkey2(KEY_LEFT_ALT, KEY_LEFT_ARROW); // Retroceder
    setAction("Atras");
  }
  else if (a == "FORWARD") {
    hotkey2(KEY_LEFT_ALT, KEY_RIGHT_ARROW); // Avanzar
    setAction("Adelante");
  }
  else if (a == "PAGE_UP") {
    tapKey(KEY_PAGE_UP);            // Subir página
    setAction("Page Up");
  }
  else if (a == "PAGE_DOWN") {
    tapKey(KEY_PAGE_DOWN);          // Bajar página
    setAction("Page Down");
  }
  else if (a == "LEFT") {
    tapKey(KEY_LEFT_ARROW);         // Flecha izquierda
    setAction("Izquierda");
  }
  else if (a == "RIGHT") {
    tapKey(KEY_RIGHT_ARROW);        // Flecha derecha
    setAction("Derecha");
  }
  else if (a == "UP") {
    tapKey(KEY_UP_ARROW);           // Flecha arriba
    setAction("Arriba");
  }
  else if (a == "DOWN") {
    tapKey(KEY_DOWN_ARROW);         // Flecha abajo
    setAction("Abajo");
  }
  else if (a == "ENTER") {
    tapKey(KEY_RETURN);             // Tecla Enter
    setAction("Enter");
  }
  else if (a == "ESC") {
    tapKey(KEY_ESC);                // Tecla Escape
    setAction("Escape");
  }
  else if (a == "F5") {
    tapKey(KEY_F5);                 // Tecla F5
    setAction("F5");
  }
  else if (a == "FULLSCREEN") {
    tapKey('f');                    // Envía la letra F
    setAction("Fullscreen");
  }
  else if (a == "WIN_D") {
    hotkeyChar(KEY_LEFT_GUI, 'd');  // Mostrar escritorio
    setAction("Escritorio");
  }
  else if (a == "COPY") {
    hotkeyChar(KEY_LEFT_CTRL, 'c'); // Copiar
    setAction("Copiar");
  }
  else if (a == "PASTE") {
    hotkeyChar(KEY_LEFT_CTRL, 'v'); // Pegar
    setAction("Pegar");
  }
  else if (a == "CUT") {
    hotkeyChar(KEY_LEFT_CTRL, 'x'); // Cortar
    setAction("Cortar");
  }
  else if (a == "UNDO") {
    hotkeyChar(KEY_LEFT_CTRL, 'z'); // Deshacer
    setAction("Deshacer");
  }
  else if (a == "REDO") {
    hotkeyChar(KEY_LEFT_CTRL, 'y'); // Rehacer
    setAction("Rehacer");
  }
  else if (a == "NEW_TAB") {
    hotkeyChar(KEY_LEFT_CTRL, 't'); // Nueva pestaña
    setAction("Nueva tab");
  }
  else if (a == "CLOSE_TAB") {
    hotkeyChar(KEY_LEFT_CTRL, 'w'); // Cerrar pestaña
    setAction("Cerrar tab");
  }
  else if (a == "ZOOM_IN") {
    hotkeyChar(KEY_LEFT_CTRL, '='); // Aumentar zoom
    setAction("Zoom +");
  }
  else if (a == "ZOOM_OUT") {
    hotkeyChar(KEY_LEFT_CTRL, '-'); // Reducir zoom
    setAction("Zoom -");
  }
  else if (a == "ZOOM_RESET") {
    hotkeyChar(KEY_LEFT_CTRL, '0'); // Restaurar zoom
    setAction("Zoom 100");
  }
  else if (a == "PLAY_PAUSE") {
    consumerTap(CONSUMER_CONTROL_PLAY_PAUSE); // Reproducir o pausar
    setAction("Play/Pausa");
  }
  else if (a == "MUTE") {
    consumerTap(CONSUMER_CONTROL_MUTE); // Silenciar
    setAction("Mute");
  }
  else if (a == "VOL_UP") {
    consumerTap(CONSUMER_CONTROL_VOLUME_INCREMENT); // Subir volumen
    setAction("Volumen +");
  }
  else if (a == "VOL_DOWN") {
    consumerTap(CONSUMER_CONTROL_VOLUME_DECREMENT); // Bajar volumen
    setAction("Volumen -");
  }
  else if (a == "NEXT_TRACK") {
    consumerTap(CONSUMER_CONTROL_SCAN_NEXT); // Siguiente canción
    setAction("Pista +");
  }
  else if (a == "PREV_TRACK") {
    consumerTap(CONSUMER_CONTROL_SCAN_PREVIOUS); // Canción anterior
    setAction("Pista -");
  }
}

// ============================================================
// COMUNICACIÓN SERIAL CON PYTHON
// ============================================================

// Envía el estado actual del dispositivo
void sendStatus(const char* prefix = "STATUS") {
  Serial.print(prefix);
  Serial.print(',');
  Serial.print(modeName());
  Serial.print(',');
  Serial.print(locked ? '1' : '0');
  Serial.print(',');
  Serial.print(lastAction);
  Serial.print(',');
  Serial.print(cursorRole);
  Serial.print(',');
  Serial.println(actionRole);
}

// Envía identificación de HOLOTOUCH
void sendHello() {
  Serial.print("HOLOTOUCH_USB,V7,");
  Serial.print(modeName());
  Serial.print(',');
  Serial.print(locked ? '1' : '0');
  Serial.print(',');
  Serial.print(cursorRole);
  Serial.print(',');
  Serial.println(actionRole);
}

// Interpreta los mensajes recibidos desde Python
void processCommand(String cmd) {
  cmd.trim();
  if (!cmd.length()) return;

  lastPcCommand = millis();         // Registra actividad del PC

  if (cmd == "HELLO") {
    sendHello();                    // Responde con identificación
    return;
  }

  if (cmd == "PING") {
    Serial.println("PONG");         // Confirma comunicación
    return;
  }

  if (cmd == "STATUS") {
    sendStatus();                   // Envía estado actual
    return;
  }

  if (cmd == "MODE_NEXT") {
    nextMode();                     // Cambia al siguiente modo
    sendStatus();
    return;
  }

  if (cmd == "LOCK_TOGGLE") {
    toggleLock();                   // Bloquea o desbloquea
    sendStatus();
    return;
  }

  // Selecciona un modo específico
  if (cmd.startsWith("MODE,")) {
    String m = cmd.substring(5);
    m.toUpperCase();

    if (m == "MOUSE") setMode(MODE_MOUSE);
    else if (m == "MEDIA") setMode(MODE_MEDIA);
    else if (m == "PRESENT") setMode(MODE_PRESENT);
    else if (m == "NAV") setMode(MODE_NAV);

    sendStatus();
    return;
  }

  // Actualiza el perfil mostrado en OLED
  if (cmd.startsWith("PROFILE,")) {
    activeProfile = cmd.substring(8);
    activeProfile.trim();
    activeProfile.toUpperCase();

    if (activeProfile.length() > 14)
      activeProfile = activeProfile.substring(0, 14);

    return;
  }

  // Actualiza los roles de las manos
  if (cmd.startsWith("ROLE,")) {
    int p = cmd.indexOf(',', 5);

    if (p > 0) {
      cursorRole = cmd.substring(5, p);
      actionRole = cmd.substring(p + 1);

      cursorRole.trim();
      actionRole.trim();
    }
    return;
  }

  // No permite movimientos si está bloqueado
  if (locked) return;

  // Mueve el cursor según las coordenadas recibidas
  if (cmd.startsWith("MOVE,")) {
    int c1 = cmd.indexOf(',');
    int c2 = cmd.indexOf(',', c1 + 1);

    if (c2 > c1) {
      int dx = constrain(cmd.substring(c1 + 1, c2).toInt(), -127, 127);
      int dy = constrain(cmd.substring(c2 + 1).toInt(), -127, 127);

      Mouse.move(dx, dy);           // Mueve el mouse
    }
    return;
  }

  // Controla la rueda del mouse
  if (cmd.startsWith("SCROLL,")) {
    int wheel = constrain(cmd.substring(7).toInt(), -12, 12);

    Mouse.move(0, 0, wheel);
    setAction("Scroll");
    return;
  }

  // Mantiene presionado el clic izquierdo
  if (cmd == "DRAG_START") {
    if (!dragging) {
      Mouse.press(MOUSE_LEFT);
      dragging = true;
      setAction("Arrastrando");
    }
    return;
  }

  // Suelta el clic izquierdo
  if (cmd == "DRAG_END") {
    if (dragging) Mouse.release(MOUSE_LEFT);

    dragging = false;
    setAction("Soltar");
    return;
  }

  // Ejecuta una acción enviada por Python
  if (cmd.startsWith("ACT,")) {
    runAction(cmd.substring(4));
    return;
  }

  // Compatibilidad con comandos antiguos de V6
  if (cmd == "PRIMARY" || cmd == "CLICK")
    runAction("CLICK");
  else if (cmd == "SECONDARY" || cmd == "RIGHTCLICK")
    runAction("RIGHTCLICK");
  else if (cmd == "THREE" || cmd == "ALT_TAB")
    runAction("ALT_TAB");
  else if (cmd == "SWIPE_LEFT")
    runAction("BACK");
  else if (cmd == "SWIPE_RIGHT")
    runAction("FORWARD");
  else if (cmd == "SWIPE_UP")
    runAction("PAGE_UP");
  else if (cmd == "SWIPE_DOWN")
    runAction("PAGE_DOWN");
}

// Lee los comandos que llegan por USB
void readUSBCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();    // Lee un carácter

    if (c == '\r') continue;        // Ignora retorno de carro

    // Procesa el comando cuando termina la línea
    if (c == '\n') {
      rxBuffer[rxPos] = '\0';

      if (rxPos > 0)
        processCommand(String(rxBuffer));

      rxPos = 0;
      continue;
    }

    // Guarda caracteres hasta completar el comando
    if (rxPos < RX_BUFFER_SIZE - 1) {
      rxBuffer[rxPos++] = c;
    } else {
      rxPos = 0;                    // Reinicia si se llena
    }
  }
}

// ============================================================
// CONTROL DEL BOTÓN FÍSICO
// ============================================================

// Detecta pulsación corta, doble y larga
void handleButton() {
  bool reading = digitalRead(BUTTON_PIN);

  // Detecta cambios en el botón
  if (reading != lastRawButton) {
    lastDebounceTime = millis();
  }

  // Elimina rebotes eléctricos
  if (millis() - lastDebounceTime > DEBOUNCE_MS &&
      reading != stableButton) {

    stableButton = reading;

    // Botón presionado
    if (stableButton == LOW) {
      buttonPressStart = millis();
      longPressDone = false;
    }

    // Botón soltado
    else if (!longPressDone) {

      // Detecta doble pulsación
      if (pendingShort &&
          millis() - firstReleaseAt <= DOUBLE_PRESS_MS) {

        pendingShort = false;

        Serial.println("EVENT,SWAP_ROLES"); // Avisa a Python
        setAction("Swap manos");
      }

      // Guarda la primera pulsación
      else {
        pendingShort = true;
        firstReleaseAt = millis();
      }
    }
  }

  // Pulsación larga: bloquear o desbloquear
  if (stableButton == LOW && !longPressDone &&
      millis() - buttonPressStart >= LONG_PRESS_MS) {

    longPressDone = true;
    pendingShort = false;

    toggleLock();
    sendStatus();
  }

  // Pulsación corta: cambiar modo
  if (pendingShort &&
      millis() - firstReleaseAt > DOUBLE_PRESS_MS) {

    pendingShort = false;

    nextMode();
    Serial.println("EVENT,MODE_NEXT");
    sendStatus();
  }

  lastRawButton = reading;
}

// ============================================================
// INICIO DEL SISTEMA
// ============================================================

// Se ejecuta una sola vez al encender
void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP); // Configura el botón

  initOLED();                        // Inicia la pantalla

  Mouse.begin();                     // Inicia mouse USB
  Keyboard.begin();                  // Inicia teclado USB
  Consumer.begin();                  // Inicia multimedia
  USB.begin();                       // Activa USB

  // Comunicación con Python
  Serial.begin(SERIAL_BAUD);
  delay(700);

  lastPcCommand = 0;
  setAction("USB listo");

  drawOLED(true);                    // Muestra estado inicial
}

// ============================================================
// BUCLE PRINCIPAL
// ============================================================

// Se ejecuta continuamente mientras esté encendido
void loop() {
  readUSBCommands();                 // Recibe comandos de Python
  handleButton();                    // Revisa el botón físico
  drawOLED();                        // Actualiza la pantalla
  delay(1);                          // Pequeña pausa
}

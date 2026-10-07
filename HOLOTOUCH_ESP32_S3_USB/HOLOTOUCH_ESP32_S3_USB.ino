#include <Wire.h>
#include <Adafruit_GFX.h>
#include <Adafruit_SSD1306.h>
#include "USB.h"
#include "USBHIDMouse.h"
#include "USBHIDKeyboard.h"
#include "USBHIDConsumerControl.h"

// ============================================================
// HOLOTOUCH V7 PRO - ESP32-S3
// USB CDC + USB HID + OLED 128x64 + boton fisico
// ============================================================

#define OLED_SDA 8
#define OLED_SCL 9
#define BUTTON_PIN 13
#define SCREEN_WIDTH 128
#define SCREEN_HEIGHT 64
#define SERIAL_BAUD 115200
#define RX_BUFFER_SIZE 192

Adafruit_SSD1306 display(SCREEN_WIDTH, SCREEN_HEIGHT, &Wire, -1);
USBHIDMouse Mouse;
USBHIDKeyboard Keyboard;
USBHIDConsumerControl Consumer;

bool oledOK = false;
bool locked = false;
bool dragging = false;

unsigned long lastOLEDRefresh = 0;
unsigned long lastPcCommand = 0;
unsigned long lastAnim = 0;
uint8_t animFrame = 0;

String lastAction = "Arrancando";
String activeProfile = "MOUSE";
String cursorRole = "L";
String actionRole = "R";

char rxBuffer[RX_BUFFER_SIZE];
size_t rxPos = 0;

enum ControlMode : uint8_t {
  MODE_MOUSE = 0,
  MODE_MEDIA = 1,
  MODE_PRESENT = 2,
  MODE_NAV = 3
};

ControlMode currentMode = MODE_MOUSE;

// Boton:
// corto = modo siguiente
// doble = intercambiar roles (evento a Python)
// largo = bloquear/desbloquear
bool lastRawButton = HIGH;
bool stableButton = HIGH;
unsigned long lastDebounceTime = 0;
unsigned long buttonPressStart = 0;
bool longPressDone = false;

bool pendingShort = false;
unsigned long firstReleaseAt = 0;

const unsigned long DEBOUNCE_MS = 35;
const unsigned long LONG_PRESS_MS = 900;
const unsigned long DOUBLE_PRESS_MS = 330;

// ============================================================
// ESTADO / UTILIDADES
// ============================================================

const char* modeName() {
  switch (currentMode) {
    case MODE_MOUSE: return "MOUSE";
    case MODE_MEDIA: return "MEDIA";
    case MODE_PRESENT: return "PRESENT";
    case MODE_NAV: return "NAV";
  }
  return "?";
}

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

void setAction(const String &s) {
  lastAction = s;
}

void setMode(uint8_t m) {
  if (m > MODE_NAV) return;
  releaseEverything();
  currentMode = (ControlMode)m;
  setAction(String("Modo ") + modeName());
}

void nextMode() {
  setMode(((uint8_t)currentMode + 1) % 4);
}

void toggleLock() {
  locked = !locked;
  releaseEverything();
  setAction(locked ? "BLOQUEADO" : "ACTIVO");
}

String oledTrim(String s, uint8_t maxChars) {
  if (s.length() <= maxChars) return s;
  return s.substring(0, maxChars);
}

// ============================================================
// OLED
// ============================================================

void initOLED() {
  Wire.begin(OLED_SDA, OLED_SCL);
  delay(60);

  if (display.begin(SSD1306_SWITCHCAPVCC, 0x3C)) {
    oledOK = true;
  } else if (display.begin(SSD1306_SWITCHCAPVCC, 0x3D)) {
    oledOK = true;
  }

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

void drawOLED(bool force = false) {
  if (!oledOK) return;
  if (!force && millis() - lastOLEDRefresh < 120) return;
  lastOLEDRefresh = millis();

  if (millis() - lastAnim > 220) {
    lastAnim = millis();
    animFrame = (animFrame + 1) % 4;
  }

  bool pcOnline = (millis() - lastPcCommand) < 2600UL;

  display.clearDisplay();

  // Cabecera invertida
  display.fillRect(0, 0, 128, 12, SSD1306_WHITE);
  display.setTextColor(SSD1306_BLACK);
  display.setTextSize(1);
  display.setCursor(3, 2);
  display.print("HOLOTOUCH V7");

  display.setCursor(103, 2);
  display.print(pcOnline ? "PC" : "--");

  display.setTextColor(SSD1306_WHITE);

  // Modo + estado
  display.setCursor(2, 16);
  display.print("MODE ");
  display.print(modeName());

  display.setCursor(78, 16);
  display.print(locked ? "LOCK" : "LIVE");

  // Perfil de aplicacion
  display.setCursor(2, 28);
  display.print("APP  ");
  display.print(oledTrim(activeProfile, 14));

  // Roles
  display.setCursor(2, 40);
  display.print(cursorRole);
  display.print(":CUR ");
  display.print(actionRole);
  display.print(":ACT");

  const char spinner[4] = {'|', '/', '-', '\\'};
  display.setCursor(115, 40);
  display.print(pcOnline ? spinner[animFrame] : 'x');

  // Accion
  display.drawFastHLine(0, 50, 128, SSD1306_WHITE);
  display.setCursor(2, 54);
  display.print("> ");
  display.print(oledTrim(lastAction, 18));

  display.display();
}

// ============================================================
// HID
// ============================================================

void tapKey(uint8_t key, uint16_t holdMs = 35) {
  Keyboard.press(key);
  delay(holdMs);
  Keyboard.release(key);
}

void hotkey2(uint8_t mod, uint8_t key) {
  Keyboard.press(mod);
  delay(20);
  Keyboard.press(key);
  delay(50);
  Keyboard.release(key);
  Keyboard.release(mod);
}

void hotkeyChar(uint8_t mod, char key) {
  Keyboard.press(mod);
  delay(20);
  Keyboard.press(key);
  delay(50);
  Keyboard.release(key);
  Keyboard.release(mod);
}

void consumerTap(uint16_t code) {
  Consumer.press(code);
  delay(25);
  Consumer.release();
}

void runAction(String a) {
  a.trim();
  a.toUpperCase();

  if (a == "CANCEL") {
    releaseEverything();
    setAction("CANCEL");
    return;
  }

  if (locked) return;

  if (a == "CLICK") {
    Mouse.click(MOUSE_LEFT);
    setAction("Click");
  }
  else if (a == "RIGHTCLICK") {
    Mouse.click(MOUSE_RIGHT);
    setAction("Click der");
  }
  else if (a == "DOUBLECLICK") {
    Mouse.click(MOUSE_LEFT);
    delay(85);
    Mouse.click(MOUSE_LEFT);
    setAction("Doble click");
  }
  else if (a == "ALT_TAB") {
    hotkey2(KEY_LEFT_ALT, KEY_TAB);
    setAction("Alt+Tab");
  }
  else if (a == "WIN_TAB") {
    hotkey2(KEY_LEFT_GUI, KEY_TAB);
    setAction("Win+Tab");
  }
  else if (a == "BACK") {
    hotkey2(KEY_LEFT_ALT, KEY_LEFT_ARROW);
    setAction("Atras");
  }
  else if (a == "FORWARD") {
    hotkey2(KEY_LEFT_ALT, KEY_RIGHT_ARROW);
    setAction("Adelante");
  }
  else if (a == "PAGE_UP") {
    tapKey(KEY_PAGE_UP);
    setAction("Page Up");
  }
  else if (a == "PAGE_DOWN") {
    tapKey(KEY_PAGE_DOWN);
    setAction("Page Down");
  }
  else if (a == "LEFT") {
    tapKey(KEY_LEFT_ARROW);
    setAction("Izquierda");
  }
  else if (a == "RIGHT") {
    tapKey(KEY_RIGHT_ARROW);
    setAction("Derecha");
  }
  else if (a == "UP") {
    tapKey(KEY_UP_ARROW);
    setAction("Arriba");
  }
  else if (a == "DOWN") {
    tapKey(KEY_DOWN_ARROW);
    setAction("Abajo");
  }
  else if (a == "ENTER") {
    tapKey(KEY_RETURN);
    setAction("Enter");
  }
  else if (a == "ESC") {
    tapKey(KEY_ESC);
    setAction("Escape");
  }
  else if (a == "F5") {
    tapKey(KEY_F5);
    setAction("F5");
  }
  else if (a == "FULLSCREEN") {
    tapKey('f');
    setAction("Fullscreen");
  }
  else if (a == "WIN_D") {
    hotkeyChar(KEY_LEFT_GUI, 'd');
    setAction("Escritorio");
  }
  else if (a == "COPY") {
    hotkeyChar(KEY_LEFT_CTRL, 'c');
    setAction("Copiar");
  }
  else if (a == "PASTE") {
    hotkeyChar(KEY_LEFT_CTRL, 'v');
    setAction("Pegar");
  }
  else if (a == "CUT") {
    hotkeyChar(KEY_LEFT_CTRL, 'x');
    setAction("Cortar");
  }
  else if (a == "UNDO") {
    hotkeyChar(KEY_LEFT_CTRL, 'z');
    setAction("Deshacer");
  }
  else if (a == "REDO") {
    hotkeyChar(KEY_LEFT_CTRL, 'y');
    setAction("Rehacer");
  }
  else if (a == "NEW_TAB") {
    hotkeyChar(KEY_LEFT_CTRL, 't');
    setAction("Nueva tab");
  }
  else if (a == "CLOSE_TAB") {
    hotkeyChar(KEY_LEFT_CTRL, 'w');
    setAction("Cerrar tab");
  }
  else if (a == "ZOOM_IN") {
    hotkeyChar(KEY_LEFT_CTRL, '=');
    setAction("Zoom +");
  }
  else if (a == "ZOOM_OUT") {
    hotkeyChar(KEY_LEFT_CTRL, '-');
    setAction("Zoom -");
  }
  else if (a == "ZOOM_RESET") {
    hotkeyChar(KEY_LEFT_CTRL, '0');
    setAction("Zoom 100");
  }
  else if (a == "PLAY_PAUSE") {
    consumerTap(CONSUMER_CONTROL_PLAY_PAUSE);
    setAction("Play/Pausa");
  }
  else if (a == "MUTE") {
    consumerTap(CONSUMER_CONTROL_MUTE);
    setAction("Mute");
  }
  else if (a == "VOL_UP") {
    consumerTap(CONSUMER_CONTROL_VOLUME_INCREMENT);
    setAction("Volumen +");
  }
  else if (a == "VOL_DOWN") {
    consumerTap(CONSUMER_CONTROL_VOLUME_DECREMENT);
    setAction("Volumen -");
  }
  else if (a == "NEXT_TRACK") {
    consumerTap(CONSUMER_CONTROL_SCAN_NEXT);
    setAction("Pista +");
  }
  else if (a == "PREV_TRACK") {
    consumerTap(CONSUMER_CONTROL_SCAN_PREVIOUS);
    setAction("Pista -");
  }
}

// ============================================================
// SERIAL
// ============================================================

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

void processCommand(String cmd) {
  cmd.trim();
  if (!cmd.length()) return;
  lastPcCommand = millis();

  if (cmd == "HELLO") {
    sendHello();
    return;
  }

  if (cmd == "PING") {
    Serial.println("PONG");
    return;
  }

  if (cmd == "STATUS") {
    sendStatus();
    return;
  }

  if (cmd == "MODE_NEXT") {
    nextMode();
    sendStatus();
    return;
  }

  if (cmd == "LOCK_TOGGLE") {
    toggleLock();
    sendStatus();
    return;
  }

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

  if (cmd.startsWith("PROFILE,")) {
    activeProfile = cmd.substring(8);
    activeProfile.trim();
    activeProfile.toUpperCase();
    if (activeProfile.length() > 14) activeProfile = activeProfile.substring(0, 14);
    return;
  }

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

  if (locked) return;

  if (cmd.startsWith("MOVE,")) {
    int c1 = cmd.indexOf(',');
    int c2 = cmd.indexOf(',', c1 + 1);
    if (c2 > c1) {
      int dx = constrain(cmd.substring(c1 + 1, c2).toInt(), -127, 127);
      int dy = constrain(cmd.substring(c2 + 1).toInt(), -127, 127);
      Mouse.move(dx, dy);
    }
    return;
  }

  if (cmd.startsWith("SCROLL,")) {
    int wheel = constrain(cmd.substring(7).toInt(), -12, 12);
    Mouse.move(0, 0, wheel);
    setAction("Scroll");
    return;
  }

  if (cmd == "DRAG_START") {
    if (!dragging) {
      Mouse.press(MOUSE_LEFT);
      dragging = true;
      setAction("Arrastrando");
    }
    return;
  }

  if (cmd == "DRAG_END") {
    if (dragging) Mouse.release(MOUSE_LEFT);
    dragging = false;
    setAction("Soltar");
    return;
  }

  if (cmd.startsWith("ACT,")) {
    runAction(cmd.substring(4));
    return;
  }

  // Compatibilidad con V6
  if (cmd == "PRIMARY" || cmd == "CLICK") runAction("CLICK");
  else if (cmd == "SECONDARY" || cmd == "RIGHTCLICK") runAction("RIGHTCLICK");
  else if (cmd == "THREE" || cmd == "ALT_TAB") runAction("ALT_TAB");
  else if (cmd == "SWIPE_LEFT") runAction("BACK");
  else if (cmd == "SWIPE_RIGHT") runAction("FORWARD");
  else if (cmd == "SWIPE_UP") runAction("PAGE_UP");
  else if (cmd == "SWIPE_DOWN") runAction("PAGE_DOWN");
}

void readUSBCommands() {
  while (Serial.available() > 0) {
    char c = (char)Serial.read();

    if (c == '\r') continue;

    if (c == '\n') {
      rxBuffer[rxPos] = '\0';
      if (rxPos > 0) processCommand(String(rxBuffer));
      rxPos = 0;
      continue;
    }

    if (rxPos < RX_BUFFER_SIZE - 1) {
      rxBuffer[rxPos++] = c;
    } else {
      rxPos = 0;
    }
  }
}

// ============================================================
// BOTON
// ============================================================

void handleButton() {
  bool reading = digitalRead(BUTTON_PIN);

  if (reading != lastRawButton) {
    lastDebounceTime = millis();
  }

  if (millis() - lastDebounceTime > DEBOUNCE_MS && reading != stableButton) {
    stableButton = reading;

    if (stableButton == LOW) {
      buttonPressStart = millis();
      longPressDone = false;
    } else if (!longPressDone) {
      if (pendingShort && millis() - firstReleaseAt <= DOUBLE_PRESS_MS) {
        pendingShort = false;
        Serial.println("EVENT,SWAP_ROLES");
        setAction("Swap manos");
      } else {
        pendingShort = true;
        firstReleaseAt = millis();
      }
    }
  }

  if (stableButton == LOW && !longPressDone &&
      millis() - buttonPressStart >= LONG_PRESS_MS) {
    longPressDone = true;
    pendingShort = false;
    toggleLock();
    sendStatus();
  }

  if (pendingShort && millis() - firstReleaseAt > DOUBLE_PRESS_MS) {
    pendingShort = false;
    nextMode();
    Serial.println("EVENT,MODE_NEXT");
    sendStatus();
  }

  lastRawButton = reading;
}

// ============================================================
// SETUP / LOOP
// ============================================================

void setup() {
  pinMode(BUTTON_PIN, INPUT_PULLUP);
  initOLED();

  Mouse.begin();
  Keyboard.begin();
  Consumer.begin();
  USB.begin();

  // Con USB CDC On Boot = Enabled comparte USB con HID.
  Serial.begin(SERIAL_BAUD);
  delay(700);

  lastPcCommand = 0;
  setAction("USB listo");
  drawOLED(true);
}

void loop() {
  readUSBCommands();
  handleButton();
  drawOLED();
  delay(1);
}

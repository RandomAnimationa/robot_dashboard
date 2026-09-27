/*
 * Robot control firmware (ESP32 + L298N)
 * --------------------------------------
 * - Creates its own WiFi network (Access Point).
 * - Receives speed commands over UDP: "L:<-255..255>,R:<-255..255>\n"
 * - Drives 2 motors through an L298N with PWM (ledc) + direction pins.
 * - Sends telemetry over UDP several times per second.
 * - Watchdog: if no command arrives within WATCHDOG_MS, the motors are
 *   stopped (safety, e.g. if the connection to the dashboard drops).
 *
 * Wiring:
 *   Motor A (left):   ENB = GPIO16   IN1 = GPIO33   IN2 = GPIO32
 *   Motor B (right):  ENA = GPIO4    IN3 = GPIO26   IN4 = GPIO25
 *
 * UDP protocol (port 4210):
 *   PC -> Robot:  "L:<int>,R:<int>\n"          (speeds -255..255)
 *   Robot -> PC:  "T:up=<ms>,rssi=<dbm>,l=<int>,r=<int>,batt=<volts>,clients=<n>\n"
 */

#include <WiFi.h>
#include <WiFiUdp.h>

// ---------- WiFi (AP) configuration ----------
const char* AP_SSID = "RobotESP32";
const char* AP_PASS = "robot1234"; // minimum 8 characters

// ---------- Motor pins ----------
#define PWM1_PIN 16   // Motor A (left) - speed
#define IN1_PIN  33  // Motor A - direction 1
#define IN2_PIN  32  // Motor A - direction 2

#define PWM2_PIN 4  // Motor B (right) - speed
#define IN3_PIN  26  // Motor B - direction 1
#define IN4_PIN  25  // Motor B - direction 2

// PWM configuration (ledc for ESP32 core v3.x)
#define PWM_FREQ 5000
#define PWM_RES  8   // 8 bits -> 0..255

// ---------- Battery (optional) ----------
// If you wire a voltage divider to an ADC pin, enable this and adjust
// BATTERY_PIN and BATTERY_DIVIDER (real ratio / reading).
#define BATTERY_ENABLED false
#define BATTERY_PIN 34
#define BATTERY_DIVIDER 2.0f   // adjust to match your resistors
#define BATTERY_VREF 3.3f

// ---------- Network / protocol ----------
#define UDP_PORT 4210
#define WATCHDOG_MS 500        // stop motors if no command arrives within this time
#define TELEMETRY_INTERVAL_MS 200

WiFiUDP udp;
char packetBuffer[128];

int currentL = 0;
int currentR = 0;
unsigned long lastCommandTime = 0;
unsigned long lastTelemetryTime = 0;

IPAddress lastClientIP;
uint16_t lastClientPort = 0;
bool haveClient = false;

// On v3.x we pass the pin directly to ledcWrite instead of a PWM channel
void setMotor(int pwmPin, int in1Pin, int in2Pin, int value) {
  value = constrain(value, -255, 255);
  if (value > 0) {
    digitalWrite(in1Pin, HIGH);
    digitalWrite(in2Pin, LOW);
  } else if (value < 0) {
    digitalWrite(in1Pin, LOW);
    digitalWrite(in2Pin, HIGH);
  } else {
    digitalWrite(in1Pin, LOW);
    digitalWrite(in2Pin, LOW);
  }
  ledcWrite(pwmPin, abs(value));
}

void applyMotors(int l, int r) {
  currentL = l;
  currentR = r;
  setMotor(PWM1_PIN, IN1_PIN, IN2_PIN, currentL);
  setMotor(PWM2_PIN, IN3_PIN, IN4_PIN, currentR);
}

void stopMotors() {
  applyMotors(0, 0);
}

float readBattery() {
  if (!BATTERY_ENABLED) return 0.0f;
  int raw = analogRead(BATTERY_PIN);
  float v = (raw / 4095.0f) * BATTERY_VREF * BATTERY_DIVIDER;
  return v;
}

void setup() {
  Serial.begin(115200);

  pinMode(IN1_PIN, OUTPUT);
  pinMode(IN2_PIN, OUTPUT);
  pinMode(IN3_PIN, OUTPUT);
  pinMode(IN4_PIN, OUTPUT);

  // New ESP32 Core 3.x API: attach pin, frequency and resolution directly
  ledcAttach(PWM1_PIN, PWM_FREQ, PWM_RES);
  ledcAttach(PWM2_PIN, PWM_FREQ, PWM_RES);

  stopMotors();

  WiFi.mode(WIFI_AP);
  WiFi.softAP(AP_SSID, AP_PASS);
  Serial.print("AP started. IP: ");
  Serial.println(WiFi.softAPIP()); // usually 192.168.4.1

  udp.begin(UDP_PORT);
  lastCommandTime = millis();
}

void handleIncomingPacket() {
  int packetSize = udp.parsePacket();
  if (packetSize <= 0) return;

  int len = udp.read(packetBuffer, sizeof(packetBuffer) - 1);
  if (len <= 0) return;
  packetBuffer[len] = 0;

  lastClientIP = udp.remoteIP();
  lastClientPort = udp.remotePort();
  haveClient = true;

  int l = 0, r = 0;
  if (sscanf(packetBuffer, "L:%d,R:%d", &l, &r) == 2) {
    applyMotors(l, r);
    lastCommandTime = millis();
  }
}

void sendTelemetry() {
  if (!haveClient) return;
  char buf[128];
  unsigned long up = millis();
  int rssi = WiFi.RSSI();
  int clients = WiFi.softAPgetStationNum();
  float batt = readBattery();

  snprintf(buf, sizeof(buf), "T:up=%lu,rssi=%d,l=%d,r=%d,batt=%.2f,clients=%d\n",
           up, rssi, currentL, currentR, batt, clients);

  udp.beginPacket(lastClientIP, lastClientPort);
  udp.write((const uint8_t*)buf, strlen(buf));
  udp.endPacket();
}

void loop() {
  handleIncomingPacket();

  if (millis() - lastCommandTime > WATCHDOG_MS) {
    if (currentL != 0 || currentR != 0) {
      stopMotors();
    }
  }

  if (millis() - lastTelemetryTime > TELEMETRY_INTERVAL_MS) {
    sendTelemetry();
    lastTelemetryTime = millis();
  }
}

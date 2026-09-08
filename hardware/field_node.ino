/*
  AI Verdant — Field Node Firmware (ESP32)
  ------------------------------------------------------------------
  Reads all five sensors and POSTs a JSON reading to the AI Verdant
  backend's /api/ingest endpoint every READ_INTERVAL_MS.

  Sensors wired:
    - DHT22           Humidity & Temperature      -> pin DHTPIN
    - HC-SR04         Ultrasonic distance          -> TRIG_PIN / ECHO_PIN
    - Analog pH probe (e.g. DFRobot SEN0161)       -> PH_PIN (ADC)
    - PIR motion sensor                            -> PIR_PIN
    - Capacitive soil moisture sensor              -> SOIL_PIN (ADC)

  Libraries required (Arduino Library Manager):
    - DHT sensor library (Adafruit)
    - ArduinoJson

  Fill in WIFI_SSID / WIFI_PASSWORD / SERVER_URL / DEVICE_API_KEY below,
  or better: move them to a separate secrets.h that you .gitignore.
*/

#include <WiFi.h>
#include <HTTPClient.h>
#include <ArduinoJson.h>
#include <DHT.h>

// ---------------------------------------------------------------- Config
const char* WIFI_SSID     = "YOUR_WIFI_SSID";
const char* WIFI_PASSWORD = "YOUR_WIFI_PASSWORD";
const char* SERVER_URL    = "http://YOUR_BACKEND_HOST:5000/api/ingest";
const char* DEVICE_API_KEY = "farm-secret-key-change-me"; // must match backend .env
const char* DEVICE_ID      = "device-001";
const char* DEVICE_NAME    = "Field A Node";
const char* FARM_NAME      = "Green Valley Farm";
const char* LOCATION       = "North Plot";
const char* CROP_TYPE      = "Tomato";

const unsigned long READ_INTERVAL_MS = 10UL * 60UL * 1000UL; // every 10 minutes

// ---------------------------------------------------------------- Pins
#define DHTPIN   4
#define DHTTYPE  DHT22
#define TRIG_PIN 5
#define ECHO_PIN 18
#define PH_PIN   34   // ADC1_CH6
#define PIR_PIN  27
#define SOIL_PIN 35   // ADC1_CH7

DHT dht(DHTPIN, DHTTYPE);

// pH probe calibration — replace with your own two-point calibration
const float PH_VOLTAGE_NEUTRAL = 1.65; // voltage reading at pH 7.0 buffer
const float PH_SLOPE = -5.70;          // pH change per volt, calibrate with pH 4/7 buffers

// Soil moisture calibration — raw ADC values at fully dry / fully wet
const int SOIL_DRY_RAW = 3000;
const int SOIL_WET_RAW = 1200;

void connectWiFi() {
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
  Serial.println(" connected.");
}

float readUltrasonicCm() {
  digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(2);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  long duration = pulseIn(ECHO_PIN, HIGH, 30000); // 30ms timeout ~5m range
  if (duration == 0) return -1;
  return duration * 0.0343 / 2.0; // speed of sound cm/us, round trip
}

float readPh() {
  int raw = analogRead(PH_PIN);
  float voltage = raw * (3.3 / 4095.0);
  return 7.0 + (voltage - PH_VOLTAGE_NEUTRAL) * PH_SLOPE;
}

float readSoilMoisturePct() {
  int raw = analogRead(SOIL_PIN);
  float pct = (float)(SOIL_DRY_RAW - raw) / (SOIL_DRY_RAW - SOIL_WET_RAW) * 100.0;
  if (pct < 0) pct = 0;
  if (pct > 100) pct = 100;
  return pct;
}

void sendReading(float tempC, float humidity, float soilPct, float ph, float distanceCm, bool motion) {
  if (WiFi.status() != WL_CONNECTED) { connectWiFi(); }

  HTTPClient http;
  http.begin(SERVER_URL);
  http.addHeader("Content-Type", "application/json");
  http.addHeader("X-Device-Key", DEVICE_API_KEY);

  StaticJsonDocument<512> doc;
  doc["device_id"] = DEVICE_ID;
  doc["device_name"] = DEVICE_NAME;
  doc["farm_name"] = FARM_NAME;
  doc["location"] = LOCATION;
  doc["crop_type"] = CROP_TYPE;
  doc["temperature_c"] = tempC;
  doc["humidity_pct"] = humidity;
  doc["soil_moisture_pct"] = soilPct;
  doc["ph"] = ph;
  doc["water_level_cm"] = distanceCm;
  doc["motion_detected"] = motion;

  String body;
  serializeJson(doc, body);

  int statusCode = http.POST(body);
  Serial.print("POST status: ");
  Serial.println(statusCode);
  Serial.println(http.getString());
  http.end();
}

void setup() {
  Serial.begin(115200);
  dht.begin();
  pinMode(TRIG_PIN, OUTPUT);
  pinMode(ECHO_PIN, INPUT);
  pinMode(PIR_PIN, INPUT);
  connectWiFi();
}

void loop() {
  float humidity = dht.readHumidity();
  float tempC = dht.readTemperature();
  float distanceCm = readUltrasonicCm();
  float ph = readPh();
  float soilPct = readSoilMoisturePct();
  bool motion = digitalRead(PIR_PIN) == HIGH;

  if (isnan(humidity) || isnan(tempC)) {
    Serial.println("DHT22 read failed, skipping this cycle.");
  } else {
    sendReading(tempC, humidity, soilPct, ph, distanceCm, motion);
  }

  delay(READ_INTERVAL_MS);
}

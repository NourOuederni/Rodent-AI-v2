/*
  Ultrasonic_Motion.ino — movement detection with HC-SR04 (ESP32-CAM)
  Wiring unchanged: VCC->3.3V, GND->GND, TRIG->12, ECHO->13

  Boot with the scene EMPTY: it calibrates a baseline for ~3 s,
  then reports MOTION whenever something enters closer than baseline.
*/

#define TRIG_PIN 12
#define ECHO_PIN 13
#define RED_LED  33

// ---- tuning ----
const float    MIN_DELTA_CM   = 6.0;   // must be at least this much closer than baseline
const float    MIN_DELTA_PCT  = 0.15;  // ...or 15% of baseline, whichever is larger
const int      CONFIRM_COUNT  = 2;     // consecutive anomalous reads to declare motion
const int      CLEAR_COUNT    = 4;     // consecutive normal reads to declare clear
const uint32_t SAMPLE_MS      = 120;   // sampling rate
// ----------------

float baseline = 0;
int   anomaly_streak = 0, normal_streak = 0;
bool  in_motion = false;
uint32_t motion_events = 0;

float readCm() {
  digitalWrite(TRIG_PIN, LOW);  delayMicroseconds(3);
  digitalWrite(TRIG_PIN, HIGH); delayMicroseconds(10);
  digitalWrite(TRIG_PIN, LOW);
  uint32_t us = pulseIn(ECHO_PIN, HIGH, 30000);
  return us == 0 ? -1 : us * 0.0343f / 2.0f;
}

// median of 3 kills single-sample spikes
float readCmStable() {
  float a = readCm(); delay(15);
  float b = readCm(); delay(15);
  float c = readCm();
  if (a < 0 || b < 0 || c < 0) return -1;
  if (a > b) { float t = a; a = b; b = t; }
  if (b > c) { float t = b; b = c; c = t; }
  if (a > b) { float t = a; a = b; b = t; }
  return b;
}

void setup() {
  Serial.begin(115200);
  pinMode(TRIG_PIN, OUTPUT); pinMode(ECHO_PIN, INPUT);
  pinMode(RED_LED, OUTPUT);  digitalWrite(RED_LED, HIGH);
  digitalWrite(TRIG_PIN, LOW);

  Serial.println("\nCalibrating baseline — keep the scene EMPTY...");
  float sum = 0; int n = 0;
  uint32_t t0 = millis();
  while (millis() - t0 < 3000) {
    float d = readCmStable();
    if (d > 0) { sum += d; n++; }
    delay(100);
  }
  if (n == 0) { Serial.println("No echo during calibration — check wiring."); while (1) delay(1000); }
  baseline = sum / n;
  Serial.printf("Baseline: %.1f cm. Watching for movement...\n", baseline);
}

void loop() {
  float d = readCmStable();
  if (d < 0) { delay(SAMPLE_MS); return; }

  float threshold = baseline - max(MIN_DELTA_CM, baseline * MIN_DELTA_PCT);
  bool anomalous = d < threshold;

  if (anomalous) { anomaly_streak++; normal_streak = 0; }
  else           { normal_streak++;  anomaly_streak = 0; }

  if (!in_motion && anomaly_streak >= CONFIRM_COUNT) {
    in_motion = true;
    motion_events++;
    Serial.printf("[%8lu ms]  MOTION #%lu — object at %.1f cm (baseline %.1f)\n",
                  (unsigned long) millis(), (unsigned long) motion_events, d, baseline);
    digitalWrite(RED_LED, LOW);
  }
  if (in_motion && normal_streak >= CLEAR_COUNT) {
    in_motion = false;
    Serial.printf("[%8lu ms]  clear\n", (unsigned long) millis());
    digitalWrite(RED_LED, HIGH);
  }

  // slow baseline adaptation while the scene is clear (drift compensation)
  if (!in_motion && !anomalous) baseline = baseline * 0.995f + d * 0.005f;

  delay(SAMPLE_MS);
}
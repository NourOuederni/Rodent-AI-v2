/*
  IR_Sensor_Test.ino — MH "Flying-Fish" IR sensor test for ESP32-CAM (AI-Thinker)

  WIRING:
    VCC -> 5V (or 3.3V)     GND -> GND     OUT -> GPIO 13
    (4th pin "EN", if present: leave unconnected)

  These LM393 boards are usually ACTIVE-LOW (OUT goes LOW on detection),
  but variants differ — this sketch just reports every transition and its
  direction, so it identifies your board's polarity for you.

  CALIBRATION: turn the blue potentiometer to set the detection distance
  (~2-30 cm). The onboard LED on the sensor lights when it detects — use
  that as ground truth while tuning.
*/

#define SENSOR_PIN  13
#define RED_LED     33      // onboard red LED, active LOW

int last_state = -1;
uint32_t events = 0;

void setup() {
  Serial.begin(115200);
  pinMode(SENSOR_PIN, INPUT);
  pinMode(RED_LED, OUTPUT);
  digitalWrite(RED_LED, HIGH);   // off

  delay(300);
  int s = digitalRead(SENSOR_PIN);
  Serial.println();
  Serial.printf("Idle state with nothing in front: %s\n", s ? "HIGH" : "LOW");
  Serial.println("=> detection will be the OPPOSITE level.");
  Serial.println("Move your hand toward the sensor...");
  last_state = s;
}

void loop() {
  int state = digitalRead(SENSOR_PIN);
  if (state != last_state) {
    last_state = state;
    events++;
    Serial.printf("[%8lu ms]  OUT went %s   (transition #%lu)\n",
                  (unsigned long) millis(), state ? "HIGH" : "LOW",
                  (unsigned long) events);
    // mirror the sensor on the board LED: assume detection = LOW (typical)
    digitalWrite(RED_LED, state == LOW ? LOW : HIGH);
  }
  delay(30);
}

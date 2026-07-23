#include <RodentDetectorV2.h>

RodentDetectorV2 detector;

uint8_t image_buffer[224 * 224 * 3];

void setup() {
  Serial.begin(115200);
  while (!Serial) {}

  if (!detector.begin()) {
    Serial.println("Failed to initialize model.");
    while (1) {}
  }
  Serial.println("Model ready.");
}

void loop() {
  // TODO: capture a frame into image_buffer here, resized to 224x224
  float rodent_prob = detector.predict(image_buffer);
  Serial.print("Rodent probability: ");
  Serial.println(rodent_prob);

  delay(1000);
}

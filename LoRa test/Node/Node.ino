#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};
int counter = 0;
unsigned long lastTx = 0;

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
#else
void onRecv(const uint8_t *mac, const uint8_t *data, int len) {
#endif
  Serial.print("RX from gateway: ");
  Serial.write(data, len);
  Serial.println();
}

void setup() {
  Serial.begin(115200);
  delay(1000);

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(1, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init FAILED");
    while (true) delay(1000);
  }
  esp_now_register_recv_cb(onRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = 1;
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  Serial.println("CAM ready");
}

void loop() {
  if (millis() - lastTx > 5000) {
    lastTx = millis();
    String msg = "CAM hello #" + String(counter++);
    esp_now_send(BCAST, (const uint8_t *)msg.c_str(), msg.length());
    Serial.println("TX: " + msg);
  }
}
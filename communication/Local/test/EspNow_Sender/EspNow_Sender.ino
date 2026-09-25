/*
  EspNow_Sender.ino — runs on the ESP32-CAM (AI-Thinker)
  Sends a fake rat alert over ESP-NOW every 5 s to the Heltec bridge.

  BEFORE FLASHING: put the HELTEC's MAC address into RECEIVER_MAC below
  (from the MAC sketch). Format: {0xAA,0xBB,0xCC,0xDD,0xEE,0xFF}
  Flash with any sensors disconnected, as usual.
*/

#include <WiFi.h>
#include <esp_now.h>

// ---- EDIT: the Heltec's MAC ----
uint8_t RECEIVER_MAC[] = { 0xAA, 0xBB, 0xCC, 0xDD, 0xEE, 0xFF };
// --------------------------------

// The alert packet — same shape the real firmware will send.
typedef struct __attribute__((packed)) {
  uint32_t alert_id;
  float    peak;
  uint8_t  rats;
  uint32_t uptime_s;
} AlertMsg;

uint32_t counter = 0;
volatile bool last_ok = false;

void onSent(const wifi_tx_info_t* info, esp_now_send_status_t status) {
  last_ok = (status == ESP_NOW_SEND_SUCCESS);
  Serial.printf("  delivery: %s\n", last_ok ? "OK" : "FAILED (receiver on? MAC right?)");
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  delay(200);
  Serial.println();
  Serial.print("Sender MAC: "); Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("esp_now_init failed — halting"); while (1) delay(1000);
  }
  esp_now_register_send_cb(onSent);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, RECEIVER_MAC, 6);
  peer.channel = 0;          // 0 = current channel; both boards default to ch1
  peer.encrypt = false;
  if (esp_now_add_peer(&peer) != ESP_OK) {
    Serial.println("add_peer failed — check the MAC"); while (1) delay(1000);
  }
  Serial.println("ESP-NOW ready. Sending a fake alert every 5 s...");
}

void loop() {
  AlertMsg msg;
  msg.alert_id = ++counter;
  msg.peak     = 0.5f + (counter % 50) / 100.0f;
  msg.rats     = 1 + (counter % 3);
  msg.uptime_s = millis() / 1000;

  Serial.printf("[send] alert #%lu  peak=%.2f rats=%u\n",
                (unsigned long) msg.alert_id, msg.peak, msg.rats);
  esp_now_send(RECEIVER_MAC, (uint8_t*) &msg, sizeof(msg));

  delay(5000);
}

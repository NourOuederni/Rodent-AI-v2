/*
  EspNow_Receiver.ino — runs on the Heltec WiFi LoRa 32 (V3)
  Receives alert packets from the ESP32-CAM over ESP-NOW and prints them.
  (LoRa forwarding gets added here later — this is the bridge-to-be.)

  Board: Tools -> Board -> esp32 -> "Heltec WiFi LoRa 32(V3)"
*/

#include <WiFi.h>
#include <esp_now.h>

typedef struct __attribute__((packed)) {
  uint32_t alert_id;
  float    peak;
  uint8_t  rats;
  uint32_t uptime_s;
} AlertMsg;

uint32_t received = 0;

void onRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
  if (len != sizeof(AlertMsg)) {
    Serial.printf("[recv] unexpected size %d (wanted %d)\n", len, (int) sizeof(AlertMsg));
    return;
  }
  AlertMsg msg;
  memcpy(&msg, data, sizeof(msg));
  received++;

  char mac[18];
  snprintf(mac, sizeof(mac), "%02X:%02X:%02X:%02X:%02X:%02X",
           info->src_addr[0], info->src_addr[1], info->src_addr[2],
           info->src_addr[3], info->src_addr[4], info->src_addr[5]);

  Serial.printf("[recv #%lu] from %s  alert #%lu  peak=%.2f  rats=%u  node-uptime=%lus\n",
                (unsigned long) received, mac,
                (unsigned long) msg.alert_id, msg.peak, msg.rats,
                (unsigned long) msg.uptime_s);
  // TODO next phase: forward this over LoRa (SX1262) and/or WiFi->Supabase
}

void setup() {
  Serial.begin(115200);
  WiFi.mode(WIFI_STA);
  delay(200);
  Serial.println();
  Serial.print("Receiver MAC (paste into the sender): ");
  Serial.println(WiFi.macAddress());

  if (esp_now_init() != ESP_OK) {
    Serial.println("esp_now_init failed — halting"); while (1) delay(1000);
  }
  esp_now_register_recv_cb(onRecv);
  Serial.println("ESP-NOW listening...");
}

void loop() { delay(1000); }

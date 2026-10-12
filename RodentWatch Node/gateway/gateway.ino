#include <RadioLib.h>
#include <SPI.h>
#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

#define ESPNOW_CHANNEL 1     // hotspot mode = 1. Router mode: use the channel the CAM printed.

#define LORA_NSS   8
#define LORA_SCK   9
#define LORA_MOSI  10
#define LORA_MISO  11
#define LORA_RST   12
#define LORA_BUSY  13
#define LORA_DIO1  14

SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY);
uint8_t BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

volatile bool rxFlag = false;
void IRAM_ATTR setFlag() { rxFlag = true; }

const int QN = 8;
uint8_t qbuf[QN][250];
uint8_t qlen[QN];
volatile uint8_t qh = 0, qt = 0;

#if ESP_ARDUINO_VERSION_MAJOR >= 3
void onNowRecv(const esp_now_recv_info_t *info, const uint8_t *data, int len) {
#else
void onNowRecv(const uint8_t *mac, const uint8_t *data, int len) {
#endif
  uint8_t n = (qh + 1) % QN;
  if (n == qt || len < 1 || len > 250) return;
  memcpy(qbuf[qh], data, len);
  qlen[qh] = len;
  qh = n;
}

void loraListen() {
  rxFlag = false;            // ignore the TX-done interrupt (this caused the echo)
  radio.startReceive();
}

void setup() {
  Serial.begin(115200);
  delay(2000);

  SPI.begin(LORA_SCK, LORA_MISO, LORA_MOSI, LORA_NSS);
  int state = radio.begin(868.0, 125.0, 7, 5, 0x12, 14, 8, 1.8);
  if (state != RADIOLIB_ERR_NONE) {
    Serial.println("LoRa init FAILED, code " + String(state));
    while (true) delay(1000);
  }
  radio.setCRC(true);
  radio.setDio1Action(setFlag);
  loraListen();

  WiFi.mode(WIFI_STA);
  WiFi.disconnect();
  esp_wifi_set_channel(ESPNOW_CHANNEL, WIFI_SECOND_CHAN_NONE);
  if (esp_now_init() != ESP_OK) {
    Serial.println("ESP-NOW init FAILED");
    while (true) delay(1000);
  }
  esp_now_register_recv_cb(onNowRecv);

  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, BCAST, 6);
  peer.channel = 0;
  peer.encrypt = false;
  esp_now_add_peer(&peer);

  Serial.println("Gateway ready");
}

void loop() {
  // CAM (ESP-NOW) -> LoRa
  if (qt != qh) {
    Serial.print("NOW->LoRa: ");
    Serial.write(qbuf[qt], qlen[qt]);
    Serial.println();
    radio.transmit(qbuf[qt], qlen[qt]);
    qt = (qt + 1) % QN;
    loraListen();
  }

  // LoRa (from Heltec A) -> CAM (ESP-NOW)
  if (rxFlag) {
    rxFlag = false;
    uint8_t buf[250];
    size_t len = radio.getPacketLength();
    if (len > sizeof(buf)) len = sizeof(buf);
    int state = radio.readData(buf, len);
    if (state == RADIOLIB_ERR_NONE && len > 0) {
      Serial.print("LoRa->NOW: ");
      Serial.write(buf, len);
      Serial.println();
      esp_now_send(BCAST, buf, len);
    }
    radio.startReceive();
  }
}
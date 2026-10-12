#include <RadioLib.h>
#include <SPI.h>

// Heltec WiFi LoRa 32 V3 pins (SX1262)
#define LORA_NSS   8
#define LORA_SCK   9
#define LORA_MOSI  10
#define LORA_MISO  11
#define LORA_RST   12
#define LORA_BUSY  13
#define LORA_DIO1  14

SX1262 radio = new Module(LORA_NSS, LORA_DIO1, LORA_RST, LORA_BUSY);

volatile bool rxFlag = false;
void IRAM_ATTR setFlag() { rxFlag = true; }

int counter = 0;
unsigned long lastTx = 0;

void sendMsg(String msg) {
  int state = radio.transmit(msg);
  if (state == RADIOLIB_ERR_NONE) Serial.println("TX: " + msg);
  else Serial.println("TX failed, code " + String(state));
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
  radio.startReceive();
  Serial.println("LoRa OK. Type a message and press Enter to send it.");
}

void loop() {
  if (millis() - lastTx > 5000) {
    lastTx = millis();
    sendMsg("hello #" + String(counter++));
  }

  if (Serial.available()) {
    String s = Serial.readStringUntil('\n');
    s.trim();
    if (s.length()) sendMsg(s);
  }

  if (rxFlag) {
    rxFlag = false;
    String s;
    int state = radio.readData(s);
    if (state == RADIOLIB_ERR_NONE) {
      Serial.println("RX: " + s + "   (RSSI " + String(radio.getRSSI()) +
                     " dBm, SNR " + String(radio.getSNR(), 1) + " dB)");
    } else {
      Serial.println("RX error, code " + String(state));
    }
    radio.startReceive();
  }
}
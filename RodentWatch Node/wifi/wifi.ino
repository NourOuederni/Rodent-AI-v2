#include <RadioLib.h>
#include <SPI.h>
#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

// ---- EDIT THESE ----
const char* WIFI_SSID     = "YOUR_WIFI";
const char* WIFI_PASSWORD = "YOUR_PASSWORD";
const char* CLOUD_URL     = "https://vkeeujkwjoiholgojrdw.supabase.co/functions/v1/ingest-alert";
const char* CLOUD_API_KEY = "YOUR_NODE_API_KEY";
const char* FW_VERSION    = "1.2.0";
const char* MODEL_VERSION = "FOMO v3";
// --------------------

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

struct Job { char json[380]; char ack[40]; int slot; };
struct AckMsg { char msg[40]; };
QueueHandle_t jobQ, ackQ;

// recent alerts, for duplicate detection (CAM retries until it hears an ACK)
struct Seen { volatile bool used; volatile bool done; char node[16]; uint32_t id; };
Seen seen[16];
int seenNext = 0;

int findSeen(const char* node, uint32_t id) {
  for (int i = 0; i < 16; i++)
    if (seen[i].used && seen[i].id == id && strcmp(seen[i].node, node) == 0) return i;
  return -1;
}

void loraListen() { rxFlag = false; radio.startReceive(); }

void sendAck(const char* s) {
  radio.transmit((uint8_t*)s, strlen(s));
  Serial.printf("TX ACK: %s\n", s);
  loraListen();
}

void cloudTask(void*) {
  Job job;
  for (;;) {
    if (xQueueReceive(jobQ, &job, portMAX_DELAY) != pdTRUE) continue;
    bool ok = false;
    if (WiFi.status() == WL_CONNECTED) {
      WiFiClientSecure client;
      client.setInsecure();
      HTTPClient http;
      if (http.begin(client, CLOUD_URL)) {
        http.addHeader("Content-Type", "application/json");
        int code = http.POST((uint8_t*)job.json, strlen(job.json));
        Serial.printf("[cloud] POST -> %d\n", code);
        ok = (code >= 200 && code < 300);
        http.end();
      }
    } else {
      Serial.println("[cloud] no WiFi");
    }
    if (job.slot >= 0) {                       // alert (heartbeats have slot -1)
      if (ok) {
        seen[job.slot].done = true;
        AckMsg a; strlcpy(a.msg, job.ack, sizeof(a.msg));
        xQueueSend(ackQ, &a, 0);
      } else {
        seen[job.slot].used = false;           // let the CAM's retry try again
      }
    }
  }
}

void handlePacket(char* p) {
  char* t[8]; int n = 0;
  for (char* tok = strtok(p, ","); tok && n < 8; tok = strtok(nullptr, ",")) t[n++] = tok;
  if (n < 2) return;

  Job job; job.slot = -1; job.ack[0] = 0;

  if (t[0][0] == 'H') {                        // H,node
    snprintf(job.json, sizeof(job.json),
      "{\"node_id\":\"%s\",\"api_key\":\"%s\",\"heartbeat_only\":true,"
      "\"firmware_version\":\"%s\",\"model_version\":\"%s\"}",
      t[1], CLOUD_API_KEY, FW_VERSION, MODEL_VERSION);
    xQueueSend(jobQ, &job, 0);
  }
  else if (t[0][0] == 'A' && n >= 7) {         // A,node,id,pos,shots,peak1000,rats
    uint32_t id = strtoul(t[2], nullptr, 10);
    int s = findSeen(t[1], id);
    if (s >= 0) {
      if (seen[s].done) {                      // already posted: just re-ACK
        char a[40]; snprintf(a, sizeof(a), "K,%s,%lu", t[1], (unsigned long)id);
        sendAck(a);
      }
      return;                                  // or still in flight: ignore
    }
    s = seenNext; seenNext = (seenNext + 1) % 16;
    seen[s].used = true; seen[s].done = false; seen[s].id = id;
    strlcpy(seen[s].node, t[1], sizeof(seen[s].node));

    snprintf(job.json, sizeof(job.json),
      "{\"node_id\":\"%s\",\"api_key\":\"%s\",\"node_alert_id\":%lu,\"node_uptime_s\":0,"
      "\"peak_score\":%.3f,\"rat_count\":%d,\"positives\":%d,\"shots\":%d,\"files\":[]}",
      t[1], CLOUD_API_KEY, (unsigned long)id, atoi(t[5]) / 1000.0f, atoi(t[6]), atoi(t[3]), atoi(t[4]));
    snprintf(job.ack, sizeof(job.ack), "K,%s,%lu", t[1], (unsigned long)id);
    job.slot = s;
    if (xQueueSend(jobQ, &job, 0) != pdTRUE) seen[s].used = false;
  }
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

  jobQ = xQueueCreate(6, sizeof(Job));
  ackQ = xQueueCreate(6, sizeof(AckMsg));
  xTaskCreatePinnedToCore(cloudTask, "cloud", 16384, nullptr, 1, nullptr, 0);

  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("WiFi");
  for (int i = 0; i < 40 && WiFi.status() != WL_CONNECTED; i++) { delay(500); Serial.print("."); }
  Serial.println(WiFi.status() == WL_CONNECTED ? " connected" : " not connected yet");
  Serial.println("Heltec A ready");
}

void loop() {
  static uint32_t lastWifiTry = 0;
  if (WiFi.status() != WL_CONNECTED && millis() - lastWifiTry > 10000) {
    lastWifiTry = millis();
    WiFi.disconnect();
    WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  }

  if (rxFlag) {
    rxFlag = false;
    uint8_t buf[250];
    size_t len = radio.getPacketLength();
    if (len > sizeof(buf) - 1) len = sizeof(buf) - 1;
    int state = radio.readData(buf, len);
    if (state == RADIOLIB_ERR_NONE && len > 0) {
      buf[len] = 0;
      Serial.printf("RX: %s  (RSSI %.0f dBm, SNR %.1f dB)\n",
                    (char*)buf, radio.getRSSI(), radio.getSNR());
      handlePacket((char*)buf);
    }
    radio.startReceive();
  }

  AckMsg a;
  if (xQueueReceive(ackQ, &a, 0) == pdTRUE) sendAck(a.msg);
}
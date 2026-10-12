/*
  cloud_post.h — cloud reporting via a dedicated FreeRTOS task.
  TLS runs in its own 16KB-stack task (loop()'s 8KB stack overflows during
  the mbedTLS handshake — the cause of the reboot-on-heartbeat).

  Wire-up in the .ino:
    - setup(), after server.begin():   cloudStart();
    - everything else stays: cloudHeartbeat() / cloudPostAlert() calls now
      just enqueue and return instantly.
*/

#ifndef CLOUD_POST_H
#define CLOUD_POST_H

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

// ---- EDIT THESE ----------------------------------------------------------
static const char* CLOUD_URL =
  "https://vkeeujkwjoiholgojrdw.supabase.co/functions/v1/ingest-alert";
static const char* CLOUD_NODE_ID  = "node-01";
static const char* CLOUD_API_KEY  = "f6ddd667-2e94-4610-9190-be0bf4658dfc";
static const char* FW_VERSION     = "1.2.0";
static const char* MODEL_VERSION  = "FOMO v3";
// --------------------------------------------------------------------------

static QueueHandle_t cloud_q = nullptr;

static void cloudTask(void*) {
  char* msg;
  for (;;) {
    if (xQueueReceive(cloud_q, &msg, portMAX_DELAY) == pdTRUE) {
      if (WiFi.status() == WL_CONNECTED) {
        WiFiClientSecure client;
        client.setInsecure();
        HTTPClient http;
        if (http.begin(client, CLOUD_URL)) {
          http.addHeader("Content-Type", "application/json");
          int code = http.POST((uint8_t*)msg, strlen(msg));
          Serial.printf("[cloud] POST -> %d\n", code);
          http.end();
        }
      } else {
        Serial.println("[cloud] skipped (no WiFi)");
      }
      free(msg);
    }
  }
}

inline void cloudStart() {
  if (cloud_q) return;
  cloud_q = xQueueCreate(6, sizeof(char*));
  xTaskCreatePinnedToCore(cloudTask, "cloud", 16384, nullptr, 1, nullptr, 0);
}

inline bool cloudEnqueue(const String& json) {
  if (!cloud_q) return false;
  char* copy = (char*) malloc(json.length() + 1);
  if (!copy) return false;
  strcpy(copy, json.c_str());
  if (xQueueSend(cloud_q, &copy, 0) != pdTRUE) { free(copy); return false; }
  return true;
}

inline bool cloudHeartbeat() {
  String j = String("{\"node_id\":\"") + CLOUD_NODE_ID +
             "\",\"api_key\":\"" + CLOUD_API_KEY +
             "\",\"heartbeat_only\":true" +
             ",\"firmware_version\":\"" + FW_VERSION +
             "\",\"model_version\":\"" + MODEL_VERSION + "\"}";
  return cloudEnqueue(j);
}

inline bool cloudPostAlert(uint32_t alertId, int positives, int shots,
                           float peak, int rats, const String& shotNamesJson) {
  String j = String("{\"node_id\":\"") + CLOUD_NODE_ID +
             "\",\"api_key\":\"" + CLOUD_API_KEY +
             "\",\"node_alert_id\":" + String(alertId) +
             ",\"node_uptime_s\":" + String(millis() / 1000) +
             ",\"peak_score\":" + String(peak, 3) +
             ",\"rat_count\":" + String(rats) +
             ",\"positives\":" + String(positives) +
             ",\"shots\":" + String(shots) +
             ",\"files\":[" + shotNamesJson + "]}";
  return cloudEnqueue(j);
}

#endif
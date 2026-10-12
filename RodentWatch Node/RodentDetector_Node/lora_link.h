#ifndef LORA_LINK_H
#define LORA_LINK_H

#include <WiFi.h>
#include <esp_now.h>
#include <esp_wifi.h>

static const char*   LINK_NODE_ID = "node-01";   // must match DEVICE_NAME
static const uint8_t LINK_CHANNEL = 1;           // used in hotspot mode
static uint8_t LINK_BCAST[6] = {0xFF, 0xFF, 0xFF, 0xFF, 0xFF, 0xFF};

static const int      MAX_PENDING   = 4;
static const uint8_t  MAX_TRIES     = 6;
static const uint32_t RETRY_BASE_MS = 20000;

struct PendingAlert {
  volatile bool used;
  uint32_t id;
  char msg[100];
  uint8_t tries;
  uint32_t nextTry;
};
static PendingAlert pend[MAX_PENDING];

inline void linkSendRaw(const char* s) {
  esp_now_send(LINK_BCAST, (const uint8_t*)s, strlen(s));
}

#if ESP_ARDUINO_VERSION_MAJOR >= 3
inline void linkOnRecv(const esp_now_recv_info_t* info, const uint8_t* data, int len) {
#else
inline void linkOnRecv(const uint8_t* mac, const uint8_t* data, int len) {
#endif
  // expected: K,<node>,<id>
  if (len < 5 || len > 40 || data[0] != 'K' || data[1] != ',') return;
  char buf[48];
  memcpy(buf, data, len);
  buf[len] = 0;
  char* node = buf + 2;
  char* comma = strchr(node, ',');
  if (!comma) return;
  *comma = 0;
  if (strcmp(node, LINK_NODE_ID) != 0) return;
  uint32_t id = strtoul(comma + 1, nullptr, 10);
  for (int i = 0; i < MAX_PENDING; i++)
    if (pend[i].used && pend[i].id == id) pend[i].used = false;   // acknowledged
}

inline bool linkBegin() {
  if (esp_now_init() != ESP_OK) { Serial.println("[link] ESP-NOW init FAILED"); return false; }
  esp_now_register_recv_cb(linkOnRecv);
  esp_now_peer_info_t peer = {};
  memcpy(peer.peer_addr, LINK_BCAST, 6);
  peer.channel = 0;                 // 0 = current WiFi channel
  peer.ifidx = WIFI_IF_STA;
  peer.encrypt = false;
  esp_now_add_peer(&peer);
  Serial.println("[link] ESP-NOW ready");
  return true;
}

inline void linkSendHeartbeat() {
  char b[40];
  snprintf(b, sizeof(b), "H,%s", LINK_NODE_ID);
  linkSendRaw(b);
  Serial.printf("[link] heartbeat sent\n");
}

inline void linkQueueAlert(uint32_t id, int positives, int shots, float peak, int rats) {
  int slot = -1;
  for (int i = 0; i < MAX_PENDING; i++) if (!pend[i].used) { slot = i; break; }
  if (slot < 0) slot = 0;           // all busy: overwrite the first
  snprintf(pend[slot].msg, sizeof(pend[slot].msg), "A,%s,%lu,%d,%d,%d,%d",
           LINK_NODE_ID, (unsigned long)id, positives, shots, (int)(peak * 1000), rats);
  pend[slot].id = id;
  pend[slot].tries = 0;
  pend[slot].nextTry = millis();
  pend[slot].used = true;
}

// call from loop(): (re)sends unacknowledged alerts
inline void linkTick() {
  for (int i = 0; i < MAX_PENDING; i++) {
    if (!pend[i].used) continue;
    if ((int32_t)(millis() - pend[i].nextTry) < 0) continue;
    if (pend[i].tries >= MAX_TRIES) {
      Serial.printf("[link] alert %lu given up (no ACK)\n", (unsigned long)pend[i].id);
      pend[i].used = false;
      continue;
    }
    linkSendRaw(pend[i].msg);
    pend[i].tries++;
    pend[i].nextTry = millis() + RETRY_BASE_MS + random(0, 5000);
    Serial.printf("[link] sent %s (try %u)\n", pend[i].msg, pend[i].tries);
  }
}

#endif
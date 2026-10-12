/*
  cloud_post.h — add cloud reporting to RodentDetector_Node.ino
  (dev mode: node has home WiFi; in production the LoRa gateway makes
   these same calls instead of the node)

  HOW TO WIRE IN:
  1) Put this file in the sketch folder and add at the top of the .ino:
       #include "cloud_post.h"
  2) Fill in the three constants below (URL from your Supabase project,
     API key from:  select id, api_key from nodes;  in the SQL editor).
  3) In runBurst(), after the alert is saved locally, add:
       cloudPostAlert(alert_counter, positives, BURST_SHOTS, burstPeak,
                      maxBlobs, shotNames);
  4) In loop(), add a heartbeat every 5 minutes:
       static uint32_t last_hb = 0;
       if (millis() - last_hb > 300000) { last_hb = millis(); cloudHeartbeat(); }
*/

#ifndef CLOUD_POST_H
#define CLOUD_POST_H

#include <WiFi.h>
#include <WiFiClientSecure.h>
#include <HTTPClient.h>

// ---- EDIT THESE ----------------------------------------------------------
static const char* CLOUD_URL =
  "https://YOUR-PROJECT-REF.supabase.co/functions/v1/ingest-alert";
static const char* CLOUD_NODE_ID  = "node-01";
static const char* CLOUD_API_KEY  = "PASTE-THE-NODE-API-KEY-UUID";
static const char* FW_VERSION     = "1.2.0";
static const char* MODEL_VERSION  = "FOMO v3";
// --------------------------------------------------------------------------

inline bool cloudSend(const String& json) {
  if (WiFi.status() != WL_CONNECTED) return false;
  WiFiClientSecure client;
  client.setInsecure();               // v1: skip cert pinning
  HTTPClient http;
  if (!http.begin(client, CLOUD_URL)) return false;
  http.addHeader("Content-Type", "application/json");
  int code = http.POST(json);
  http.end();
  Serial.printf("[cloud] POST -> %d\n", code);
  return code >= 200 && code < 300;
}

inline bool cloudHeartbeat() {
  String j = String("{\"node_id\":\"") + CLOUD_NODE_ID +
             "\",\"api_key\":\"" + CLOUD_API_KEY +
             "\",\"heartbeat_only\":true" +
             ",\"firmware_version\":\"" + FW_VERSION +
             "\",\"model_version\":\"" + MODEL_VERSION + "\"}";
  return cloudSend(j);
}

// shotNamesJson: the same comma-separated quoted list built in runBurst,
// e.g.  "\"R42_0.jpg\",\"R42_1.jpg\""   (may be empty)
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
  return cloudSend(j);
}

#endif

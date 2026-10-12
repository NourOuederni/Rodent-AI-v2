/*
  RodentDetector_Node.ino
  ESP32-CAM (AI-Thinker) - autonomous detection node + REST API for mobile app
  Alerts leave via ESP-NOW -> Heltec B -> LoRa -> Heltec A -> Supabase.
  Photos/status stay available over WiFi (CAM hotspot or router).

  BOARD SETTINGS: AI Thinker ESP32-CAM, CPU 240MHz, Flash 40MHz DIO, Huge APP.
  MODEL: put your fomo_model_data.h in the sketch folder.
*/

#include <WiFi.h>
#include <WebServer.h>
#include <SD_MMC.h>
#include <Preferences.h>
#include <time.h>
#include <math.h>
#include "esp_camera.h"
#include "img_converters.h"

#include <Chirale_TensorFlowLite.h>
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "fomo_model_data.h"
#include "lora_link.h"

// ---- EDIT THESE ----------------------------------------------------------
#define USE_HOTSPOT 0                       // 1 = CAM makes its own WiFi (recommended), 0 = join router
const char *AP_SSID       = "RodentCam-01"; // hotspot name
const char *AP_PASSWORD   = "rodent1234";   // 8+ characters
const char *WIFI_SSID     = "ENITWireless"; // only used when USE_HOTSPOT = 0
const char *WIFI_PASSWORD = "";
const char *DEVICE_NAME   = "node-01";      // must match LINK_NODE_ID in lora_link.h

const float    DETECT_THRESHOLD    = 0.5f;
const uint32_t CAPTURE_INTERVAL_MS = 5UL * 60UL * 1000UL;  // 5 min
const int      BURST_SHOTS         = 10;
const uint32_t BURST_GAP_MS        = 200;
const int      MAX_SAVE_PER_ALERT  = 3;
// --------------------------------------------------------------------------

// FOMO geometry
static const int IN_W = 96, IN_H = 96, GRID = 12, MAX_DETS = 24;

// TFLite Micro
static const int kArenaSize = 300 * 1024;
static uint8_t* tensor_arena = nullptr;
static const tflite::Model* tfl_model = nullptr;
static tflite::MicroInterpreter* interpreter = nullptr;
static TfLiteTensor *input = nullptr, *output = nullptr;
static tflite::MicroMutableOpResolver<12> resolver;

static uint8_t* gray_input = nullptr;
static uint32_t last_infer_ms = 0;

// State
Preferences prefs;
static uint32_t alert_counter = 0;
static uint32_t total_bursts = 0;
static uint32_t total_alerts_session = 0;
static String   last_burst_summary = "none yet";
static uint8_t* test_jpg = nullptr;
static size_t   test_jpg_len = 0;
static bool     sd_ok = false;
static bool     time_ok = false;

// AI-Thinker pins
#define PWDN_GPIO_NUM 32
#define RESET_GPIO_NUM -1
#define XCLK_GPIO_NUM 0
#define SIOD_GPIO_NUM 26
#define SIOC_GPIO_NUM 27
#define Y9_GPIO_NUM 35
#define Y8_GPIO_NUM 34
#define Y7_GPIO_NUM 39
#define Y6_GPIO_NUM 36
#define Y5_GPIO_NUM 21
#define Y4_GPIO_NUM 19
#define Y3_GPIO_NUM 18
#define Y2_GPIO_NUM 5
#define VSYNC_GPIO_NUM 25
#define HREF_GPIO_NUM 23
#define PCLK_GPIO_NUM 22

WebServer server(80);

// ───────────────────── Camera ─────────────────────

bool initCamera() {
  camera_config_t c;
  c.ledc_channel = LEDC_CHANNEL_0; c.ledc_timer = LEDC_TIMER_0;
  c.pin_d0 = Y2_GPIO_NUM; c.pin_d1 = Y3_GPIO_NUM; c.pin_d2 = Y4_GPIO_NUM; c.pin_d3 = Y5_GPIO_NUM;
  c.pin_d4 = Y6_GPIO_NUM; c.pin_d5 = Y7_GPIO_NUM; c.pin_d6 = Y8_GPIO_NUM; c.pin_d7 = Y9_GPIO_NUM;
  c.pin_xclk = XCLK_GPIO_NUM; c.pin_pclk = PCLK_GPIO_NUM;
  c.pin_vsync = VSYNC_GPIO_NUM; c.pin_href = HREF_GPIO_NUM;
  c.pin_sscb_sda = SIOD_GPIO_NUM; c.pin_sscb_scl = SIOC_GPIO_NUM;
  c.pin_pwdn = PWDN_GPIO_NUM; c.pin_reset = RESET_GPIO_NUM;
  c.xclk_freq_hz = 10000000;
  c.pixel_format = PIXFORMAT_JPEG;
  c.frame_size   = FRAMESIZE_QVGA;
  c.jpeg_quality = 15;
  c.fb_count     = 2;
  c.fb_location  = CAMERA_FB_IN_PSRAM;
  c.grab_mode    = CAMERA_GRAB_LATEST;
  return esp_camera_init(&c) == ESP_OK;
}

// ───────────────────── Model ─────────────────────

bool modelBegin() {
  tensor_arena = (uint8_t*) heap_caps_malloc(kArenaSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!tensor_arena) return false;
  tfl_model = tflite::GetModel(fomo_rat_int8_tflite);
  if (tfl_model->version() != TFLITE_SCHEMA_VERSION) return false;
  resolver.AddConv2D(); resolver.AddDepthwiseConv2D(); resolver.AddAdd();
  resolver.AddPad(); resolver.AddConcatenation(); resolver.AddMul();
  resolver.AddLogistic(); resolver.AddQuantize(); resolver.AddDequantize();
  resolver.AddReshape(); resolver.AddRelu6(); resolver.AddAveragePool2D();
  static tflite::MicroInterpreter si(tfl_model, resolver, tensor_arena, kArenaSize);
  interpreter = &si;
  if (interpreter->AllocateTensors() != kTfLiteOk) return false;
  input = interpreter->input(0); output = interpreter->output(0);
  return true;
}

void frameToGray(const uint8_t* src, int srcW, int srcH) {
  for (int y = 0; y < IN_H; y++) {
    int sy = y * srcH / IN_H;
    for (int x = 0; x < IN_W; x++) {
      int sx = x * srcW / IN_W;
      const uint8_t* p = src + (size_t)(sy * srcW + sx) * 3;
      gray_input[y * IN_W + x] = (uint8_t)((77u * p[2] + 150u * p[1] + 29u * p[0]) >> 8);
    }
  }
}

// Returns peak score; fills nBlobs.
float runInference(int& nBlobs) {
  const float in_s = input->params.scale; const int32_t in_z = input->params.zero_point;
  int8_t* in = input->data.int8;
  for (int i = 0; i < IN_W * IN_H; i++) {
    int32_t q = (int32_t) lroundf((gray_input[i] / 255.0f) / in_s) + in_z;
    in[i] = (int8_t) (q < -128 ? -128 : (q > 127 ? 127 : q));
  }
  uint32_t t0 = millis();
  if (interpreter->Invoke() != kTfLiteOk) { nBlobs = -1; return -1; }
  last_infer_ms = millis() - t0;

  const float out_s = output->params.scale; const int32_t out_z = output->params.zero_point;
  const int8_t* out = output->data.int8;

  float peak = 0; bool on[GRID][GRID];
  for (int r = 0; r < GRID; r++) for (int c = 0; c < GRID; c++) {
    float s = (out[r * GRID + c] - out_z) * out_s;
    if (s > peak) peak = s;
    on[r][c] = s >= DETECT_THRESHOLD;
  }
  // blob count (4-connectivity)
  bool seen[GRID][GRID] = {};
  int nb = 0, sR[GRID*GRID], sC[GRID*GRID];
  const int dr[4] = {-1,1,0,0}, dc[4] = {0,0,-1,1};
  for (int r = 0; r < GRID; r++) for (int c = 0; c < GRID; c++) {
    if (!on[r][c] || seen[r][c]) continue;
    nb++;
    int sp = 0; sR[sp] = r; sC[sp] = c; sp++; seen[r][c] = true;
    while (sp > 0) {
      sp--; int rr = sR[sp], cc = sC[sp];
      for (int k = 0; k < 4; k++) {
        int nr = rr + dr[k], nc = cc + dc[k];
        if (nr>=0 && nr<GRID && nc>=0 && nc<GRID && on[nr][nc] && !seen[nr][nc]) {
          seen[nr][nc] = true; sR[sp] = nr; sC[sp] = nc; sp++;
        }
      }
    }
  }
  nBlobs = nb;
  return peak;
}

// ───────────────────── Time ─────────────────────

String nowString() {
  if (time_ok) {
    time_t now; time(&now);
    struct tm t; localtime_r(&now, &t);
    char buf[24];
    strftime(buf, sizeof(buf), "%Y-%m-%d %H:%M:%S", &t);
    return String(buf);
  }
  return "uptime+" + String(millis() / 1000) + "s";
}

// ───────────────────── Detection burst ─────────────────────

struct Shot { camera_fb_t* fb; float peak; int blobs; };

void runBurst() {
  total_bursts++;
  Shot best[MAX_SAVE_PER_ALERT];
  for (int i = 0; i < MAX_SAVE_PER_ALERT; i++) { best[i].fb = nullptr; best[i].peak = -1; }
  int positives = 0; float burstPeak = 0; int maxBlobs = 0;

  for (int shot = 0; shot < BURST_SHOTS; shot++) {
    camera_fb_t* fb = esp_camera_fb_get();
    if (!fb) continue;

    uint8_t* rgb = (uint8_t*) ps_malloc((size_t)fb->width * fb->height * 3);
    float peak = -1; int blobs = 0;
    if (rgb) {
      if (fmt2rgb888(fb->buf, fb->len, fb->format, rgb)) {
        frameToGray(rgb, fb->width, fb->height);
        peak = runInference(blobs);
      }
      free(rgb);
    }

    bool detected = blobs > 0;
    if (detected) {
      positives++;
      if (peak > burstPeak) burstPeak = peak;
      if (blobs > maxBlobs) maxBlobs = blobs;
      int slot = -1;
      for (int i = 0; i < MAX_SAVE_PER_ALERT; i++)
        if (best[i].fb == nullptr || peak > best[i].peak) { slot = i; break; }
      if (slot >= 0) {
        int weakest = 0;
        for (int i = 1; i < MAX_SAVE_PER_ALERT; i++)
          if (best[i].peak < best[weakest].peak) weakest = i;
        if (best[weakest].fb == nullptr || peak > best[weakest].peak) {
          if (best[weakest].fb) esp_camera_fb_return(best[weakest].fb);
          best[weakest].fb = fb; best[weakest].peak = peak; best[weakest].blobs = blobs;
          fb = nullptr;   // ownership moved
        }
      }
    }
    if (fb) esp_camera_fb_return(fb);
    delay(BURST_GAP_MS);
  }

  if (positives == 0) {
    last_burst_summary = nowString() + " - clear (0/" + String(BURST_SHOTS) + ")";
    for (int i = 0; i < MAX_SAVE_PER_ALERT; i++)
      if (best[i].fb) esp_camera_fb_return(best[i].fb);
    return;
  }

  // ── Detection: new alert id, save shots, log record ──
  alert_counter++;
  prefs.putUInt("alertctr", alert_counter);
  total_alerts_session++;

  String shotNames = "";
  int saved = 0;
  if (sd_ok) {
    for (int i = 0; i < MAX_SAVE_PER_ALERT; i++) {
      if (!best[i].fb) continue;
      String fname = "/R" + String(alert_counter) + "_" + String(i) + ".jpg";
      File f = SD_MMC.open(fname, FILE_WRITE);
      if (f) {
        f.write(best[i].fb->buf, best[i].fb->len);
        f.close();
        if (saved) shotNames += ",";
        shotNames += "\"" + fname.substring(1) + "\"";
        saved++;
      }
      esp_camera_fb_return(best[i].fb);
      best[i].fb = nullptr;
    }
    File log = SD_MMC.open("/alerts.log", FILE_APPEND);
    if (log) {
      log.printf("{\"id\":%u,\"time\":\"%s\",\"positives\":%d,\"shots\":%d,"
                 "\"peak\":%.3f,\"rats\":%d,\"files\":[%s]}\n",
                 alert_counter, nowString().c_str(), positives, BURST_SHOTS,
                 burstPeak, maxBlobs, shotNames.c_str());
      log.close();
    }
  } else {
    for (int i = 0; i < MAX_SAVE_PER_ALERT; i++)
      if (best[i].fb) esp_camera_fb_return(best[i].fb);
  }

  // Send the alert over ESP-NOW -> LoRa (resent until acknowledged)
  linkQueueAlert(alert_counter, positives, BURST_SHOTS, burstPeak, maxBlobs);

  last_burst_summary = nowString() + " - ALERT #" + String(alert_counter) +
                       " (" + String(positives) + "/" + String(BURST_SHOTS) +
                       " positive, peak " + String(burstPeak, 3) + ", saved " +
                       String(saved) + " img)";
  Serial.println("[BURST] " + last_burst_summary);
}

// ───────────────────── REST API ─────────────────────

void sendJson(const String& body) {
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.send(200, "application/json", body);
}

void handleStatus() {
  uint64_t sdTotal = sd_ok ? SD_MMC.totalBytes() : 0;
  uint64_t sdUsed  = sd_ok ? SD_MMC.usedBytes()  : 0;
  String j = "{";
  j += "\"device\":\"" + String(DEVICE_NAME) + "\",";
  j += "\"time\":\"" + nowString() + "\",";
  j += "\"uptime_s\":" + String(millis() / 1000) + ",";
  j += "\"alert_counter\":" + String(alert_counter) + ",";
  j += "\"alerts_session\":" + String(total_alerts_session) + ",";
  j += "\"bursts\":" + String(total_bursts) + ",";
  j += "\"last_burst\":\"" + last_burst_summary + "\",";
  j += "\"capture_interval_s\":" + String(CAPTURE_INTERVAL_MS / 1000) + ",";
  j += "\"burst_shots\":" + String(BURST_SHOTS) + ",";
  j += "\"threshold\":" + String(DETECT_THRESHOLD, 2) + ",";
  j += "\"model_kb\":" + String(fomo_rat_int8_tflite_len / 1024.0f, 1) + ",";
  j += "\"infer_ms\":" + String(last_infer_ms) + ",";
  j += "\"sd_ok\":" + String(sd_ok ? "true" : "false") + ",";
  j += "\"sd_total_mb\":" + String(sdTotal / 1048576.0f, 1) + ",";
  j += "\"sd_used_mb\":" + String(sdUsed / 1048576.0f, 1) + ",";
  j += "\"free_heap_kb\":" + String(ESP.getFreeHeap() / 1024) + ",";
  j += "\"free_psram_kb\":" + String(ESP.getFreePsram() / 1024) + ",";
  j += "\"rssi\":" + String(WiFi.RSSI());
  j += "}";
  sendJson(j);
}

void handleAlerts() {
  if (!sd_ok) { sendJson("[]"); return; }
  File log = SD_MMC.open("/alerts.log", FILE_READ);
  if (!log) { sendJson("[]"); return; }
  String out = "[";
  bool first = true;
  while (log.available()) {
    String line = log.readStringUntil('\n');
    line.trim();
    if (!line.length()) continue;
    if (!first) out += ",";
    out += line;
    first = false;
  }
  log.close();
  out += "]";
  sendJson(out);
}

void handleImages() {
  if (!sd_ok) { sendJson("[]"); return; }
  File root = SD_MMC.open("/");
  String out = "["; bool first = true;
  File f = root.openNextFile();
  while (f) {
    String n = String(f.name());
    if (!f.isDirectory() && n.endsWith(".jpg")) {
      if (!first) out += ",";
      out += "{\"name\":\"" + n + "\",\"size\":" + String(f.size()) + "}";
      first = false;
    }
    f = root.openNextFile();
  }
  out += "]";
  sendJson(out);
}

void handleImage() {
  if (!sd_ok || !server.hasArg("name")) { server.send(400, "text/plain", "bad request"); return; }
  String name = "/" + server.arg("name");
  if (name.indexOf("..") >= 0) { server.send(400, "text/plain", "bad name"); return; }
  File f = SD_MMC.open(name, FILE_READ);
  if (!f) { server.send(404, "text/plain", "not found"); return; }
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.streamFile(f, "image/jpeg");
  f.close();
}

// ADMIN TEST: capture one frame, run inference immediately.
void handleTest() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { server.send(500, "text/plain", "capture failed"); return; }

  if (test_jpg) { free(test_jpg); test_jpg = nullptr; }
  test_jpg = (uint8_t*) ps_malloc(fb->len);
  if (test_jpg) { memcpy(test_jpg, fb->buf, fb->len); test_jpg_len = fb->len; }

  float peak = -1; int blobs = 0;
  uint8_t* rgb = (uint8_t*) ps_malloc((size_t)fb->width * fb->height * 3);
  if (rgb) {
    if (fmt2rgb888(fb->buf, fb->len, fb->format, rgb)) {
      frameToGray(rgb, fb->width, fb->height);
      peak = runInference(blobs);
    }
    free(rgb);
  }
  esp_camera_fb_return(fb);

  bool detected = blobs > 0;
  Serial.printf("[test] peak=%.3f blobs=%d infer=%lums\n", peak, blobs,
                (unsigned long) last_infer_ms);
  sendJson("{\"ok\":true,\"peak\":" + String(peak, 3) +
           ",\"blobs\":" + String(blobs) +
           ",\"detected\":" + String(detected ? "true" : "false") +
           ",\"infer_ms\":" + String(last_infer_ms) +
           ",\"threshold\":" + String(DETECT_THRESHOLD, 2) + "}");
}

void handleTestImg() {
  if (!test_jpg || test_jpg_len == 0) { server.send(404, "text/plain", "no test shot"); return; }
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.setContentLength(test_jpg_len);
  server.send(200, "image/jpeg", "");
  server.sendContent((const char*) test_jpg, test_jpg_len);
}

// GET /api/delete?names=R16_0.jpg,R16_1.jpg
void handleDelete() {
  if (!sd_ok) { server.send(500, "text/plain", "no sd"); return; }
  if (!server.hasArg("names")) { server.send(400, "text/plain", "names required"); return; }

  String names = server.arg("names");
  int deleted = 0, failed = 0;
  int start = 0;
  while (start < (int)names.length()) {
    int comma = names.indexOf(',', start);
    if (comma < 0) comma = names.length();
    String n = names.substring(start, comma);
    n.trim();
    if (n.length() && n.indexOf("..") < 0 && n.indexOf('/') < 0) {
      if (SD_MMC.remove("/" + n)) deleted++; else failed++;
    }
    start = comma + 1;
  }
  Serial.printf("[delete] removed %d, failed %d\n", deleted, failed);
  sendJson("{\"ok\":true,\"deleted\":" + String(deleted) +
           ",\"failed\":" + String(failed) + "}");
}

void handleLive() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { server.send(500, "text/plain", "capture failed"); return; }
  server.sendHeader("Access-Control-Allow-Origin", "*");
  server.setContentLength(fb->len);
  server.send(200, "image/jpeg", "");
  server.sendContent((const char*) fb->buf, fb->len);
  esp_camera_fb_return(fb);
}

void handleBurstNow() {
  runBurst();
  sendJson("{\"ok\":true,\"result\":\"" + last_burst_summary + "\"}");
}

void handleRootPage() {
  String h = "<html><body style='font-family:sans-serif;background:#111;color:#eee;padding:20px'>";
  h += "<h2>&#128000; " + String(DEVICE_NAME) + "</h2>";
  h += "<p>" + last_burst_summary + "</p>";
  h += "<p>Alerts total: " + String(alert_counter) + " | SD: " + String(sd_ok ? "OK" : "MISSING") + "</p>";
  h += "<p><a style='color:#6cf' href='/api/status'>status</a> | "
       "<a style='color:#6cf' href='/api/alerts'>alerts</a> | "
       "<a style='color:#6cf' href='/api/images'>images</a> | "
       "<a style='color:#6cf' href='/api/live'>live</a> | "
       "<a style='color:#6cf' href='/api/burst'>burst now</a></p>";
  h += "</body></html>";
  server.send(200, "text/html", h);
}

// ───────────────────── Setup / loop ─────────────────────

void setup() {
  Serial.begin(115200); Serial.println();

  if (!initCamera()) { Serial.println("Camera init failed - halting."); while (1) delay(1000); }

  gray_input = (uint8_t*) heap_caps_malloc(IN_W * IN_H, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!gray_input || !modelBegin()) { Serial.println("Model init failed - halting."); while (1) delay(1000); }
  Serial.printf("Model ready. arena used=%u B\n", (unsigned) interpreter->arena_used_bytes());

  // SD card - 1-bit mode is the reliable choice on AI-Thinker
  sd_ok = SD_MMC.begin("/sdcard", true);
  Serial.println(sd_ok ? "SD card OK" : "SD card NOT found - images will not be saved");

  prefs.begin("rodent", false);
  alert_counter = prefs.getUInt("alertctr", 0);

#if USE_HOTSPOT
  WiFi.mode(WIFI_AP_STA);
  WiFi.softAP(AP_SSID, AP_PASSWORD, LINK_CHANNEL);
  Serial.print("Hotspot '"); Serial.print(AP_SSID);
  Serial.print("' up. App URL: http://"); Serial.println(WiFi.softAPIP());
  time_ok = false;   // no internet -> uptime timestamps
#else
  WiFi.mode(WIFI_STA);
  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println();
  Serial.print("Connected. http://"); Serial.println(WiFi.localIP());
  Serial.print("ESP-NOW channel = "); Serial.println(WiFi.channel());  // put this in Heltec B
  configTime(3600, 0, "pool.ntp.org", "time.nist.gov");
  struct tm t;
  time_ok = getLocalTime(&t, 5000);
  Serial.println(time_ok ? "NTP time OK: " + nowString() : "NTP failed - using uptime timestamps");
#endif
  linkBegin();

  server.on("/",            handleRootPage);
  server.on("/api/status",  handleStatus);
  server.on("/api/alerts",  handleAlerts);
  server.on("/api/images",  handleImages);
  server.on("/api/image",   handleImage);
  server.on("/api/live",    handleLive);
  server.on("/api/delete",  handleDelete);
  server.on("/api/test",    handleTest);
  server.on("/api/testimg", handleTestImg);
  server.on("/api/burst",   handleBurstNow);
  server.begin();
  Serial.println("API server started.");
  Serial.printf("PSRAM: %u bytes\n", (unsigned) ESP.getPsramSize());

  linkSendHeartbeat();   // announce ourselves to the fleet immediately
}

void loop() {
  server.handleClient();
  linkTick();            // resend unacknowledged alerts

  // Heartbeat: first after 30 s, then every 5 min
  static uint32_t last_hb = 0;
  uint32_t hb_interval = (last_hb == 0) ? 30000 : 300000;
  if (millis() - last_hb > hb_interval) { last_hb = millis(); linkSendHeartbeat(); }

  static uint32_t last_capture = 0;
  // First burst 15 s after boot, then every CAPTURE_INTERVAL_MS
  if ((last_capture == 0 && millis() > 15000) ||
      (last_capture != 0 && millis() - last_capture >= CAPTURE_INTERVAL_MS)) {
    last_capture = millis();
    runBurst();
  }
}
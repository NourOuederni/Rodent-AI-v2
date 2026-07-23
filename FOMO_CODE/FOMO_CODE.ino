/*
  RodentDetectorV2_WebServer.ino  — FOMO edition
  ESP32-CAM (AI-Thinker) + FOMO rat DETECTOR (MobileNetV2 alpha=0.35, int8)

  This model is a DETECTOR, not a classifier:
    Input : 96 x 96 x 1  GRAYSCALE  (int8)
    Output: 12 x 12 x 1  heatmap    (int8, per-cell rat probability)
  Detection = threshold the heatmap, group touching hot cells into blobs,
  each blob's centroid = one rat. Dashboard overlays the heatmap on the frame
  and shows a live rat count.

  REQUIRED LIBRARY (Library Manager):
    - Chirale_TensorFlowLite   (provides TensorFlowLite.h + the micro runtime)

  MODEL DATA — generate fomo_model_data.h and drop it in THIS sketch folder:
    xxd -i fomo_rat_int8.tflite > fomo_model_data.h
    (no xxd on Windows? use this Python one-liner:)
    python -c "d=open('fomo_rat_int8.tflite','rb').read(); open('fomo_model_data.h','w').write('alignas(8) const unsigned char fomo_rat_int8_tflite[]={%s};\nconst unsigned int fomo_rat_int8_tflite_len=%d;\n'%(','.join(map(str,d)),len(d)))"
    The array MUST be named fomo_rat_int8_tflite. Keep alignas(8) — the
    flatbuffer must be aligned for tflite-micro.

  BOARD SETTINGS:
    - Board: "AI Thinker ESP32-CAM"
    - PSRAM: "Enabled"          <-- required (arena + buffers live in PSRAM)
    - Partition Scheme: "Huge APP (3MB No OTA/1MB SPIFFS)"
*/

#include <WiFi.h>
#include <WebServer.h>
#include <math.h>
#include <mbedtls/base64.h>
#include "esp_camera.h"
#include "img_converters.h"

#include <Chirale_TensorFlowLite.h>
#include "tensorflow/lite/micro/micro_interpreter.h"
#include "tensorflow/lite/micro/micro_mutable_op_resolver.h"
#include "tensorflow/lite/schema/schema_generated.h"

#include "fomo_model_data.h"   // fomo_rat_int8_tflite[], fomo_rat_int8_tflite_len

// ---- EDIT THESE ----
const char *WIFI_SSID     = "MAXBOX5G_AF58";
const char *WIFI_PASSWORD = "vmg6mub4kw7k";     // do NOT commit real credentials
const float DETECT_THRESHOLD = 0.5f;            // per-cell cutoff (notebook thr; raise to 0.6 for fewer false alarms)
// ---------------------

// FOMO geometry
static const int IN_W = 96, IN_H = 96;   // model input
static const int GRID = 12;              // 96 / stride(8)
static const int MAX_DETS = 24;

// TFLite Micro runtime
static const int  kArenaSize = 300 * 1024;      // in PSRAM; bump if AllocateTensors fails
static uint8_t*   tensor_arena = nullptr;
static const tflite::Model*      tfl_model   = nullptr;
static tflite::MicroInterpreter* interpreter = nullptr;
static TfLiteTensor* input  = nullptr;
static TfLiteTensor* output = nullptr;
static tflite::MicroMutableOpResolver<12> resolver;

// Buffers / stats
static uint8_t* gray_input = nullptr;    // 96x96 grayscale (model input + /debug)
static uint32_t total_frames = 0;
static uint32_t total_detections = 0;
static uint32_t last_infer_ms = 0;

// AI-Thinker ESP32-CAM pin map
#define PWDN_GPIO_NUM     32
#define RESET_GPIO_NUM    -1
#define XCLK_GPIO_NUM      0
#define SIOD_GPIO_NUM     26
#define SIOC_GPIO_NUM     27
#define Y9_GPIO_NUM       35
#define Y8_GPIO_NUM       34
#define Y7_GPIO_NUM       39
#define Y6_GPIO_NUM       36
#define Y5_GPIO_NUM       21
#define Y4_GPIO_NUM       19
#define Y3_GPIO_NUM       18
#define Y2_GPIO_NUM        5
#define VSYNC_GPIO_NUM    25
#define HREF_GPIO_NUM     23
#define PCLK_GPIO_NUM     22

WebServer server(80);

struct Det { float cx, cy; float score; int cells; };  // cx,cy normalized [0,1]

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;   config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM; config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM; config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;   config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size   = FRAMESIZE_QVGA;   // 320x240
    config.jpeg_quality = 12;
    config.fb_count     = 2;
    config.fb_location  = CAMERA_FB_IN_PSRAM;
  } else {
    Serial.println("WARNING: PSRAM not found — enable it in Tools > PSRAM.");
    config.frame_size   = FRAMESIZE_QQVGA;
    config.jpeg_quality = 15;
    config.fb_count     = 1;
    config.fb_location  = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) { Serial.printf("Camera init failed 0x%x\n", err); return false; }
  return true;
}

bool modelBegin() {
  tensor_arena = (uint8_t*) heap_caps_malloc(kArenaSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!tensor_arena) { Serial.println("arena alloc failed"); return false; }

  tfl_model = tflite::GetModel(fomo_rat_int8_tflite);
  if (tfl_model->version() != TFLITE_SCHEMA_VERSION) {
    Serial.println("model schema version mismatch"); return false;
  }

  // Ops used by MobileNetV2(0.35)+FOMO int8. Missing one => AllocateTensors fails.
  resolver.AddConv2D();
  resolver.AddDepthwiseConv2D();
  resolver.AddAdd();
  resolver.AddPad();
  resolver.AddConcatenation();
  resolver.AddMul();
  resolver.AddLogistic();
  resolver.AddQuantize();
  resolver.AddDequantize();
  resolver.AddReshape();
  resolver.AddRelu6();
  resolver.AddAveragePool2D();

  static tflite::MicroInterpreter static_interp(tfl_model, resolver, tensor_arena, kArenaSize);
  interpreter = &static_interp;
  if (interpreter->AllocateTensors() != kTfLiteOk) {
    Serial.println("AllocateTensors failed — increase kArenaSize"); return false;
  }
  input  = interpreter->input(0);
  output = interpreter->output(0);
  return true;
}

// RGB888 (fmt2rgb888 gives B,G,R) -> 96x96 grayscale (ITU-R 601 luma), nearest neighbor.
void frameToGray(const uint8_t* src, int srcW, int srcH) {
  for (int y = 0; y < IN_H; y++) {
    int sy = y * srcH / IN_H;
    for (int x = 0; x < IN_W; x++) {
      int sx = x * srcW / IN_W;
      const uint8_t* p = src + (size_t)(sy * srcW + sx) * 3;   // p[0]=B p[1]=G p[2]=R
      uint32_t l = (77u * p[2] + 150u * p[1] + 29u * p[0]) >> 8;
      gray_input[y * IN_W + x] = (uint8_t) l;
    }
  }
}

// Fill int8 input from grayscale, invoke, read 12x12 scores. true on success.
bool runInference(float scores[GRID][GRID]) {
  const float   in_scale = input->params.scale;
  const int32_t in_zp    = input->params.zero_point;
  int8_t* in = input->data.int8;
  for (int i = 0; i < IN_W * IN_H; i++) {
    float v = gray_input[i] / 255.0f;               // [0,1], matches training (arr/255)
    int32_t q = (int32_t) lroundf(v / in_scale) + in_zp;
    if (q < -128) q = -128; else if (q > 127) q = 127;
    in[i] = (int8_t) q;
  }

  uint32_t t0 = millis();
  if (interpreter->Invoke() != kTfLiteOk) return false;
  last_infer_ms = millis() - t0;

  const float   out_scale = output->params.scale;
  const int32_t out_zp    = output->params.zero_point;
  const int8_t* out = output->data.int8;
  for (int r = 0; r < GRID; r++)
    for (int c = 0; c < GRID; c++)
      scores[r][c] = (out[r * GRID + c] - out_zp) * out_scale;
  return true;
}

// Group touching hot cells (4-connectivity) into blobs; centroid of each = one rat.
int detectBlobs(float scores[GRID][GRID], float thr, Det* dets, int maxDets) {
  bool on[GRID][GRID], seen[GRID][GRID];
  for (int r = 0; r < GRID; r++)
    for (int c = 0; c < GRID; c++) { on[r][c] = scores[r][c] >= thr; seen[r][c] = false; }

  int nd = 0, stackR[GRID * GRID], stackC[GRID * GRID];
  const int dr[4] = {-1, 1, 0, 0}, dc[4] = {0, 0, -1, 1};
  for (int r = 0; r < GRID; r++) {
    for (int c = 0; c < GRID; c++) {
      if (!on[r][c] || seen[r][c]) continue;
      int sp = 0; stackR[sp] = r; stackC[sp] = c; sp++; seen[r][c] = true;
      long sumR = 0, sumC = 0; int cnt = 0; float best = 0;
      while (sp > 0) {
        sp--; int rr = stackR[sp], cc = stackC[sp];
        sumR += rr; sumC += cc; cnt++;
        if (scores[rr][cc] > best) best = scores[rr][cc];
        for (int k = 0; k < 4; k++) {
          int nr = rr + dr[k], nc = cc + dc[k];
          if (nr >= 0 && nr < GRID && nc >= 0 && nc < GRID && on[nr][nc] && !seen[nr][nc]) {
            seen[nr][nc] = true; stackR[sp] = nr; stackC[sp] = nc; sp++;
          }
        }
      }
      if (nd < maxDets) {
        dets[nd].cy    = ((float)sumR / cnt + 0.5f) / GRID;
        dets[nd].cx    = ((float)sumC / cnt + 0.5f) / GRID;
        dets[nd].score = best;
        dets[nd].cells = cnt;
        nd++;
      }
    }
  }
  return nd;
}

String base64Encode(const uint8_t* data, size_t len) {
  size_t outLen = 0;
  mbedtls_base64_encode(NULL, 0, &outLen, data, len);
  uint8_t* outBuf = (uint8_t*) ps_malloc(outLen);
  if (!outBuf) return String("");
  size_t written = 0;
  mbedtls_base64_encode(outBuf, outLen, &written, data, len);
  String result; result.reserve(written);
  for (size_t i = 0; i < written; i++) result += (char) outBuf[i];
  free(outBuf);
  return result;
}

String formatUptime() {
  uint32_t s = millis() / 1000, h = s / 3600; s %= 3600;
  uint32_t m = s / 60; s %= 60;
  char buf[24];
  snprintf(buf, sizeof(buf), "%luh %lum %lus", (unsigned long)h, (unsigned long)m, (unsigned long)s);
  return String(buf);
}

void handleRoot() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) { server.send(500, "text/plain", "Camera capture failed"); return; }

  int frameW = fb->width, frameH = fb->height;
  float scores[GRID][GRID];
  for (int r = 0; r < GRID; r++) for (int c = 0; c < GRID; c++) scores[r][c] = -1.0f;
  Det dets[MAX_DETS]; int ndet = 0; bool ok = false;

  uint8_t* rgb = (uint8_t*) ps_malloc((size_t)frameW * frameH * 3);
  if (rgb) {
    if (fmt2rgb888(fb->buf, fb->len, fb->format, rgb)) {
      frameToGray(rgb, frameW, frameH);
      if (runInference(scores)) { ndet = detectBlobs(scores, DETECT_THRESHOLD, dets, MAX_DETS); ok = true; }
    }
    free(rgb);
  }

  String imageBase64 = base64Encode(fb->buf, fb->len);
  size_t jpegLen = fb->len;
  esp_camera_fb_return(fb);

  total_frames++;
  bool detected = ok && ndet > 0;
  if (detected) total_detections++;

  float peak = 0;
  for (int r = 0; r < GRID; r++) for (int c = 0; c < GRID; c++) if (scores[r][c] > peak) peak = scores[r][c];

  String verdict, badgeClass;
  if (!ok)           { verdict = "INFERENCE FAILED"; badgeClass = "fail"; }
  else if (detected) { verdict = "RAT DETECTED  x" + String(ndet); badgeClass = "alert"; }
  else               { verdict = "ALL CLEAR"; badgeClass = "clear"; }

  String html; html.reserve(14000 + imageBase64.length());
  html += F("<!DOCTYPE html><html><head><meta charset='utf-8'>"
            "<meta name='viewport' content='width=device-width,initial-scale=1'>"
            "<meta http-equiv='refresh' content='3'>"
            "<title>Rodent Detector</title><style>"
            ":root{--bg:#0d1117;--card:#161b22;--border:#30363d;--text:#e6edf3;--muted:#8b949e;"
            "--red:#f85149;--green:#3fb950;--amber:#d29922;--accent:#58a6ff;}"
            "*{box-sizing:border-box;margin:0;padding:0;}"
            "body{font-family:-apple-system,'Segoe UI',Roboto,sans-serif;background:var(--bg);"
            "color:var(--text);padding:16px;max-width:560px;margin:0 auto;}"
            "h1{font-size:20px;font-weight:600;margin-bottom:2px;}"
            ".sub{color:var(--muted);font-size:12px;margin-bottom:14px;}"
            ".card{background:var(--card);border:1px solid var(--border);border-radius:12px;"
            "padding:14px;margin-bottom:12px;}"
            ".cam{position:relative;line-height:0;}"
            ".cam img{width:100%;border-radius:8px;display:block;}"
            ".grid{position:absolute;inset:0;display:grid;"
            "grid-template-columns:repeat(12,1fr);grid-template-rows:repeat(12,1fr);border-radius:8px;overflow:hidden;}"
            ".grid div{outline:.5px solid rgba(255,255,255,.04);}"
            ".dot{position:absolute;width:12px;height:12px;margin:-6px 0 0 -6px;border-radius:50%;"
            "background:var(--accent);border:2px solid #fff;box-shadow:0 0 6px var(--accent);}"
            ".badge{display:block;text-align:center;font-size:24px;font-weight:700;"
            "letter-spacing:1px;padding:12px;border-radius:10px;margin-top:12px;}"
            ".alert{background:rgba(248,81,73,.15);color:var(--red);border:1px solid var(--red);}"
            ".clear{background:rgba(63,185,80,.12);color:var(--green);border:1px solid var(--green);}"
            ".fail{background:rgba(139,148,158,.12);color:var(--muted);border:1px solid var(--border);}"
            "table{width:100%;border-collapse:collapse;font-size:13px;}"
            "td{padding:5px 0;border-bottom:1px solid var(--border);}"
            "td:first-child{color:var(--muted);}"
            "td:last-child{text-align:right;font-variant-numeric:tabular-nums;}"
            "tr:last-child td{border-bottom:none;}"
            ".sect{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);margin-bottom:8px;}"
            "</style></head><body>");

  html += F("<h1>&#128000; Rodent Detector</h1>"
            "<div class='sub'>FOMO MobileNetV2 &alpha;=0.35 &middot; 96&times;96 gray &middot; 12&times;12 grid "
            "&middot; int8 &middot; auto-refresh 3s</div>");

  // Camera + heatmap overlay + centroid dots
  html += F("<div class='card'><div class='cam'>");
  html += "<img src='data:image/jpeg;base64," + imageBase64 + "'/>";
  html += F("<div class='grid'>");
  for (int r = 0; r < GRID; r++) {
    for (int c = 0; c < GRID; c++) {
      float s = scores[r][c]; if (s < 0) s = 0;
      html += "<div style='background:rgba(248,81,73," + String(s * 0.85f, 2) + ")'></div>";
    }
  }
  html += F("</div>");  // .grid
  for (int i = 0; i < ndet; i++)
    html += "<div class='dot' style='left:" + String(dets[i].cx * 100.0f, 1) +
            "%;top:" + String(dets[i].cy * 100.0f, 1) + "%'></div>";
  html += "<div class='badge " + badgeClass + "'>" + verdict + "</div>";
  html += F("</div></div>");  // .cam .card

  // Inference card
  html += F("<div class='card'><div class='sect'>Inference</div><table>");
  html += "<tr><td>Latency</td><td>" + String(last_infer_ms) + " ms</td></tr>";
  html += "<tr><td>Rats this frame</td><td>" + String(ndet) + "</td></tr>";
  html += "<tr><td>Peak cell score</td><td>" + String(peak, 3) + "</td></tr>";
  html += "<tr><td>Frames analysed</td><td>" + String(total_frames) + "</td></tr>";
  html += "<tr><td>Frames with rats</td><td>" + String(total_detections) + "</td></tr>";
  html += F("</table></div>");

  // Model card
  html += F("<div class='card'><div class='sect'>Model</div><table>");
  html += "<tr><td>Model size</td><td>" + String(fomo_rat_int8_tflite_len / 1024.0f, 1) + " KB</td></tr>";
  html += "<tr><td>Input</td><td>96&times;96&times;1 int8</td></tr>";
  html += "<tr><td>Output</td><td>12&times;12&times;1 int8</td></tr>";
  html += "<tr><td>Input scale / zp</td><td>" + String(input->params.scale, 6) + " / " + String(input->params.zero_point) + "</td></tr>";
  html += "<tr><td>Output scale / zp</td><td>" + String(output->params.scale, 6) + " / " + String(output->params.zero_point) + "</td></tr>";
  html += "<tr><td>Arena used</td><td>" + String(interpreter->arena_used_bytes() / 1024.0f, 0) + " / " + String(kArenaSize / 1024.0f, 0) + " KB</td></tr>";
  html += "<tr><td>Threshold</td><td>" + String(DETECT_THRESHOLD, 2) + "</td></tr>";
  html += F("</table></div>");

  // System card
  html += F("<div class='card'><div class='sect'>System</div><table>");
  html += "<tr><td>Frame</td><td>" + String(frameW) + "&times;" + String(frameH) + " (" + String(jpegLen / 1024.0f, 1) + " KB JPEG)</td></tr>";
  html += "<tr><td>Free heap</td><td>" + String(ESP.getFreeHeap() / 1024.0f, 0) + " KB</td></tr>";
  html += "<tr><td>Free PSRAM</td><td>" + String(ESP.getFreePsram() / 1024.0f, 0) + " KB</td></tr>";
  html += "<tr><td>WiFi RSSI</td><td>" + String(WiFi.RSSI()) + " dBm</td></tr>";
  html += "<tr><td>IP</td><td>" + WiFi.localIP().toString() + "</td></tr>";
  html += "<tr><td>Uptime</td><td>" + formatUptime() + "</td></tr>";
  html += F("</table></div>");

  html += F("</body></html>");
  server.send(200, "text/html", html);
}

// Serves the exact 96x96 grayscale model input as a BMP — open http://<ip>/debug
void handleDebug() {
  const int W = IN_W, H = IN_H;
  const uint32_t rowSize = W * 3;          // 288, 4-byte aligned
  const uint32_t fileSize = 54 + rowSize * H;
  uint8_t hdr[54] = {0};
  hdr[0] = 'B'; hdr[1] = 'M';
  hdr[2] = fileSize; hdr[3] = fileSize >> 8; hdr[4] = fileSize >> 16; hdr[5] = fileSize >> 24;
  hdr[10] = 54; hdr[14] = 40;
  hdr[18] = W; hdr[19] = W >> 8; hdr[22] = H; hdr[23] = H >> 8;
  hdr[26] = 1; hdr[28] = 24;

  WiFiClient client = server.client();
  client.print("HTTP/1.1 200 OK\r\nContent-Type: image/bmp\r\nContent-Length: ");
  client.print(fileSize);
  client.print("\r\nConnection: close\r\n\r\n");
  client.write(hdr, 54);
  uint8_t row[IN_W * 3];
  for (int y = H - 1; y >= 0; y--) {                 // BMP is bottom-up
    for (int x = 0; x < W; x++) {
      uint8_t g = gray_input[y * W + x];
      row[x * 3 + 0] = g; row[x * 3 + 1] = g; row[x * 3 + 2] = g;
    }
    client.write(row, rowSize);
  }
}

void handleSelfTest() {
  for (int y = 0; y < IN_H; y++)
    for (int x = 0; x < IN_W; x++)
      gray_input[y * IN_W + x] = (uint8_t)((x + y) & 0xFF);
  float scores[GRID][GRID];
  bool ok = runInference(scores);
  float peak = 0; int hot = 0;
  for (int r = 0; r < GRID; r++) for (int c = 0; c < GRID; c++) {
    if (scores[r][c] > peak) peak = scores[r][c];
    if (scores[r][c] >= DETECT_THRESHOLD) hot++;
  }
  Det d[MAX_DETS]; int n = ok ? detectBlobs(scores, DETECT_THRESHOLD, d, MAX_DETS) : 0;
  server.send(200, "text/plain",
              "selftest ok=" + String(ok) + " peak=" + String(peak, 4) +
              " hotCells=" + String(hot) + " blobs=" + String(n) +
              " infer=" + String(last_infer_ms) + "ms");
}

void setup() {
  Serial.begin(115200); Serial.println();

  if (!initCamera()) { Serial.println("Camera init failed — halting."); while (1) delay(1000); }

  gray_input = (uint8_t*) heap_caps_malloc(IN_W * IN_H, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!gray_input) { Serial.println("gray buffer alloc failed — halting."); while (1) delay(1000); }

  if (!modelBegin()) { Serial.println("Model init failed — halting."); while (1) delay(1000); }
  Serial.printf("Model ready. size=%u B, arena used=%u B\n",
                fomo_rat_int8_tflite_len, (unsigned) interpreter->arena_used_bytes());

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) { delay(500); Serial.print("."); }
  Serial.println();
  Serial.print("Connected. Open http://");
  Serial.println(WiFi.localIP());

  server.on("/", handleRoot);
  server.on("/debug", handleDebug);
  server.on("/selftest", handleSelfTest);
  server.begin();
  Serial.println("Web server started.");
}

void loop() {
  server.handleClient();
}
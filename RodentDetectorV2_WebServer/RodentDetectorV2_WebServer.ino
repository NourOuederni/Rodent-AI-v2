/*
  RodentDetectorV2_WebServer.ino
  ESP32-CAM (AI-Thinker) + RodentDetectorV2 library (MobileNetV2 alpha=0.35, int8)

  Captures a frame, runs it through the MobileNetV2 rodent classifier, and
  serves a live dashboard: camera image, verdict, confidence bar, inference
  latency, model / memory / WiFi diagnostics, and a running detection counter.

  REQUIRED LIBRARIES (install via Library Manager before compiling):
    - Chirale_TensorFlowLite   (provides TensorFlowLite.h)
    - RodentDetectorV2         (your generated library — install as .zip via
                                Sketch > Include Library > Add .ZIP Library.
                                IMPORTANT: replace src/RodentDetectorV2.h and
                                src/RodentDetectorV2.cpp inside the zip with the
                                updated versions that apply ImageNet
                                normalisation — the auto-generated ones feed
                                raw uint8 to the model, which is wrong for
                                this MobileNetV2 export.)

  BOARD SETTINGS (Tools menu):
    - Board: "AI Thinker ESP32-CAM"
    - PSRAM: "Enabled"                    <-- required (tensor arena lives there)
    - Partition Scheme: "Huge APP (3MB No OTA/1MB SPIFFS)"

  WIRING NOTE:
    ESP32-CAM boards need an FTDI/USB-serial adapter to upload. Hold IO0 to
    GND while resetting to enter upload mode.
*/

#include <WiFi.h>
#include <WebServer.h>
#include <mbedtls/base64.h>
#include "esp_camera.h"
#include "img_converters.h"
#include <RodentDetectorV3.h>

// ---- EDIT THESE ----
const char *WIFI_SSID = "MAXBOX5G_AF58";
const char *WIFI_PASSWORD = "vmg6mub4kw7k";
const float CONFIDENCE_THRESHOLD = 0.5f;   // matches the notebook's INT8_THRESHOLD
// ---------------------

static const int MODEL_INPUT_SIZE = 224;   // MobileNetV2 input size

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
RodentDetectorV3 detector;

static uint8_t* model_input_buffer = nullptr;

// Running stats
static uint32_t total_frames     = 0;
static uint32_t total_detections = 0;
static float    last_probability = -1.0f;

bool initCamera() {
  camera_config_t config;
  config.ledc_channel = LEDC_CHANNEL_0;
  config.ledc_timer   = LEDC_TIMER_0;
  config.pin_d0 = Y2_GPIO_NUM;
  config.pin_d1 = Y3_GPIO_NUM;
  config.pin_d2 = Y4_GPIO_NUM;
  config.pin_d3 = Y5_GPIO_NUM;
  config.pin_d4 = Y6_GPIO_NUM;
  config.pin_d5 = Y7_GPIO_NUM;
  config.pin_d6 = Y8_GPIO_NUM;
  config.pin_d7 = Y9_GPIO_NUM;
  config.pin_xclk = XCLK_GPIO_NUM;
  config.pin_pclk = PCLK_GPIO_NUM;
  config.pin_vsync = VSYNC_GPIO_NUM;
  config.pin_href = HREF_GPIO_NUM;
  config.pin_sscb_sda = SIOD_GPIO_NUM;
  config.pin_sscb_scl = SIOC_GPIO_NUM;
  config.pin_pwdn = PWDN_GPIO_NUM;
  config.pin_reset = RESET_GPIO_NUM;
  config.xclk_freq_hz = 20000000;
  config.pixel_format = PIXFORMAT_JPEG;

  if (psramFound()) {
    config.frame_size = FRAMESIZE_QVGA;   // 320x240
    config.jpeg_quality = 12;
    config.fb_count = 2;
    config.fb_location = CAMERA_FB_IN_PSRAM;
  } else {
    Serial.println("WARNING: PSRAM not found — enable it in Tools > PSRAM.");
    config.frame_size = FRAMESIZE_QQVGA;
    config.jpeg_quality = 15;
    config.fb_count = 1;
    config.fb_location = CAMERA_FB_IN_DRAM;
  }

  esp_err_t err = esp_camera_init(&config);
  if (err != ESP_OK) {
    Serial.printf("Camera init failed with error 0x%x\n", err);
    return false;
  }
  return true;
}

// Nearest-neighbor resize from RGB888 (srcW x srcH) into model_input_buffer.
void resizeToModelInput(const uint8_t* src, int srcW, int srcH) {
  for (int y = 0; y < MODEL_INPUT_SIZE; y++) {
    int srcY = y * srcH / MODEL_INPUT_SIZE;
    for (int x = 0; x < MODEL_INPUT_SIZE; x++) {
      int srcX = x * srcW / MODEL_INPUT_SIZE;
      const uint8_t* s = src + (srcY * srcW + srcX) * 3;
      uint8_t* d = model_input_buffer + (y * MODEL_INPUT_SIZE + x) * 3;
      d[0] = s[2];   // swap R and B
      d[1] = s[1];
      d[2] = s[0];
    }
  }
}

String base64Encode(const uint8_t* data, size_t len) {
  size_t outLen = 0;
  mbedtls_base64_encode(NULL, 0, &outLen, data, len);
  uint8_t* outBuf = (uint8_t*)ps_malloc(outLen);
  if (!outBuf) return String("");
  size_t written = 0;
  mbedtls_base64_encode(outBuf, outLen, &written, data, len);
  String result;
  result.reserve(written);
  for (size_t i = 0; i < written; i++) result += (char)outBuf[i];
  free(outBuf);
  return result;
}

String formatUptime() {
  uint32_t s = millis() / 1000;
  uint32_t h = s / 3600; s %= 3600;
  uint32_t m = s / 60;   s %= 60;
  char buf[24];
  snprintf(buf, sizeof(buf), "%luh %lum %lus", (unsigned long)h, (unsigned long)m, (unsigned long)s);
  return String(buf);
}

void handleRoot() {
  camera_fb_t* fb = esp_camera_fb_get();
  if (!fb) {
    server.send(500, "text/plain", "Camera capture failed");
    return;
  }

  uint8_t* rgbBuf = (uint8_t*)ps_malloc(fb->width * fb->height * 3);
  float probability = -1.0f;
  int frameW = fb->width, frameH = fb->height;

  if (rgbBuf) {
    if (fmt2rgb888(fb->buf, fb->len, fb->format, rgbBuf)) {
      resizeToModelInput(rgbBuf, fb->width, fb->height);
      probability = detector.predict(model_input_buffer);
    }
    free(rgbBuf);
  }

  String imageBase64 = base64Encode(fb->buf, fb->len);
  size_t jpegLen = fb->len;
  esp_camera_fb_return(fb);

  // Update stats
  total_frames++;
  last_probability = probability;
  bool detected = (probability >= CONFIDENCE_THRESHOLD);
  if (detected) total_detections++;

  // Verdict styling
  String verdict, badgeClass;
  if (probability < 0.0f)      { verdict = "INFERENCE FAILED"; badgeClass = "fail"; }
  else if (detected)           { verdict = "RAT DETECTED";     badgeClass = "alert"; }
  else                         { verdict = "ALL CLEAR";        badgeClass = "clear"; }

  int probPct = (probability >= 0.0f) ? (int)(probability * 100.0f + 0.5f) : 0;
  int threshPct = (int)(CONFIDENCE_THRESHOLD * 100.0f + 0.5f);

  String html;
  html.reserve(6000 + imageBase64.length());
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
            "img{width:100%;border-radius:8px;display:block;}"
            ".badge{display:block;text-align:center;font-size:24px;font-weight:700;"
            "letter-spacing:1px;padding:12px;border-radius:10px;margin-top:12px;}"
            ".alert{background:rgba(248,81,73,.15);color:var(--red);border:1px solid var(--red);}"
            ".clear{background:rgba(63,185,80,.12);color:var(--green);border:1px solid var(--green);}"
            ".fail{background:rgba(139,148,158,.12);color:var(--muted);border:1px solid var(--border);}"
            ".bar-wrap{background:#21262d;border-radius:6px;height:14px;margin:10px 0 4px;"
            "position:relative;overflow:hidden;}"
            ".bar{height:100%;border-radius:6px;transition:width .3s;}"
            ".thresh{position:absolute;top:-3px;bottom:-3px;width:2px;background:var(--amber);}"
            ".bar-label{display:flex;justify-content:space-between;font-size:11px;color:var(--muted);}"
            "table{width:100%;border-collapse:collapse;font-size:13px;}"
            "td{padding:5px 0;border-bottom:1px solid var(--border);}"
            "td:first-child{color:var(--muted);}"
            "td:last-child{text-align:right;font-variant-numeric:tabular-nums;}"
            "tr:last-child td{border-bottom:none;}"
            ".sect{font-size:11px;text-transform:uppercase;letter-spacing:1px;color:var(--muted);"
            "margin-bottom:8px;}"
            "</style></head><body>");

  html += F("<h1>&#128000; Rodent Detector</h1>"
            "<div class='sub'>MobileNetV2 &alpha;=0.35 &middot; int8 TFLite Micro &middot; ESP32-CAM"
            " &middot; auto-refresh 3s</div>");

  // Camera + verdict card
  html += F("<div class='card'>");
  html += "<img src='data:image/jpeg;base64," + imageBase64 + "'/>";
  html += "<div class='badge " + badgeClass + "'>" + verdict + "</div>";

  if (probability >= 0.0f) {
    String barColor = detected ? "var(--red)" : "var(--green)";
    html += F("<div class='bar-wrap'><div class='bar' style='background:");
    html += barColor + ";width:" + String(probPct) + "%'></div>";
    html += "<div class='thresh' style='left:" + String(threshPct) + "%'></div></div>";
    html += "<div class='bar-label'><span>Confidence: " + String(probability * 100.0f, 1)
          + "%</span><span>threshold " + String(threshPct) + "%</span></div>";
  }
  html += F("</div>");

  // Inference card
  html += F("<div class='card'><div class='sect'>Inference</div><table>");
  html += "<tr><td>Latency</td><td>" + String(detector.lastInferenceMs()) + " ms</td></tr>";
  html += "<tr><td>Raw probability</td><td>" + String(probability, 4) + "</td></tr>";
  html += "<tr><td>Frames analysed</td><td>" + String(total_frames) + "</td></tr>";
  html += "<tr><td>Detections</td><td>" + String(total_detections) + "</td></tr>";
  html += F("</table></div>");

  // Model card
  html += F("<div class='card'><div class='sect'>Model</div><table>");
  html += "<tr><td>Model size</td><td>" + String(detector.modelBytes() / 1024.0f, 1) + " KB</td></tr>";
  html += "<tr><td>Input</td><td>224&times;224&times;3 int8</td></tr>";
  html += "<tr><td>Input scale / zp</td><td>" + String(detector.inputScale(), 6)
        + " / " + String(detector.inputZeroPoint()) + "</td></tr>";
  html += "<tr><td>Output scale / zp</td><td>" + String(detector.outputScale(), 6)
        + " / " + String(detector.outputZeroPoint()) + "</td></tr>";
  html += "<tr><td>Arena used</td><td>" + String(detector.arenaBytesUsed() / 1024.0f, 0)
        + " / " + String(detector.arenaBytesTotal() / 1024.0f, 0) + " KB</td></tr>";
  html += F("</table></div>");

  // System card
  html += F("<div class='card'><div class='sect'>System</div><table>");
  html += "<tr><td>Frame</td><td>" + String(frameW) + "&times;" + String(frameH)
        + " (" + String(jpegLen / 1024.0f, 1) + " KB JPEG)</td></tr>";
  html += "<tr><td>Free heap</td><td>" + String(ESP.getFreeHeap() / 1024.0f, 0) + " KB</td></tr>";
  html += "<tr><td>Free PSRAM</td><td>" + String(ESP.getFreePsram() / 1024.0f, 0) + " KB</td></tr>";
  html += "<tr><td>WiFi RSSI</td><td>" + String(WiFi.RSSI()) + " dBm</td></tr>";
  html += "<tr><td>IP</td><td>" + WiFi.localIP().toString() + "</td></tr>";
  html += "<tr><td>Uptime</td><td>" + formatUptime() + "</td></tr>";
  html += F("</table></div>");

  html += F("</body></html>");
  server.send(200, "text/html", html);
}
// Serves the exact model input as a viewable BMP — open http://<ip>/debug
void handleDebug() {
  const int W = MODEL_INPUT_SIZE, H = MODEL_INPUT_SIZE;
  const uint32_t rowSize = W * 3;              // 672, already 4-byte aligned
  const uint32_t imgSize = rowSize * H;
  const uint32_t fileSize = 54 + imgSize;

  uint8_t hdr[54] = {0};
  hdr[0]='B'; hdr[1]='M';
  hdr[2]=fileSize; hdr[3]=fileSize>>8; hdr[4]=fileSize>>16; hdr[5]=fileSize>>24;
  hdr[10]=54; hdr[14]=40;
  hdr[18]=W; hdr[19]=W>>8; hdr[22]=H; hdr[23]=H>>8;
  hdr[26]=1; hdr[28]=24;

  WiFiClient client = server.client();
  client.print("HTTP/1.1 200 OK\r\nContent-Type: image/bmp\r\nContent-Length: ");
  client.print(fileSize);
  client.print("\r\nConnection: close\r\n\r\n");
  client.write(hdr, 54);

  // BMP is bottom-up and BGR
  uint8_t row[672];
  for (int y = H - 1; y >= 0; y--) {
    for (int x = 0; x < W; x++) {
      const uint8_t* p = model_input_buffer + (y * W + x) * 3;
      row[x*3+0] = p[2];  // B
      row[x*3+1] = p[1];  // G
      row[x*3+2] = p[0];  // R
    }
    client.write(row, rowSize);
  }
}
void handleSelfTest() {
  for (int y = 0; y < MODEL_INPUT_SIZE; y++)
    for (int x = 0; x < MODEL_INPUT_SIZE; x++) {
      uint8_t v = (uint8_t)((x + y) & 0xFF);
      uint8_t* p = model_input_buffer + (y * MODEL_INPUT_SIZE + x) * 3;
      p[0] = v; p[1] = (uint8_t)(v ^ 0x55); p[2] = (uint8_t)(255 - v);
    }
  float prob = detector.predict(model_input_buffer);
  server.send(200, "text/plain",
              "Self-test probability: " + String(prob, 6));
}
void setup() {
  Serial.begin(115200);
  Serial.println();

  if (!initCamera()) {
    Serial.println("Camera init failed — halting.");
    while (1) { delay(1000); }
  }

  model_input_buffer = (uint8_t*) heap_caps_malloc(
      MODEL_INPUT_SIZE * MODEL_INPUT_SIZE * 3, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (!model_input_buffer) {
    Serial.println("Failed to allocate model input buffer in PSRAM — halting.");
    while (1) { delay(1000); }
  }

  if (!detector.begin()) {
    Serial.println("Model init failed — halting.");
    while (1) { delay(1000); }
  }
  Serial.printf("Model ready. Size: %.1f KB, arena used: %.0f KB\n",
                detector.modelBytes() / 1024.0f,
                detector.arenaBytesUsed() / 1024.0f);

  WiFi.begin(WIFI_SSID, WIFI_PASSWORD);
  Serial.print("Connecting to WiFi");
  while (WiFi.status() != WL_CONNECTED) {
    delay(500);
    Serial.print(".");
  }
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

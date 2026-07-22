/*
 * ESP32-CAM + Edge Impulse inference + Web Server
 * -----------------------------------------------
 * Combines the Edge Impulse "esp32_camera" inferencing example with a
 * lightweight web server (using the built-in WebServer.h, not the full
 * async app_httpd.cpp from CameraWebServer, since we only need 3 routes).
 *
 * Behaviour:
 *  - Every 10 seconds, the ESP32 takes 5 photos back-to-back.
 *  - Each photo is run through the Edge Impulse classifier.
 *  - The JPEG + inference result of each of the 5 photos is kept in RAM.
 *  - A web page (auto-refreshing) shows all 5 images side-by-side with
 *    their inference results underneath.
 *
 * Board settings (Arduino IDE):
 *  - Board: "AI Thinker ESP32-CAM" (or your specific ESP32-CAM board)
 *  - PSRAM: Enabled
 *  - Partition Scheme: "Huge APP (3MB No OTA/1MB SPIFFS)" or similar
 *    (Edge Impulse models + camera + web server need the extra flash)
 *
 * Library requirements:
 *  - Your Edge Impulse Arduino library (the one containing
 *    nour-project-1_inferencing.h) must be installed/added as a .zip lib
 *  - ESP32 board package (esp_camera.h, WebServer.h are included in it)
 */

#include <WiFi.h>
#include <WebServer.h>

#include <nour-project-1_inferencing.h>
#include "edge-impulse-sdk/dsp/image/image.hpp"
#include "esp_camera.h"
#include "img_converters.h"

/* ------------------------------------------------------------------------ */
/* WiFi credentials - EDIT THESE                                            */
/* ------------------------------------------------------------------------ */
const char *WIFI_SSID = "MAXBOX5G_AF58";
const char *WIFI_PASS = "vmg6mub4kw7k";

/* ------------------------------------------------------------------------ */
/* Batch/timing configuration                                               */
/* ------------------------------------------------------------------------ */
#define NUM_SHOTS_PER_BATCH   5
#define BATCH_PERIOD_MS       10000   // total time for one batch of 5 shots

/* ------------------------------------------------------------------------ */
/* Confidence threshold: only detections >= this value are reported         */
/* Raise to reduce false positives; lower to improve recall                 */
/* ------------------------------------------------------------------------ */
#define CONFIDENCE_THRESHOLD  0.70f

/* ------------------------------------------------------------------------ */
/* Camera model - AI Thinker (same as your original example)                */
/* ------------------------------------------------------------------------ */
#define CAMERA_MODEL_AI_THINKER

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

/* ------------------------------------------------------------------------ */
/* Constant defines from your EI example                                    */
/* ------------------------------------------------------------------------ */
#define EI_CAMERA_RAW_FRAME_BUFFER_COLS           320
#define EI_CAMERA_RAW_FRAME_BUFFER_ROWS           240
#define EI_CAMERA_FRAME_BYTE_SIZE                 3

/* ------------------------------------------------------------------------ */
/* Camera config                                                            */
/* ------------------------------------------------------------------------ */
static camera_config_t camera_config = {
    .pin_pwdn = PWDN_GPIO_NUM,
    .pin_reset = RESET_GPIO_NUM,
    .pin_xclk = XCLK_GPIO_NUM,
    .pin_sscb_sda = SIOD_GPIO_NUM,
    .pin_sscb_scl = SIOC_GPIO_NUM,

    .pin_d7 = Y9_GPIO_NUM,
    .pin_d6 = Y8_GPIO_NUM,
    .pin_d5 = Y7_GPIO_NUM,
    .pin_d4 = Y6_GPIO_NUM,
    .pin_d3 = Y5_GPIO_NUM,
    .pin_d2 = Y4_GPIO_NUM,
    .pin_d1 = Y3_GPIO_NUM,
    .pin_d0 = Y2_GPIO_NUM,
    .pin_vsync = VSYNC_GPIO_NUM,
    .pin_href = HREF_GPIO_NUM,
    .pin_pclk = PCLK_GPIO_NUM,

    .xclk_freq_hz = 20000000,
    .ledc_timer = LEDC_TIMER_0,
    .ledc_channel = LEDC_CHANNEL_0,

    .pixel_format = PIXFORMAT_JPEG,
    .frame_size = FRAMESIZE_QVGA,

    .jpeg_quality = 12,
    .fb_count = 1,
    .fb_location = CAMERA_FB_IN_PSRAM,
    .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
};

/* ------------------------------------------------------------------------ */
/* Shared state between capture task and web server                        */
/* ------------------------------------------------------------------------ */
struct CapturedShot {
    uint8_t *jpeg_buf;      // malloc'd JPEG bytes (copy, safe to serve)
    size_t   jpeg_len;
    String   result_text;   // human readable inference result
    String   bbox_json;     // "[]" or "[{\"label\":...,\"value\":...,\"x\":...,\"y\":...,\"width\":...,\"height\":...}]"
    unsigned long millis_taken;
    bool     valid;
};

static CapturedShot shots[NUM_SHOTS_PER_BATCH];
static SemaphoreHandle_t shotsMutex;
static unsigned long lastBatchStart = 0;

static bool is_initialised = false;
static uint8_t *snapshot_buf; // scratch RGB888 buffer used during inference

WebServer server(80);

/* ------------------------------------------------------------------------ */
/* Function declarations                                                    */
/* ------------------------------------------------------------------------ */
bool ei_camera_init(void);
bool ei_camera_capture_and_save(uint32_t img_width, uint32_t img_height,
                                 uint8_t **out_jpeg, size_t *out_jpeg_len);
static int ei_camera_get_data(size_t offset, size_t length, float *out_ptr);
void captureTask(void *pvParameters);
void handleRoot();
void handleImage();
void handleResults();

/* ------------------------------------------------------------------------ */
/* setup / loop                                                             */
/* ------------------------------------------------------------------------ */
void setup() {
    Serial.begin(115200);
    Serial.println();
    Serial.println("Edge Impulse + Camera Web Server");

    if (!ei_camera_init()) {
        Serial.println("Failed to initialize camera!");
    } else {
        Serial.println("Camera initialized");
    }

    shotsMutex = xSemaphoreCreateMutex();
    for (int i = 0; i < NUM_SHOTS_PER_BATCH; i++) {
        shots[i].jpeg_buf = nullptr;
        shots[i].jpeg_len = 0;
        shots[i].bbox_json = "[]";
        shots[i].valid = false;
    }

    WiFi.mode(WIFI_STA);
    WiFi.begin(WIFI_SSID, WIFI_PASS);
    Serial.print("Connecting to WiFi");
    while (WiFi.status() != WL_CONNECTED) {
        delay(300);
        Serial.print(".");
    }
    Serial.println();
    Serial.print("Connected. Open http://");
    Serial.println(WiFi.localIP());

    server.on("/", HTTP_GET, handleRoot);
    server.on("/image", HTTP_GET, handleImage);
    server.on("/results", HTTP_GET, handleResults);
    server.begin();

    // Background task that owns the camera + runs inference.
    xTaskCreatePinnedToCore(
        captureTask,
        "captureTask",
        8192,
        NULL,
        1,
        NULL,
        1 /* core 1 */
    );
}

void loop() {
    server.handleClient();
    delay(2);
}

/* ------------------------------------------------------------------------ */
/* Background task: every BATCH_PERIOD_MS, take 5 shots + run inference     */
/* ------------------------------------------------------------------------ */
void captureTask(void *pvParameters) {
    for (;;) {
        lastBatchStart = millis();

        for (int i = 0; i < NUM_SHOTS_PER_BATCH; i++) {
            uint8_t *jpeg_buf = nullptr;
            size_t jpeg_len = 0;

            snapshot_buf = (uint8_t *)malloc(
                EI_CAMERA_RAW_FRAME_BUFFER_COLS * EI_CAMERA_RAW_FRAME_BUFFER_ROWS *
                EI_CAMERA_FRAME_BYTE_SIZE);

            String resultText;
            String bboxJson = "[]";

            if (snapshot_buf == nullptr) {
                resultText = "ERR: out of memory for snapshot buffer";
            } else if (!ei_camera_capture_and_save(
                           (size_t)EI_CLASSIFIER_INPUT_WIDTH,
                           (size_t)EI_CLASSIFIER_INPUT_HEIGHT,
                           &jpeg_buf, &jpeg_len)) {
                resultText = "ERR: failed to capture image";
            } else {
                ei::signal_t signal;
                signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
                signal.get_data = &ei_camera_get_data;

                ei_impulse_result_t result = {0};
                EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);

                if (err != EI_IMPULSE_OK) {
                    resultText = "ERR: classifier failed (" + String((int)err) + ")";
                } else {
                    resultText += "DSP: " + String(result.timing.dsp) + "ms  ";
                    resultText += "Class: " + String(result.timing.classification) + "ms\n";

#if EI_CLASSIFIER_OBJECT_DETECTION == 1
                    resultText += "Bounding boxes:\n";
                    bboxJson = "[";
                    bool firstBox = true;
                    for (uint32_t b = 0; b < result.bounding_boxes_count; b++) {
                        ei_impulse_result_bounding_box_t bb = result.bounding_boxes[b];
                        if (bb.value < CONFIDENCE_THRESHOLD) continue;  // filter low-confidence
                        resultText += String(bb.label) + " (" + String(bb.value, 3) + ") "
                                      + "x:" + String(bb.x) + " y:" + String(bb.y)
                                      + " w:" + String(bb.width) + " h:" + String(bb.height) + "\n";

                        if (!firstBox) bboxJson += ",";
                        firstBox = false;
                        String label = String(bb.label);
                        label.replace("\\", "\\\\");
                        label.replace("\"", "\\\"");
                        bboxJson += "{\"label\":\"" + label + "\""
                                   + ",\"value\":" + String(bb.value, 3)
                                   + ",\"x\":" + String(bb.x)
                                   + ",\"y\":" + String(bb.y)
                                   + ",\"width\":" + String(bb.width)
                                   + ",\"height\":" + String(bb.height) + "}";
                    }
                    bboxJson += "]";
#else
                    for (uint16_t c = 0; c < EI_CLASSIFIER_LABEL_COUNT; c++) {
                        resultText += String(ei_classifier_inferencing_categories[c]) + ": "
                                      + String(result.classification[c].value, 5) + "\n";
                    }
#endif

#if EI_CLASSIFIER_HAS_ANOMALY
                    resultText += "Anomaly: " + String(result.anomaly, 3) + "\n";
#endif
                }
            }

            if (snapshot_buf != nullptr) {
                free(snapshot_buf);
                snapshot_buf = nullptr;
            }

            // Publish this shot to the shared array
            if (xSemaphoreTake(shotsMutex, portMAX_DELAY) == pdTRUE) {
                if (shots[i].jpeg_buf != nullptr) {
                    free(shots[i].jpeg_buf);
                    shots[i].jpeg_buf = nullptr;
                }
                shots[i].jpeg_buf = jpeg_buf;   // may be nullptr if capture failed
                shots[i].jpeg_len = jpeg_len;
                shots[i].result_text = resultText;
                shots[i].bbox_json = bboxJson;
                shots[i].millis_taken = millis();
                shots[i].valid = (jpeg_buf != nullptr);
                xSemaphoreGive(shotsMutex);
            } else if (jpeg_buf != nullptr) {
                free(jpeg_buf);
            }

            Serial.printf("Shot %d/%d done: %s\n", i + 1, NUM_SHOTS_PER_BATCH,
                          resultText.c_str());
        }

        // Sleep out whatever remains of the 10-second batch window.
        long elapsed = (long)(millis() - lastBatchStart);
        long remaining = (long)BATCH_PERIOD_MS - elapsed;
        if (remaining > 0) {
            vTaskDelay(pdMS_TO_TICKS(remaining));
        }
    }
}

/* ------------------------------------------------------------------------ */
/* Camera init (from your EI example)                                       */
/* ------------------------------------------------------------------------ */
bool ei_camera_init(void) {
    if (is_initialised) return true;

    esp_err_t err = esp_camera_init(&camera_config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed with error 0x%x\n", err);
        return false;
    }

    sensor_t *s = esp_camera_sensor_get();
    if (s->id.PID == OV3660_PID) {
        s->set_vflip(s, 1);
        s->set_brightness(s, 1);
        s->set_saturation(s, 0);
    }

    is_initialised = true;
    return true;
}

/* ------------------------------------------------------------------------ */
/* Capture: grabs a frame, converts to RGB888 + resizes into snapshot_buf   */
/* for the classifier, THEN re-encodes that same cropped/resized buffer as */
/* JPEG for the web page. Serving the exact image the model saw means the  */
/* bounding box coordinates from the classifier line up pixel-for-pixel    */
/* with what's displayed in the browser - no extra scaling/offset math.    */
/* ------------------------------------------------------------------------ */
bool ei_camera_capture_and_save(uint32_t img_width, uint32_t img_height,
                                 uint8_t **out_jpeg, size_t *out_jpeg_len) {
    bool do_resize = false;

    if (!is_initialised) {
        Serial.println("ERR: Camera is not initialized");
        return false;
    }

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("Camera capture failed");
        return false;
    }

    bool converted = fmt2rgb888(fb->buf, fb->len, PIXFORMAT_JPEG, snapshot_buf);
    esp_camera_fb_return(fb);

    if (!converted) {
        Serial.println("Conversion failed");
        *out_jpeg = nullptr;
        *out_jpeg_len = 0;
        return false;
    }

    if ((img_width != EI_CAMERA_RAW_FRAME_BUFFER_COLS) ||
        (img_height != EI_CAMERA_RAW_FRAME_BUFFER_ROWS)) {
        do_resize = true;
    }

    if (do_resize) {
        ei::image::processing::crop_and_interpolate_rgb888(
            snapshot_buf,
            EI_CAMERA_RAW_FRAME_BUFFER_COLS,
            EI_CAMERA_RAW_FRAME_BUFFER_ROWS,
            snapshot_buf,
            img_width,
            img_height);
    }

    // Re-encode the exact classifier-input image as JPEG for the browser.
    uint8_t *jpg_out = nullptr;
    size_t jpg_out_len = 0;
    bool encoded = fmt2jpg(snapshot_buf, img_width * img_height * EI_CAMERA_FRAME_BYTE_SIZE,
                            img_width, img_height, PIXFORMAT_RGB888, 90,
                            &jpg_out, &jpg_out_len);
    if (!encoded) {
        Serial.println("JPEG encode failed");
        *out_jpeg = nullptr;
        *out_jpeg_len = 0;
        return false;
    }

    *out_jpeg = jpg_out;       // allocated by fmt2jpg, freed later via free()
    *out_jpeg_len = jpg_out_len;
    return true;
}

static int ei_camera_get_data(size_t offset, size_t length, float *out_ptr) {
    size_t pixel_ix = offset * 3;
    size_t pixels_left = length;
    size_t out_ptr_ix = 0;

    while (pixels_left != 0) {
        out_ptr[out_ptr_ix] = (snapshot_buf[pixel_ix + 2] << 16) +
                               (snapshot_buf[pixel_ix + 1] << 8) +
                               snapshot_buf[pixel_ix];
        out_ptr_ix++;
        pixel_ix += 3;
        pixels_left--;
    }
    return 0;
}

/* ------------------------------------------------------------------------ */
/* Web handlers                                                             */
/* ------------------------------------------------------------------------ */
void handleImage() {
    if (!server.hasArg("id")) {
        server.send(400, "text/plain", "missing id");
        return;
    }
    int id = server.arg("id").toInt();
    if (id < 0 || id >= NUM_SHOTS_PER_BATCH) {
        server.send(400, "text/plain", "bad id");
        return;
    }

    if (xSemaphoreTake(shotsMutex, pdMS_TO_TICKS(2000)) != pdTRUE) {
        server.send(503, "text/plain", "busy");
        return;
    }

    if (!shots[id].valid || shots[id].jpeg_buf == nullptr) {
        xSemaphoreGive(shotsMutex);
        server.send(404, "text/plain", "no image yet");
        return;
    }

    server.sendHeader("Cache-Control", "no-store, no-cache, must-revalidate, max-age=0");
    server.sendHeader("Pragma", "no-cache");
    server.sendHeader("Expires", "-1");
    // send_P copies from the buffer synchronously, safe to release after.
    server.send_P(200, "image/jpeg", (const char *)shots[id].jpeg_buf, shots[id].jpeg_len);
    xSemaphoreGive(shotsMutex);
}

void handleResults() {
    String json = "[";
    if (xSemaphoreTake(shotsMutex, pdMS_TO_TICKS(2000)) == pdTRUE) {
        for (int i = 0; i < NUM_SHOTS_PER_BATCH; i++) {
            if (i > 0) json += ",";
            String text = shots[i].result_text;
            text.replace("\\", "\\\\");
            text.replace("\"", "\\\"");
            text.replace("\n", "\\n");
            json += "{\"id\":" + String(i) +
                    ",\"valid\":" + (shots[i].valid ? "true" : "false") +
                    ",\"millis\":" + String(shots[i].millis_taken) +
                    ",\"text\":\"" + text + "\"" +
                    ",\"boxes\":" + shots[i].bbox_json + "}";
        }
        xSemaphoreGive(shotsMutex);
    }
    json += "]";
    server.send(200, "application/json", json);
}

void handleRoot() {
    String html = R"HTML(
<!DOCTYPE html>
<html>
<head>
  <meta charset="utf-8">
  <title>ESP32 Edge Impulse Inference</title>
  <style>
    body { font-family: sans-serif; background:#111; color:#eee; margin:0; padding:20px; }
    h1 { font-size: 1.3em; }
    .grid { display:flex; flex-wrap:wrap; gap:16px; }
    .card { background:#1c1c1c; border-radius:8px; padding:10px; width:280px; }
    .imgwrap { position:relative; width:100%; background:#000; border-radius:6px; overflow:hidden; }
    .imgwrap img { display:block; width:100%; }
    .box { position:absolute; border:2px solid #ff3b30; box-sizing:border-box; pointer-events:none; }
    .box-label { position:absolute; top:-1.3em; left:-2px; background:#ff3b30; color:#fff;
                 font-size:0.7em; padding:1px 4px; border-radius:3px; white-space:nowrap; }
    pre { white-space:pre-wrap; font-size:0.8em; color:#9f9; }
    .stamp { color:#888; font-size:0.75em; }
  </style>
</head>
<body>
  <h1>Latest batch (5 shots, refreshed every 10s)</h1>
  <div class="grid" id="grid"></div>
  <script>
    const N = )HTML" + String(NUM_SHOTS_PER_BATCH) + R"HTML(;
    const NATIVE_W = )HTML" + String(EI_CLASSIFIER_INPUT_WIDTH) + R"HTML(;
    const NATIVE_H = )HTML" + String(EI_CLASSIFIER_INPUT_HEIGHT) + R"HTML(;

    const objectUrls = {};

    function buildGrid() {
      const grid = document.getElementById('grid');
      grid.innerHTML = '';
      for (let i = 0; i < N; i++) {
        const card = document.createElement('div');
        card.className = 'card';
        card.innerHTML = `
          <div class="imgwrap" id="wrap${i}">
            <img id="img${i}">
          </div>
          <div class="stamp" id="stamp${i}"></div>
          <pre id="text${i}">waiting...</pre>`;
        grid.appendChild(card);
      }
    }

    async function loadImage(id) {
      const res = await fetch('/image?id=' + id + '&t=' + Date.now(), { cache: 'no-store' });
      if (!res.ok) return;
      const blob = await res.blob();
      const url = URL.createObjectURL(blob);
      const img = document.getElementById('img' + id);
      if (!img) { URL.revokeObjectURL(url); return; }
      const oldUrl = objectUrls[id];
      img.src = url;
      objectUrls[id] = url;
      if (oldUrl) URL.revokeObjectURL(oldUrl);
    }

    function drawBoxes(id, boxes) {
      const wrap = document.getElementById('wrap' + id);
      if (!wrap) return;
      wrap.querySelectorAll('.box').forEach(el => el.remove());
      if (!boxes || boxes.length === 0) return;

      const renderedW = wrap.clientWidth;
      const renderedH = wrap.clientHeight;
      const scaleX = renderedW / NATIVE_W;
      const scaleY = renderedH / NATIVE_H;

      boxes.forEach(b => {
        const div = document.createElement('div');
        div.className = 'box';
        div.style.left = (b.x * scaleX) + 'px';
        div.style.top = (b.y * scaleY) + 'px';
        div.style.width = (b.width * scaleX) + 'px';
        div.style.height = (b.height * scaleY) + 'px';
        const label = document.createElement('div');
        label.className = 'box-label';
        label.textContent = b.label + ' ' + Math.round(b.value * 100) + '%';
        div.appendChild(label);
        wrap.appendChild(div);
      });
    }

    async function refresh() {
      try {
        const res = await fetch('/results', { cache: 'no-store' });
        const data = await res.json();
        for (const shot of data) {
          const txt = document.getElementById('text' + shot.id);
          const stamp = document.getElementById('stamp' + shot.id);
          if (shot.valid) {
            await loadImage(shot.id);
            drawBoxes(shot.id, shot.boxes);
          }
          if (txt) txt.textContent = shot.valid ? shot.text : 'no image yet';
          if (stamp) stamp.textContent = 'updated ' + ((Date.now() - shot.millis) / 1000).toFixed(1) + 's ago (device ms)';
        }
      } catch (e) {
        console.error(e);
      }
    }

    buildGrid();
    refresh();
    setInterval(refresh, 3000);
  </script>
</body>
</html>
)HTML";

    server.send(200, "text/html", html);
}

#if !defined(EI_CLASSIFIER_SENSOR) || EI_CLASSIFIER_SENSOR != EI_CLASSIFIER_SENSOR_CAMERA
#error "Invalid model for current sensor"
#endif

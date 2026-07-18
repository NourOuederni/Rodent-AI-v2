/*
 * Rodent-AI  -  ESP32-CAM (AI Thinker / OV2640 / OV3660) rat-presence detector
 * ---------------------------------------------------------------------------
 * Runs your Edge Impulse FOMO model on-device and adds TEMPORAL FILTERING so a
 * single noisy frame cannot trigger a false alarm: a rat is only reported as
 * PRESENT when it is detected in at least DETECT_MIN_HITS of the last
 * DETECT_WINDOW frames. A rat that lingers to eat is on-screen for hundreds of
 * frames, so this recovers the ~30% per-frame misses while killing flicker and
 * false positives.
 *
 * SETUP
 *  1. Edge Impulse Studio -> Deployment -> "Arduino library" -> Build.
 *     In Arduino IDE:  Sketch > Include Library > Add .ZIP Library...
 *  2. Replace the include below with YOUR project header (the file that ends
 *     with "_inferencing.h" inside that library).
 *  3. Board: "AI Thinker ESP32-CAM".  Tools > PSRAM: Enabled.
 *  4. Wire your alert device (buzzer / relay / external LED) to ALERT_PIN.
 *
 * Structure follows the official Edge Impulse ESP32 camera example, with the
 * temporal-filtering + alert logic added.
 */

// >>> CHANGE THIS to your exported project header <<<
#include <Rodent_AI_inferencing.h>

#include <stdlib.h>
#include <string.h>
#include "esp_camera.h"

/* ----------------------- tunable behaviour ----------------------- */
#define CONFIDENCE_THRESHOLD   0.5f   // min FOMO score to count a rat cell
#define DETECT_WINDOW          10     // frames to look back over        (M)
#define DETECT_MIN_HITS        3      // hits within window to CONFIRM   (N)
#define CLEAR_MAX_HITS         1      // hits at/below which we CLEAR
#define ALERT_COOLDOWN_MS      5000   // min gap between new-presence alerts

/* ----------------------- I/O pins (AI Thinker) ------------------- */
#define ALERT_PIN     13   // buzzer / relay / external LED (active HIGH)
#define STATUS_LED    33   // on-board red LED (active LOW)
// NB: GPIO 4 is the very bright on-board flash LED (left unused here).
// Avoid GPIO 12 as an output that is HIGH at boot (it is a strapping pin).

/* ----------------------- camera pins (AI Thinker) ---------------- */
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

/* ----------------------- capture buffer sizing ------------------- */
#define EI_CAMERA_RAW_FRAME_BUFFER_COLS   320
#define EI_CAMERA_RAW_FRAME_BUFFER_ROWS   240
#define EI_CAMERA_FRAME_BYTE_SIZE         3

static bool is_initialised = false;
static uint8_t *snapshot_buf = nullptr;   // RGB888 working buffer

static camera_config_t camera_config = {
    .pin_pwdn = PWDN_GPIO_NUM,
    .pin_reset = RESET_GPIO_NUM,
    .pin_xclk = XCLK_GPIO_NUM,
    .pin_sccb_sda = SIOD_GPIO_NUM,
    .pin_sccb_scl = SIOC_GPIO_NUM,
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
    .pixel_format = PIXFORMAT_JPEG,      // converted to RGB888 after capture
    .frame_size = FRAMESIZE_QVGA,        // 320x240
    .jpeg_quality = 12,
    .fb_count = 1,
    .fb_location = CAMERA_FB_IN_PSRAM,
    .grab_mode = CAMERA_GRAB_WHEN_EMPTY,
};

/* ----------------------- temporal filter state ------------------- */
static bool detect_history[DETECT_WINDOW];
static uint8_t history_idx = 0;
static bool alert_active = false;
static uint32_t last_alert_ms = 0;

/* ----------------------- forward declarations -------------------- */
bool ei_camera_init(void);
bool ei_camera_capture(uint32_t img_width, uint32_t img_height, uint8_t *out_buf);
static int ei_camera_get_data(size_t offset, size_t length, float *out_ptr);
void on_presence_confirmed(uint16_t count, uint8_t hits);
void on_presence_cleared(void);

/* ============================== setup ============================= */
void setup() {
    Serial.begin(115200);
    while (!Serial && millis() < 3000) { }

    pinMode(ALERT_PIN, OUTPUT);
    pinMode(STATUS_LED, OUTPUT);
    digitalWrite(ALERT_PIN, LOW);
    digitalWrite(STATUS_LED, HIGH);         // off (active LOW)

    for (uint8_t i = 0; i < DETECT_WINDOW; i++) detect_history[i] = false;

    if (!ei_camera_init()) {
        Serial.println("ERR: camera init failed - check board selection / PSRAM.");
    } else {
        Serial.println("Rodent-AI camera ready.");
    }
}

/* ============================== loop ============================== */
void loop() {
    if (!is_initialised) { delay(100); return; }

    snapshot_buf = (uint8_t *)malloc(EI_CAMERA_RAW_FRAME_BUFFER_COLS *
                                     EI_CAMERA_RAW_FRAME_BUFFER_ROWS *
                                     EI_CAMERA_FRAME_BYTE_SIZE);
    if (!snapshot_buf) {
        Serial.println("ERR: failed to allocate snapshot buffer.");
        delay(200);
        return;
    }

    if (!ei_camera_capture(EI_CLASSIFIER_INPUT_WIDTH,
                           EI_CLASSIFIER_INPUT_HEIGHT, snapshot_buf)) {
        Serial.println("ERR: capture failed.");
        free(snapshot_buf);
        delay(50);
        return;
    }

    ei::signal_t signal;
    signal.total_length = EI_CLASSIFIER_INPUT_WIDTH * EI_CLASSIFIER_INPUT_HEIGHT;
    signal.get_data = &ei_camera_get_data;

    ei_impulse_result_t result = { 0 };
    EI_IMPULSE_ERROR err = run_classifier(&signal, &result, false);
    free(snapshot_buf);
    snapshot_buf = nullptr;

    if (err != EI_IMPULSE_OK) {
        Serial.printf("ERR: run_classifier returned %d\n", err);
        delay(50);
        return;
    }

    /* ---- count rat detections in this frame ---- */
    uint16_t rats_this_frame = 0;
#if EI_CLASSIFIER_OBJECT_DETECTION == 1
    for (uint32_t i = 0; i < result.bounding_boxes_count; i++) {
        ei_impulse_result_bounding_box_t bb = result.bounding_boxes[i];
        if (bb.value >= CONFIDENCE_THRESHOLD) {
            rats_this_frame++;
        }
    }
#else
    // Fallback if the model was built as a plain image classifier, not FOMO.
    for (uint16_t i = 0; i < EI_CLASSIFIER_LABEL_COUNT; i++) {
        if (strcmp(result.classification[i].label, "rat") == 0 &&
            result.classification[i].value >= CONFIDENCE_THRESHOLD) {
            rats_this_frame = 1;
        }
    }
#endif

    bool detected_now = rats_this_frame > 0;

    /* ---- temporal filtering (ring buffer over last M frames) ---- */
    detect_history[history_idx] = detected_now;
    history_idx = (history_idx + 1) % DETECT_WINDOW;

    uint8_t hits = 0;
    for (uint8_t i = 0; i < DETECT_WINDOW; i++) {
        if (detect_history[i]) hits++;
    }

    if (!alert_active && hits >= DETECT_MIN_HITS) {
        alert_active = true;
        on_presence_confirmed(rats_this_frame, hits);
    } else if (alert_active && hits <= CLEAR_MAX_HITS) {
        alert_active = false;
        on_presence_cleared();
    }

    digitalWrite(STATUS_LED, alert_active ? LOW : HIGH);   // active LOW
    digitalWrite(ALERT_PIN, alert_active ? HIGH : LOW);

    Serial.printf("frame raw=%d  hits=%u/%u  state=%s  (dsp %d ms, nn %d ms)\n",
                  detected_now, hits, DETECT_WINDOW,
                  alert_active ? "RAT" : "clear",
                  result.timing.dsp, result.timing.classification);
}

/* ----------------------- alert callbacks ------------------------- */
void on_presence_confirmed(uint16_t count, uint8_t hits) {
    uint32_t now = millis();
    if (now - last_alert_ms < ALERT_COOLDOWN_MS) return;   // debounce repeats
    last_alert_ms = now;
    Serial.printf(">>> RAT PRESENT (peak count=%u, hits=%u/%u) <<<\n",
                  count, hits, DETECT_WINDOW);
    // TODO: your action here -> log to SD, send Wi-Fi/MQTT alert, sound buzzer.
}

void on_presence_cleared(void) {
    Serial.println("--- scene clear ---");
}

/* =====================  Edge Impulse camera glue  ==================== */
bool ei_camera_init(void) {
    if (is_initialised) return true;

    esp_err_t err = esp_camera_init(&camera_config);
    if (err != ESP_OK) {
        Serial.printf("Camera init failed 0x%x\n", err);
        return false;
    }

    sensor_t *s = esp_camera_sensor_get();
    if (s->id.PID == OV3660_PID) {          // OV3660 tweaks for better image
        s->set_vflip(s, 1);
        s->set_brightness(s, 1);
        s->set_saturation(s, 0);
    }

    is_initialised = true;
    return true;
}

bool ei_camera_capture(uint32_t img_width, uint32_t img_height, uint8_t *out_buf) {
    if (!is_initialised) {
        Serial.println("ERR: camera not initialised.");
        return false;
    }

    camera_fb_t *fb = esp_camera_fb_get();
    if (!fb) {
        Serial.println("ERR: camera capture returned null.");
        return false;
    }

    bool converted = fmt2rgb888(fb->buf, fb->len, fb->format, snapshot_buf);
    esp_camera_fb_return(fb);
    if (!converted) {
        Serial.println("ERR: JPEG->RGB888 conversion failed.");
        return false;
    }

    // resize the 320x240 RGB888 frame into the model's (square) input in place
    if (img_width != EI_CAMERA_RAW_FRAME_BUFFER_COLS ||
        img_height != EI_CAMERA_RAW_FRAME_BUFFER_ROWS) {
        ei::image::processing::crop_and_interpolate_rgb888(
            out_buf,
            EI_CAMERA_RAW_FRAME_BUFFER_COLS,
            EI_CAMERA_RAW_FRAME_BUFFER_ROWS,
            out_buf,
            img_width,
            img_height);
    }
    return true;
}

// Pack the RGB888 working buffer into the float feature vector EI expects.
static int ei_camera_get_data(size_t offset, size_t length, float *out_ptr) {
    size_t pixel_ix = offset * 3;
    size_t pixels_left = length;
    size_t out_ptr_ix = 0;

    while (pixels_left != 0) {
        out_ptr[out_ptr_ix] = (snapshot_buf[pixel_ix] << 16) +
                              (snapshot_buf[pixel_ix + 1] << 8) +
                              snapshot_buf[pixel_ix + 2];
        out_ptr_ix++;
        pixel_ix += 3;
        pixels_left--;
    }
    return 0;
}

#include "RodentDetectorV3.h"
#include "model_data.h"

#include <Arduino.h>
#include <esp_heap_caps.h>

#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/micro/micro_log.h>
#include <tensorflow/lite/schema/schema_generated.h>

namespace {
  // MobileNetV2 alpha=0.35 at 224x224 has intermediate activations well over
  // 1 MB (e.g. the first expanded block is 112x112x96 int8 ≈ 1.2 MB), so the
  // tensor arena CANNOT live in the ESP32's 520 KB internal SRAM. It is
  // allocated in PSRAM at begin(). 3 MB is a safe ceiling; the actual usage
  // is reported by arenaBytesUsed() after begin().
  constexpr size_t kTensorArenaSize = 3 * 1024 * 1024;
  uint8_t* tensor_arena = nullptr;

  const tflite::Model* model = nullptr;
  tflite::MicroInterpreter* interpreter = nullptr;
  TfLiteTensor* input = nullptr;
  TfLiteTensor* output = nullptr;

  // ImageNet normalisation constants — MUST match load_image() in the
  // training notebook exactly.
  constexpr float kMean[3] = {0.485f, 0.456f, 0.406f};
  constexpr float kStd[3]  = {0.229f, 0.224f, 0.225f};

  constexpr int kInputSize = 224;
}

RodentDetectorV3::RodentDetectorV3() {}

bool RodentDetectorV3::begin() {
  model = tflite::GetModel(g_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    MicroPrintf("Model schema version mismatch!");
    return false;
  }

  // Arena in PSRAM — mandatory, see note above.
  tensor_arena = (uint8_t*) heap_caps_malloc(
      kTensorArenaSize, MALLOC_CAP_SPIRAM | MALLOC_CAP_8BIT);
  if (tensor_arena == nullptr) {
    MicroPrintf("Failed to allocate tensor arena in PSRAM. "
                "Enable PSRAM in Tools > PSRAM.");
    return false;
  }
  _arena_size = kTensorArenaSize;

  // Ops used by int8 MobileNetV2 (alpha=0.35, avg pooling, sigmoid head).
  // If you get an "unresolved op" error at runtime, add the missing op here
  // and bump the template count.
  static tflite::MicroMutableOpResolver<12> resolver;
  resolver.AddConv2D();
  resolver.AddDepthwiseConv2D();
  resolver.AddFullyConnected();
  resolver.AddLogistic();          // sigmoid
  resolver.AddAveragePool2D();
  resolver.AddMean();              // GlobalAveragePooling lowers to MEAN
  resolver.AddReshape();
  resolver.AddAdd();               // residual connections
  resolver.AddPad();
  resolver.AddQuantize();
  resolver.AddDequantize();
  resolver.AddSoftmax();           // harmless if unused

  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, kTensorArenaSize);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    MicroPrintf("AllocateTensors() failed");
    return false;
  }

  input  = interpreter->input(0);
  output = interpreter->output(0);

  // Capture quantisation params — needed to quantise normalised floats.
  _in_scale       = input->params.scale;
  _in_zero_point  = input->params.zero_point;
  _out_scale      = output->params.scale;
  _out_zero_point = output->params.zero_point;

  _initialized = true;
  return true;
}

float RodentDetectorV3::predict(const uint8_t* rgb888) {
  if (!_initialized) return -1.0f;

  // Preprocess: raw uint8 RGB -> ImageNet-normalised float -> int8 quantised.
  // This must mirror the training notebook's load_image() +
  // evaluate_tflite_int8() exactly, or accuracy will silently collapse.
  int8_t* dst = input->data.int8;
  const int n_pixels = kInputSize * kInputSize;

  for (int i = 0; i < n_pixels; i++) {
    const uint8_t* px = rgb888 + i * 3;
    for (int c = 0; c < 3; c++) {
      float norm = ((float)px[c] / 255.0f - kMean[c]) / kStd[c];
      int q = (int) roundf(norm / _in_scale) + _in_zero_point;
      if (q < -128) q = -128;
      if (q >  127) q =  127;
      dst[i * 3 + c] = (int8_t) q;
    }
  }

  uint32_t t0 = millis();
  if (interpreter->Invoke() != kTfLiteOk) {
    MicroPrintf("Invoke() failed");
    return -1.0f;
  }
  _last_inference_ms = millis() - t0;

  // Dequantise the int8 sigmoid output back to a float probability.
  int8_t raw = output->data.int8[0];
  return ((float)raw - _out_zero_point) * _out_scale;
}

size_t RodentDetectorV3::arenaBytesUsed() const {
  return interpreter ? interpreter->arena_used_bytes() : 0;
}

size_t RodentDetectorV3::modelBytes() const {
  return g_model_len;
}
#include "RodentDetectorV3.h"
#include "model_data.h"

#include <tensorflow/lite/micro/micro_interpreter.h>
#include <tensorflow/lite/micro/micro_mutable_op_resolver.h>
#include <tensorflow/lite/micro/micro_log.h>
#include <tensorflow/lite/schema/schema_generated.h>

namespace {
  constexpr int kTensorArenaSize = 200 * 1024;  // tune down/up depending on your board's RAM
  alignas(16) uint8_t tensor_arena[kTensorArenaSize];

  const tflite::Model* model = nullptr;
  tflite::MicroInterpreter* interpreter = nullptr;
  TfLiteTensor* input = nullptr;
  TfLiteTensor* output = nullptr;
}

RodentDetectorV2::RodentDetectorV2() {}

bool RodentDetectorV2::begin() {
  model = tflite::GetModel(g_model);
  if (model->version() != TFLITE_SCHEMA_VERSION) {
    MicroPrintf("Model schema version mismatch!");
    return false;
  }

  // Add only the ops your model actually needs (keeps flash usage down).
  // If you get an "unresolved op" error at runtime, add the missing op here.
  static tflite::MicroMutableOpResolver<10> resolver;
  resolver.AddConv2D();
  resolver.AddDepthwiseConv2D();
  resolver.AddFullyConnected();
  resolver.AddLogistic();
  resolver.AddAveragePool2D();
  resolver.AddReshape();
  resolver.AddAdd();
  resolver.AddMul();
  resolver.AddPad();
  resolver.AddMean();

  static tflite::MicroInterpreter static_interpreter(
      model, resolver, tensor_arena, kTensorArenaSize);
  interpreter = &static_interpreter;

  if (interpreter->AllocateTensors() != kTfLiteOk) {
    MicroPrintf("AllocateTensors() failed");
    return false;
  }

  input = interpreter->input(0);
  output = interpreter->output(0);
  _initialized = true;
  return true;
}

float RodentDetectorV2::predict(const uint8_t* image_data) {
  if (!_initialized) return -1.0f;

  memcpy(input->data.uint8, image_data, input->bytes);

  if (interpreter->Invoke() != kTfLiteOk) {
    MicroPrintf("Invoke() failed");
    return -1.0f;
  }

  uint8_t raw = output->data.uint8[0];
  float scale = output->params.scale;
  int zero_point = output->params.zero_point;
  return (raw - zero_point) * scale;
}

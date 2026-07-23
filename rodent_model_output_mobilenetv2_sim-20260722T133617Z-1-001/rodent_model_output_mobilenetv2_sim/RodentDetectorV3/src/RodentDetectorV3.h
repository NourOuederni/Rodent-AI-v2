#ifndef RODENTDETECTORV3_H
#define RODENTDETECTORV3_H

#include <Chirale_TensorFlowLite.h>
#include <stdint.h>

// RodentDetectorV3 — MobileNetV2 (alpha=0.35) int8 TFLite Micro wrapper.
//
// IMPORTANT: this model expects ImageNet-normalised input:
//     norm = (pixel/255 - mean) / std
// quantised to int8 with the input tensor's own scale/zero-point.
// predict() handles all of that internally — just hand it raw RGB888 bytes.

class RodentDetectorV3 {
  public:
    RodentDetectorV3();

    // Allocates the tensor arena in PSRAM (required — MobileNetV2's
    // intermediate activations do not fit in internal SRAM).
    bool begin();

    // input: pointer to 224*224*3 raw RGB888 bytes (uint8, 0-255),
    //        already resized to the model input size.
    // returns: probability that the image contains a rodent (0.0 - 1.0),
    //          or -1.0f on failure.
    float predict(const uint8_t* rgb888);

    // Diagnostics — valid after begin() / predict()
    uint32_t lastInferenceMs() const { return _last_inference_ms; }
    float    inputScale()      const { return _in_scale; }
    int      inputZeroPoint()  const { return _in_zero_point; }
    float    outputScale()     const { return _out_scale; }
    int      outputZeroPoint() const { return _out_zero_point; }
    size_t   arenaBytesUsed()  const;
    size_t   arenaBytesTotal() const { return _arena_size; }
    size_t   modelBytes()      const;

  private:
    bool     _initialized = false;
    float    _in_scale = 1.0f;
    int      _in_zero_point = 0;
    float    _out_scale = 1.0f;
    int      _out_zero_point = 0;
    uint32_t _last_inference_ms = 0;
    size_t   _arena_size = 0;
};

#endif  // RODENTDETECTORV3_H
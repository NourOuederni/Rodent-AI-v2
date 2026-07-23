#ifndef RODENTDETECTORV2_H
#define RODENTDETECTORV2_H

#include <TensorFlowLite.h>

class RodentDetectorV3 {
  public:
    RodentDetectorV3();
    bool begin();
    // input: pointer to 224*224*3 uint8 RGB bytes, already resized to model input size
    // returns: probability that the image contains a rodent (0.0 - 1.0)
    float predict(const uint8_t* image_data);

  private:
    bool _initialized = false;
};

#endif  // RODENTDETECTORV3_H

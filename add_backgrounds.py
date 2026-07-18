"""
add_backgrounds.py

Inject BACKGROUND / NEGATIVE images (empty scenes with NO rat) into the
merged dataset so the detector learns what "nothing here" looks like and
stops raising false alarms on shadows, food, reflections, etc.

Each background is written into all three places your pipeline uses:
  1. datasets/merged_dataset/images/    -> the .jpg image
  2. datasets/merged_dataset/labels/    -> an EMPTY .txt file (YOLO background)
  3. datasets/merged_dataset/ei_upload/ -> the .jpg + an empty-box JSON
                                           {"version": 1, "boundingBoxes": []}

HOW TO USE
----------
1. Put your empty-scene images (captured from the REAL camera at the feeding
   station: empty, food-but-no-rat, day + night/IR, shadows) into a folder,
   e.g.  backgrounds_source/
2. Run:  python add_backgrounds.py
3. Re-upload the ei_upload folder to Edge Impulse and retrain.

Notes
-----
* Background images are named  bg_000001.jpg, bg_000002.jpg, ...  so they are
  easy to spot and never collide with your numbered positives.
* An EMPTY .txt label is the correct YOLO way to mark a background image.
  Your dataset_check.py will list these as "empty_label" -- that is EXPECTED
  for backgrounds and is NOT an error.
* Aim for roughly 10-20% backgrounds relative to your positive images.

Requires: pillow  (pip install pillow)
"""

import json
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

# ----------------------------- configuration ------------------------------
SOURCE_DIR = "backgrounds_source"          # put your empty-scene images here
MERGED_DIR = "datasets/merged_dataset"
PREFIX = "bg_"                             # naming prefix for backgrounds
JPEG_QUALITY = 90
RESIZE_MAX_DIM = None                      # e.g. 1024 to cap size; None = keep
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp", ".webp"}
# --------------------------------------------------------------------------


def next_start_index(images_dir: Path) -> int:
    """Continue numbering after any bg_ files that already exist."""
    max_idx = 0
    for p in images_dir.glob(f"{PREFIX}*.jpg"):
        digits = p.stem[len(PREFIX):]
        if digits.isdigit():
            max_idx = max(max_idx, int(digits))
    return max_idx + 1


def load_rgb(path: Path):
    """Open an image, verify it is not corrupted, return an RGB copy."""
    try:
        with Image.open(path) as probe:
            probe.verify()                     # detect corruption
        im = Image.open(path).convert("RGB")   # reopen after verify
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        return None, f"unreadable/corrupted: {e}"
    if RESIZE_MAX_DIM:
        im.thumbnail((RESIZE_MAX_DIM, RESIZE_MAX_DIM), Image.LANCZOS)
    return im, None


def main():
    src = Path(SOURCE_DIR)
    images_dir = Path(MERGED_DIR) / "images"
    labels_dir = Path(MERGED_DIR) / "labels"
    ei_dir = Path(MERGED_DIR) / "ei_upload"

    if not src.is_dir():
        print(f"ERROR: source folder not found: {src.resolve()}")
        print("Create it, drop your empty-scene images inside, then re-run.")
        sys.exit(1)

    for d in (images_dir, labels_dir, ei_dir):
        d.mkdir(parents=True, exist_ok=True)

    sources = sorted(p for p in src.iterdir()
                     if p.is_file() and p.suffix.lower() in IMAGE_EXTS)
    if not sources:
        print(f"No images found in {src.resolve()} "
              f"(looked for {sorted(IMAGE_EXTS)}).")
        sys.exit(0)

    idx = next_start_index(images_dir)
    added = 0
    skipped = 0

    print(f"Found {len(sources)} candidate background images. Injecting...\n")
    for p in sources:
        im, err = load_rgb(p)
        if err:
            skipped += 1
            print(f"  SKIP {p.name}: {err}")
            continue

        name = f"{PREFIX}{idx:06d}"
        idx += 1

        # 1) YOLO image
        im.save(images_dir / f"{name}.jpg", "JPEG", quality=JPEG_QUALITY)
        # 2) YOLO empty label (marks the image as background)
        (labels_dir / f"{name}.txt").write_text("")
        # 3) Edge Impulse image + empty-box JSON
        im.save(ei_dir / f"{name}.jpg", "JPEG", quality=JPEG_QUALITY)
        (ei_dir / f"{name}.json").write_text(
            json.dumps({"version": 1, "boundingBoxes": []})
        )
        added += 1

    # summary + ratio guidance
    positives = len([q for q in images_dir.glob("*.jpg")
                     if not q.stem.startswith(PREFIX)])
    backgrounds = len(list(images_dir.glob(f"{PREFIX}*.jpg")))
    ratio = (backgrounds / positives * 100) if positives else 0

    print("\nDone.")
    print(f"  Backgrounds added this run: {added}")
    print(f"  Skipped (bad images):       {skipped}")
    print(f"  Total positives:            {positives}")
    print(f"  Total backgrounds:          {backgrounds} "
          f"({ratio:.1f}% of positives)")
    if ratio < 10:
        print("  TIP: aim for ~10-20% backgrounds; add more empty-scene frames.")
    elif ratio > 30:
        print("  NOTE: >30% backgrounds can start to hurt recall.")


if __name__ == "__main__":
    main()

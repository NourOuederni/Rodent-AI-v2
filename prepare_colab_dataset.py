"""
prepare_colab_dataset.py
========================
Selects up to 6 000 unique scenes from merged_dataset (pHash dedup),
generates 600 background crops, and writes everything to
  datasets/colab_dataset/{images, labels}/
ready to ZIP and upload to Google Drive for Colab training.

Run: python prepare_colab_dataset.py
Then ZIP datasets/colab_dataset/ and upload to Drive.
"""

import random, shutil
from pathlib import Path
import numpy as np
from PIL import Image, ImageFilter
import imagehash

# ── configuration ─────────────────────────────────────────────────────────
IMAGES_DIR   = Path("datasets/merged_dataset/images")
LABELS_DIR   = Path("datasets/merged_dataset/labels")
OUTPUT_DIR   = Path("datasets/colab_dataset")
TARGET_POS   = 6000    # positive (rat) images to keep
TARGET_BG    = 600     # background (empty) images to generate
PHASH_THR    = 8       # perceptual hash dedup threshold
TRAIN_RATIO  = 0.8
RANDOM_SEED  = 42
MIN_SIDE     = 120     # min side to extract a background crop
MARGIN       = 6       # pixels to shrink rat bounding boxes
JPEG_QUALITY = 90
# ──────────────────────────────────────────────────────────────────────────

random.seed(RANDOM_SEED)
np.random.seed(RANDOM_SEED)

for split in ["train", "val"]:
    (OUTPUT_DIR / "images" / split).mkdir(parents=True, exist_ok=True)
    (OUTPUT_DIR / "labels" / split).mkdir(parents=True, exist_ok=True)


# ── helpers ───────────────────────────────────────────────────────────────
def read_yolo(txt_path):
    boxes = []
    if txt_path.exists():
        for line in txt_path.read_text().splitlines():
            parts = line.strip().split()
            if len(parts) == 5:
                boxes.append([float(x) for x in parts])
    return boxes  # [[cls, cx, cy, w, h], ...]  normalised


def rat_free_square(boxes, W, H):
    """Return (x1,y1,x2,y2) of the largest rat-free region, or None."""
    if not boxes:
        side = min(W, H)
        return (0, 0, side, side)

    # union bounding box of all rats (expanded by MARGIN)
    pxs = [(b[1] - b[3] / 2) * W - MARGIN for b in boxes]
    pys = [(b[2] - b[4] / 2) * H - MARGIN for b in boxes]
    pxe = [(b[1] + b[3] / 2) * W + MARGIN for b in boxes]
    pye = [(b[2] + b[4] / 2) * H + MARGIN for b in boxes]
    rx1, ry1 = int(max(0, min(pxs))), int(max(0, min(pys)))
    rx2, ry2 = int(min(W, max(pxe))), int(min(H, max(pye)))

    # try the four complement strips
    candidates = [
        (0,   0,   W,   ry1),   # above rats
        (0,   ry2, W,   H),     # below
        (0,   0,   rx1, H),     # left
        (rx2, 0,   W,   H),     # right
    ]
    best = None
    best_side = 0
    for x1, y1, x2, y2 in candidates:
        w, h = x2 - x1, y2 - y1
        side = min(w, h)
        if side >= MIN_SIDE and side > best_side:
            best = (x1, y1, x1 + side, y1 + side)
            best_side = side
    return best


def esp32_look(im):
    """Simulate ESP32-CAM appearance."""
    arr = np.array(im.convert("RGB")).astype(float)
    arr += np.random.normal(0, 4, arr.shape)
    arr = np.clip(arr, 0, 255)
    if random.random() < 0.7:
        g = arr.mean(axis=2, keepdims=True)
        arr = np.repeat(g, 3, axis=2)
    if random.random() < 0.3:
        arr *= random.uniform(0.5, 0.9)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    im2 = Image.fromarray(arr)
    if random.random() < 0.5:
        s = random.randint(48, 80)
        im2 = im2.resize((s, s), Image.BILINEAR).resize((im.width, im.height), Image.NEAREST)
    return im2


# ── step 1: select unique positives ───────────────────────────────────────
print(f"Step 1 — selecting up to {TARGET_POS} unique positive scenes …")
all_images = sorted(IMAGES_DIR.glob("*.jpg"))
random.shuffle(all_images)

seen_hashes = set()
selected = []

for img_path in all_images:
    if len(selected) >= TARGET_POS:
        break
    lbl_path = LABELS_DIR / img_path.with_suffix(".txt").name
    if not lbl_path.exists():
        continue
    boxes = read_yolo(lbl_path)
    if not boxes:          # skip images without rats
        continue
    try:
        h = str(imagehash.phash(Image.open(img_path)))
    except Exception:
        continue
    if any(abs(imagehash.hex_to_hash(h) - imagehash.hex_to_hash(s)) < PHASH_THR
           for s in seen_hashes):
        continue
    seen_hashes.add(h)
    selected.append((img_path, lbl_path))
    if len(selected) % 500 == 0:
        print(f"  {len(selected)}/{TARGET_POS}")

print(f"  Selected {len(selected)} positives.")

# Copy them into train/val splits
random.shuffle(selected)
n_train = round(len(selected) * TRAIN_RATIO)
for i, (img_path, lbl_path) in enumerate(selected):
    split = "train" if i < n_train else "val"
    shutil.copy(img_path, OUTPUT_DIR / "images" / split / img_path.name)
    shutil.copy(lbl_path, OUTPUT_DIR / "labels" / split / lbl_path.name)


# ── step 2: generate backgrounds ──────────────────────────────────────────
print(f"\nStep 2 — generating {TARGET_BG} background crops …")
bg_hashes = set()
bg_count = 0
shuffle_copy = list(all_images)
random.shuffle(shuffle_copy)

for img_path in shuffle_copy:
    if bg_count >= TARGET_BG:
        break
    lbl_path = LABELS_DIR / img_path.with_suffix(".txt").name
    try:
        im = Image.open(img_path).convert("RGB")
    except Exception:
        continue
    W, H = im.size
    boxes = read_yolo(lbl_path)
    region = rat_free_square(boxes, W, H)
    if region is None:
        continue
    x1, y1, x2, y2 = region
    if min(x2 - x1, y2 - y1) < MIN_SIDE:
        continue
    crop = im.crop((x1, y1, x2, y2))
    crop = esp32_look(crop)
    h = str(imagehash.phash(crop))
    if any(abs(imagehash.hex_to_hash(h) - imagehash.hex_to_hash(s)) < PHASH_THR
           for s in bg_hashes):
        continue
    bg_hashes.add(h)
    bg_count += 1
    name = f"bg_{bg_count:06d}"
    split = "train" if bg_count <= round(TARGET_BG * TRAIN_RATIO) else "val"
    crop.save(OUTPUT_DIR / "images" / split / f"{name}.jpg", quality=JPEG_QUALITY)
    (OUTPUT_DIR / "labels" / split / f"{name}.txt").write_text("")  # empty = background
    if bg_count % 100 == 0:
        print(f"  {bg_count}/{TARGET_BG}")

print(f"  Generated {bg_count} backgrounds.")


# ── step 3: write data.yaml ───────────────────────────────────────────────
(OUTPUT_DIR / "data.yaml").write_text(
    "path: /content/colab_dataset\n"
    "train: images/train\n"
    "val:   images/val\n"
    "nc: 1\n"
    "names: ['rat']\n"
)

train_imgs = len(list((OUTPUT_DIR / "images" / "train").glob("*.jpg")))
val_imgs   = len(list((OUTPUT_DIR / "images" / "val").glob("*.jpg")))
print(f"\nDone.")
print(f"  train: {train_imgs} images")
print(f"  val:   {val_imgs} images")
print(f"  total: {train_imgs + val_imgs}")
print(f"\nNext:")
print(f"  1. Run: Compress-Archive -Path datasets/colab_dataset -DestinationPath colab_dataset.zip")
print(f"  2. Upload colab_dataset.zip to Google Drive")
print(f"  3. Open rodent_colab_training.ipynb in Google Colab")

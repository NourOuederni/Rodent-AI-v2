import json
import random
from pathlib import Path

import numpy as np
from PIL import Image
import imagehash

# ----------------------------- configuration ------------------------------
IMAGES_DIR = Path("datasets/merged_dataset/images")
LABELS_DIR = Path("datasets/merged_dataset/labels")
CURATED_DIR = Path("datasets/ei_curated")      # where the positives already live
PREFIX = "bg_"

TARGET_BG = 350            # total backgrounds to create (~15-18% of positives)
TRAIN_RATIO = 0.8          # split, same as the positives
MIN_SIDE = 120             # min side (px) of a usable rat-free square
MARGIN = 6                 # px kept away from any rat box
PHASH_THRESHOLD = 8        # dedup: skip backgrounds too similar to accepted ones
RANDOM_SEED = 42
JPEG_QUALITY = 90

# match the positives' style distribution / ESP32-CAM look
P_CLEAN = 1.0 / 3.0        # keep as clean color (like the untouched originals)
P_GRAYSCALE = 0.7
P_DARKEN = 0.6
P_LOWRES = 0.7
P_NOISE = 0.5
P_HFLIP = 0.5
# --------------------------------------------------------------------------


def read_yolo_boxes(txt_path: Path):
    """Return a list of (xc, yc, w, h) normalized floats."""
    boxes = []
    if not txt_path.exists():
        return boxes
    for line in txt_path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            _cls = int(float(parts[0]))
            xc, yc, w, h = (float(v) for v in parts[1:])
        except ValueError:
            continue
        boxes.append((xc, yc, w, h))
    return boxes


def rat_free_square(boxes, W, H):
    """Largest rat-free square as (left, top, side), or None.

    Any rat's left edge is >= union-left, so the strip left of the union box is
    guaranteed rat-free; same reasoning for right/top/bottom strips.
    """
    if not boxes:
        side = min(W, H)
        return ((W - side) // 2, (H - side) // 2, side)

    ux0, uy0, ux1, uy1 = float(W), float(H), 0.0, 0.0
    for xc, yc, w, h in boxes:
        ux0 = min(ux0, (xc - w / 2) * W - MARGIN)
        uy0 = min(uy0, (yc - h / 2) * H - MARGIN)
        ux1 = max(ux1, (xc + w / 2) * W + MARGIN)
        uy1 = max(uy1, (yc + h / 2) * H + MARGIN)
    ux0 = max(0.0, ux0); uy0 = max(0.0, uy0)
    ux1 = min(float(W), ux1); uy1 = min(float(H), uy1)

    candidates = [
        (0, 0, max(0.0, ux0), H),   # left strip
        (min(float(W), ux1), 0, W, H),  # right strip
        (0, 0, W, max(0.0, uy0)),   # top strip
        (0, min(float(H), uy1), W, H),  # bottom strip
    ]
    best = None
    for x0, y0, x1, y1 in candidates:
        rw, rh = x1 - x0, y1 - y0
        side = int(min(rw, rh))
        if side >= MIN_SIDE and (best is None or side > best[2]):
            cx0 = int(x0 + (rw - side) / 2)
            cy0 = int(y0 + (rh - side) / 2)
            best = (cx0, cy0, side)
    return best


def augment(im: Image.Image) -> Image.Image:
    """Apply the ESP32-CAM domain-randomization look to a background crop."""
    if random.random() < P_HFLIP:
        im = im.transpose(Image.FLIP_LEFT_RIGHT)
    if random.random() < P_GRAYSCALE:
        im = im.convert("L").convert("RGB")
    arr = np.asarray(im).astype(np.float32)
    if random.random() < P_DARKEN:
        gamma = random.uniform(1.3, 2.2)
        arr = 255.0 * (arr / 255.0) ** gamma
    if random.random() < P_NOISE:
        arr = arr + np.random.normal(0, random.uniform(4, 14), arr.shape)
    arr = np.clip(arr, 0, 255).astype(np.uint8)
    out = Image.fromarray(arr)
    if random.random() < P_LOWRES:
        w, h = out.size
        f = random.uniform(0.35, 0.6)
        out = out.resize((max(1, int(w * f)), max(1, int(h * f))), Image.BILINEAR)
        out = out.resize((w, h), Image.NEAREST)
    return out


def next_index(*dirs) -> int:
    mx = 0
    for d in dirs:
        for p in d.glob(f"{PREFIX}*.jpg"):
            s = p.stem[len(PREFIX):]
            if s.isdigit():
                mx = max(mx, int(s))
    return mx + 1


def load_labels(path: Path):
    if path.exists():
        data = json.loads(path.read_text())
        return data, data.get("boundingBoxes", {})
    return {"version": 1, "type": "bounding-box-labels", "boundingBoxes": {}}, {}


def main():
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    train_dir = CURATED_DIR / "training"
    test_dir = CURATED_DIR / "testing"
    for d in (train_dir, test_dir):
        d.mkdir(parents=True, exist_ok=True)

    train_data, train_bb = load_labels(train_dir / "bounding_boxes.labels")
    test_data, test_bb = load_labels(test_dir / "bounding_boxes.labels")
    if not train_bb:
        print("WARNING: no positives found in datasets/ei_curated/training - "
              "run curate_and_augment.py first.")

    imgs = sorted(IMAGES_DIR.glob("*.jpg"))
    random.shuffle(imgs)
    print(f"Scanning up to {len(imgs)} images for rat-free regions "
          f"(target {TARGET_BG})...")

    accepted_hashes = []
    crops = []
    for p in imgs:
        if len(crops) >= TARGET_BG:
            break
        boxes = read_yolo_boxes(LABELS_DIR / f"{p.stem}.txt")
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        W, H = im.size
        sq = rat_free_square(boxes, W, H)
        if sq is None:
            continue
        x0, y0, side = sq
        crop = im.crop((x0, y0, x0 + side, y0 + side))
        hsh = imagehash.phash(crop)
        if any((hsh - h) <= PHASH_THRESHOLD for h in accepted_hashes):
            continue
        accepted_hashes.append(hsh)
        crops.append(crop)
        if len(crops) % 100 == 0:
            print(f"  collected {len(crops)}/{TARGET_BG}")

    print(f"Collected {len(crops)} diverse rat-free backgrounds.")
    if not crops:
        print("No usable rat-free regions found. Lower MIN_SIDE and retry.")
        return

    random.shuffle(crops)
    n_train = int(len(crops) * TRAIN_RATIO)
    idx = next_index(train_dir, test_dir)
    added = {"training": 0, "testing": 0}

    for i, crop in enumerate(crops):
        if i < n_train:
            out_dir, bb, split = train_dir, train_bb, "training"
        else:
            out_dir, bb, split = test_dir, test_bb, "testing"
        out = crop if random.random() < P_CLEAN else augment(crop)
        name = f"{PREFIX}{idx:06d}.jpg"
        idx += 1
        out.save(out_dir / name, "JPEG", quality=JPEG_QUALITY)
        bb[name] = []                       # empty boxes = background sample
        added[split] += 1

    for data, bb in ((train_data, train_bb), (test_data, test_bb)):
        data["version"] = 1
        data["type"] = "bounding-box-labels"
        data["boundingBoxes"] = bb
    (train_dir / "bounding_boxes.labels").write_text(json.dumps(train_data))
    (test_dir / "bounding_boxes.labels").write_text(json.dumps(test_data))

    positives = sum(1 for k in list(train_bb) + list(test_bb)
                    if not k.startswith(PREFIX))
    backgrounds = sum(1 for k in list(train_bb) + list(test_bb)
                      if k.startswith(PREFIX))
    ratio = backgrounds / positives * 100 if positives else 0.0

    print("\nDone.")
    print(f"  Backgrounds added : training {added['training']}, "
          f"testing {added['testing']}")
    print(f"  Positives         : {positives}")
    print(f"  Backgrounds total : {backgrounds} ({ratio:.1f}% of positives)")
    if ratio < 10:
        print("  TIP: raise TARGET_BG for more (~10-20% recommended).")
    elif ratio > 30:
        print("  NOTE: >30% backgrounds can start to hurt recall.")
    print("\nNext steps:")
    print("  1) edge-impulse-uploader --directory datasets/ei_curated")
    print("     (only new bg_*.jpg upload; existing images skipped by hash)")
    print("  2) Studio -> Impulse -> Image -> Generate features")
    print("  3) Retrain, then Model testing to compare precision.")


if __name__ == "__main__":
    main()

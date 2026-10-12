"""
curate_and_augment.py

Builds a smaller, higher-quality training set that looks more like the real
ESP32-CAM feed, then packages it in Edge Impulse upload format.

Two problems it addresses:
  1. You have ~11,783 images -> too many/slow for FOMO, and many are near-dups
     of the same scene (which inflates validation and wastes training budget).
  2. Your images are color / bright / high-res, but the deployment camera is
     grayscale-ish, low-res and often dark (night/IR). This "domain gap" is a
     big reason the unseen test set scored lower than validation.

What it does:
  * CURATE: groups near-identical scenes with a perceptual hash and caps how
    many frames each scene contributes, then selects up to TARGET_COUNT images
    (optionally biased toward the grayscale-looking ones).
  * AUGMENT (domain randomization): for each selected image it emits the
    original plus AUG_PER_IMAGE variants that simulate the ESP32-CAM look
    (grayscale, darken/gamma, low-res pixelation, sensor noise, optional
    horizontal flip). Bounding boxes are carried over and flipped correctly.
  * EXPORT: writes <stem>.jpg + <stem>.json (Edge Impulse bounding-box format)
    into OUTPUT_DIR, ready to drag-and-drop into Edge Impulse Studio.

Requires: pillow, numpy, imagehash   (pip install pillow numpy imagehash)
"""

import json
import os
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageEnhance
import imagehash

# ----------------------------- configuration ------------------------------
IMAGES_DIR = Path("datasets/merged_dataset/images")
LABELS_DIR = Path("datasets/merged_dataset/labels")
OUTPUT_DIR = Path("datasets/ei_curated")
LABEL_NAME = "rat"

TARGET_COUNT = int(os.environ.get("TARGET_COUNT", "1800"))  # source images before augmenting
MAX_PER_SCENE = int(os.environ.get("MAX_PER_SCENE", "4"))    # near-duplicate cap per scene
PHASH_THRESHOLD = 8        # lower = stricter grouping of "same scene"
FAVOR_GRAYSCALE = True     # prefer images already close to the IR/grayscale look

# drop frames that are unrealistic for a single fixed camera
FILTER_COLLAGES = True     # skip stitched/collage frames (interior divider gutters)
MIN_ASPECT = 0.5           # skip very tall images (width/height below this)
MAX_ASPECT = 2.0           # skip very wide images (width/height above this)
COLLAGE_GUTTER_STD = 7.0   # a near-uniform interior line (low row/col std) = candidate
COLLAGE_SIDE_TEXTURE = 22.0  # ...only a real divider if textured content is on BOTH sides

AUG_PER_IMAGE = int(os.environ.get("AUG_PER_IMAGE", "2"))    # augmented copies per curated image
TRAIN_RATIO = 0.8          # source-level split; a source + its augs stay together
RANDOM_SEED = 42
JPEG_QUALITY = 90

# per-augmentation probabilities (each variant samples a random combination)
P_GRAYSCALE = 0.7
P_DARKEN = 0.6
P_LOWRES = 0.7
P_NOISE = 0.5
P_HFLIP = 0.5
# --------------------------------------------------------------------------


def read_yolo_boxes(txt_path: Path):
    """Return a list of (cls, xc, yc, w, h) normalized floats."""
    boxes = []
    if not txt_path.exists():
        return boxes
    for line in txt_path.read_text().splitlines():
        parts = line.split()
        if len(parts) != 5:
            continue
        try:
            cls = int(float(parts[0]))
            xc, yc, w, h = (float(v) for v in parts[1:])
        except ValueError:
            continue
        boxes.append((cls, xc, yc, w, h))
    return boxes


def yolo_to_ei(boxes, img_w, img_h, flipped=False):
    """Convert normalized YOLO boxes to Edge Impulse absolute-pixel boxes."""
    ei_boxes = []
    for _, xc, yc, w, h in boxes:
        if flipped:
            xc = 1.0 - xc
        x = (xc - w / 2.0) * img_w
        y = (yc - h / 2.0) * img_h
        bw = w * img_w
        bh = h * img_h
        # clamp to image bounds
        x = max(0, min(img_w - 1, x))
        y = max(0, min(img_h - 1, y))
        bw = max(1, min(img_w - x, bw))
        bh = max(1, min(img_h - y, bh))
        ei_boxes.append({
            "label": LABEL_NAME,
            "x": int(round(x)),
            "y": int(round(y)),
            "width": int(round(bw)),
            "height": int(round(bh)),
        })
    return ei_boxes


def grayscale_score(im: Image.Image) -> float:
    """Mean per-pixel channel spread. Lower = the image is already grayscale."""
    small = im.convert("RGB").resize((32, 32))
    arr = np.asarray(small).astype(np.int16)
    diff = (np.abs(arr[:, :, 0] - arr[:, :, 1]) +
            np.abs(arr[:, :, 0] - arr[:, :, 2]) +
            np.abs(arr[:, :, 1] - arr[:, :, 2]))
    return float(diff.mean())


def looks_like_collage(im: Image.Image) -> bool:
    """Flag stitched/collage frames by detecting an interior 'gutter': a
    near-uniform line that has textured content on BOTH sides (a divider between
    two panels). A plain sky or white studio background is uniform too, but its
    neighbouring lines are also uniform, so it is NOT flagged."""
    g = np.asarray(im.convert("L").resize((160, 160))).astype(np.float32)
    n = g.shape[0]
    lo, hi = int(n * 0.15), int(n * 0.85)

    def has_divider(line_std):
        for i in range(lo, hi):
            if line_std[i] < COLLAGE_GUTTER_STD:
                above = line_std[max(0, i - 12):max(1, i - 3)].mean()
                below = line_std[i + 3:i + 12].mean()
                if above > COLLAGE_SIDE_TEXTURE and below > COLLAGE_SIDE_TEXTURE:
                    return True
        return False

    return has_divider(g.std(axis=1)) or has_divider(g.std(axis=0))


def curate(paths):
    """Group by perceptual hash, cap per scene, optionally bias to grayscale."""
    print("Curating: hashing images and grouping scenes (this may take a bit)...")
    items = []
    skipped_collage = 0
    skipped_aspect = 0
    for p in paths:
        try:
            with Image.open(p) as im:
                im = im.convert("RGB")
                w, h = im.size
                ar = w / h if h else 0
                if ar < MIN_ASPECT or ar > MAX_ASPECT:
                    skipped_aspect += 1
                    continue
                if FILTER_COLLAGES and looks_like_collage(im):
                    skipped_collage += 1
                    continue
                ph = imagehash.phash(im)
                score = grayscale_score(im) if FAVOR_GRAYSCALE else 0.0
            items.append((p, ph, score))
        except Exception as e:  # noqa: BLE001 - report and skip bad files
            print(f"  skip {p.name}: {e}")

    print(f"  filtered out {skipped_collage} collage-like and "
          f"{skipped_aspect} extreme-aspect images")
    if not items:
        return []

    # sort by hash so near-identical scenes sit next to each other
    items.sort(key=lambda t: str(t[1]))
    groups = []
    cur = [items[0]]
    for i in range(1, len(items)):
        if (items[i][1] - items[i - 1][1]) < PHASH_THRESHOLD:
            cur.append(items[i])
        else:
            groups.append(cur)
            cur = [items[i]]
    groups.append(cur)
    print(f"  found {len(groups)} scene groups from {len(items)} images")

    # within each scene keep up to MAX_PER_SCENE (most grayscale first)
    selected = []
    for g in groups:
        g_sorted = sorted(g, key=lambda t: t[2])
        selected.extend(g_sorted[:MAX_PER_SCENE])

    random.shuffle(selected)
    if FAVOR_GRAYSCALE:
        selected.sort(key=lambda t: t[2])   # most grayscale first
    selected = selected[:TARGET_COUNT]
    print(f"  selected {len(selected)} images "
          f"(cap {MAX_PER_SCENE}/scene, target {TARGET_COUNT})")
    return [p for p, _, _ in selected]


def augment(im: Image.Image):
    """Apply a random domain-randomization combo. Returns (image, flipped)."""
    flipped = False
    out = im.convert("RGB")

    if random.random() < P_HFLIP:
        out = out.transpose(Image.FLIP_LEFT_RIGHT)
        flipped = True

    if random.random() < P_GRAYSCALE:
        out = out.convert("L").convert("RGB")        # keep 3 channels

    if random.random() < P_DARKEN:
        factor = random.uniform(0.35, 0.8)           # simulate night
        out = ImageEnhance.Brightness(out).enhance(factor)

    if random.random() < P_LOWRES:
        w, h = out.size
        scale = random.uniform(0.15, 0.4)            # simulate ESP32-CAM low-res
        small = out.resize((max(8, int(w * scale)), max(8, int(h * scale))),
                           Image.BILINEAR)
        out = small.resize((w, h), Image.BILINEAR)

    if random.random() < P_NOISE:
        arr = np.asarray(out).astype(np.int16)
        noise = np.random.normal(0, random.uniform(4, 14), arr.shape)
        arr = np.clip(arr + noise, 0, 255).astype(np.uint8)
        out = Image.fromarray(arr)

    return out, flipped


def save_variant(out_img, boxes_yolo, out_dir, stem, flipped, category):
    """Save one image and return its Edge Impulse label entry."""
    w, h = out_img.size
    out_img.save(out_dir / f"{stem}.jpg", "JPEG", quality=JPEG_QUALITY)
    return {
        "path": f"{stem}.jpg",
        "category": category,
        "boundingBoxes": yolo_to_ei(boxes_yolo, w, h, flipped=flipped),
    }


def main():
    random.seed(RANDOM_SEED)
    np.random.seed(RANDOM_SEED)

    if not IMAGES_DIR.is_dir():
        print(f"ERROR: {IMAGES_DIR.resolve()} not found")
        return

    all_imgs = sorted(p for p in IMAGES_DIR.glob("*.jpg")
                      if not p.stem.startswith("bg_"))
    if not all_imgs:
        print("No positive images found.")
        return

    chosen = curate(all_imgs)
    if not chosen:
        print("Nothing selected; check your dataset paths.")
        return

    random.shuffle(chosen)
    n_train = int(len(chosen) * TRAIN_RATIO)
    splits = [
        (chosen[:n_train], OUTPUT_DIR / "training", "training"),
        (chosen[n_train:], OUTPUT_DIR / "testing", "testing"),
    ]

    print("\nAugmenting + exporting to Edge Impulse object detection format...")
    grand_total = 0
    for srcs, out_dir, category in splits:
        out_dir.mkdir(parents=True, exist_ok=True)
        entries = []
        idx = 1
        for p in srcs:
            boxes = read_yolo_boxes(LABELS_DIR / f"{p.stem}.txt")
            try:
                base = Image.open(p).convert("RGB")
            except Exception as e:  # noqa: BLE001 - report and skip bad files
                print(f"  skip {p.name}: {e}")
                continue

            entries.append(save_variant(base, boxes, out_dir,
                                        f"cur_{idx:06d}", False, category))
            idx += 1
            for _ in range(AUG_PER_IMAGE):
                aug_img, flipped = augment(base)
                entries.append(save_variant(aug_img, boxes, out_dir,
                                            f"cur_{idx:06d}", flipped, category))
                idx += 1

        labels_path = out_dir / "bounding_boxes.labels"

        bboxes = {e["path"]: e["boundingBoxes"] for e in entries}
        labels_path.write_text(json.dumps(
            {"version": 1, "type": "bounding-box-labels",
             "boundingBoxes": bboxes}))
        grand_total += len(entries)
        print(f"  {category}: {len(entries)} images -> {labels_path}")

    print(f"\nDone. Wrote {grand_total} images to {OUTPUT_DIR.resolve()}")
    print("UPLOAD (use the Edge Impulse CLI, NOT the browser uploader):")
    print("  1. Dashboard > Project info: labeling method =")
    print("     'Bounding boxes (object detection)'.")
    print("  2. npm install -g edge-impulse-cli   (needs Node.js)")
    print(f"  3. edge-impulse-uploader --directory {OUTPUT_DIR}")
    print("     (reads training/ + testing/ bounding_boxes.labels, splits by")
    print("      folder name, attaches the rat boxes). Verify a sample shows a")
    print("      box and the labeling queue is 0.")
    print("Tip: also turn ON training augmentation in the FOMO block.")


if __name__ == "__main__":
    main()

"""
generate_object_negatives.py

Synthesize HARD-NEGATIVE images to fix the "anything I put in front of the
camera is detected as a rat" failure, WITHOUT needing real photos.

The model currently fires "rat" on ANY foreground object because it only ever
saw rats (foreground) vs an empty station (background). It learned
"foreground blob = rat" instead of "rat-shaped thing = rat".

This script pastes NON-rat "objects" (varied geometric / textured blobs, both
darker and lighter than the scene, with a soft shadow, random rotation and
size, some elongated like a spoon/stick) onto rat-free station crops, then
applies the ESP32-CAM look. Each image is labeled as BACKGROUND (empty boxes),
so the model learns "a foreground object is NOT automatically a rat".

Honest limitation: these are synthetic distractors. They break the shortcut and
reduce object false-positives a lot, but they are not a full substitute for real
photos of the specific objects. If one specific object still triggers in the
field, add a few real frames of THAT object as background later.

Writes neg_*.jpg + empty-box entries into datasets/ei_curated/{training,testing}.

Requires: pillow, numpy, imagehash
"""

import json
import math
import os
import random
from pathlib import Path

import numpy as np
from PIL import Image, ImageDraw, ImageFilter
import imagehash

# ----------------------------- configuration ------------------------------
IMAGES_DIR = Path("datasets/merged_dataset/images")
LABELS_DIR = Path("datasets/merged_dataset/labels")
CURATED_DIR = Path("datasets/ei_curated")
PREFIX = "neg_"

TARGET_NEG = int(os.environ.get("TARGET_NEG", "1000"))  # object-negatives to create
TRAIN_RATIO = 0.8          # split, same as the rest
MIN_SIDE = 140             # min side (px) of a usable rat-free square
MARGIN = 6                 # px kept away from any rat box
PHASH_THRESHOLD = 8        # dedup base scenes for diversity
OBJ_MIN = 1                # min objects pasted per image
OBJ_MAX = 3                # max objects pasted per image
RANDOM_SEED = 20260727     # changed so this run adds DIFFERENT negatives than before
JPEG_QUALITY = 90

# ESP32-CAM look applied AFTER pasting (same spirit as the other scripts)
P_GRAYSCALE = 0.75
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
    """Largest rat-free square as (left, top, side), or None. The strip beyond
    the union of all rat boxes (+margin) is guaranteed rat-free."""
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
        (0, 0, max(0.0, ux0), H),
        (min(float(W), ux1), 0, W, H),
        (0, 0, W, max(0.0, uy0)),
        (0, min(float(H), uy1), W, H),
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


def _shape_mask(size, shape):
    """White (255) filled shape on a black L-mask."""
    w, h = size
    m = Image.new("L", (w, h), 0)
    d = ImageDraw.Draw(m)
    if shape == "rect":
        d.rectangle([0, 0, w - 1, h - 1], fill=255)
    elif shape == "ellipse":
        d.ellipse([0, 0, w - 1, h - 1], fill=255)
    elif shape == "triangle":
        d.polygon([(w // 2, 0), (0, h - 1), (w - 1, h - 1)], fill=255)
    else:  # irregular polygon
        n = random.randint(5, 7)
        cx, cy, r = w / 2.0, h / 2.0, min(w, h) / 2.0
        pts = []
        for k in range(n):
            a = 2 * math.pi * k / n + random.uniform(-0.25, 0.25)
            rr = r * random.uniform(0.6, 1.0)
            pts.append((cx + rr * math.cos(a), cy + rr * math.sin(a)))
        d.polygon(pts, fill=255)
    return m


def _texture_patch(size, all_imgs):
    """A random image region resized to size (gives a realistic gray texture)."""
    for _ in range(5):
        p = random.choice(all_imgs)
        try:
            im = Image.open(p).convert("RGB")
        except Exception:
            continue
        W, H = im.size
        s = min(W, H)
        if s < 8:
            continue
        cs = random.randint(max(8, s // 4), max(9, s // 2))
        x = random.randint(0, W - cs)
        y = random.randint(0, H - cs)
        return im.crop((x, y, x + cs, y + cs)).resize(size)
    v = random.randint(0, 255)
    return Image.new("RGB", size, (v, v, v))


def _make_object(all_imgs, scene_side):
    """Build one RGBA distractor object (fill + shape), rotated."""
    base = int(scene_side * random.uniform(0.16, 0.5))
    base = max(10, base)
    if random.random() < 0.4:                       # elongated (spoon/stick)
        long_side = int(base * random.uniform(1.6, 3.0))
        thin = max(6, base // 2)
        size = (long_side, thin) if random.random() < 0.5 else (thin, long_side)
    else:
        size = (base, base)

    shape = random.choice(["rect", "ellipse", "triangle", "polygon"])
    mask = _shape_mask(size, shape)

    kind = random.random()
    w0, h0 = size
    if kind < 0.45:                                 # solid gray (dark or light)
        val = random.randint(0, 255)
        fill = Image.new("RGB", size, (val, val, val))
    elif kind < 0.70:                               # gradient
        a, b = random.randint(0, 255), random.randint(0, 255)
        if random.random() < 0.5:                   # horizontal gradient
            line = np.linspace(a, b, w0).astype(np.uint8)
            gray = np.repeat(line[None, :], h0, axis=0)      # (h0, w0)
        else:                                       # vertical gradient
            line = np.linspace(a, b, h0).astype(np.uint8)
            gray = np.repeat(line[:, None], w0, axis=1)      # (h0, w0)
        arr = np.stack([gray, gray, gray], axis=2)           # (h0, w0, 3)
        fill = Image.fromarray(arr)
    else:                                           # real texture patch
        fill = _texture_patch(size, all_imgs)

    obj = Image.new("RGBA", size, (0, 0, 0, 0))
    obj.paste(fill, (0, 0), mask)
    ang = random.uniform(0, 360)
    obj = obj.rotate(ang, expand=True, resample=Image.BILINEAR,
                     fillcolor=(0, 0, 0, 0))
    return obj


def paste_objects(base, all_imgs):
    """Paste 1..OBJ_MAX distractor objects (with shadows) onto a station crop."""
    scene = base.convert("RGBA")
    W, H = scene.size
    for _ in range(random.randint(OBJ_MIN, OBJ_MAX)):
        obj = _make_object(all_imgs, min(W, H))
        ow, oh = obj.size
        if ow >= W or oh >= H:
            f = min((W - 2) / ow, (H - 2) / oh)
            obj = obj.resize((max(1, int(ow * f)), max(1, int(oh * f))))
            ow, oh = obj.size
        px = random.randint(0, max(0, W - ow))
        py = random.randint(0, max(0, H - oh))

        # soft drop shadow grounds the object so it reads as "placed"
        alpha = obj.split()[3]
        off = int(min(W, H) * 0.02) + 2
        shadow = Image.new("RGBA", (W, H), (0, 0, 0, 0))
        shadow.paste((0, 0, 0, 130), (px + off, py + off), alpha)
        shadow = shadow.filter(ImageFilter.GaussianBlur(off))
        scene = Image.alpha_composite(scene, shadow)
        scene.paste(obj, (px, py), obj)
    return scene.convert("RGB")


def augment(im: Image.Image) -> Image.Image:
    """ESP32-CAM domain look on the finished negative image."""
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
        print("WARNING: no positives in ei_curated/training - run "
              "curate_and_augment.py first.")

    all_imgs = sorted(IMAGES_DIR.glob("*.jpg"))
    random.shuffle(all_imgs)
    print(f"Scanning up to {len(all_imgs)} images for rat-free scenes "
          f"(target {TARGET_NEG} object-negatives)...")

    accepted, scenes = [], []
    for p in all_imgs:
        if len(scenes) >= TARGET_NEG:
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
        if any((hsh - a) <= PHASH_THRESHOLD for a in accepted):
            continue
        accepted.append(hsh)
        scenes.append(crop)
        if len(scenes) % 50 == 0:
            print(f"  collected {len(scenes)}/{TARGET_NEG}")

    print(f"Collected {len(scenes)} base scenes.")
    if not scenes:
        print("No usable rat-free regions found. Lower MIN_SIDE and retry.")
        return

    random.shuffle(scenes)
    n_train = int(len(scenes) * TRAIN_RATIO)
    idx = next_index(train_dir, test_dir)
    added = {"training": 0, "testing": 0}

    for i, crop in enumerate(scenes):
        if i < n_train:
            out_dir, bb, split = train_dir, train_bb, "training"
        else:
            out_dir, bb, split = test_dir, test_bb, "testing"
        composed = paste_objects(crop, all_imgs)
        out = augment(composed)
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

    positives = sum(1 for v in list(train_bb.values()) + list(test_bb.values())
                    if len(v) > 0)
    negatives = sum(1 for v in list(train_bb.values()) + list(test_bb.values())
                    if len(v) == 0)
    ratio = negatives / positives * 100 if positives else 0.0

    print("\nDone.")
    print(f"  Object-negatives added : training {added['training']}, "
          f"testing {added['testing']}")
    print(f"  Positives (with boxes) : {positives}")
    print(f"  All negatives (empty)  : {negatives} ({ratio:.1f}% of positives)")
    print("\nNext steps:")
    print("  1) (optional) preview a few neg_*.jpg to sanity-check")
    print("  2) wipe the Edge Impulse project data, then")
    print("     edge-impulse-uploader --directory datasets/ei_curated")
    print("  3) Generate features, retrain (aug ON), Model testing.")


if __name__ == "__main__":
    main()

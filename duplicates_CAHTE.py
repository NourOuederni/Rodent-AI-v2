"""
dedupe_by_label_area_ssim.py

Compares the CROPPED LABELED REGION of each image (not the whole picture)
to find duplicates -- catches cases where the same subject was annotated
in two different images with different backgrounds/crops, lighting,
color, or compression around it.

PIPELINE:

    Load images + crop labeled boxes
       |
    CLAHE-normalize each crop (neutralizes lighting/color/compression)
       |
    Compute pHash of the NORMALIZED crop
       |
    Group images with similar crop-hashes (loose threshold, candidate filter)
       |
    Within each group: confirm with SSIM (strict, pixel-level) OR
    ORB keypoint matching + RANSAC (tolerant of shift/scale/rotation)
       |
    Write a manifest + contact sheets, THEN move confirmed duplicates

HOW A MATCH IS DECIDED (two things must be true):
  1. Same number of boxes, and each box's normalized AREA (w*h) matches
     within AREA_TOLERANCE -- cheap filter, checked first.
  2. Each box's cropped CONTENT matches via SSIM at CONTENT_THRESHOLD,
     OR via ORB+RANSAC geometric matching -- catches cases SSIM misses
     (crop shift, brightness/color shift, slight rotation) without
     losing SSIM's precision on true near-pixel matches.

SAFETY: confirmed duplicates (image + label) are MOVED to a review
folder, nothing is deleted. A manifest.json + contact sheet image are
written per group BEFORE anything is moved, so every match can be
verified visually (with its SSIM score / ORB inlier count) instead of
by eye alone.

Usage:
    pip install pillow numpy scikit-image imagehash opencv-python-headless --break-system-packages
    python dedupe_by_label_area_ssim.py
"""

import json
import shutil
import sys
from pathlib import Path

import cv2
import numpy as np
from PIL import Image, ImageDraw
from skimage.metrics import structural_similarity as ssim
import imagehash

MERGED_DIR = "datasets/merged_dataset"
REVIEW_DIR = "datasets/duplicates_by_label_review_ssim"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# How close two normalized box areas (w*h, both already 0-1) need to be to
# even bother comparing pixel content. 0.02 = within 2% relative difference.
AREA_TOLERANCE = 0.02

# Stage 1 (pHash on the CLAHE-normalized crop) -- loose candidate filter.
HASH_SIZE = 8  # 8x8 = 64-bit hash
HASH_GROUP_THRESHOLD = 10  # loosened vs raw-pixel hashing to give matching margin

# Stage 2a (SSIM on the normalized crop) -- strict final confirmation
# (-1 to 1, 1.0 = structurally identical).
CONTENT_THRESHOLD = 0.99

# Stage 2b (ORB + RANSAC) -- geometric confirmation, tolerant of crop
# shift, scale, rotation, and brightness changes that SSIM is not.
ORB_N_FEATURES = 500
ORB_MIN_GOOD_MATCHES = 8      # min Lowe-ratio-passing matches before trying homography
ORB_MIN_INLIERS = 10          # min RANSAC inliers to call it a match
ORB_MIN_INLIER_RATIO = 0.6    # inliers / good matches

# Crops are resized to this fixed size for pHash/SSIM/ORB, since box crops
# naturally come out at different pixel sizes.
COMPARE_SIZE = (128, 128)

_clahe = cv2.createCLAHE(clipLimit=2.0, tileGridSize=(8, 8))
_orb = cv2.ORB_create(nfeatures=ORB_N_FEATURES)
_bf = cv2.BFMatcher(cv2.NORM_HAMMING)


def parse_boxes(label_path: Path):
    """Return list of (class_id, x_center, y_center, w, h), all normalized
    0-1, from a YOLO .txt label file."""
    boxes = []
    if not label_path.exists():
        return boxes
    for line in label_path.read_text().splitlines():
        parts = line.strip().split()
        if len(parts) < 5:
            continue
        class_id, xc, yc, w, h = parts[:5]
        boxes.append((int(class_id), float(xc), float(yc), float(w), float(h)))
    return boxes


def crop_box(im: Image.Image, xc, yc, w, h):
    """Crop a normalized YOLO box out of a PIL image. Computes pixel
    width/height first, then derives left/top from the center and that
    fixed size (rather than rounding all four edges independently) --
    otherwise two boxes with identical normalized w/h can end up 1px
    different in size after rounding, throwing off the comparison."""
    img_w, img_h = im.size
    box_w = round(w * img_w)
    box_h = round(h * img_h)
    center_x = round(xc * img_w)
    center_y = round(yc * img_h)

    left = max(0, center_x - box_w // 2)
    top = max(0, center_y - box_h // 2)
    right = min(img_w, left + box_w)
    bottom = min(img_h, top + box_h)

    if right <= left or bottom <= top:
        return None
    return im.crop((left, top, right, bottom))


def normalize_gray(crop: Image.Image) -> np.ndarray:
    """Grayscale + resize + CLAHE contrast normalization. This neutralizes
    lighting/color/compression differences BEFORE hashing, SSIM, or ORB
    ever see the crop, so all three stages compare on a level footing."""
    gray = np.array(crop.convert("L").resize(COMPARE_SIZE, Image.LANCZOS), dtype=np.uint8)
    return _clahe.apply(gray)


def build_box_records(images_dir: Path, labels_dir: Path):
    """
    For every image that has a label file, crop out each box, CLAHE-
    normalize it, and compute its pHash (stage 1), normalized grayscale
    array (stage 2a/SSIM), and ORB keypoints+descriptors (stage 2b).
    Returns {img_path: [(area, hash_int, norm_gray, keypoints, descriptors), ...]}
    sorted by area descending per image.
    """
    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    total = len(image_paths)
    print(f"Cropping + normalizing labeled regions for {total} images...\n")

    records = {}
    for i, img_path in enumerate(image_paths, start=1):
        label_path = labels_dir / f"{img_path.stem}.txt"
        boxes = parse_boxes(label_path)
        if not boxes:
            continue

        try:
            with Image.open(img_path) as im:
                im = im.convert("RGB")
                box_records = []
                for (_cls, xc, yc, w, h) in boxes:
                    crop = crop_box(im, xc, yc, w, h)
                    if crop is None:
                        continue
                    area = w * h
                    norm_gray = normalize_gray(crop)
                    h_hash = int(str(imagehash.phash(Image.fromarray(norm_gray), hash_size=HASH_SIZE)), 16)
                    keypoints, descriptors = _orb.detectAndCompute(norm_gray, None)
                    box_records.append((area, h_hash, norm_gray, keypoints, descriptors))
                box_records.sort(key=lambda r: r[0], reverse=True)
                if box_records:
                    records[img_path] = box_records
        except Exception as e:
            print(f"\n[WARNING] Could not process {img_path.name}: {e}")

        pct = i / total * 100 if total else 100
        sys.stdout.write(f"\r  processed {i}/{total} ({pct:.1f}%)")
        sys.stdout.flush()

    print()  # newline after progress line
    return records


def group_by_hash(records: dict, threshold: int):
    """
    Stage 1: cheap candidate filter, using the LARGEST box's pHash per
    image (the main subject) as a representative signature. Vectorized
    with numpy in row blocks. Deliberately loose (high recall) -- the
    final area + SSIM/ORB check happens in stage 2.
    """
    paths = list(records.keys())
    n = len(paths)
    hash_array = np.array([records[p][0][1] for p in paths], dtype=np.uint64)
    parent = list(range(n))

    def find(x):
        while parent[x] != x:
            parent[x] = parent[parent[x]]
            x = parent[x]
        return x

    def union(a, b):
        ra, rb = find(a), find(b)
        if ra != rb:
            parent[ra] = rb

    print(f"\nGrouping {n} images by similar crop pHash (candidate threshold={threshold})...\n")

    block_size = 500
    for start in range(0, n, block_size):
        end = min(start + block_size, n)
        block = hash_array[start:end]
        xor = block[:, None] ^ hash_array[None, :]
        dist = np.unpackbits(xor.view(np.uint8), axis=-1).reshape(xor.shape[0], xor.shape[1], -1).sum(axis=-1)

        for local_i in range(end - start):
            global_i = start + local_i
            close = np.where(dist[local_i] <= threshold)[0]
            for j in close:
                if j != global_i:
                    union(global_i, int(j))

        pct = end / n * 100 if n else 100
        sys.stdout.write(f"\r  grouped {end}/{n} ({pct:.1f}%)")
        sys.stdout.flush()

    print()  # newline after progress line

    groups = {}
    for i in range(n):
        root = find(i)
        groups.setdefault(root, []).append(paths[i])

    return [g for g in groups.values() if len(g) > 1]


def orb_match(kp1, desc1, kp2, desc2):
    """Match ORB descriptors with a Lowe ratio test, then verify the match
    geometrically with RANSAC homography. Tolerant of crop shift, scale,
    rotation, and brightness differences that raw SSIM is not.
    Returns (matched: bool, inlier_count: int, good_match_count: int)."""
    if desc1 is None or desc2 is None or len(desc1) < 2 or len(desc2) < 2:
        return False, 0, 0

    raw_matches = _bf.knnMatch(desc1, desc2, k=2)
    good = [m for m, n in raw_matches if m.distance < 0.75 * n.distance]

    if len(good) < ORB_MIN_GOOD_MATCHES:
        return False, 0, len(good)

    src_pts = np.float32([kp1[m.queryIdx].pt for m in good]).reshape(-1, 1, 2)
    dst_pts = np.float32([kp2[m.trainIdx].pt for m in good]).reshape(-1, 1, 2)

    _, mask = cv2.findHomography(src_pts, dst_pts, cv2.RANSAC, 5.0)
    if mask is None:
        return False, 0, len(good)

    inliers = int(mask.sum())
    inlier_ratio = inliers / len(good)
    matched = inliers >= ORB_MIN_INLIERS and inlier_ratio >= ORB_MIN_INLIER_RATIO
    return matched, inliers, len(good)


def compare_boxes(box_a, box_b):
    """Compare one box pair. Returns a dict with the match decision plus
    evidence (SSIM score / ORB inlier count) -- used both to decide the
    match and to annotate the contact sheet / manifest for visual review."""
    area_a, _hash_a, gray_a, kp_a, desc_a = box_a
    area_b, _hash_b, gray_b, kp_b, desc_b = box_b

    result = {"matched": False, "method": None, "ssim": None,
              "orb_inliers": None, "orb_good_matches": None}

    if area_a == 0 or area_b == 0:
        return result
    if abs(area_a - area_b) / max(area_a, area_b) > AREA_TOLERANCE:
        return result

    score = float(ssim(gray_a, gray_b))
    result["ssim"] = round(score, 4)
    if score >= CONTENT_THRESHOLD:
        result["matched"] = True
        result["method"] = "ssim"
        return result

    orb_matched, inliers, good = orb_match(kp_a, desc_a, kp_b, desc_b)
    result["orb_inliers"] = inliers
    result["orb_good_matches"] = good
    if orb_matched:
        result["matched"] = True
        result["method"] = "orb"
    return result


def boxes_match(boxes_a, boxes_b):
    """True (+ per-box evidence) only if EVERY box pairs up within
    AREA_TOLERANCE and is confirmed by SSIM or ORB+RANSAC."""
    if len(boxes_a) != len(boxes_b):
        return False, []
    evidence = []
    for box_a, box_b in zip(boxes_a, boxes_b):
        result = compare_boxes(box_a, box_b)
        if not result["matched"]:
            return False, []
        evidence.append(result)
    return True, evidence


def confirm_matches(candidate_groups, records: dict):
    """
    Stage 2: within each pHash candidate group, confirm true duplicates
    using boxes_match() (area + per-box SSIM/ORB). Uses greedy
    cluster-representative matching (compare each image only against
    existing cluster representatives, not every pair) to stay fast.
    Every candidate group is processed, regardless of size.
    Returns a list of clusters: {"paths": [...], "evidence": {path: [...]}}
    """
    total_candidates = sum(len(g) for g in candidate_groups)
    print(f"\nConfirming {len(candidate_groups)} candidate group(s) "
          f"({total_candidates} images total) with SSIM + ORB...\n")

    confirmed = []
    checked = 0
    for group in candidate_groups:
        clusters = []  # each: {"paths": [rep, ...], "evidence": {path: evidence_list}}

        for p in group:
            placed = False
            for cluster in clusters:
                rep = cluster["paths"][0]
                matched, evidence = boxes_match(records[rep], records[p])
                if matched:
                    cluster["paths"].append(p)
                    cluster["evidence"][p] = evidence
                    placed = True
                    break
            if not placed:
                clusters.append({"paths": [p], "evidence": {}})

            checked += 1
            if checked % 5 == 0 or checked == total_candidates:
                pct = checked / total_candidates * 100 if total_candidates else 100
                sys.stdout.write(f"\r  confirmed {checked}/{total_candidates} candidate images ({pct:.1f}%)")
                sys.stdout.flush()

        confirmed.extend(c for c in clusters if len(c["paths"]) > 1)

    print()  # newline after progress line
    return confirmed


def build_contact_sheet(cluster, images_dir: Path, out_path: Path):
    """Render a duplicate group as a row of side-by-side thumbnails, each
    labeled with filename + match evidence, so a group can be verified
    visually instead of by eye alone."""
    paths = cluster["paths"]
    thumb_size = 200
    padding = 10
    label_h = 80
    width = len(paths) * (thumb_size + padding) + padding
    height = thumb_size + label_h + padding * 2
    sheet = Image.new("RGB", (width, height), "white")
    draw = ImageDraw.Draw(sheet)

    for i, p in enumerate(paths):
        x = padding + i * (thumb_size + padding)
        try:
            with Image.open(images_dir / p.name) as im:
                im = im.convert("RGB")
                im.thumbnail((thumb_size, thumb_size))
                sheet.paste(im, (x, padding))
        except Exception:
            pass

        if i == 0:
            label = f"{p.name}\n(kept)"
        else:
            ev = cluster["evidence"].get(p, [])
            parts = []
            for box_i, e in enumerate(ev):
                if e["method"] == "ssim":
                    parts.append(f"box{box_i}: SSIM {e['ssim']}")
                elif e["method"] == "orb":
                    parts.append(f"box{box_i}: ORB {e['orb_inliers']}in/{e['orb_good_matches']}m")
            label = f"{p.name}\n" + "\n".join(parts)

        draw.multiline_text((x, thumb_size + padding + 5), label, fill="black")

    sheet.save(out_path)


def main():
    images_dir = Path(MERGED_DIR) / "images"
    labels_dir = Path(MERGED_DIR) / "labels"

    out_dir = Path(REVIEW_DIR)
    out_images = out_dir / "images"
    out_labels = out_dir / "labels"
    contact_sheets_dir = out_dir / "contact_sheets"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)
    contact_sheets_dir.mkdir(parents=True, exist_ok=True)

    records = build_box_records(images_dir, labels_dir)

    if len(records) < 2:
        print("\nNot enough labeled images to compare.")
        return

    candidate_groups = group_by_hash(records, HASH_GROUP_THRESHOLD)
    group_sizes = sorted((len(g) for g in candidate_groups), reverse=True)
    print(f"\nFound {len(candidate_groups)} candidate group(s) from pHash pre-filter.")
    if group_sizes:
        print(f"  Largest candidate group: {group_sizes[0]} images")
        print(f"  Top 5 group sizes:       {group_sizes[:5]}")

    clusters = confirm_matches(candidate_groups, records) if candidate_groups else []

    print(f"\nFound {len(clusters)} duplicate group(s).\n")

    manifest = []
    moved_images = 0
    for group_num, cluster in enumerate(clusters, start=1):
        cluster["paths"].sort(key=lambda p: p.name)
        keeper = cluster["paths"][0]
        losers = cluster["paths"][1:]

        print(f"  [group {group_num}] keeping {keeper.name}, moving {len(losers)} duplicate(s): "
              f"{', '.join(p.name for p in losers)}")

        sheet_path = contact_sheets_dir / f"group_{group_num:04d}.jpg"
        build_contact_sheet(cluster, images_dir, sheet_path)

        manifest.append({
            "group": group_num,
            "kept": keeper.name,
            "moved": [
                {"file": p.name, "evidence": cluster["evidence"].get(p, [])}
                for p in losers
            ],
            "contact_sheet": str(sheet_path.relative_to(out_dir)),
        })

        for img_path in losers:
            dst_img = out_images / img_path.name
            shutil.move(str(img_path), str(dst_img))

            label_path = labels_dir / f"{img_path.stem}.txt"
            if label_path.exists():
                shutil.move(str(label_path), str(out_labels / label_path.name))

            moved_images += 1

    (out_dir / "manifest.json").write_text(json.dumps(manifest, indent=2))

    remaining_images = sum(1 for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)

    print("\nDone.")
    print(f"  Duplicate groups found:     {len(clusters)}")
    print(f"  Images removed (moved out): {moved_images}")
    print(f"  Images remaining in merged: {remaining_images}")
    print(f"  Review folder:              {out_dir.resolve()}")
    print(f"  Contact sheets:             {contact_sheets_dir.resolve()}")
    print(f"  Manifest (match evidence):  {(out_dir / 'manifest.json').resolve()}")
    print("\nNothing was deleted. Open the contact sheets in the review folder to")
    print("verify matches visually (SSIM score / ORB inlier count shown per box)")
    print("before deleting the review folder for good. If any group was wrongly")
    print("matched, move those specific files back into merged_dataset/images")
    print("and .../labels.")


if __name__ == "__main__":
    main()
import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
import imagehash

MERGED_DIR = "datasets/merged_dataset"
REVIEW_DIR = "datasets/duplicates_by_label_review_ssim"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# How close two normalized box areas (w*h, both already 0-1) need to be to
# even bother comparing pixel content. 0.02 = within 2% relative difference.
AREA_TOLERANCE = 0.02

# Stage 1 (pHash on the crop) -- loose candidate filter.
HASH_SIZE = 8  # 8x8 = 64-bit hash
HASH_GROUP_THRESHOLD = 6

# Stage 2 (SSIM on the crop) -- strict final confirmation (-1 to 1, 1.0 =
# structurally identical).
CONTENT_THRESHOLD = 0.99

# Crops are resized to this fixed size for both the pHash and the SSIM
# comparison, since box crops naturally come out at different pixel sizes.
COMPARE_SIZE = (128, 128)


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


def build_box_records(images_dir: Path, labels_dir: Path):
    """
    For every image that has a label file, crop out each box and compute
    BOTH its pHash (stage 1) and its resized grayscale array (stage 2).
    Returns {img_path: [(area, hash_int, gray_array), ...]} sorted by area
    descending per image.
    """
    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    total = len(image_paths)
    print(f"Cropping labeled regions for {total} images...\n")

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
                    h_hash = int(str(imagehash.phash(crop, hash_size=HASH_SIZE)), 16)
                    gray = crop.convert("L").resize(COMPARE_SIZE, Image.LANCZOS)
                    gray_array = np.array(gray, dtype=np.uint8)
                    box_records.append((area, h_hash, gray_array))
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
    final box-by-box area + SSIM check happens in stage 2.
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


def boxes_match(boxes_a, boxes_b):
    """True if two images' box lists are the same length and every box
    pairs up (by descending area order) within AREA_TOLERANCE and passes
    SSIM at CONTENT_THRESHOLD."""
    if len(boxes_a) != len(boxes_b):
        return False
    for (area_a, _hash_a, gray_a), (area_b, _hash_b, gray_b) in zip(boxes_a, boxes_b):
        if area_a == 0 or area_b == 0:
            return False
        relative_diff = abs(area_a - area_b) / max(area_a, area_b)
        if relative_diff > AREA_TOLERANCE:
            return False
        score = ssim(gray_a, gray_b)
        if score < CONTENT_THRESHOLD:
            return False
    return True


def confirm_with_ssim(candidate_groups, records: dict):
    """
    Stage 2: within each pHash candidate group, confirm true duplicates
    using boxes_match() (area + per-box SSIM). Uses greedy
    cluster-representative matching (compare each image only against
    existing cluster representatives, not every pair) to stay fast, with
    per-image progress reporting. Every candidate group is processed here,
    regardless of size.
    """
    total_candidates = sum(len(g) for g in candidate_groups)
    print(f"\nConfirming {len(candidate_groups)} candidate group(s) "
          f"({total_candidates} images total) with SSIM (threshold={CONTENT_THRESHOLD})...\n")

    confirmed_groups = []
    checked = 0
    for group in candidate_groups:
        clusters = []  # list of lists of paths; clusters[i][0] is the representative

        for p in group:
            placed = False
            for cluster in clusters:
                if boxes_match(records[cluster[0]], records[p]):
                    cluster.append(p)
                    placed = True
                    break
            if not placed:
                clusters.append([p])

            checked += 1
            if checked % 5 == 0 or checked == total_candidates:
                pct = checked / total_candidates * 100 if total_candidates else 100
                sys.stdout.write(f"\r  confirmed {checked}/{total_candidates} candidate images ({pct:.1f}%)")
                sys.stdout.flush()

        confirmed_groups.extend(c for c in clusters if len(c) > 1)

    print()  # newline after progress line
    return confirmed_groups


def main():
    images_dir = Path(MERGED_DIR) / "images"
    labels_dir = Path(MERGED_DIR) / "labels"

    out_dir = Path(REVIEW_DIR)
    out_images = out_dir / "images"
    out_labels = out_dir / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

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

    if not candidate_groups:
        groups = []
    else:
        groups = confirm_with_ssim(candidate_groups, records)

    print(f"\nFound {len(groups)} duplicate group(s).\n")

    moved_images = 0
    for group_num, group in enumerate(groups, start=1):
        group_sorted = sorted(group, key=lambda p: p.name)
        keeper = group_sorted[0]
        losers = group_sorted[1:]

        print(f"  [group {group_num}] keeping {keeper.name}, moving {len(losers)} duplicate(s): "
              f"{', '.join(p.name for p in losers)}")

        for img_path in losers:
            dst_img = out_images / img_path.name
            shutil.move(str(img_path), str(dst_img))

            label_path = labels_dir / f"{img_path.stem}.txt"
            if label_path.exists():
                shutil.move(str(label_path), str(out_labels / label_path.name))

            moved_images += 1

    remaining_images = sum(1 for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)

    print("\nDone.")
    print(f"  Duplicate groups found:     {len(groups)}")
    print(f"  Images removed (moved out): {moved_images}")
    print(f"  Images remaining in merged: {remaining_images}")
    print(f"  Review folder:              {out_dir.resolve()}")
    print("\nNothing was deleted. Check the review folder -- if the moved images")
    print("really are unwanted duplicates, delete that folder. If any group was")
    print("wrongly matched, move those specific files back into")
    print("merged_dataset/images and .../labels.")


if __name__ == "__main__":
    main()
"""
dedupe_images_ssim.py

Compares the FULL, UNCROPPED image (not just the labeled box region) to
find duplicate / near-duplicate images in the merged dataset. Confirmed
duplicates (image + label) are moved to a review folder -- nothing is
deleted.

WHY TWO STAGES:
Running SSIM on every possible PAIR of images is O(n^2) and each individual
comparison is fairly expensive -- on a few thousand images that's millions
of SSIM calls, which is why the plain SSIM-only version of this script was
slow. This version fixes that with a two-stage pipeline:

    1. Load images
    2. Compute a pHash (perceptual hash) for every image -- cheap, fast
    3. Group images with SIMILAR hashes (loose threshold, high recall --
       this is just a candidate filter, not the final decision)
    4. Run SSIM only INSIDE each candidate group, to confirm which of the
       candidates are actually true duplicates (strict threshold, high
       precision)

pHash alone can be fooled by genuinely different images that happen to
hash similarly (rare, but possible), so SSIM still makes the final call --
it's just no longer being run on every pair in the whole dataset, only on
the much smaller set of images that already look close by hash. This
keeps the expensive comparison scoped to where it's actually needed.

HASH_GROUP_THRESHOLD = 10 (Hamming distance, out of 64 bits): deliberately
loose. Its only job is to make sure real duplicates aren't missed before
SSIM gets a chance to look at them -- a few unrelated images ending up in
the same candidate group is fine and cheap, since SSIM filters those back
out in the next step.

CONTENT_THRESHOLD = 0.99 (SSIM, -1 to 1 range, 1.0 = structurally
identical): this is the strict, final decision. Only images that are
essentially the same picture will be confirmed as duplicates. Lower it
slightly (e.g. 0.95) if real duplicates are being missed at the SSIM stage.

SAFETY: nothing is deleted. Duplicates are MOVED to a review folder so you
can double check before permanently removing them.

Usage:
    pip install pillow numpy scikit-image imagehash --break-system-packages
    python dedupe_images_ssim.py
"""

import shutil
import sys
from pathlib import Path

import numpy as np
from PIL import Image
from skimage.metrics import structural_similarity as ssim
import imagehash

MERGED_DIR = "datasets/merged_dataset"
REVIEW_DIR = "datasets/duplicates_review_ssim_merged"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# Stage 1 (pHash) -- loose candidate filter. See explanation above.
HASH_SIZE = 8  # 8x8 = 64-bit hash
HASH_GROUP_THRESHOLD = 10

# Stage 2 (SSIM) -- strict final confirmation. See explanation above.
CONTENT_THRESHOLD = 0.99

# Every image is resized to this fixed size before SSIM comparison, so SSIM
# can compare them (needs matching shapes) and comparison stays fast.
COMPARE_SIZE = (128, 128)


def build_records(images_dir: Path):
    """
    Load every image once, computing BOTH its pHash (for the fast stage-1
    candidate filter) and its resized grayscale array (for the stage-2 SSIM
    confirmation, done later only within candidate groups). Progress shown
    since this touches every file.
    """
    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    total = len(image_paths)
    print(f"Loading {total} images and computing pHashes...\n")

    hashes = {}
    grays = {}
    for i, img_path in enumerate(image_paths, start=1):
        try:
            with Image.open(img_path) as im:
                im_rgb = im.convert("RGB")
                hashes[img_path] = int(str(imagehash.phash(im_rgb, hash_size=HASH_SIZE)), 16)
                gray = im_rgb.convert("L").resize(COMPARE_SIZE, Image.LANCZOS)
                grays[img_path] = np.array(gray, dtype=np.uint8)
        except Exception as e:
            print(f"\n[WARNING] Could not load {img_path.name}: {e}")

        pct = i / total * 100 if total else 100
        sys.stdout.write(f"\r  loaded {i}/{total} ({pct:.1f}%)")
        sys.stdout.flush()

    print()  # newline after progress line
    return hashes, grays


def group_by_hash(hashes: dict, threshold: int):
    """
    Stage 1: cheap candidate filter. Groups images whose pHash is within
    `threshold` Hamming-distance bits of each other. Vectorized with numpy
    in row blocks so it stays fast even on a few thousand images. This is
    deliberately loose (high recall) -- SSIM makes the final call afterward.
    """
    paths = list(hashes.keys())
    n = len(paths)
    hash_array = np.array([hashes[p] for p in paths], dtype=np.uint64)
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

    print(f"\nGrouping {n} images by similar pHash (candidate threshold={threshold})...\n")

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


def crops_match(image_a: np.ndarray, image_b: np.ndarray) -> bool:
    """
    Compare two (whole, uncropped) images using SSIM. If the score is below
    CONTENT_THRESHOLD, they're NOT considered the same content.
    """
    score = ssim(image_a, image_b)
    if score < CONTENT_THRESHOLD:
        return False
    return True


def confirm_with_ssim(candidate_groups, grays: dict):
    """
    Stage 2: within each pHash candidate group (usually small), run pairwise
    SSIM to confirm true duplicates. A candidate group can split into
    multiple confirmed groups, or shrink if some members turn out not to
    really match. Returns the final list of confirmed duplicate groups.
    """
    total_candidates = sum(len(g) for g in candidate_groups)
    print(f"\nConfirming {len(candidate_groups)} candidate group(s) "
          f"({total_candidates} images total) with SSIM (threshold={CONTENT_THRESHOLD})...\n")

    confirmed_groups = []
    checked = 0
    for group in candidate_groups:
        parent = {p: p for p in group}

        def find(x):
            while parent[x] != x:
                parent[x] = parent[parent[x]]
                x = parent[x]
            return x

        def union(a, b):
            ra, rb = find(a), find(b)
            if ra != rb:
                parent[ra] = rb

        for i in range(len(group)):
            for j in range(i + 1, len(group)):
                p1, p2 = group[i], group[j]
                if crops_match(grays[p1], grays[p2]):
                    union(p1, p2)

        sub_groups = {}
        for p in group:
            root = find(p)
            sub_groups.setdefault(root, []).append(p)

        confirmed_groups.extend(g for g in sub_groups.values() if len(g) > 1)

        checked += len(group)
        pct = checked / total_candidates * 100 if total_candidates else 100
        sys.stdout.write(f"\r  confirmed {checked}/{total_candidates} candidate images ({pct:.1f}%)")
        sys.stdout.flush()

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

    hashes, grays = build_records(images_dir)

    if len(hashes) < 2:
        print("\nNot enough images to compare.")
        return

    candidate_groups = group_by_hash(hashes, HASH_GROUP_THRESHOLD)
    print(f"\nFound {len(candidate_groups)} candidate group(s) from pHash pre-filter.")

    if not candidate_groups:
        groups = []
    else:
        groups = confirm_with_ssim(candidate_groups, grays)

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
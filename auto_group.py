"""
auto_group.py

Automatically groups your rodent images by "same background / same camera
spot" so you don't have to sort them by hand. It then writes them into
subfolders (group_0001/, group_0002/, ..., singles/) that plug directly
into extract_backgrounds.py.

Expects your dataset laid out as:

    datasets/merged_dataset/
        images/
            img001.jpg
            img002.jpg
            ...
        labels/
            img001.txt
            img002.txt
            ...

Every image and its matching label file (same filename stem) are copied
together -- COPIED, never moved, so your original merged_dataset is left
completely untouched. Output structure mirrors the input:

    grouped/
        group_0001/
            images/img001.jpg  images/img014.jpg  ...
            labels/img001.txt  labels/img014.txt  ...
        group_0002/
            images/...
            labels/...
        singles/
            images/...
            labels/...

If an image has no matching label file, the image is still copied and a
warning is printed -- it just won't have a label counterpart in the output.

HOW IT WORKS
------------
1. Coarse pass: compute a perceptual hash (phash) of each image after
   masking out the center region (where a rat is most likely to be) so the
   rat itself doesn't distort the hash. Images with near-identical
   backgrounds get near-identical hashes even though the rat differs.
2. Cluster images whose hashes are within a small Hamming-distance
   threshold of each other (union-find), since two images can be "linked"
   through a chain of similar images even if the first and last look a
   bit different (e.g. lighting drifted slightly over a session).
3. Refine with ORB keypoint matching within each coarse cluster to filter
   out false positives (two unrelated but visually similar scenes, e.g.
   two different plain dirt patches).
4. Any image that doesn't cluster with at least MIN_GROUP_SIZE-1 others
   goes into singles/.

This is a heuristic, not ground truth -- spot check a few groups afterward.
Adjust HASH_THRESHOLD (looser/tighter) and ORB_MIN_INLIERS if groups look
wrong (too broad = merging different locations; too narrow = splitting the
same location into many tiny groups).

------------------------------------------------------------------------
SETUP
------------------------------------------------------------------------
pip install opencv-python numpy pillow imagehash --break-system-packages

------------------------------------------------------------------------
RUN
------------------------------------------------------------------------
python auto_group.py --input datasets/merged_dataset --output grouped/
"""

import argparse
import shutil
from pathlib import Path

import cv2
import numpy as np
from PIL import Image
import imagehash

HASH_THRESHOLD = 10      # lower = stricter (fewer, tighter groups)
ORB_MIN_INLIERS = 15     # min matched keypoints to confirm same background
MIN_GROUP_SIZE = 4       # groups smaller than this get moved to singles/
CENTER_MASK_FRAC = 0.5   # fraction of image (centered) to blank out before hashing


def compute_masked_hash(path: Path):
    """Perceptual hash with the center region blanked out (likely rat location)."""
    img = Image.open(path).convert("RGB")
    w, h = img.size
    arr = np.array(img)

    mw, mh = int(w * CENTER_MASK_FRAC), int(h * CENTER_MASK_FRAC)
    x0, y0 = (w - mw) // 2, (h - mh) // 2
    arr[y0:y0 + mh, x0:x0 + mw] = 0  # blank center

    masked_img = Image.fromarray(arr)
    return imagehash.phash(masked_img, hash_size=16)


class UnionFind:
    def __init__(self, n):
        self.parent = list(range(n))

    def find(self, x):
        while self.parent[x] != x:
            self.parent[x] = self.parent[self.parent[x]]
            x = self.parent[x]
        return x

    def union(self, a, b):
        ra, rb = self.find(a), self.find(b)
        if ra != rb:
            self.parent[ra] = rb


def orb_confirm_same_background(path_a: Path, path_b: Path, orb, matcher):
    """Returns True if two images share enough matched background keypoints."""
    img_a = cv2.imread(str(path_a), cv2.IMREAD_GRAYSCALE)
    img_b = cv2.imread(str(path_b), cv2.IMREAD_GRAYSCALE)
    if img_a is None or img_b is None:
        return False

    img_a = cv2.resize(img_a, (400, 300))
    img_b = cv2.resize(img_b, (400, 300))

    kp_a, des_a = orb.detectAndCompute(img_a, None)
    kp_b, des_b = orb.detectAndCompute(img_b, None)
    if des_a is None or des_b is None:
        return False

    matches = matcher.match(des_a, des_b)
    good = [m for m in matches if m.distance < 40]
    return len(good) >= ORB_MIN_INLIERS


def find_label_for_image(image_path: Path, labels_dir: Path):
    """Find the label file matching an image's filename stem, any extension."""
    candidates = list(labels_dir.glob(f"{image_path.stem}.*"))
    return candidates[0] if candidates else None


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--input", required=True,
                         help="Dataset root containing images/ and labels/ subfolders")
    parser.add_argument("--output", required=True)
    parser.add_argument("--hash-threshold", type=int, default=HASH_THRESHOLD)
    parser.add_argument("--min-group-size", type=int, default=MIN_GROUP_SIZE)
    parser.add_argument("--skip-orb-refine", action="store_true",
                         help="Skip ORB confirmation step (faster, less precise)")
    args = parser.parse_args()

    input_dir = Path(args.input)
    images_dir = input_dir / "images"
    labels_dir = input_dir / "labels"
    out_dir = Path(args.output)
    out_dir.mkdir(parents=True, exist_ok=True)

    if not images_dir.is_dir():
        raise SystemExit(f"Expected an 'images' folder inside {input_dir}, found none.")
    if not labels_dir.is_dir():
        print(f"[warning] No 'labels' folder found inside {input_dir} -- "
              f"proceeding with images only.")

    exts = {".jpg", ".jpeg", ".png", ".bmp"}
    paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in exts)
    n = len(paths)
    print(f"Found {n} images. Computing perceptual hashes...")

    hashes = []
    for i, p in enumerate(paths):
        try:
            hashes.append(compute_masked_hash(p))
        except Exception as e:
            print(f"[error] hashing {p.name}: {e}")
            hashes.append(None)
        if (i + 1) % 500 == 0:
            print(f"  hashed {i + 1}/{n}")

    print("Clustering by hash similarity...")
    uf = UnionFind(n)
    # naive O(n^2) comparison -- fine up to a few thousand images;
    # for larger datasets, consider bucketing by hash prefix first.
    for i in range(n):
        if hashes[i] is None:
            continue
        for j in range(i + 1, n):
            if hashes[j] is None:
                continue
            if hashes[i] - hashes[j] <= args.hash_threshold:
                uf.union(i, j)

    # collect coarse clusters
    clusters = {}
    for i in range(n):
        root = uf.find(i)
        clusters.setdefault(root, []).append(i)

    if not args.skip_orb_refine:
        print("Refining clusters with ORB keypoint matching...")
        orb = cv2.ORB_create(nfeatures=500)
        matcher = cv2.BFMatcher(cv2.NORM_HAMMING)
        refined_clusters = []
        for members in clusters.values():
            if len(members) < 2:
                refined_clusters.append(members)
                continue
            # verify against the first member of the cluster; split off
            # any image that doesn't actually match via ORB
            anchor = members[0]
            confirmed = [anchor]
            rejected = []
            for idx in members[1:]:
                if orb_confirm_same_background(paths[anchor], paths[idx], orb, matcher):
                    confirmed.append(idx)
                else:
                    rejected.append(idx)
            refined_clusters.append(confirmed)
            if rejected:
                refined_clusters.append(rejected)  # will be re-evaluated as their own group(s)
        clusters = {i: c for i, c in enumerate(refined_clusters)}

    def copy_image_and_label(idx, dest_root: Path):
        """Copies (never moves) an image and its matching label, if any,
        into dest_root/images/ and dest_root/labels/."""
        img_path = paths[idx]
        dest_images = dest_root / "images"
        dest_labels = dest_root / "labels"
        dest_images.mkdir(parents=True, exist_ok=True)
        dest_labels.mkdir(parents=True, exist_ok=True)

        shutil.copy2(img_path, dest_images / img_path.name)

        if labels_dir.is_dir():
            label_path = find_label_for_image(img_path, labels_dir)
            if label_path is not None:
                shutil.copy2(label_path, dest_labels / label_path.name)
            else:
                print(f"[warning] no label found for {img_path.name}")

    print("Writing grouped folders (copying images + labels, originals untouched)...")
    singles_dir = out_dir / "singles"
    group_num = 0
    total_grouped = 0

    for members in clusters.values():
        if len(members) >= args.min_group_size:
            group_num += 1
            group_dir = out_dir / f"group_{group_num:04d}"
            for idx in members:
                copy_image_and_label(idx, group_dir)
            total_grouped += len(members)
        else:
            for idx in members:
                copy_image_and_label(idx, singles_dir)

    n_singles = n - total_grouped
    print(f"\nDone. {group_num} groups created ({total_grouped} images), "
          f"{n_singles} images placed in singles/.")
    print(f"All files were COPIED -- your original dataset in {input_dir} is untouched.")
    print(f"Output written to: {out_dir}")
    print("\nSpot-check a few groups before running extract_backgrounds.py on this output.")


if __name__ == "__main__":
    main()
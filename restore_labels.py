"""
restore_labeled_images.py

After reviewing the "empty labels" images in CVAT, you exported YOLO-format
labels (obj_train_data/*.txt, obj.data, obj.names, train.txt). Some flagged
images were deleted during review, so they'll have no matching label file.

This script:
  1. Looks at every label file in the CVAT export (obj_train_data/).
  2. For each one, finds the matching image in the empty_labels_review folder.
  3. Moves that image + its new label into merged_dataset/images and
     merged_dataset/labels.
  4. Any image left in empty_labels_review with no matching CVAT label
     (i.e. you deleted it in CVAT) is simply left where it is.

Nothing is deleted by this script.

Usage:
    python restore_labeled_images.py
"""

import shutil
import sys
from pathlib import Path

MERGED_DIR = "datasets/merged_dataset"
EMPTY_LABELS_DIR = "datasets/empty_labels_review"
CVAT_EXPORT_DIR = "datasets/annotations/obj_train_data"  # folder containing the new .txt label files from CVAT

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def main():
    cvat_labels_dir = Path(CVAT_EXPORT_DIR)
    review_images_dir = Path(EMPTY_LABELS_DIR) / "images"
    review_labels_dir = Path(EMPTY_LABELS_DIR) / "labels"

    merged_images_dir = Path(MERGED_DIR) / "images"
    merged_labels_dir = Path(MERGED_DIR) / "labels"
    merged_images_dir.mkdir(parents=True, exist_ok=True)
    merged_labels_dir.mkdir(parents=True, exist_ok=True)

    if not cvat_labels_dir.is_dir():
        print(f"ERROR: CVAT export folder not found: {cvat_labels_dir.resolve()}")
        sys.exit(1)
    if not review_images_dir.is_dir():
        print(f"ERROR: review images folder not found: {review_images_dir.resolve()}")
        sys.exit(1)

    # Map of stem -> image path, for every image currently sitting in review
    review_images = {
        p.stem: p for p in review_images_dir.iterdir()
        if p.suffix.lower() in IMAGE_EXTS
    }

    # New label files from the CVAT export
    cvat_labels = sorted(cvat_labels_dir.glob("*.txt"))

    total = len(cvat_labels)
    print(f"Found {total} label files in CVAT export.")
    print(f"Found {len(review_images)} images waiting in review folder.\n")

    moved = 0
    missing_image_for_label = []

    for i, label_path in enumerate(cvat_labels, start=1):
        stem = label_path.stem
        img_path = review_images.get(stem)

        if img_path is None:
            # A label exists but we can't find the matching image in review.
            # (Shouldn't normally happen — flag it instead of silently skipping.)
            missing_image_for_label.append(label_path.name)
        else:
            # Move image -> merged_dataset/images
            shutil.move(str(img_path), str(merged_images_dir / img_path.name))
            # Move (new) label -> merged_dataset/labels
            shutil.move(str(label_path), str(merged_labels_dir / label_path.name))
            # Remove it from the lookup so we can compute leftovers afterward
            del review_images[stem]
            moved += 1

        pct = i / total * 100 if total else 100
        sys.stdout.write(f"\r  processed {i}/{total} ({pct:.1f}%) | moved so far: {moved}")
        sys.stdout.flush()

    print()  # newline after progress bar

    # Anything still left in review_images had no label -> was deleted in CVAT.
    # We leave those files untouched in EMPTY_LABELS_DIR/images.
    leftover = sorted(review_images.values())

    # Clean up any now-orphaned label files still sitting in review/labels
    # (old empty labels for images that got moved out)
    orphan_labels_removed = 0
    if review_labels_dir.is_dir():
        for lbl in review_labels_dir.iterdir():
            if lbl.suffix == ".txt" and lbl.stem not in {p.stem for p in leftover}:
                # this old empty label's image is gone (either moved to merged or deleted)
                # only remove it if there's truly no image left for it in review
                if lbl.stem not in review_images_dir_stems(review_images_dir):
                    lbl.unlink()
                    orphan_labels_removed += 1

    print("\nDone.")
    print(f"  Images + labels moved back to merged_dataset: {moved}")
    print(f"  Images left in review (no label -> deleted in CVAT): {len(leftover)}")
    if missing_image_for_label:
        print(f"  WARNING: {len(missing_image_for_label)} label file(s) had no matching "
              f"image in review folder:")
        for name in missing_image_for_label:
            print(f"    - {name}")
    print(f"  Old empty label leftovers cleaned up: {orphan_labels_removed}")
    print(f"\n  merged_dataset:      {Path(MERGED_DIR).resolve()}")
    print(f"  review folder (rest): {Path(EMPTY_LABELS_DIR).resolve()}")


def review_images_dir_stems(review_images_dir: Path):
    return {p.stem for p in review_images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS}


if __name__ == "__main__":
    main()
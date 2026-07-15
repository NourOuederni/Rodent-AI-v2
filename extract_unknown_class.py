"""
extract_unknown_class.py

Scans the MERGED dataset (produced by merge_datasets_yaml.py) for every
image that has at least one box labeled "unknown_0" (class ID 1 in
UNIFIED_CLASSES), and copies those images + their label files into a
separate review folder so you can eyeball them and decide whether they're
actually rats, something else, or junk boxes to delete.

It also crops out just the "unknown_0" boxes themselves as small image
snippets (in a crops/ subfolder), since that's usually faster to review
than opening full images and hunting for the box.

Usage:
    pip install pillow --break-system-packages   (if not already installed)
    python extract_unknown_class.py
"""

import shutil
import sys
from pathlib import Path
from PIL import Image

MERGED_DIR = "datasets/merged_dataset"      # where merge_datasets_yaml.py wrote its output
REVIEW_DIR = "datasets/unknown_0_review"    # where flagged images get copied

UNKNOWN_CLASS_ID = 1   # "unknown_0" is index 1 in UNIFIED_CLASSES = ["rat", "unknown_0"]

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def yolo_box_to_pixels(x_center, y_center, w, h, img_w, img_h):
    """Convert normalized YOLO box (0-1 range) to pixel (left, top, right, bottom)."""
    x_center *= img_w
    y_center *= img_h
    w *= img_w
    h *= img_h
    left = max(0, int(x_center - w / 2))
    top = max(0, int(y_center - h / 2))
    right = min(img_w, int(x_center + w / 2))
    bottom = min(img_h, int(y_center + h / 2))
    return left, top, right, bottom


def main():
    images_dir = Path(MERGED_DIR) / "images"
    labels_dir = Path(MERGED_DIR) / "labels"

    out_dir = Path(REVIEW_DIR)
    out_images = out_dir / "images"
    out_labels = out_dir / "labels"
    out_crops = out_dir / "crops"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)
    out_crops.mkdir(parents=True, exist_ok=True)

    flagged_images = 0
    flagged_boxes = 0

    # Pre-pass just to get a total count for the progress line below.
    all_label_files = sorted(p for p in labels_dir.iterdir() if p.suffix.lower() == ".txt")
    total_labels = len(all_label_files)
    print(f"Scanning {total_labels} label files for unknown_0 boxes...\n")

    for scanned, label_path in enumerate(all_label_files, start=1):
        lines = label_path.read_text().splitlines()
        unknown_lines = []
        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue
            if int(parts[0]) == UNKNOWN_CLASS_ID:
                unknown_lines.append(parts)

        # Live progress line, overwritten in place (no scroll spam).
        pct = (scanned / total_labels * 100) if total_labels else 100
        sys.stdout.write(
            f"\r  scanned {scanned}/{total_labels} ({pct:.1f}%) "
            f"| flagged so far: {flagged_images}"
        )
        sys.stdout.flush()

        if not unknown_lines:
            continue  # this image has no unknown_0 boxes, skip it

        # Find the matching image (same stem, any image extension)
        stem = label_path.stem
        matches = [p for p in images_dir.glob(f"{stem}.*") if p.suffix.lower() in IMAGE_EXTS]
        if not matches:
            print(f"[WARNING] Label {label_path.name} has unknown_0 boxes but no matching image found, skipping.")
            continue
        img_path = matches[0]

        # Copy the full image + its full label file (with ALL boxes, not just
        # unknown_0) into the review folder, so you have full context.
        shutil.copy2(img_path, out_images / img_path.name)
        shutil.copy2(label_path, out_labels / label_path.name)
        flagged_images += 1

        # Also save a cropped snippet of just each unknown_0 box, for fast review.
        try:
            with Image.open(img_path) as im:
                img_w, img_h = im.size
                for i, parts in enumerate(unknown_lines):
                    _, xc, yc, w, h = parts[:5]
                    box = yolo_box_to_pixels(float(xc), float(yc), float(w), float(h), img_w, img_h)
                    crop = im.crop(box)
                    crop_name = f"{stem}_box{i}{img_path.suffix}"
                    crop.save(out_crops / crop_name)
                    flagged_boxes += 1
        except Exception as e:
            print(f"[WARNING] Could not crop boxes from {img_path.name}: {e}")

    print()  # newline after the in-place progress line
    print("Done.")
    print(f"  Images with unknown_0 boxes: {flagged_images}")
    print(f"  Total unknown_0 boxes:       {flagged_boxes}")
    print(f"  Full images + labels copied to: {out_images.resolve()} / {out_labels.resolve()}")
    print(f"  Cropped box snippets saved to:  {out_crops.resolve()}")
    print("\nReview tip: browse crops/ first (fastest way to see just the boxed")
    print("region), then open the matching full image in images/ if you need")
    print("more context on any particular one.")


if __name__ == "__main__":
    main()
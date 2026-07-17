"""
move_empty_labels.py

Finds every image whose label file is EMPTY (0 bytes, or a .txt with no
actual annotation lines) and moves that image + its label out of the
merged dataset into a separate folder. Nothing is deleted.

Usage:
    python move_empty_labels.py
"""

import shutil
import sys
from pathlib import Path

MERGED_DIR = "datasets/merged_dataset"
EMPTY_LABELS_DIR = "datasets/empty_labels_review"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def is_empty_label(label_path: Path) -> bool:
    if label_path.stat().st_size == 0:
        return True
    if label_path.suffix == ".txt":
        return not label_path.read_text().strip()
    return False


def main():
    images_dir = Path(MERGED_DIR) / "images"
    labels_dir = Path(MERGED_DIR) / "labels"

    out_dir = Path(EMPTY_LABELS_DIR)
    out_images = out_dir / "images"
    out_labels = out_dir / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    total = len(image_paths)
    print(f"Checking {total} images for empty labels...\n")

    moved = 0
    for i, img_path in enumerate(image_paths, start=1):
        label_path = labels_dir / f"{img_path.stem}.txt"

        if label_path.exists() and is_empty_label(label_path):
            shutil.move(str(img_path), str(out_images / img_path.name))
            shutil.move(str(label_path), str(out_labels / label_path.name))
            moved += 1

        pct = i / total * 100 if total else 100
        sys.stdout.write(f"\r  checked {i}/{total} ({pct:.1f}%) | moved so far: {moved}")
        sys.stdout.flush()

    print()  # newline after progress line

    remaining_images = sum(1 for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)

    print("\nDone.")
    print(f"  Images with empty labels moved: {moved}")
    print(f"  Images remaining in merged:      {remaining_images}")
    print(f"  Review folder:                   {out_dir.resolve()}")


if __name__ == "__main__":
    main()
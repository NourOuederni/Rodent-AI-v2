"""
rename_dataset_sequential.py

Renames every image (and its matching label file) in the merged dataset to
a sequential zero-padded number, e.g.:

    images/000001.jpg   labels/000001.txt
    images/000002.jpg   labels/000002.txt
    images/000003.jpg   labels/000003.txt
    ...

Files are processed in sorted (alphabetical) order of their current name,
so the numbering is stable and repeatable.

Renaming is done in TWO passes (first to temporary names, then to final
names) so it's safe even if some of the target numeric names happen to
already exist -- nothing gets overwritten or lost mid-run.

Usage:
    python rename_dataset_sequential.py
"""

import sys
from pathlib import Path

MERGED_DIR = "datasets/merged_dataset"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# Number of digits to zero-pad to, e.g. 6 -> 000001.jpg. Make sure this is
# large enough for your total image count (6 digits = up to 999,999).
PAD_WIDTH = 6


def main():
    images_dir = Path(MERGED_DIR) / "images"
    labels_dir = Path(MERGED_DIR) / "labels"

    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    total = len(image_paths)
    print(f"Found {total} images to rename.\n")

    if total == 0:
        print("Nothing to do.")
        return

    # --- Pass 1: rename everything to temporary names -------------------
    # Avoids collisions if a target numeric name (e.g. "000042.jpg")
    # happens to already exist among the current filenames.
    print("Pass 1/2: renaming to temporary names...\n")
    temp_pairs = []  # (final_stem, temp_img_path, temp_label_path_or_None)

    for i, img_path in enumerate(image_paths, start=1):
        final_stem = str(i).zfill(PAD_WIDTH)
        temp_img_path = images_dir / f"__tmp_{i}{img_path.suffix}"
        img_path.rename(temp_img_path)

        label_path = labels_dir / f"{img_path.stem}.txt"
        temp_label_path = None
        if label_path.exists():
            temp_label_path = labels_dir / f"__tmp_{i}.txt"
            label_path.rename(temp_label_path)

        temp_pairs.append((final_stem, temp_img_path, temp_label_path))

        pct = i / total * 100
        sys.stdout.write(f"\r  renamed {i}/{total} ({pct:.1f}%)")
        sys.stdout.flush()

    print()  # newline after progress line

    # --- Pass 2: rename from temporary names to final numbered names ----
    print("\nPass 2/2: renaming to final numbered names...\n")
    missing_labels = 0

    for i, (final_stem, temp_img_path, temp_label_path) in enumerate(temp_pairs, start=1):
        final_img_path = images_dir / f"{final_stem}{temp_img_path.suffix}"
        temp_img_path.rename(final_img_path)

        if temp_label_path is not None:
            final_label_path = labels_dir / f"{final_stem}.txt"
            temp_label_path.rename(final_label_path)
        else:
            missing_labels += 1

        pct = i / total * 100
        sys.stdout.write(f"\r  renamed {i}/{total} ({pct:.1f}%)")
        sys.stdout.flush()

    print()  # newline after progress line

    print("\nDone.")
    print(f"  Images renamed:     {total}")
    print(f"  Naming scheme:      {'0' * PAD_WIDTH}.ext  (e.g. {'1'.zfill(PAD_WIDTH)}.jpg)")
    if missing_labels:
        print(f"  [NOTE] {missing_labels} image(s) had no matching label file, so only the image was renamed.")


if __name__ == "__main__":
    main()
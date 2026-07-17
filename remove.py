"""
remove_runs_images_from_merged.py

You have a folder called "runs" full of images. This script:
  1. Lists every image found in runs/ (recursively, in case they're in subfolders).
  2. For each one, finds the image with the same filename in merged_dataset/images
     and removes it (along with its matching label in merged_dataset/labels, if any).

Nothing is deleted forever by default — matched files are moved to a
"removed_from_merged" backup folder instead, so you can double check before
permanently deleting them. Set PERMANENTLY_DELETE = True below if you're sure
and just want them gone.

Usage:
    python remove_runs_images_from_merged.py
"""

import shutil
import sys
from pathlib import Path

RUNS_DIR = "datasets/runs"
MERGED_DIR = "datasets/merged_dataset"
BACKUP_DIR = "datasets/removed_from_merged"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# If True, matched files are permanently deleted instead of moved to BACKUP_DIR.
PERMANENTLY_DELETE = False


def main():
    runs_dir = Path(RUNS_DIR)
    merged_images_dir = Path(MERGED_DIR) / "images"
    merged_labels_dir = Path(MERGED_DIR) / "labels"

    if not runs_dir.is_dir():
        print(f"ERROR: runs folder not found: {runs_dir.resolve()}")
        sys.exit(1)
    if not merged_images_dir.is_dir():
        print(f"ERROR: merged_dataset/images not found: {merged_images_dir.resolve()}")
        sys.exit(1)

    # Find every image in runs/ (recursive, in case they're nested in subfolders)
    runs_images = sorted(
        p for p in runs_dir.rglob("*") if p.suffix.lower() in IMAGE_EXTS
    )

    print(f"Found {len(runs_images)} image(s) in '{runs_dir}':\n")
    for p in runs_images:
        print(f"  {p.relative_to(runs_dir)}")
    print()

    if not runs_images:
        print("Nothing to do.")
        return

    if not PERMANENTLY_DELETE:
        backup_images_dir = Path(BACKUP_DIR) / "images"
        backup_labels_dir = Path(BACKUP_DIR) / "labels"
        backup_images_dir.mkdir(parents=True, exist_ok=True)
        backup_labels_dir.mkdir(parents=True, exist_ok=True)

    removed = 0
    not_found = []

    for img in runs_images:
        match = merged_images_dir / img.name
        if not match.exists():
            not_found.append(img.name)
            continue

        label_match = merged_labels_dir / f"{match.stem}.txt"

        if PERMANENTLY_DELETE:
            match.unlink()
            if label_match.exists():
                label_match.unlink()
        else:
            shutil.move(str(match), str(backup_images_dir / match.name))
            if label_match.exists():
                shutil.move(str(label_match), str(backup_labels_dir / label_match.name))

        removed += 1

    print("Done.")
    print(f"  Images removed from merged_dataset: {removed}")
    if not PERMANENTLY_DELETE:
        print(f"  (moved to backup folder: {Path(BACKUP_DIR).resolve()})")
    if not_found:
        print(f"  {len(not_found)} image(s) from 'runs' had no match in merged_dataset:")
        for name in not_found:
            print(f"    - {name}")


if __name__ == "__main__":
    main()
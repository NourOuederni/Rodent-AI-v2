"""
Build fomo_dataset.zip for the Colab training notebook.

The archive intentionally uses forward-slash paths such as
training/cur_000001.jpg. That keeps Colab/Linux extraction simple even when the
zip is created on Windows.
"""

from __future__ import annotations

import json
from pathlib import Path
from zipfile import ZIP_DEFLATED, ZipFile


CURATED_DIR = Path("datasets/ei_curated")
OUT_ZIP = Path("fomo_dataset.zip")
SPLITS = ("training", "testing")
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def load_labels(split_dir: Path) -> dict[str, list[dict]]:
    labels_path = split_dir / "bounding_boxes.labels"
    if not labels_path.exists():
        raise FileNotFoundError(f"Missing labels file: {labels_path}")
    data = json.loads(labels_path.read_text())
    return data.get("boundingBoxes", {})


def split_summary(split: str) -> tuple[list[Path], int, int]:
    split_dir = CURATED_DIR / split
    if not split_dir.is_dir():
        raise FileNotFoundError(f"Missing split folder: {split_dir}")

    labels = load_labels(split_dir)
    images_by_name = {
        p.name: p for p in split_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS
    }
    missing_images = sorted(set(labels) - set(images_by_name))
    unlabeled_images = sorted(set(images_by_name) - set(labels))
    if missing_images:
        raise RuntimeError(f"{split}: {len(missing_images)} label entries have no image")
    if unlabeled_images:
        print(f"  {split}: ignoring {len(unlabeled_images)} stale unlabeled images")

    positives = sum(1 for boxes in labels.values() if boxes)
    backgrounds = len(labels) - positives
    images = [images_by_name[name] for name in sorted(labels)]
    return images + [split_dir / "bounding_boxes.labels"], positives, backgrounds


def main() -> None:
    all_files: list[tuple[Path, str]] = []
    print("Preparing Colab dataset zip...")

    for split in SPLITS:
        files, positives, backgrounds = split_summary(split)
        print(f"  {split}: {positives} positives, {backgrounds} backgrounds")
        for path in files:
            arcname = f"{split}/{path.name}"
            all_files.append((path, arcname))

    with ZipFile(OUT_ZIP, "w", compression=ZIP_DEFLATED) as zf:
        for path, arcname in all_files:
            zf.write(path, arcname)

    print(f"Done: {OUT_ZIP.resolve()} ({OUT_ZIP.stat().st_size / (1024 * 1024):.1f} MB)")


if __name__ == "__main__":
    main()

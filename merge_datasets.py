"""
merge_datasets_yaml.py

Merges multiple YOLO-format datasets (images/ + labels/) into one combined
dataset, using each dataset's data.yaml to figure out what its class IDs
actually mean, then rewriting every label file so class IDs are consistent
across the merged set.

Why this exists: each of your datasets was exported separately, so class ID 0
does NOT mean the same thing in every one. This script fixes that instead of
just dumping label files together blindly.

Usage:
    1. Edit DATASETS with the path to each dataset folder.
    2. Edit OUTPUT_DIR to where you want the merged result written.
    3. Double check ALIASES / MANUAL_CLASSES / UNIFIED_CLASSES match your data.
    4. pip install pyyaml (if not already installed)
    5. Run: python merge_datasets_yaml.py
"""

import shutil
import sys
import yaml
from pathlib import Path

# ---------------------------------------------------------------------
# 1. DATASETS: tag -> folder path
# ---------------------------------------------------------------------
DATASETS = {
    "rdmodel":     "datasets/Rat Detection Model YOLOv10.v1i.yolov8",
    "ratv3":       "datasets/rat detection.v3i.yolov8",
    "ratv2":       "datasets/rat.v2-v2.yolov8",
    "ratv2i":      "datasets/rat.v2i.yolov8",
    "ratv4":       "datasets/rats.v4i.yolov8",
    "nightvision": "datasets/nightvision",   # no data.yaml in this one
}

OUTPUT_DIR = "datasets/merged_dataset"

SPLIT_SUBFOLDERS = ["train", "valid", "test"]
IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}

# ---------------------------------------------------------------------
# 2. MANUAL_CLASSES: for any dataset with NO data.yaml, hardcode its
#    class list here. Position in the list = the class ID that dataset's
#    .txt label files actually use.
# ---------------------------------------------------------------------
MANUAL_CLASSES = {
    "nightvision": ["rat"],   # single class, always index 0
}

# ---------------------------------------------------------------------
# 3. ALIASES: raw class name (exactly as it appears in that dataset's
#    data.yaml "names:" list) -> canonical name to merge it into.
#
#    Resolves the specific mess found in your files:
#      - ratv3's two leftover "project name" classes both actually mean "rat"
#      - ratv2's "Tikus" is Malay/Indonesian for "rat"
#      - ratv2's "0" is a suspicious/likely-broken class. It is NOT folded
#        into "rat" automatically -- it's kept as its own flagged class
#        ("unknown_0") so you can inspect those specific boxes and decide
#        whether to keep, relabel, or drop them.
#
#    Any raw name not listed here is assumed to already be canonical
#    (e.g. "rat" maps to itself).
# ---------------------------------------------------------------------
ALIASES = {
    "rat detection - v10 2023-04-10 5-08pm": "rat",
    "rat detection - v2 2024-08-03 2-50pm": "rat",
    "Tikus": "rat",
    "0": "unknown_0",   # deliberately NOT merged into "rat"
}

# Final class list for the merged dataset. Position here = the class ID
# that will be written into every remapped label file.
UNIFIED_CLASSES = ["rat", "unknown_0"]


def load_classes(tag: str, dataset_path: Path):
    """
    Return this dataset's ordered raw class name list (position = its
    original class ID), either from data.yaml or MANUAL_CLASSES.
    """
    if tag in MANUAL_CLASSES:
        return MANUAL_CLASSES[tag]

    yaml_path = dataset_path / "data.yaml"
    if not yaml_path.exists():
        print(f"[WARNING] No data.yaml for '{tag}' and no MANUAL_CLASSES entry "
              f"-- its labels will NOT be remapped (all lines dropped).")
        return []

    with open(yaml_path, "r") as f:
        data = yaml.safe_load(f)
    return data.get("names", [])


def build_remap(raw_names):
    """
    Build {old_class_id: new_class_id} for one dataset from its raw class
    name list. Any class that can't be resolved to something in
    UNIFIED_CLASSES is dropped (its boxes will be skipped, with a warning).
    """
    remap = {}
    for old_id, raw_name in enumerate(raw_names):
        canonical = ALIASES.get(raw_name, raw_name)
        if canonical not in UNIFIED_CLASSES:
            print(f"    [WARNING] class '{raw_name}' (id {old_id}) -> "
                  f"'{canonical}' is not in UNIFIED_CLASSES, its boxes will "
                  f"be dropped. Add it to ALIASES/UNIFIED_CLASSES if that's wrong.")
            continue
        remap[old_id] = UNIFIED_CLASSES.index(canonical)
    return remap


def remap_label_file(src_path: Path, dst_path: Path, remap: dict):
    """
    Copy one label file, rewriting YOLO .txt class IDs per `remap`.
    Lines whose class ID has no entry in remap (dropped class) are skipped.
    Non-.txt labels (xml/json/etc.) are copied unchanged -- ID remapping
    only applies to YOLO .txt format.
    """
    if src_path.suffix.lower() != ".txt":
        shutil.copy2(src_path, dst_path)
        return

    out_lines = []
    for line in src_path.read_text().splitlines():
        parts = line.strip().split()
        if not parts:
            continue
        old_id = int(parts[0])
        if old_id not in remap:
            continue
        parts[0] = str(remap[old_id])
        out_lines.append(" ".join(parts))

    dst_path.write_text("\n".join(out_lines) + ("\n" if out_lines else ""))


def count_images(dataset_path: Path):
    """Quick pre-pass: count how many images this dataset has, across all
    its split subfolders, so we can show an overall progress percentage."""
    total = 0
    for img_dir, _ in find_split_dirs(dataset_path):
        total += sum(1 for p in img_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    return total


def find_split_dirs(dataset_path: Path):
    for split in SPLIT_SUBFOLDERS:
        base = dataset_path / split if split else dataset_path
        img_dir = base / "images"
        lbl_dir = base / "labels"
        if img_dir.exists():
            yield img_dir, lbl_dir


def merge():
    out_images = Path(OUTPUT_DIR) / "images"
    out_labels = Path(OUTPUT_DIR) / "labels"
    out_images.mkdir(parents=True, exist_ok=True)
    out_labels.mkdir(parents=True, exist_ok=True)

    total_images = 0
    total_labels = 0
    missing_labels = []

    # Pre-pass: count everything upfront so we can show a running
    # "X / grand_total" and percentage instead of the terminal looking frozen.
    print("Scanning datasets to count files...")
    valid_datasets = [(tag, Path(p)) for tag, p in DATASETS.items() if Path(p).exists()]
    for tag, p in DATASETS.items():
        if not Path(p).exists():
            print(f"[WARNING] Dataset path not found, skipping: {p}")
    per_dataset_counts = {tag: count_images(path) for tag, path in valid_datasets}
    grand_total = sum(per_dataset_counts.values())
    print(f"Found {grand_total} images across {len(valid_datasets)} datasets.\n")

    processed = 0
    for tag, dataset_path in valid_datasets:
        raw_names = load_classes(tag, dataset_path)
        remap = build_remap(raw_names)
        print(f"[{tag}] classes: {raw_names} -> remap {remap}")
        dataset_total = per_dataset_counts[tag]

        dataset_count = 0
        for img_dir, lbl_dir in find_split_dirs(dataset_path):
            for img_path in sorted(img_dir.iterdir()):
                if img_path.suffix.lower() not in IMAGE_EXTS:
                    continue

                new_stem = f"{tag}_{img_path.stem}"
                new_img_path = out_images / f"{new_stem}{img_path.suffix}"
                shutil.copy2(img_path, new_img_path)

                label_path = None
                if lbl_dir.exists():
                    matches = list(lbl_dir.glob(f"{img_path.stem}.*"))
                    if matches:
                        label_path = matches[0]

                if label_path:
                    new_lbl_path = out_labels / f"{new_stem}{label_path.suffix}"
                    remap_label_file(label_path, new_lbl_path, remap)
                    total_labels += 1
                else:
                    missing_labels.append(str(img_path))

                dataset_count += 1
                total_images += 1
                processed += 1

                # Live progress line, overwritten in place (no scroll spam).
                # Prints every image; on very large datasets you can change
                # the modulo below (e.g. `if processed % 25 == 0`) to update
                # less often.
                pct = (processed / grand_total * 100) if grand_total else 100
                sys.stdout.write(
                    f"\r  [{tag}] {dataset_count}/{dataset_total} in this dataset "
                    f"| overall {processed}/{grand_total} ({pct:.1f}%)"
                )
                sys.stdout.flush()

        print()  # newline after this dataset's progress line
        print(f"[{tag}] copied {dataset_count} images\n")

    # Write out the unified data.yaml for the merged dataset
    merged_yaml = {"nc": len(UNIFIED_CLASSES), "names": UNIFIED_CLASSES}
    with open(Path(OUTPUT_DIR) / "data.yaml", "w") as f:
        yaml.safe_dump(merged_yaml, f)

    print("Merge complete.")
    print(f"  Total images copied: {total_images}")
    print(f"  Total labels copied: {total_labels}")
    print(f"  Unified classes:     {UNIFIED_CLASSES}")
    print(f"  Output folder:       {Path(OUTPUT_DIR).resolve()}")

    if missing_labels:
        print(f"\n[NOTE] {len(missing_labels)} images had no matching label file, e.g.:")
        for p in missing_labels[:5]:
            print(f"    - {p}")

    sanity_check(out_images, out_labels)


def sanity_check(images_dir: Path, labels_dir: Path):
    """
    Reports images with no label, labels that are empty, and labels with
    no matching image. Does NOT check for duplicate images yet.
    """
    image_stems = {p.stem for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS}
    label_files = {p.stem: p for p in labels_dir.iterdir() if p.is_file()}

    missing_label = sorted(image_stems - label_files.keys())
    orphaned_label = sorted(label_files.keys() - image_stems)

    empty_label = []
    for stem, path in label_files.items():
        if stem in image_stems and path.stat().st_size == 0:
            empty_label.append(stem)
        elif stem in image_stems and path.suffix == ".txt":
            content = path.read_text().strip()
            if not content:
                empty_label.append(stem)

    print("\n--- Sanity check ---")
    print(f"  Images total:               {len(image_stems)}")
    print(f"  Labels total:               {len(label_files)}")
    print(f"  Images with NO label file:  {len(missing_label)}")
    print(f"  Labels with EMPTY content:  {len(empty_label)}")
    print(f"  Orphaned labels (no image): {len(orphaned_label)}")

    if missing_label:
        print("\n  Examples of images missing labels:")
        for s in missing_label[:5]:
            print(f"    - {s}")
    if empty_label:
        print("\n  Examples of empty labels:")
        for s in empty_label[:5]:
            print(f"    - {s}")
    if orphaned_label:
        print("\n  Examples of orphaned labels:")
        for s in orphaned_label[:5]:
            print(f"    - {s}")


if __name__ == "__main__":
    merge()
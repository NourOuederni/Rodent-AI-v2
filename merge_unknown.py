"""
merge_unknown_into_rat.py

Now that you've manually reviewed the unknown_0 crops and confirmed they're
all actually rats, this rewrites every label file in the merged dataset:
every box with class ID 1 (unknown_0) becomes class ID 0 (rat).

After this runs, the merged dataset has a single class: "rat" (ID 0).
It also rewrites data.yaml to reflect that.

Usage:
    python merge_unknown_into_rat.py
"""

import sys
from pathlib import Path
import yaml

MERGED_DIR = "datasets/merged_dataset"

OLD_UNKNOWN_ID = 1   # "unknown_0" in the current merged data.yaml
NEW_RAT_ID = 0        # "rat"

FINAL_CLASSES = ["rat"]


def main():
    labels_dir = Path(MERGED_DIR) / "labels"
    label_files = sorted(p for p in labels_dir.iterdir() if p.suffix.lower() == ".txt")
    total = len(label_files)

    print(f"Found {total} label files to check.\n")

    files_changed = 0
    boxes_changed = 0

    for scanned, label_path in enumerate(label_files, start=1):
        lines = label_path.read_text().splitlines()
        new_lines = []
        file_touched = False

        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue
            class_id = int(parts[0])
            if class_id == OLD_UNKNOWN_ID:
                parts[0] = str(NEW_RAT_ID)
                file_touched = True
                boxes_changed += 1
            new_lines.append(" ".join(parts))

        if file_touched:
            label_path.write_text("\n".join(new_lines) + ("\n" if new_lines else ""))
            files_changed += 1

        # Live progress line, overwritten in place (no scroll spam).
        pct = (scanned / total * 100) if total else 100
        sys.stdout.write(
            f"\r  checked {scanned}/{total} ({pct:.1f}%) "
            f"| files changed so far: {files_changed} | boxes changed so far: {boxes_changed}"
        )
        sys.stdout.flush()

    print()  # newline after the in-place progress line

    # Update data.yaml to reflect the single final class
    yaml_path = Path(MERGED_DIR) / "data.yaml"
    merged_yaml = {"nc": len(FINAL_CLASSES), "names": FINAL_CLASSES}
    with open(yaml_path, "w") as f:
        yaml.safe_dump(merged_yaml, f)

    print("Done.")
    print(f"  Label files changed: {files_changed} / {total}")
    print(f"  Boxes reclassified:  {boxes_changed}")
    print(f"  data.yaml updated to a single class: {FINAL_CLASSES}")
    print(f"  Output folder: {Path(MERGED_DIR).resolve()}")


if __name__ == "__main__":
    main()
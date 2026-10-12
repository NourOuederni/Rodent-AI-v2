import csv
import sys
from pathlib import Path

from PIL import Image, UnidentifiedImageError

MERGED_DIR = "datasets/merged_dataset"
REPORT_PATH = "dataset_issues_report.csv"

IMAGE_EXTS = {".jpg", ".jpeg", ".png", ".bmp"}


def is_empty_label(label_path: Path) -> bool:
    if label_path.stat().st_size == 0:
        return True
    return not label_path.read_text().strip()


def get_malformed_lines(label_path: Path) -> list[str]:
    """Return descriptions of any line that doesn't look like a valid
    'class x_center y_center width height' annotation."""
    problems = []
    lines = [l for l in label_path.read_text().splitlines() if l.strip()]

    for line_no, line in enumerate(lines, start=1):
        parts = line.split()
        if len(parts) != 5:
            problems.append(f"line {line_no}: expected 5 values, got {len(parts)} -> '{line}'")
            continue
        try:
            cls_id = int(parts[0])
            x, y, w, h = (float(v) for v in parts[1:])
        except ValueError:
            problems.append(f"line {line_no}: non-numeric value -> '{line}'")
            continue
        if cls_id < 0:
            problems.append(f"line {line_no}: negative class id ({cls_id})")
        if not (0 <= x <= 1 and 0 <= y <= 1 and 0 < w <= 1 and 0 < h <= 1):
            problems.append(f"line {line_no}: value(s) out of expected [0,1] range -> '{line}'")

    return problems


def check_image_corrupted(img_path: Path) -> str | None:
    try:
        with Image.open(img_path) as im:
            im.verify()
        with Image.open(img_path) as im:
            im.load()
    except (UnidentifiedImageError, OSError, SyntaxError, ValueError) as e:
        return f"corrupted image: {e}"
    return None


def main():
    images_dir = Path(MERGED_DIR) / "images"
    labels_dir = Path(MERGED_DIR) / "labels"

    if not images_dir.is_dir():
        print(f"ERROR: images folder not found: {images_dir.resolve()}")
        sys.exit(1)
    if not labels_dir.is_dir():
        print(f"ERROR: labels folder not found: {labels_dir.resolve()}")
        sys.exit(1)

    image_paths = sorted(p for p in images_dir.iterdir() if p.suffix.lower() in IMAGE_EXTS)
    total = len(image_paths)
    print(f"Checking {total} images + their labels...\n")

    rows = []
    empty_label_count = 0
    malformed_count = 0
    corrupted_count = 0
    missing_label_count = 0

    for i, img_path in enumerate(image_paths, start=1):
        # --- corrupted image check ---
        corrupt_msg = check_image_corrupted(img_path)
        if corrupt_msg:
            corrupted_count += 1
            rows.append([img_path.name, "corrupted_image", corrupt_msg])

        # --- label checks ---
        label_path = labels_dir / f"{img_path.stem}.txt"
        if not label_path.exists():
            missing_label_count += 1
            rows.append([img_path.name, "missing_label", "no matching label file"])
        elif is_empty_label(label_path):
            empty_label_count += 1
            rows.append([img_path.name, "empty_label", "label file has no annotation lines"])
        else:
            malformed = get_malformed_lines(label_path)
            for problem in malformed:
                malformed_count += 1
                rows.append([img_path.name, "malformed_label", problem])

        if i == total or i % 100 == 0:
            pct = i / total * 100 if total else 100
            sys.stdout.write(f"\r  checked {i}/{total} ({pct:.1f}%)")
            sys.stdout.flush()

    print()

    with open(REPORT_PATH, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["image", "issue_type", "details"])
        writer.writerows(rows)

    print("\nDone.")
    print(f"  Corrupted images:        {corrupted_count}")
    print(f"  Empty label files:       {empty_label_count}")
    print(f"  Malformed label lines:   {malformed_count}")
    print(f"  Missing label files:     {missing_label_count}")
    print(f"  Full report written to: {Path(REPORT_PATH).resolve()}")


if __name__ == "__main__":
    main()

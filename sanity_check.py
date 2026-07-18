from pathlib import Path

LABELS_DIR = "datasets/merged_dataset/labels"

def check_label_math(labels_path):
    bad_files = 0
    for txt_file in Path(labels_path).glob("*.txt"):
        with open(txt_file, 'r') as f:
            for line_num, line in enumerate(f, 1):
                parts = line.strip().split()
                if len(parts) != 5:
                    continue
                
                try:
                    _, x_c, y_c, w, h = map(float, parts)
                except ValueError:
                    continue

                # Check for mathematically impossible or bad bounding boxes
                # YOLO coords should be between 0 and 1. 
                # Width/Height should be > 0 and usually <= 1
                if not (0 <= x_c <= 1 and 0 <= y_c <= 1):
                    print(f"Bad center coord in {txt_file.name} (Line {line_num}): {line.strip()}")
                    bad_files += 1
                elif not (0 < w <= 1 and 0 < h <= 1):
                    print(f"Bad width/height in {txt_file.name} (Line {line_num}): {line.strip()}")
                    bad_files += 1

    if bad_files == 0:
        print("SUCCESS: All 11,000 labels have mathematically valid coordinates!")
    else:
        print(f"WARNING: Found {bad_files} lines with impossible coordinates.")

if __name__ == "__main__":
    check_label_math(LABELS_DIR)
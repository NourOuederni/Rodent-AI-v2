import os
from pathlib import Path

LABELS_DIR = "datasets/merged_dataset/labels"

def convert_polygons_to_bboxes(labels_path):
    for txt_file in Path(labels_path).glob("*.txt"):
        with open(txt_file, 'r') as f:
            lines = f.readlines()
        
        new_lines = []
        changed = False
        
        for line in lines:
            parts = line.strip().split()
            if not parts:
                continue
                
            # If it's already a normal bounding box (5 values), leave it alone
            if len(parts) == 5:
                new_lines.append(line.strip())
                continue
            
            # If it's a polygon/OBB (class + pairs of coordinates)
            try:
                cls_id = parts[0]
                coords = [float(p) for p in parts[1:]]
                
                # Separate X and Y coordinates
                xs = coords[0::2] # Even indices are X
                ys = coords[1::2] # Odd indices are Y
                
                # Calculate bounding box
                x_min, x_max = min(xs), max(xs)
                y_min, y_max = min(ys), max(ys)
                
                # Convert to YOLO format (x_center, y_center, width, height)
                x_center = (x_min + x_max) / 2
                y_center = (y_min + y_max) / 2
                width = x_max - x_min
                height = y_max - y_min
                
                new_line = f"{cls_id} {x_center:.6f} {y_center:.6f} {width:.6f} {height:.6f}"
                new_lines.append(new_line)
                changed = True
                
            except Exception as e:
                print(f"Error processing {txt_file.name}: {e}")
                new_lines.append(line.strip()) # Keep original if it fails

        # Overwrite the file if we converted any polygons
        if changed:
            with open(txt_file, 'w') as f:
                f.write("\n".join(new_lines) + "\n")
            print(f"Converted polygons to bboxes in: {txt_file.name}")

if __name__ == "__main__":
    convert_polygons_to_bboxes(LABELS_DIR)
    print("Done!")
import json
import sys
import shutil
from pathlib import Path
from PIL import Image

DATASET_DIR = "datasets/merged_dataset"
# Create a new "third" folder for Edge Impulse
OUTPUT_DIR = Path(DATASET_DIR) / "ei_upload"

def create_ei_metadata():
    images_dir = Path(DATASET_DIR) / "images"
    labels_dir = Path(DATASET_DIR) / "labels"
    
    # Create the output folder if it doesn't exist
    OUTPUT_DIR.mkdir(parents=True, exist_ok=True)
    
    valid_extensions = ['.jpg', '.jpeg', '.png']
    all_images = [p for p in images_dir.iterdir() if p.suffix.lower() in valid_extensions]
    total_images = len(all_images)
    
    if total_images == 0:
        print("No images found in the directory!")
        return

    print(f"Found {total_images} images. Copying images and creating JSON in '{OUTPUT_DIR.name}'...\n")
    
    processed_count = 0
    skipped_count = 0

    for img_path in all_images:
        label_path = labels_dir / f"{img_path.stem}.txt"
        
        # Define where the new files will go
        out_img_path = OUTPUT_DIR / img_path.name
        out_json_path = OUTPUT_DIR / f"{img_path.stem}.json"

        if not label_path.exists():
            skipped_count += 1
            processed_count += 1
            sys.stdout.write(f"\rProgress: {processed_count}/{total_images} processed (Skipped: {skipped_count})")
            sys.stdout.flush()
            continue

        try:
            # 1. Copy the original image to the new folder
            shutil.copy(img_path, out_img_path)
            
            # 2. Read the original image to get dimensions
            with Image.open(img_path) as img:
                img_w, img_h = img.size
            
            bboxes = []
            with open(label_path, 'r') as f:
                for line in f.readlines():
                    parts = line.strip().split()
                    if len(parts) != 5:
                        continue
                    
                    _, x_c, y_c, w, h = map(float, parts)
                    
                    # Convert YOLO to Edge Impulse pixel coordinates
                    x_min = (x_c - w / 2) * img_w
                    y_min = (y_c - h / 2) * img_h
                    width = w * img_w
                    height = h * img_h
                    
                    bboxes.append({
                        "label": "rat",
                        "x": int(x_min),
                        "y": int(y_min),
                        "width": int(width),
                        "height": int(height)
                    })
            
            # 3. Save the new JSON file to the new folder
            metadata = {
                "version": 1,
                "boundingBoxes": bboxes
            }
            
            with open(out_json_path, 'w') as f:
                json.dump(metadata, f)
                
        except Exception as e:
            print(f"\nError processing {img_path.name}: {e}")
            skipped_count += 1

        processed_count += 1
        sys.stdout.write(f"\rProgress: {processed_count}/{total_images} processed (Skipped: {skipped_count})")
        sys.stdout.flush()

    print(f"\n\nDone! Your Edge Impulse data is ready in: {OUTPUT_DIR}")

if __name__ == "__main__":
    create_ei_metadata()
import os
import random
import shutil
from collections import defaultdict
from pathlib import Path
from PIL import Image
import imagehash

# Configuration
DATASET_DIR = Path("datasets/merged_dataset/ei_upload")
TRAIN_RATIO = 0.8
RANDOM_SEED = 42
# How similar do backgrounds need to be to be considered the "same place"?
# Lower number = stricter (must look almost identical). Higher number = more loose.
HAMMING_THRESHOLD = 10 

def split_dataset_by_background():
    if not DATASET_DIR.exists():
        print(f"Error: Directory '{DATASET_DIR}' does not exist.")
        return

    print("Step 1: Creating visual fingerprints for all images (this may take a minute)...")
    valid_pairs = []
    for file_path in DATASET_DIR.iterdir():
        if file_path.is_file() and file_path.suffix.lower() in ['.jpg', '.jpeg', '.png']:
            json_path = file_path.with_suffix('.json')
            if json_path.exists():
                try:
                    # Create a fingerprint of the image
                    img_hash = imagehash.phash(Image.open(file_path))
                    valid_pairs.append((str(img_hash), file_path, json_path))
                except Exception as e:
                    print(f"Could not process {file_path.name}: {e}")

    if not valid_pairs:
        print("No valid image/JSON pairs found.")
        return

    # 2. Sort images by their visual fingerprint!
    # This puts images with the exact same background right next to each other.
    valid_pairs.sort(key=lambda x: x[0])

    print("Step 2: Grouping similar backgrounds together...")
    groups = []
    current_group = [valid_pairs[0]]
    
    for i in range(1, len(valid_pairs)):
        current_hash = imagehash.hex_to_hash(valid_pairs[i][0])
        prev_hash = imagehash.hex_to_hash(valid_pairs[i-1][0])
        
        # If the difference between fingerprints is small, they are the same place
        if (current_hash - prev_hash) < HAMMING_THRESHOLD:
            current_group.append(valid_pairs[i])
        else:
            # Background changed, save the current group and start a new one
            groups.append(current_group)
            current_group = [valid_pairs[i]]
    groups.append(current_group) # Add the final group

    print(f"Found {len(groups)} unique scene locations.")

    # 3. Shuffle the groups (not the individual images)
    random.seed(RANDOM_SEED)
    random.shuffle(groups)

    # 4. Calculate split sizes based on the number of unique scenes
    total_scenes = len(groups)
    train_scene_count = int(total_scenes * TRAIN_RATIO)
    
    train_groups = groups[:train_scene_count]
    test_groups = groups[train_scene_count:]

    # 5. Create directories
    train_dir = DATASET_DIR / "training"
    test_dir = DATASET_DIR / "testing"
    train_dir.mkdir(exist_ok=True)
    test_dir.mkdir(exist_ok=True)

    # 6. Move files
    train_count = 0
    test_count = 0

    print("Step 3: Moving files to training and testing folders...")
    for group in train_groups:
        for _, img, json_file in group:
            shutil.move(str(img), str(train_dir / img.name))
            shutil.move(str(json_file), str(train_dir / json_file.name))
            train_count += 1

    for group in test_groups:
        for _, img, json_file in group:
            shutil.move(str(img), str(test_dir / img.name))
            shutil.move(str(json_file), str(test_dir / json_file.name))
            test_count += 1

    print("\n✅ Dataset successfully split by background scene (No Data Leakage)!")
    print(f"Unique Training Scenes: {len(train_groups)} ({train_count} images)")
    print(f"Unique Testing Scenes:  {len(test_groups)} ({test_count} images)")

if __name__ == "__main__":
    split_dataset_by_background()
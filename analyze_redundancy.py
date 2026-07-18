"""One-off dataset redundancy analysis.

Hashes every image with a 64-bit perceptual hash (pHash), clusters near-
duplicates at several Hamming-distance thresholds, prints how much of the
dataset is redundant, and saves a montage of the biggest duplicate clusters.
"""
import time
from pathlib import Path

import numpy as np
from PIL import Image
import imagehash

IMAGES_DIR = Path("datasets/merged_dataset/images")
THRESHOLDS = [2, 5, 8, 10]      # Hamming distance on 64-bit pHash
MONTAGE_THR = 8                 # threshold used to pick clusters to show
MONTAGE_CLUSTERS = 6            # number of biggest clusters to display
MONTAGE_PER = 8                 # thumbnails per cluster (row)
THUMB = 128
OUT_PNG = Path("datasets/redundancy_clusters.png")


def main():
    paths = sorted(IMAGES_DIR.glob("*.jpg"))
    if not paths:
        print(f"No images in {IMAGES_DIR.resolve()}")
        return
    print(f"Found {len(paths)} images. Hashing (pHash)...")

    packed_list, kept = [], []
    t0 = time.time()
    for i, p in enumerate(paths):
        try:
            h = imagehash.phash(Image.open(p))          # 8x8 bool
            packed_list.append(np.packbits(h.hash.flatten()))
            kept.append(p)
        except Exception as e:  # noqa: BLE001 - skip unreadable files
            print(f"  skip {p.name}: {e}")
        if (i + 1) % 2000 == 0:
            print(f"  hashed {i + 1}/{len(paths)}  ({time.time() - t0:.0f}s)")

    packed = np.array(packed_list, dtype=np.uint8)       # (N, 8)
    N = len(packed)
    print(f"Hashed {N} images in {time.time() - t0:.0f}s\n")

    popcount = np.array([bin(x).count("1") for x in range(256)], dtype=np.uint16)

    parent = {thr: np.arange(N) for thr in THRESHOLDS}

    def find(par, x):
        while par[x] != x:
            par[x] = par[par[x]]
            x = par[x]
        return x

    def union(par, a, b):
        ra, rb = find(par, a), find(par, b)
        if ra != rb:
            par[rb] = ra

    print("Clustering near-duplicates...")
    t0 = time.time()
    for i in range(N):
        dist = popcount[packed ^ packed[i]].sum(axis=1)   # (N,)
        dist[: i + 1] = 255                               # only j > i
        for thr in THRESHOLDS:
            par = parent[thr]
            for j in np.where(dist <= thr)[0]:
                union(par, i, int(j))
        if (i + 1) % 2000 == 0:
            print(f"  clustered {i + 1}/{N}  ({time.time() - t0:.0f}s)")

    print("\nRedundancy by similarity threshold (0 = identical, higher = looser):")
    print(f"{'thr':>4} {'distinct':>9} {'redundant':>10} {'%redundant':>11}")
    cluster_data = {}
    for thr in THRESHOLDS:
        par = parent[thr]
        roots = np.array([find(par, i) for i in range(N)])
        uniq, counts = np.unique(roots, return_counts=True)
        redundant = N - len(uniq)
        print(f"{thr:>4} {len(uniq):>9} {redundant:>10} {100 * redundant / N:>10.1f}%")
        cluster_data[thr] = (roots, uniq, counts)

    roots, uniq, counts = cluster_data[MONTAGE_THR]
    order = np.argsort(-counts)
    print(f"\nBiggest near-duplicate clusters at thr={MONTAGE_THR}:")
    big = []
    for k in order[:MONTAGE_CLUSTERS]:
        members = [kept[idx] for idx in np.where(roots == uniq[k])[0]]
        big.append(members)
        print(f"  {counts[k]:>4} near-identical frames  (e.g. {members[0].name})")

    singletons = int((counts == 1).sum())
    print(f"\nUnique one-off images (no near-duplicate) at thr={MONTAGE_THR}: {singletons}")

    rows = len(big)
    canvas = Image.new("RGB", (MONTAGE_PER * THUMB, rows * THUMB), (20, 20, 20))
    for r, members in enumerate(big):
        for c in range(min(MONTAGE_PER, len(members))):
            try:
                im = Image.open(members[c]).convert("RGB").resize((THUMB, THUMB))
                canvas.paste(im, (c * THUMB, r * THUMB))
            except Exception:  # noqa: BLE001
                pass
    OUT_PNG.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT_PNG)
    print(f"\nSaved montage -> {OUT_PNG.resolve()}")
    print("Each row = one cluster of near-identical frames (redundant data).")


if __name__ == "__main__":
    main()

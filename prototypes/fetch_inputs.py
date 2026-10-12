"""Fetch the renderer's inputs with full provenance and register them in the manifest.

Replaces the prototype's hand-placed files (lot.png, s02_diff.jpg, s05_diff.jpg,
hi_diff.jpg, hi_disp.jpg), whose sources were unknown, with:

  - Poly Haven snow_02 (fresh) and snow_05 (dirty road snow), CC0, Rob Tuytel
  - Wikimedia Commons "Wet Prius, alone in an empty parking lot", CC BY 2.0,
    Angelo DeSantis: an elevated, CCTV-like view of a snow-free lot

Raw downloads go to raw/harvested/<source>/, derived texture tiles to
textures/<material>/ (registered as texture patches with their parent), and
scene files in prototypes/scenes/ reference them by data-root-relative path.

    python prototypes/fetch_inputs.py [--config config/default.yaml]
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.request
from pathlib import Path

import cv2
import numpy as np

from snowcv.core import (
    AssetRecord,
    DuplicateAssetError,
    Kind,
    Layout,
    Manifest,
    file_sha256,
    load_config,
    load_schema,
)

MODULE = "prototypes.fetch_inputs"
UA = {"User-Agent": "snowcv-research/0.1 (dataset tooling; contact via repository owner)"}
CC0_URL = "https://creativecommons.org/publicdomain/zero/1.0/"

POLYHAVEN = {
    # asset: maps to fetch (4k jpg). Real-world size comes from the API (mm).
    "snow_02": ("Diffuse", "Displacement"),
    "snow_05": ("Diffuse",),
}

# Metadata verified on 2026-10-12 via the Openverse API (Commons API was rate-limiting).
COMMONS_LOT = {
    "title": "File:Wet Prius, alone in an empty parking lot (9927867963).jpg",
    "page": "https://commons.wikimedia.org/w/index.php?curid=28572155",
    "author": "Angelo DeSantis from Berkeley, US (Flickr 78023771@N00)",
    "licence": "CC BY 2.0",
    "licence_url": "https://creativecommons.org/licenses/by/2.0/",
    "original": "https://upload.wikimedia.org/wikipedia/commons/9/91/Wet_Prius%2C_alone_in_an_empty_parking_lot_%289927867963%29.jpg",
    "thumb": "https://thumb.wikimedia.org/wikipedia/commons/thumb/9/91/Wet_Prius%2C_alone_in_an_empty_parking_lot_%289927867963%29.jpg/1280px-Wet_Prius%2C_alone_in_an_empty_parking_lot_%289927867963%29.jpg",
    "meta": {
        "flickr_id": "9927867963",
        "openverse_id": "4df8bed4-1e8f-4abf-96a0-720c5389d55a",
        "original_size": [2500, 1895],
        "privacy_note": "one parked car; number plate not legible at working resolution; no people",
    },
}


def get(url: str, retries: int = 5) -> bytes:
    for attempt in range(retries):
        try:
            with urllib.request.urlopen(urllib.request.Request(url, headers=UA), timeout=120) as r:
                return r.read()
        except Exception as e:  # noqa: BLE001 - retried, then re-raised
            if attempt == retries - 1:
                raise
            wait = 5 * 2**attempt
            print(f"  {e}; retry in {wait}s", file=sys.stderr)
            time.sleep(wait)
    raise AssertionError("unreachable")


def register(m: Manifest, rec: AssetRecord, **kw) -> AssetRecord:
    try:
        return m.add_asset(rec, module=MODULE, **kw)
    except DuplicateAssetError as e:
        return m.get(e.existing_id)


def fetch_polyhaven(m: Manifest, layout: Layout) -> dict[str, AssetRecord]:
    out = {}
    for asset, maps in POLYHAVEN.items():
        info = json.loads(get(f"https://api.polyhaven.com/info/{asset}"))
        files = json.loads(get(f"https://api.polyhaven.com/files/{asset}"))
        author = ", ".join(info["authors"])
        size_m = [d / 1000 for d in info["dimensions"]]  # API gives millimetres
        for mp in maps:
            url = files[mp]["4k"]["jpg"]["url"]
            source_id = f"{asset}/{mp.lower()}/4k"
            existing = m.find("polyhaven", source_id)
            if existing:
                out[f"{asset}:{mp}"] = existing
                continue
            path = layout.raw_harvested("polyhaven", Path(url).name)
            path.parent.mkdir(parents=True, exist_ok=True)
            print(f"polyhaven {asset} {mp}")
            path.write_bytes(get(url))
            h, w = cv2.imread(str(path), cv2.IMREAD_UNCHANGED).shape[:2]
            out[f"{asset}:{mp}"] = register(
                m,
                AssetRecord(
                    origin="harvested", source="polyhaven", source_id=source_id,
                    url=f"https://polyhaven.com/a/{asset}", author=author,
                    licence="CC0", licence_url=CC0_URL,
                    path=layout.rel(path), sha256=file_sha256(path), width=w, height=h,
                    meta={"map": mp.lower(), "real_size_m": size_m, "download_url": url,
                          "categories": info.get("categories", [])},
                ),
            )
    return out


def fetch_lot(m: Manifest, layout: Layout) -> AssetRecord:
    existing = m.find("wikimedia", COMMONS_LOT["title"])
    if existing:
        return existing
    path = layout.raw_harvested("wikimedia", "wet_prius_empty_parking_lot_9927867963.jpg")
    path.parent.mkdir(parents=True, exist_ok=True)
    # Wikimedia asks automated clients to use standard thumbnail sizes (https://w.wiki/GHai);
    # 1280 px is enough for the renderer's 1000 px working width.
    data, used = get(COMMONS_LOT["thumb"]), "thumb_1280"
    path.write_bytes(data)
    h, w = cv2.imread(str(path)).shape[:2]
    print(f"wikimedia lot ({used}, {w}x{h})")
    return register(
        m,
        AssetRecord(
            origin="harvested", source="wikimedia", source_id=COMMONS_LOT["title"],
            url=COMMONS_LOT["page"], author=COMMONS_LOT["author"],
            licence=COMMONS_LOT["licence"], licence_url=COMMONS_LOT["licence_url"],
            path=layout.rel(path), sha256=file_sha256(path), width=w, height=h,
            meta={**COMMONS_LOT["meta"], "downloaded": used},
        ),
    )


def make_patch(m, layout, parent: AssetRecord, material: str, patch_id: str, img: np.ndarray, ppm: float, **meta):
    path = layout.texture(material, patch_id)
    path.parent.mkdir(parents=True, exist_ok=True)
    cv2.imwrite(str(path), img)
    return register(
        m,
        AssetRecord(
            kind=Kind.TEXTURE_PATCH, origin="harvested", source="proto_inputs",
            url=parent.url, author=parent.author, licence=parent.licence, licence_url=parent.licence_url,
            path=layout.rel(path), sha256=file_sha256(path), width=img.shape[1], height=img.shape[0],
            meta={"material": material, "px_per_metre": ppm, **meta},
        ),
        parents=[(parent.asset_id, "source")],
    )


def derive_tiles(m: Manifest, layout: Layout, ph: dict[str, AssetRecord]) -> dict[str, AssetRecord]:
    """Renderer tiles at the resolutions render_snow_v2.py expects."""
    out = {}
    d02, disp02, d05 = ph["snow_02:Diffuse"], ph["snow_02:Displacement"], ph["snow_05:Diffuse"]
    s02 = d02.meta["real_size_m"][0]
    s05 = d05.meta["real_size_m"][0]
    img02 = cv2.imread(str(layout.abs(d02.path)))
    img05 = cv2.imread(str(layout.abs(d05.path)))
    dsp02 = cv2.imread(str(layout.abs(disp02.path)), cv2.IMREAD_GRAYSCALE)

    def tile(img, size_m, ppm):
        n = int(round(size_m * ppm))
        return cv2.resize(img, (n, n), interpolation=cv2.INTER_AREA)

    out["fresh"] = make_patch(m, layout, d02, "fresh", "snow02_tile_128ppm", tile(img02, s02, 128), 128.0,
                              crop_m=[0, 0, s02, s02])
    out["dirty"] = make_patch(m, layout, d05, "dirty", "snow05_tile_96ppm", tile(img05, s05, 96), 96.0,
                              crop_m=[0, 0, s05, s05])
    # 0.5 m high-res crop for near-field detail, 512 px/m, plus the matching displacement crop
    ppm_src = img02.shape[1] / s02
    n = int(round(0.5 * ppm_src))
    y0 = x0 = int(round(0.6 * ppm_src))
    hi = cv2.resize(img02[y0:y0 + n, x0:x0 + n], (256, 256), interpolation=cv2.INTER_AREA)
    hd = cv2.resize(dsp02[y0:y0 + n, x0:x0 + n], (256, 256), interpolation=cv2.INTER_AREA)
    crop = [x0 / ppm_src, y0 / ppm_src, (x0 + n) / ppm_src, (y0 + n) / ppm_src]
    out["hi_diff"] = make_patch(m, layout, d02, "fresh", "snow02_hi_512ppm", hi, 512.0, crop_m=crop)
    out["hi_disp"] = make_patch(m, layout, disp02, "fresh", "snow02_hi_disp_512ppm", hd, 512.0, crop_m=crop,
                                map="displacement")
    return out


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--config")
    args = ap.parse_args(argv)
    cfg, schema = load_config(args.config), load_schema()
    layout = Layout(cfg.data_root, schema)
    layout.ensure()
    with Manifest.open(cfg, schema) as m:
        ph = fetch_polyhaven(m, layout)
        lot = fetch_lot(m, layout)
        tiles = derive_tiles(m, layout, ph)
        summary = {"lot": lot.asset_id, **{k: v.asset_id for k, v in tiles.items()}}
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

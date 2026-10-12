"""
First-shot snow renderer: procedural snow masks (metric, top-down) -> photoreal-ish
composite on a real snow-free parking-lot photo, with exact labels.

Pipeline
  1. Ground plane: homography image <-> metres, fitted from 4 stall-marking points.
  2. Surface mask: lot polygon minus posts / cones / signs (colour heuristics).
  3. Snow material map in a top-down grid (generator from snowmask_proto.py),
     coverage targeted inside an inspection zone, measured in ground area (m²).
  4. Rendering in LINEAR light:
       illumination S = blur(inpainted ground) / ground_albedo   (shadows, sky tint, lamps)
       snow = S * albedo(material) * texture_detail * relief_shading
       texture sampled perspective-correctly from ground coords, mip-mapped by footprint
     plus contact darkening and wet rims on the bare ground around snow.
  5. Camera matching: slight blur, signal-dependent noise, JPEG re-encode.

Textures: Poly Haven snow_02 (fresh) and snow_05 (dirty, road) — CC0.
"""
import argparse
import json
import sys
from pathlib import Path

import numpy as np
import cv2
from scipy import ndimage as ndi
import snowmask_proto as G

rng_master = np.random.default_rng(7)

# Scene-specific values (photo, ground geometry, lot layout, textures) are read from a
# scene JSON by setup(); see scenes/original_lot.json (the photo this prototype was tuned
# on) and scenes/wet_prius.json. The globals below are filled in by setup().
SCENE = None
IMG = H_IMG = W_IMG = H_i2m = None
P = X0 = Y0 = BW = BH = None
GROUND_ALBEDO = INSPECTION_ZONE = HC = None
SNOW_ALBEDO = np.array([0.86, 0.84, 0.82])            # BGR, fresh snow ~0.8-0.9, faintly blue


def _config_path(scene):
    """Scene 'config' > $SNOWCV_CONFIG > the repository's config/default.yaml."""
    import os
    return scene.get("config") or os.environ.get("SNOWCV_CONFIG") or str(Path(__file__).resolve().parents[1] / "config" / "default.yaml")


def _resolve(scene, rel):
    base = scene.get("paths_relative_to", "cwd")
    if base == "data_root":
        from snowcv.core import load_config
        return str(Path(load_config(_config_path(scene)).data_root) / rel)
    if base == "scene_dir":
        return str(Path(scene["_dir"]) / rel)
    return rel


def setup(scene_path):
    """Load a scene JSON and derive all per-photo globals the pipeline uses."""
    global SCENE, IMG, H_IMG, W_IMG, H_i2m, P, X0, Y0, BW, BH, GROUND_ALBEDO, INSPECTION_ZONE, HC
    global uu, vv, GX, GY, FOOT, BEV_MX, BEV_MY, FRESH_T, DIRTY_T, TEX_PPM, HI_T, HI_PPM, RELIEF_T, V_HOR
    SCENE = json.load(open(scene_path))
    SCENE["_dir"] = str(Path(scene_path).resolve().parent)
    IMG = cv2.imread(_resolve(SCENE, SCENE["image"]))       # BGR uint8
    if IMG is None:
        raise FileNotFoundError(_resolve(SCENE, SCENE["image"]))
    if SCENE.get("work_size"):
        IMG = cv2.resize(IMG, tuple(SCENE["work_size"]), interpolation=cv2.INTER_AREA)
    H_IMG, W_IMG = IMG.shape[:2]
    if "H_i2m" in SCENE:                                     # image px -> ground metres
        H_i2m = np.array(SCENE["H_i2m"], np.float64)
    else:
        H_i2m = cv2.getPerspectiveTransform(np.float32(SCENE["src_px"]), np.float32(SCENE["dst_m"]))
    b = SCENE["bev"]                                         # BEV grid (metres -> px)
    P, X0, Y0, BW, BH = b["px_per_m"], b["x0_m"], b["y0_m"], b["width_m"], b["height_m"]
    G.PX_PER_M = P                                           # generator works at the same resolution
    GROUND_ALBEDO = SCENE["ground_albedo"]
    INSPECTION_ZONE = tuple(SCENE["inspection_zone_m"])      # x0,y0,x1,y1 metres: where coverage is scored
    HC = SCENE["camera_height_m"]                            # sets parallax of snow thickness

    # ground coords
    uu, vv = np.meshgrid(np.arange(W_IMG, dtype=np.float32), np.arange(H_IMG, dtype=np.float32))
    pts = np.stack([uu, vv], -1).reshape(-1, 1, 2)
    gm = cv2.perspectiveTransform(pts, H_i2m).reshape(H_IMG, W_IMG, 2)   # metres per image pixel
    GX, GY = gm[..., 0], gm[..., 1]
    # footprint: metres covered by one image pixel (sqrt of Jacobian determinant)
    dxu, dxv = np.gradient(GX, axis=1), np.gradient(GX, axis=0)
    dyu, dyv = np.gradient(GY, axis=1), np.gradient(GY, axis=0)
    FOOT = np.sqrt(np.abs(dxu * dyv - dxv * dyu)) + 1e-6
    BEV_MX = ((GX - X0) * P).astype(np.float32)           # image pixel -> BEV pixel (for remap)
    BEV_MY = ((GY - Y0) * P).astype(np.float32)

    # textures
    t = SCENE["textures"]
    FRESH_T = load_tile(_resolve(SCENE, t["fresh"]["path"]))
    DIRTY_T = load_tile(_resolve(SCENE, t["dirty"]["path"]), crop=t["dirty"].get("crop_cols"))
    TEX_PPM = {"fresh": t["fresh"]["ppm"], "dirty": t["dirty"]["ppm"]}
    # high-res real snow + its displacement -> micro-relief shading tile
    HI_T = load_tile(_resolve(SCENE, t["hi_diff"]["path"]))
    HI_PPM = t["hi_diff"]["ppm"]
    disp = cv2.imread(_resolve(SCENE, t["hi_disp"]["path"]), cv2.IMREAD_GRAYSCALE).astype(np.float32) / 255.0
    disp_m = (disp - disp.mean()) * t["hi_disp"].get("relief_amp_m", 0.02)
    gy_, gx_ = np.gradient(disp_m * HI_PPM)                  # slope (m/m)
    n = np.dstack([-gx_, -gy_, np.ones_like(disp_m)]); n /= np.linalg.norm(n, axis=2, keepdims=True)
    L = np.array([0.15, -0.55, 0.82]); L /= np.linalg.norm(L)
    sh = 0.55 + 0.45 * np.clip((n * L).sum(2), 0, 1) / L[2]
    RELIEF_T = np.repeat((sh / sh.mean())[..., None], 3, axis=2).astype(np.float32)

    h = H_i2m[2]                                             # horizon: row where h31*u + h32*v + h33 = 0
    V_HOR = float(-(h[0] * (W_IMG / 2) + h[2]) / h[1])


def srgb_to_lin(x):
    x = x.astype(np.float32) / 255.0
    return np.where(x <= 0.04045, x / 12.92, ((x + 0.055) / 1.055) ** 2.4)


def lin_to_srgb(x):
    x = np.clip(x, 0, 1)
    y = np.where(x <= 0.0031308, x * 12.92, 1.055 * x ** (1 / 2.4) - 0.055)
    return (y * 255 + 0.5).astype(np.uint8)


# ---------------------------------------------------------- surface mask ----
def surface_mask():
    sc = SCENE["surface"]
    m = np.zeros((H_IMG, W_IMG), np.uint8)
    cv2.fillPoly(m, [np.int32(sc["polygon"])], 1)
    obstacles = np.zeros((H_IMG, W_IMG), np.uint8)
    heur = sc.get("heuristics")
    if heur:                                           # colour heuristics tuned on the original lot photo
        far = heur["far_row_max"]
        hsv = cv2.cvtColor(IMG, cv2.COLOR_BGR2HSV)
        orange = cv2.inRange(hsv, (0, 110, 90), (16, 255, 255)) | cv2.inRange(hsv, (165, 110, 90), (180, 255, 255))
        yellow = cv2.inRange(hsv, (15, 80, 120), (35, 255, 255))
        n, lab, st, _ = cv2.connectedComponentsWithStats(yellow)
        posts = np.zeros_like(yellow)
        for i in range(1, n):                          # compact blobs = posts/blocks; long thin = paint
            x, y, w, h, a = st[i]
            if y < far and a < 600 and h >= 7 and h >= w * 1.3 and max(w, h) < 40:   # upright posts only
                posts[lab == i] = 255
        orange[far:] = 0                               # cones/signs live at the far edge; paint is near
        obstacles |= cv2.dilate(orange | posts, np.ones((5, 5), np.uint8))
        # dark vertical clutter at the far edge (pole base, sign, bollards): very dark pixels near horizon
        dark = ((IMG.mean(2) < 45) & (vv < heur["dark_row_max"])).astype(np.uint8) * 255
        obstacles |= cv2.dilate(dark, np.ones((3, 3), np.uint8))
    for poly in sc.get("exclude_polygons", []):        # hand-drawn occluders (cars, planters, ...)
        cv2.fillPoly(obstacles, [np.int32(poly)], 255)
    k = sc.get("exclude_dilate_px", 0)
    if k:
        obstacles = cv2.dilate(obstacles, np.ones((2 * k + 1, 2 * k + 1), np.uint8))
    m[obstacles > 0] = 0
    return m.astype(bool)


# --------------------------------------------------------- BEV layout -------
def bev_layout(img_surface):
    w, h = G.m(BW), G.m(BH)
    Hm = np.array([[P, 0, -X0 * P], [0, P, -Y0 * P], [0, 0, 1]], np.float64) @ H_i2m
    surf = cv2.warpPerspective(img_surface.astype(np.uint8), Hm, (w, h), flags=cv2.INTER_NEAREST) > 0
    surf = ndi.binary_closing(surf, iterations=2)
    lay = SCENE["layout"]                              # metric ground frame; shifted to BEV origin here
    sw = lay["stall_w_m"]
    aisles = [(a - Y0, b - Y0) for a, b in lay["aisles_m"]]
    stalls = [(x - X0, a - Y0, x + sw - X0, b - Y0)
              for r in lay["stall_rows"] for a, b in [r["y_m"]] for x in np.arange(r["x_m"][0], r["x_m"][1], sw)]
    return dict(W=BW, H=BH, surface=surf, aisles=aisles, stalls=stalls, stall_w=sw)


def bev_zone(shape):
    zx0, zy0, zx1, zy1 = INSPECTION_ZONE
    z = np.zeros(shape, bool)
    z[G.m(zy0 - Y0):G.m(zy1 - Y0), G.m(zx0 - X0):G.m(zx1 - X0)] = True
    return z


def edge_piles(lay, rng, n):
    """Piles pushed against the real lot boundary, inside the visible zone."""
    surf = lay['surface']
    zone = bev_zone(surf.shape)
    edge = surf & ~ndi.binary_erosion(surf, iterations=2) & zone
    ys, xs = np.nonzero(edge)
    out = np.zeros_like(surf)
    if len(xs) == 0 or n == 0:
        return out
    hh, ww = surf.shape
    yy, xx = np.mgrid[0:hh, 0:ww]
    for _ in range(n):
        k = rng.integers(len(xs))
        r = rng.uniform(2.0, 4.0) * P
        noise = G.fbm(hh, ww, 2.0, 3, rng)
        out |= np.hypot(xx - xs[k], yy - ys[k]) < r * (0.7 + 0.6 * noise)
    return out & surf


def make_material(lay, target, scenario, rng):
    """Same layer logic as the generator, coverage scored in the inspection zone (ground m²)."""
    surf = lay['surface']
    hh, ww = surf.shape
    zone = bev_zone(surf.shape) & surf
    dist_edge = ndi.distance_transform_edt(np.pad(surf, 1))[1:-1, 1:-1] / P
    for _ in range(25):
        depth = G.fbm(hh, ww, base_m=rng.uniform(4, 10), octaves=5, rng=rng)
        depth += 0.35 * np.exp(-dist_edge / rng.uniform(1.5, 4.0))
        snow, ridges = surf.copy(), np.zeros_like(surf)
        if scenario != 'uncleared':
            frac = rng.uniform(0.2, 0.45) if scenario == 'partial' else rng.uniform(0.7, 0.95)
            snow, ridges = G.plow(snow, lay, rng, frac, rng.uniform(2.5, 3.5))
        pile = edge_piles(lay, rng, rng.integers(1, 3)) if scenario != 'uncleared' else np.zeros_like(surf)
        vis_aisles = [a for a in lay['aisles'] if a[1] > SCENE['track_aisle_min_y_m'] - Y0]  # aisles in the visible range
        tracks = G.tire_tracks(dict(lay, aisles=vis_aisles), rng, rng.integers(10, 20))
        paths = G.footpaths(lay, rng, rng.integers(1, 4))
        mat = np.full((hh, ww), G.BARE, np.uint8)
        mat[snow] = G.FRESH
        mat[ridges] = G.FRESH
        mat[(tracks | paths) & snow] = G.PACKED
        mat[pile] = G.PILE
        mat[~surf] = G.BARE
        cov = lambda mm: np.isin(mm, G.COUNTED)[zone].mean()

        def melt(t):
            mm = mat.copy()
            mlt = (depth < t) & np.isin(mm, (G.FRESH, G.PACKED))
            mm[mlt] = G.BARE
            rim = ndi.binary_dilation(mlt, iterations=G.m(0.3)) & np.isin(mm, (G.FRESH, G.PACKED))
            mm[rim & (rng.random(mm.shape) < 0.5)] = G.SLUSH
            return mm
        if cov(mat) < target:
            continue
        lo, hi = 0.0, 1.0
        for _ in range(18):
            mid = (lo + hi) / 2
            lo, hi = (mid, hi) if cov(melt(mid)) > target else (lo, mid)
        mm = G.roughen(melt((lo + hi) / 2), rng, amp_m=0.12, scale_m=0.5)
        mm[~surf] = G.BARE
        if abs(cov(mm) - target) < 0.03:
            return mm, depth, cov(mm)
    raise RuntimeError("target coverage not reachable")


# ------------------------------------------------------------ textures ------
def load_tile(path, crop=None):
    t = cv2.imread(path).astype(np.float32)
    if crop:
        x0, x1 = crop
        t = t[:, x0:x1]
    t = srgb_to_lin(t.astype(np.uint8))
    ref = np.percentile(t.reshape(-1, 3), 90, axis=0)     # "clean snow" reference of this photo
    return np.clip(t / ref, 0, 1.25)                     # relative albedo detail, keeps dirt chroma


def sample_tile(tile, ppm, gx, gy, foot, angle, offset):
    """Perspective-correct, mip-mapped tile sampling in ground coordinates (BORDER_WRAP tiling)."""
    c, s = np.cos(angle), np.sin(angle)
    tx = (c * gx - s * gy + offset[0]) * ppm
    ty = (s * gx + c * gy + offset[1]) * ppm
    level = np.clip(np.log2(foot * ppm + 1e-6), 0, 6)
    pyr = [tile]
    for _ in range(6):
        pyr.append(cv2.pyrDown(pyr[-1]) if min(pyr[-1].shape[:2]) > 4 else pyr[-1])
    out = np.zeros(gx.shape + (3,), np.float32)
    for l, t in enumerate(pyr):
        w = np.clip(1 - np.abs(level - l), 0, 1)[..., None]
        if w.max() == 0:
            continue
        sc = t.shape[1] / tile.shape[1]
        smp = cv2.remap(t, (tx * sc).astype(np.float32), (ty * sc).astype(np.float32),
                        cv2.INTER_LINEAR, borderMode=cv2.BORDER_WRAP)
        out += w * smp
    return out


# ------------------------------------------------------------- render -------
def context_mask():
    """Ground-like pixels beyond the lot edge (curbs, islands, far lots) in the band below the horizon."""
    hsv = cv2.cvtColor(IMG, cv2.COLOR_BGR2HSV)
    # only the strip just past the lot edge (curb, tree islands, sidewalk): a thin band above the lot polygon
    top = np.argmax(SURF, axis=0)                                     # first lot row per column
    c = SCENE['context']
    band = (vv >= top[None, :] - c['band_px']) & (vv < top[None, :]) & (vv > c['min_row'])
    groundish = (hsv[..., 1] < 60) & (IMG.mean(2) > 55) & (hsv[..., 2] < 220)
    m = band & groundish & ~SURF
    return ndi.binary_opening(m, iterations=1)


def remap_img(a, dv):
    """Sample image-space map a at (u, v + dv) — vertical parallax shift."""
    return cv2.remap(a, uu, vv + dv.astype(np.float32), cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE)


def render(mat_bev, depth_bev, rng, ctx_cov):
    img_lin = srgb_to_lin(IMG)
    surf = SURF
    toimg = lambda a, bv=0: cv2.remap(a.astype(np.float32), BEV_MX, BEV_MY, cv2.INTER_LINEAR, borderValue=bv)

    # 1) illumination from cleaned ground (log-domain low-pass)
    hsv = cv2.cvtColor(IMG, cv2.COLOR_BGR2HSV)
    paint = cv2.inRange(hsv, (15, 60, 90), (35, 255, 255)) | cv2.inRange(hsv, (0, 0, 175), (180, 50, 255))
    for poly in SCENE["surface"].get("exclude_polygons", []):   # occluders are not ground: keep them out too
        cv2.fillPoly(paint, [np.int32(poly)], 255)
    paint = cv2.dilate(paint, np.ones((5, 5), np.uint8))
    clean = cv2.inpaint(IMG, paint, 6, cv2.INPAINT_TELEA)
    il = SCENE.get("illum", {})
    illum = np.exp(cv2.GaussianBlur(np.log(srgb_to_lin(clean) + 1e-3), (0, 0), il.get("blur_px", 12))) / GROUND_ALBEDO
    if "band" in il:                                       # wet / specular ground: brightness swings are mostly
        lum = illum.mean(2)                                # reflections and wet patches, not light. Keep only a
        med = np.median(lum[surf])                         # narrow band around the lot median.
        lo, hi = med * il["band"][0], med * il["band"][1]
        illum = illum * (np.clip(lum, lo, hi) / (lum + 1e-6))[..., None]

    # 2) wet / slush ruts: part of the tyre tracks are worn through to wet pavement
    mat_bev = mat_bev.copy()
    wet_ruts = (mat_bev == G.PACKED) & (G.fbm(*mat_bev.shape, 8.0, 3, rng) > 0.55)
    mat_bev[wet_ruts] = G.SLUSH

    # 3) footprint alpha with powdery feathered edges (BEV), plus snow thickness
    snowy_b = np.isin(mat_bev, (G.FRESH, G.PACKED, G.PILE))
    d_in = ndi.distance_transform_edt(snowy_b) / P
    feather = 0.03 + 0.25 * G.fbm(*mat_bev.shape, 3.0, 3, rng)
    grain = G.fbm(*mat_bev.shape, 0.15, 3, rng)
    ramp = np.clip(d_in / feather, 0, 1)
    snowy = np.clip(ramp * 1.6 - (1 - ramp) * (grain - 0.35) * 1.2, 0, 1) * snowy_b
    t0 = rng.uniform(0.05, 0.12)                                       # scene snow depth (m)
    thick = t0 * (0.7 + 0.6 * depth_bev) * np.clip(d_in / 0.12, 0.15, 1)   # thins toward edges
    thick = np.where(mat_bev == G.PACKED, thick * 0.35, thick)          # ruts are compacted
    thick += 0.8 * ndi.gaussian_filter((mat_bev == G.PILE).astype(np.float32), 1.0 * P)
    thick = ndi.gaussian_filter((thick * snowy_b).astype(np.float32), 0.03 * P)
    soft = lambda a: cv2.GaussianBlur(a.astype(np.float32), (0, 0), 0.04 * P + 0.5)
    alpha_g = toimg(soft(snowy)) * surf                                 # ground footprint
    a_sl = toimg(soft(mat_bev == G.SLUSH)) * surf
    far = np.clip((FOOT - 0.05) / 0.15, 0, 1)
    alpha_g = alpha_g * (1 - far) + cv2.GaussianBlur(alpha_g, (0, 0), 1.2) * far

    # 4) relief shading of the snow surface (BEV height field incl. ruts, ridges, piles)
    gy_, gx_ = np.gradient(thick * P)
    n = np.dstack([-gx_, -gy_, np.ones_like(thick)]); n /= np.linalg.norm(n, axis=2, keepdims=True)
    L = np.array([0.15, -0.55, 0.82]); L /= np.linalg.norm(L)
    shade = toimg((0.55 + 0.45 * np.clip((n * L).sum(2), 0, 1) / L[2]), 1.0)

    # 5) albedo: high-res real snow near, 2 m tiles mid-range, dirt on ruts/edges, large-scale variation
    ang, off = rng.uniform(0, np.pi), rng.uniform(0, 2, 2)
    # anti-tiling: three rotated/offset/rescaled samples, blended by a low-frequency noise partition
    wmap = toimg(G.fbm(*mat_bev.shape, 1.5, 3, rng))
    ws = [np.clip(1 - np.abs(wmap * 3 - k) , 0, 1) for k in (0.5, 1.5, 2.5)]
    wsum = sum(ws) + 1e-6
    hi = 0; relief = 0
    for k, (da, sc) in enumerate([(0.0, 1.0), (2.1, 0.83), (4.2, 1.21)]):
        o = off + np.array([0.37, 0.71]) * k
        hi = hi + (ws[k] / wsum)[..., None] * sample_tile(HI_T, HI_PPM * sc, GX, GY, FOOT, ang + da, o)
        relief = relief + (ws[k] / wsum)[..., None] * sample_tile(RELIEF_T, HI_PPM * sc, GX, GY, FOOT, ang + da, o)
    lo1 = sample_tile(FRESH_T, TEX_PPM["fresh"], GX, GY, FOOT, ang + 0.7, off[::-1])
    lo2 = sample_tile(FRESH_T, TEX_PPM["fresh"] * 0.37, GX, GY, FOOT, ang + 1.9, off)
    hi = 1 + 1.5 * (hi - hi.mean((0, 1)))
    lo = 1 + 0.9 * (cv2.GaussianBlur(0.6 * lo1 + 0.4 * lo2, (0, 0), 0.7) - 1)
    fresh = hi * lo * relief
    dirty = sample_tile(DIRTY_T, TEX_PPM["dirty"], GX, GY, FOOT, rng.uniform(-0.2, 0.2), off)
    rut = (mat_bev == G.PACKED).astype(np.float32)
    spray = ndi.gaussian_filter(ndi.binary_dilation(rut > 0, iterations=G.m(0.35)).astype(np.float32), 0.15 * P)
    dirt_bev = np.maximum.reduce([rut, 0.45 * spray, 0.35 * (G.fbm(*mat_bev.shape, 6.0, 4, rng) > 0.62)])
    dirt_w = toimg(ndi.gaussian_filter(dirt_bev, 0.08 * P))[..., None]
    packed = toimg(soft(rut))[..., None]
    big = toimg(G.fbm(*mat_bev.shape, 4.0, 4, rng))
    detail = (fresh * (1 - dirt_w) + dirty * dirt_w) * (0.9 + 0.2 * big)[..., None]
    albedo = SNOW_ALBEDO * detail * (1 - 0.45 * packed)
    snow_lin = illum * albedo * shade[..., None]

    # 6) thickness parallax: snow top appears shifted up by h*(v - v_horizon)/HC pixels
    h_img = toimg(thick) * surf
    dv = h_img * np.clip(vv - V_HOR, 0, None) / HC
    dv = remap_img(h_img, dv) * np.clip(vv - V_HOR, 0, None) / HC      # one fixed-point refinement
    a_top = remap_img(alpha_g, dv)
    top_col = remap_img(snow_lin, dv)
    a_wall = np.clip(alpha_g - a_top, 0, 1)                            # camera-facing vertical faces
    wall_col = snow_lin * 0.62 * np.array([1.06, 1.0, 0.94])           # less sky light, slightly bluer
    edge = np.clip(a_top - cv2.erode(a_top, np.ones((3, 3), np.uint8)), 0, 1)
    top_col = top_col * (1 + 0.08 * edge[..., None])                    # rounded lip catches light

    # 7) bare ground: contact darkening, wet rims, slush ruts
    vis = np.clip(a_top + a_wall, 0, 1)
    rim = cv2.GaussianBlur(alpha_g, (0, 0), 2.5)
    edge_g = np.clip(rim - alpha_g, 0, 1) * surf          # ground only: never darken occluders (cars, posts)
    ground = img_lin * (1 - 0.18 * edge_g)[..., None]
    wet = np.clip(a_sl + 0.6 * edge_g * (1 - alpha_g), 0, 1)[..., None]
    ground = ground * (1 - 0.35 * wet)
    slush_col = 0.55 * ground + 0.45 * illum * SNOW_ALBEDO * 0.3 * fresh
    ground = ground * (1 - a_sl[..., None]) + slush_col * a_sl[..., None]

    # 8) context: snow beyond the lot edge (not scored, but labelled as snow)
    ctx = CTX.astype(np.float32)
    noise = cv2.resize(G.fbm(40, 160, 1.0, 4, rng), (W_IMG, H_IMG))   # ground-foreshortened blobs
    a_ctx = ctx * np.clip((ctx_cov - noise) * 8 + 0.5, 0, 1)
    ctx_col = illum * SNOW_ALBEDO * lo

    out = ground * (1 - vis[..., None]) + top_col * a_top[..., None] + wall_col * a_wall[..., None]
    out = out * (1 - a_ctx[..., None]) + ctx_col * a_ctx[..., None]
    vis_all = np.clip(vis + a_ctx, 0, 1)

    # 9) camera matching
    out_s = lin_to_srgb(out).astype(np.float32)
    out_s = out_s * (1 - vis_all[..., None]) + cv2.GaussianBlur(out_s, (0, 0), 0.6) * vis_all[..., None]
    hp = IMG.astype(np.float32) - cv2.GaussianBlur(IMG.astype(np.float32), (0, 0), 1.5)
    y0, y1, x0, x1 = SCENE['noise_roi']                  # plain ground region for the noise estimate
    sigma0 = np.median(np.abs(hp[y0:y1, x0:x1])) * 1.48
    bright = out_s.mean(2, keepdims=True) / 128.0
    out_s += rng.normal(0, 1, out_s.shape) * sigma0 * np.sqrt(np.clip(bright, 0.3, 3)) * vis_all[..., None]
    ok, enc = cv2.imencode(".jpg", np.clip(out_s, 0, 255).astype(np.uint8), [cv2.IMWRITE_JPEG_QUALITY, 88])
    final = cv2.imdecode(enc, cv2.IMREAD_COLOR)
    label = vis_all > 0.5                     # every visible snow pixel (lot + context)
    footprint = (alpha_g > 0.5) & surf        # ground footprint inside the lot -> coverage %
    return final, label, footprint, mat_bev


def register_renders(out_dir, results):
    """Register renders as synthetic assets, linked to the background and texture tiles they used."""
    from snowcv.core import AssetRecord, Layout, Manifest, file_sha256, load_config, load_schema
    cfg, schema = load_config(_config_path(SCENE)), load_schema()
    layout = Layout(cfg.data_root, schema)
    with Manifest.open(cfg, schema) as m:
        def asset_for(rel):
            hits = list(m.query(path=rel))
            if not hits:
                raise SystemExit(f"input {rel} is not in the manifest; run prototypes/fetch_inputs.py first")
            return hits[0].asset_id
        parents = [(asset_for(SCENE["image"]), "background")]
        parents += [(asset_for(t["path"]), "texture") for t in SCENE["textures"].values()]
        for r in results:
            path = Path(out_dir) / r["image"]
            rec = m.add_asset(
                AssetRecord(origin="synthetic", source="m10_renderer_proto", licence="DERIVED",
                            path=layout.rel(path), sha256=file_sha256(path), width=W_IMG, height=H_IMG,
                            meta={k: v for k, v in r.items() if k != "image"} | {"scene": SCENE["name"]}),
                parents=parents, module="prototypes.render_snow_v2", params={"scene": SCENE["name"], "case": r["case"]},
            )
            print(f"registered {rec.asset_id}  {rec.path}")


if __name__ == "__main__":
    ap = argparse.ArgumentParser(description="Render snow onto a snow-free scene with exact labels.")
    ap.add_argument("--scene", default=str(Path(__file__).parent / "scenes" / "original_lot.json"))
    ap.add_argument("--out", default=".", help="output directory")
    ap.add_argument("--register", action="store_true", help="register renders in the manifest (out must be under the data root)")
    args = ap.parse_args()
    setup(args.scene)
    out = Path(args.out); out.mkdir(parents=True, exist_ok=True)
    SURF = surface_mask()
    CTX = context_mask()
    LAY = bev_layout(SURF)
    cases = [tuple(c) for c in SCENE.get("cases", [(0.08, "plowed", 0.5), (0.25, "plowed+melt", 0.6),
                                                       (0.50, "partial", 0.85), (0.85, "uncleared", 0.95)])]
    tiles, results = [], []
    zx0, zy0, zx1, zy1 = INSPECTION_ZONE
    inz = SURF & (GX > zx0) & (GX < zx1) & (GY > zy0) & (GY < zy1)
    zone_bev = bev_zone(LAY["surface"].shape) & LAY["surface"]
    area = FOOT ** 2
    for i, (t, scn, cc) in enumerate(cases):
        rng = np.random.default_rng(1000 + i)
        mat_bev, depth_bev, cov = make_material(LAY, t, scn, rng)
        img, label, foot, mat_final = render(mat_bev, depth_bev, rng, cc)
        name = f"v2_render_{i}_{scn}.jpg"
        cv2.imwrite(str(out / name), img, [cv2.IMWRITE_JPEG_QUALITY, 92])
        cv2.imwrite(str(out / f"v2_label_{i}_{scn}.png"), (label * 255).astype(np.uint8))
        lab_cov = (area * foot)[inz].sum() / area[inz].sum()
        cov_wet = np.isin(mat_final, G.COUNTED)[zone_bev].mean()      # after wet ruts turn PACKED -> SLUSH
        print(f"{scn:12s} target {t:.0%} | generator {cov:.1%} | after wet ruts {cov_wet:.1%} | footprint ground-area {lab_cov:.1%}")
        results.append(dict(case=i, scenario=scn, image=name, label=f"v2_label_{i}_{scn}.png", target=t,
                            generator_coverage=round(float(cov), 4), after_wet_ruts=round(float(cov_wet), 4),
                            label_ground_coverage=round(float(lab_cov), 4)))
        ov = img.copy()
        ov[label] = (0.45 * ov[label] + 0.55 * np.array([255, 120, 0])).astype(np.uint8)
        tiles.append((img, ov, scn, lab_cov))
    rows = []
    th = int(round(600 * H_IMG / W_IMG))
    for img, ov, scn, c in tiles:
        a, b = cv2.resize(img, (600, th)), cv2.resize(ov, (600, th))
        cv2.putText(a, f"{scn}: {c:.0%} of inspection zone", (12, 30), 0, 0.8, (255, 255, 255), 2)
        cv2.putText(b, "label overlay", (12, 30), 0, 0.8, (255, 255, 255), 2)
        rows.append(np.hstack([a, b]))
    cv2.imwrite(str(out / "v2_contact_sheet.jpg"), np.vstack(rows), [cv2.IMWRITE_JPEG_QUALITY, 88])
    json.dump({"scene": SCENE["name"], "cases": results}, open(out / "summary.json", "w"), indent=1)
    if args.register:
        register_renders(out, results)

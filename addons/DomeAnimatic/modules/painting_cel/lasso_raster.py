"""
lasso_raster.py — Pure numpy + GPU-texture helpers for the lasso transform.

No bpy/operator state lives here: every function takes explicit arguments and
returns numpy arrays or GPU textures. That keeps the pixel math unit-testable
in isolation from the modal operator.

See lasso_transform_ops.py for the operator that drives these functions and
lasso_draw.py for the on-screen GPU preview.
"""

import math

try:
    import gpu
except Exception:
    gpu = None

try:
    import numpy as np
except ImportError:
    np = None


# ── Image read / write ────────────────────────────────────────────────────────

def read_pixels(img) -> "np.ndarray":
    """Full image as (h, w, 4) float32 via foreach_get."""
    w, h = img.size
    buf  = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return buf.reshape(h, w, 4)


def write_pixels(img, buf) -> None:
    img.pixels.foreach_set(np.ascontiguousarray(buf, dtype=np.float32).ravel())
    img.update()


# ── Polygon rasterization ─────────────────────────────────────────────────────

def rasterize_polygon(points_px, bx0: int, by0: int, bw: int, bh: int) -> "np.ndarray":
    """Even-odd point-in-polygon mask (bh, bw) bool, tested at pixel centers."""
    yy, xx = np.mgrid[0:bh, 0:bw]
    xs = xx.astype(np.float32) + (bx0 + 0.5)
    ys = yy.astype(np.float32) + (by0 + 0.5)
    inside = np.zeros((bh, bw), dtype=bool)
    pts = np.asarray(points_px, dtype=np.float32)
    px1, py1 = pts[:, 0], pts[:, 1]
    px2, py2 = np.roll(px1, -1), np.roll(py1, -1)
    with np.errstate(divide='ignore', invalid='ignore'):
        for i in range(len(pts)):
            crosses = (py1[i] > ys) != (py2[i] > ys)
            if not crosses.any():
                continue
            x_at = (px2[i] - px1[i]) * (ys - py1[i]) / (py2[i] - py1[i]) + px1[i]
            inside ^= crosses & (xs < x_at)
    return inside


# ── GPU texture upload ────────────────────────────────────────────────────────

def make_texture(buf_hw4):
    """Upload a (h, w, 4) float32 numpy buffer as a GPUTexture (straight alpha)."""
    h, w = buf_hw4.shape[:2]
    flat = np.ascontiguousarray(buf_hw4, dtype=np.float32).ravel()
    data = gpu.types.Buffer('FLOAT', w * h * 4, flat)
    return gpu.types.GPUTexture((w, h), format='RGBA16F', data=data)


# ── Affine composite (the CPU bake) ───────────────────────────────────────────

def composite_float(dest_buf, patch, corners,
                    tx: float, ty: float, angle: float, scale: float,
                    bx0: int, by0: int) -> None:
    """Sample the floating `patch` through the inverse affine (bilinear,
    premultiplied) and alpha-over it into `dest_buf` — fully vectorized.
    Mutates dest_buf in place.

    Parameters mirror the operator's accumulated affine  p' = s*R(a)*p + t :
      patch    — (ph, pw, 4) float32 straight RGBA, alpha=0 outside the lasso
      corners  — the four transformed bbox corners in dest pixel space, used
                 only to bound the work region
      tx, ty   — translation      angle — rotation (rad)      scale — uniform
      bx0, by0 — patch origin in the source image (undoes the crop offset)
    """
    dh, dw = dest_buf.shape[:2]

    corners = np.asarray(corners, dtype=np.float64)
    dx0 = max(0,  int(math.floor(corners[:, 0].min())) - 1)
    dy0 = max(0,  int(math.floor(corners[:, 1].min())) - 1)
    dx1 = min(dw, int(math.ceil(corners[:, 0].max())) + 1)
    dy1 = min(dh, int(math.ceil(corners[:, 1].max())) + 1)
    if dx1 <= dx0 or dy1 <= dy0:
        return

    ph, pw = patch.shape[:2]

    # Inverse affine: p = R(-a) * (q - t) / s   at dest pixel centers
    yy, xx = np.mgrid[dy0:dy1, dx0:dx1]
    qx = xx.astype(np.float32) + 0.5 - tx
    qy = yy.astype(np.float32) + 0.5 - ty
    ca, sa = math.cos(angle), math.sin(angle)
    inv_s  = 1.0 / max(scale, 1e-6)
    u = ( ca * qx + sa * qy) * inv_s - bx0 - 0.5
    v = (-sa * qx + ca * qy) * inv_s - by0 - 0.5

    patch_pre = patch.copy()
    patch_pre[..., :3] *= patch_pre[..., 3:4]

    u0 = np.floor(u).astype(np.int32)
    v0 = np.floor(v).astype(np.int32)
    fu = (u - u0)[..., None]
    fv = (v - v0)[..., None]

    def tap(vi, ui):
        valid = (ui >= 0) & (ui < pw) & (vi >= 0) & (vi < ph)
        smp = patch_pre[np.clip(vi, 0, ph - 1), np.clip(ui, 0, pw - 1)]
        return smp * valid[..., None]

    src = (tap(v0,     u0    ) * (1.0 - fu) * (1.0 - fv)
         + tap(v0,     u0 + 1) * fu         * (1.0 - fv)
         + tap(v0 + 1, u0    ) * (1.0 - fu) * fv
         + tap(v0 + 1, u0 + 1) * fu         * fv)

    # Alpha-over in premultiplied space, back to straight
    dst      = dest_buf[dy0:dy1, dx0:dx1]
    dst_pre  = dst.copy()
    dst_pre[..., :3] *= dst_pre[..., 3:4]
    src_a    = src[..., 3:4]
    out_pre  = src + dst_pre * (1.0 - src_a)
    out_a    = out_pre[..., 3:4]
    out_rgb  = np.zeros_like(out_pre[..., :3])
    np.divide(out_pre[..., :3], out_a, out=out_rgb, where=out_a > 1e-6)

    dest_buf[dy0:dy1, dx0:dx1, :3] = out_rgb
    dest_buf[dy0:dy1, dx0:dx1, 3]  = out_pre[..., 3]

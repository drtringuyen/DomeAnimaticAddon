"""
image_io.py — Pure file I/O helpers for the painting_cel module.

Handles: filename construction, PNG create/copy, cel folder access, VSE-to-slot loading.
No operators, no PropertyGroups, no GPU — only data and disk operations.
"""

import bpy
import os
import glob

try:
    import numpy as np
except ImportError:
    np = None

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp, sp


# ── Frame / folder helpers ────────────────────────────────────────────────────

def dome_frame() -> int:
    dome = bpy.data.scenes.get("Dome Animatic")
    return int(dome.frame_current) if dome else int(bpy.context.scene.frame_current)


def cel_folder_abs() -> str:
    raw = sp().cel_folder
    return bpy.path.abspath(raw)


def ensure_cel_folder() -> str:
    folder = cel_folder_abs()
    os.makedirs(folder, exist_ok=True)
    return folder


# ── Filename helpers ──────────────────────────────────────────────────────────

def _track1_stem() -> str:
    """
    Clean stem from the track-1 (Baked) VSE strip at the current playhead.
    Strips trailing _BG/_Cel_A/_Cel_B/_f_NNNNN suffixes.
    """
    import re
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return ""
    frame = dome_scene.frame_current
    strip = vse_helpers.vse_get_strip_on_channel(dome_scene, 1, frame,
                                                 include_muted=True)
    if strip is None:
        return ""
    if strip.type == 'IMAGE':
        el = strip.strip_elem_from_frame(frame)
        name = os.path.splitext(el.filename)[0] if el else ""
    elif strip.type == 'MOVIE':
        name = os.path.splitext(os.path.basename(strip.filepath))[0]
    else:
        return ""
    if not name:
        return ""
    stem = re.sub(r'_(BG|Cel_A|Cel_B)_f_\d+$', '', name)
    stem = re.sub(r'_f_\d+$', '', stem)
    return stem


def cel_filename(slot_id: str, frame: int) -> str:
    """Canonical filename: <stem>_<label>_f_<frame:05d>.png"""
    stem  = _track1_stem()
    label = cel_store.BY_SLOT[slot_id].filename_label
    return f"{stem}_{label}_f_{frame:05d}.png" if stem else f"{label}_f_{frame:05d}.png"


def find_closest_cel_file(slot_id: str):
    """
    Return (abs_path, frame_number) of the closest PNG to the current playhead,
    or (None, None) if nothing found.
    """
    folder = cel_folder_abs()
    if not os.path.isdir(folder):
        return None, None
    stem  = _track1_stem()
    label = cel_store.BY_SLOT[slot_id].filename_label
    if not stem:
        return None, None
    pattern = os.path.join(folder, f"{stem}_{label}_f_*.png")
    matches = glob.glob(pattern)
    if not matches:
        return None, None
    current = dome_frame()
    best_path, best_dist = None, float('inf')
    for path in matches:
        base  = os.path.splitext(os.path.basename(path))[0]
        parts = base.rsplit('_f_', 1)
        if len(parts) != 2:
            continue
        try:
            file_frame = int(parts[1])
        except ValueError:
            continue
        dist = abs(file_frame - current)
        if dist < best_dist:
            best_dist = dist
            best_path = path
    if best_path is None:
        return None, None
    frame_num = int(os.path.splitext(os.path.basename(best_path))[0].rsplit('_f_', 1)[1])
    return best_path, frame_num


# ── PNG write helpers ─────────────────────────────────────────────────────────

def get_reference_size() -> tuple[int, int]:
    """(w, h) from track-1 VSE channel-1 source file, floor to nearest 10. Fallback (960, 590)."""
    _, filepath, _, _ = vse_helpers.get_dome_animatic_frame_info()
    if filepath and os.path.exists(filepath):
        ref = bpy.data.images.load(filepath, check_existing=True)
        if ref.size[0] > 0:
            w = (ref.size[0] // 10) * 10 or ref.size[0]
            h = (ref.size[1] // 10) * 10 or ref.size[1]
            return w, h
    return 960, 590


def get_preview_size() -> tuple[int, int]:
    """(w, h) from tex_width/height × tex_scale, floor to nearest 10."""
    s = sp()
    w = (int(s.tex_width  * s.tex_scale) // 10) * 10 or max(1, int(s.tex_width  * s.tex_scale))
    h = (int(s.tex_height * s.tex_scale) // 10) * 10 or max(1, int(s.tex_height * s.tex_scale))
    return max(1, w), max(1, h)


def create_blank_png(abs_path: str, width: int, height: int) -> None:
    img = bpy.data.images.new("__cel_tmp__", width=width, height=height,
                               alpha=True, float_buffer=False)
    img.alpha_mode = 'STRAIGHT'
    if np is not None:
        buf = np.zeros(width * height * 4, dtype=np.float32)
        img.pixels.foreach_set(buf)
        img.update()
    img.filepath_raw = abs_path
    img.file_format  = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def copy_track1_to_png(track1_strip, frame: int, abs_path: str,
                       w: int, h: int) -> None:
    if np is None:
        create_blank_png(abs_path, w, h)
        return
    src_path = vse_helpers.resolve_strip_image_path(track1_strip, frame)
    if not src_path or not os.path.exists(src_path):
        create_blank_png(abs_path, w, h)
        return
    src = bpy.data.images.load(src_path, check_existing=True)
    try:
        _ = src.pixels[0]
    except Exception:
        src.reload()
    if src.size[0] == 0:
        create_blank_png(abs_path, w, h)
        return
    sw, sh = src.size[0], src.size[1]
    buf = np.empty(sw * sh * 4, dtype=np.float32)
    src.pixels.foreach_get(buf)
    out = bpy.data.images.new("__cel_bg_copy__", width=sw, height=sh,
                               alpha=True, float_buffer=False)
    out.alpha_mode   = 'STRAIGHT'
    out.pixels.foreach_set(buf)
    out.update()
    if (sw, sh) != (w, h):
        out.scale(w, h)
    out.filepath_raw = abs_path
    out.file_format  = 'PNG'
    out.save()
    bpy.data.images.remove(out)
    vse_helpers.log(f"[PaintingCel] Copied track-1 pixels → {abs_path}")


def copy_image_to_png(src_abs_path: str, dst_abs_path: str,
                      w: int, h: int) -> None:
    if np is None:
        create_blank_png(dst_abs_path, w, h)
        return
    src = bpy.data.images.load(src_abs_path, check_existing=True)
    try:
        _ = src.pixels[0]
    except Exception:
        src.reload()
    if src.size[0] == 0:
        create_blank_png(dst_abs_path, w, h)
        return
    sw, sh = src.size[0], src.size[1]
    buf = np.empty(sw * sh * 4, dtype=np.float32)
    src.pixels.foreach_get(buf)
    out = bpy.data.images.new("__cel_copy_tmp__", width=sw, height=sh,
                               alpha=True, float_buffer=False)
    out.alpha_mode = 'STRAIGHT'
    out.pixels.foreach_set(buf)
    out.update()
    if (sw, sh) != (w, h):
        out.scale(w, h)
    out.filepath_raw = dst_abs_path
    out.file_format  = 'PNG'
    out.save()
    bpy.data.images.remove(out)


def load_abs_into_slot(slot_id: str, abs_path: str, w: int, h: int) -> None:
    cel_img = cel_store.get_or_create_cel_image(slot_id, w, h)
    if cel_img.packed_file:
        cel_img.unpack(method='USE_ORIGINAL')
    try:
        rel = bpy.path.relpath(abs_path)
    except ValueError:
        rel = abs_path
    cel_img.filepath     = rel
    cel_img.filepath_raw = abs_path
    cel_img.source       = 'FILE'
    cel_img.reload()
    cel_img.alpha_mode   = 'STRAIGHT'


def load_slot_from_vse(slot_id: str, w: int, h: int) -> None:
    """Read the current VSE strip path for this slot's channel and load it."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return
    channel = cel_store.BY_SLOT[slot_id].vse_channel
    frame   = dome_frame()
    strip   = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
    if strip is None:
        return
    path = vse_helpers.resolve_strip_image_path(strip, frame)
    if path and os.path.exists(path):
        load_abs_into_slot(slot_id, path, w, h)
        slot_key = slot_id.lower()
        setattr(gp(), f"{slot_key}_filepath", path)
        vse_helpers.log(f"[PaintingCel] Loaded from VSE: {path}")

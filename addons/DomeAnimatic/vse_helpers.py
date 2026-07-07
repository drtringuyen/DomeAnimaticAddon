"""
vse_helpers.py — Shared VSE strip + viewport + image helpers.

Pure utility functions used across all modules. No operators, no PropertyGroup
registrations. All bpy.data.window_managers[0].domeanimatic_* references
replaced with gp() / sp() from global_scene_shared_props.
"""

import bpy
import os
from . import cel_store
from .global_scene_shared_props import gp


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg: str) -> None:
    print(msg)


def show_labels(context) -> bool:
    try:
        return gp(context).show_labels
    except Exception:
        return False


# ── VSE helpers — strip queries ───────────────────────────────────────────────

def get_active_strip_at_frame(scene, frame):
    """Highest-channel unmuted IMAGE/MOVIE strip at frame."""
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type in ('IMAGE', 'MOVIE') and not s.mute
        and s.frame_final_start <= frame < s.frame_final_end
    ]
    return max(candidates, key=lambda s: s.channel) if candidates else None


def resolve_strip_image_path(strip, frame) -> str | None:
    """Absolute filepath of the image for a strip at a given frame."""
    if strip.type == 'IMAGE':
        el = strip.strip_elem_from_frame(frame)
        if el:
            return bpy.path.abspath(os.path.join(strip.directory, el.filename))
    elif strip.type == 'MOVIE':
        return bpy.path.abspath(strip.filepath)
    return None


def get_dome_animatic_frame_info():
    """(name_stem, filepath, strip, el) from Dome Animatic VSE at playhead."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return None, None, None, None
    frame = dome_scene.frame_current
    strip = get_active_strip_at_frame(dome_scene, frame)
    if strip is None:
        return None, None, None, None
    if strip.type == 'IMAGE':
        el = strip.strip_elem_from_frame(frame)
        if el:
            filepath = bpy.path.abspath(os.path.join(strip.directory, el.filename))
            return os.path.splitext(el.filename)[0], filepath, strip, el
    elif strip.type == 'MOVIE':
        filepath = bpy.path.abspath(strip.filepath)
        return os.path.splitext(os.path.basename(strip.filepath))[0], filepath, strip, None
    return None, None, None, None


def get_current_scene_frame_info(scene):
    """(name_stem, filepath) from a scene's VSE at playhead."""
    frame = scene.frame_current
    strip = get_active_strip_at_frame(scene, frame)
    if strip is None:
        return None, None
    if strip.type == 'IMAGE':
        el = strip.strip_elem_from_frame(frame)
        if el:
            return (os.path.splitext(el.filename)[0],
                    bpy.path.abspath(os.path.join(strip.directory, el.filename)))
    elif strip.type == 'MOVIE':
        return (os.path.splitext(os.path.basename(strip.filepath))[0],
                bpy.path.abspath(strip.filepath))
    return None, None


def vse_get_strip_on_channel(scene, channel: int, frame: int,
                              include_muted: bool = False):
    """IMAGE strip on exactly `channel` containing `frame`.

    Channel is tested first: it rejects ~95% of strips with one int compare,
    skipping the remaining RNA attribute reads (the strip list also contains
    hundreds of sound strips on other channels)."""
    seq = scene.sequence_editor
    if not seq:
        return None
    for s in seq.strips_all:
        if (s.channel == channel and s.type == 'IMAGE'
                and (include_muted or not s.mute)
                and s.frame_final_start <= frame < s.frame_final_end):
            return s
    return None


def vse_get_strips_on_channels(scene, channels, frame: int,
                               include_muted: bool = False) -> dict:
    """One pass over strips_all → {channel: IMAGE strip or None}.

    Equivalent to calling vse_get_strip_on_channel once per channel but ~N×
    cheaper — the strip list is walked a single time. Use this in per-frame /
    per-redraw code (sync handler, watchers, panel draw)."""
    out = {ch: None for ch in channels}
    seq = scene.sequence_editor
    if not seq:
        return out
    for s in seq.strips_all:
        if (s.channel in out and s.type == 'IMAGE'
                and (include_muted or not s.mute)
                and s.frame_final_start <= frame < s.frame_final_end):
            out[s.channel] = s
    return out


def vse_get_channel_end_frame(scene, channel: int):
    seq = scene.sequence_editor
    if not seq:
        return None
    strips = [s for s in seq.strips_all if s.channel == channel and s.type == 'IMAGE']
    return max((s.frame_final_end for s in strips), default=None)


def vse_get_channel_start_frame(scene, channel: int):
    seq = scene.sequence_editor
    if not seq:
        return None
    strips = [s for s in seq.strips_all if s.channel == channel and s.type == 'IMAGE']
    return min((s.frame_final_start for s in strips), default=None)


def vse_insert_image_strip(scene, channel: int, abs_filepath: str,
                           frame_start: int, frame_end: int):
    """Insert a single-image IMAGE strip spanning frame_start→frame_end."""
    seq = scene.sequence_editor
    if not seq:
        return None
    if frame_end <= frame_start:
        log(f"[VseHelpers] invalid range {frame_start}->{frame_end}")
        return None
    try:
        rel = bpy.path.relpath(abs_filepath)
    except ValueError:
        rel = abs_filepath
    filename = os.path.basename(abs_filepath)
    for s in seq.strips_all:
        s.select = False
    strip = seq.strips.new_image(
        name=os.path.splitext(filename)[0],
        filepath=rel,
        channel=channel,
        frame_start=frame_start,
    )
    strip.frame_final_end = frame_end
    strip.select           = True
    seq.active_strip       = strip
    log(f"[VseHelpers] Inserted '{strip.name}' ch{channel} {frame_start}->{frame_end}")
    return strip


def vse_get_strip_right_of(scene, channel: int, frame: int):
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type == 'IMAGE' and s.channel == channel and s.frame_final_start > frame
    ]
    return min(candidates, key=lambda s: s.frame_final_start) if candidates else None


def vse_get_strip_left_of_frame(scene, channel: int, frame: int):
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type == 'IMAGE' and s.channel == channel and s.frame_final_end <= frame
    ]
    return max(candidates, key=lambda s: s.frame_final_end) if candidates else None


def vse_get_strip_left_of(scene, channel: int, strip):
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type == 'IMAGE' and s.channel == channel
        and s.frame_final_end <= strip.frame_final_start and s is not strip
    ]
    return max(candidates, key=lambda s: s.frame_final_end) if candidates else None


def vse_cut_strip_at_frame(scene, channel: int, frame: int, new_abs_filepath: str):
    """Trim existing strip to end at frame; insert new strip from frame to original end."""
    existing = vse_get_strip_on_channel(scene, channel, frame)
    if existing is None:
        return None
    if frame <= existing.frame_final_start:
        return None
    orig_end              = existing.frame_final_end
    existing.frame_final_end = frame
    return vse_insert_image_strip(scene, channel, new_abs_filepath, frame, orig_end)


# ── Strip transform copy ──────────────────────────────────────────────────────

def copy_strip_transform(src, dst) -> None:
    dst.transform.offset_x  = src.transform.offset_x
    dst.transform.offset_y  = src.transform.offset_y
    dst.transform.scale_x   = src.transform.scale_x
    dst.transform.scale_y   = src.transform.scale_y
    dst.transform.rotation  = src.transform.rotation
    dst.transform.origin    = src.transform.origin
    dst.crop.min_x          = src.crop.min_x
    dst.crop.min_y          = src.crop.min_y
    dst.crop.max_x          = src.crop.max_x
    dst.crop.max_y          = src.crop.max_y
    dst.blend_type          = src.blend_type
    dst.blend_alpha         = src.blend_alpha
    dst.color_saturation    = src.color_saturation
    dst.color_multiply      = src.color_multiply
    dst.use_flip_x          = src.use_flip_x
    dst.use_flip_y          = src.use_flip_y


# ── Scene matching ────────────────────────────────────────────────────────────

def _longest_common_substring(a: str, b: str) -> int:
    m, n   = len(a), len(b)
    longest = 0
    for i in range(m):
        for j in range(n):
            length = 0
            while i + length < m and j + length < n and a[i+length] == b[j+length]:
                length += 1
            longest = max(longest, length)
    return longest


def find_closest_scene(name: str):
    if not name:
        return None, 0
    best_scene, best_score = None, 0
    for scene in bpy.data.scenes:
        s = scene.name
        if s == name:
            return s, 100
        score = 80 if (s.startswith(name) or name.startswith(s)) else 0
        score = max(score, _longest_common_substring(name.lower(), s.lower()))
        if score > best_score:
            best_score, best_scene = score, s
    return best_scene, best_score


# ── Viewport helpers ──────────────────────────────────────────────────────────

_dome_view_state: dict | None = None


def save_dome_view_state(context) -> None:
    global _dome_view_state
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    r3d = space.region_3d
                    _dome_view_state = {
                        "view_location":    r3d.view_location.copy(),
                        "view_rotation":    r3d.view_rotation.copy(),
                        "view_distance":    r3d.view_distance,
                        "view_perspective": r3d.view_perspective,
                    }
                    return


def restore_dome_view_state(context) -> None:
    global _dome_view_state
    if _dome_view_state is None:
        return
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    r3d = space.region_3d
                    r3d.view_location    = _dome_view_state["view_location"]
                    r3d.view_rotation    = _dome_view_state["view_rotation"]
                    r3d.view_distance    = _dome_view_state["view_distance"]
                    r3d.view_perspective = _dome_view_state["view_perspective"]
                    return


def switch_all_view3d_to_camera(context) -> None:
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.region_3d.view_perspective = 'CAMERA'


# ── Image Editor helpers ──────────────────────────────────────────────────────

def restore_image_editor_to_live(context) -> None:
    live_img = cel_store.get_live_image()
    if live_img is None:
        return
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            for space in area.spaces:
                if space.type == 'IMAGE_EDITOR':
                    space.image = live_img


def set_image_editor_image(context, image) -> None:
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            for space in area.spaces:
                if space.type == 'IMAGE_EDITOR':
                    space.image = image
                    area.tag_redraw()


def set_paint_target(image: bpy.types.Image, mat=None) -> None:
    """Set image as the active texture-paint target in the Dome Animatic scene.

    Updates two independent systems that Blender checks:
    - scene.tool_settings.image_paint.canvas  (IMAGE paint mode / header dropdown)
    - the material's active Image Texture node (MATERIAL paint mode)
    """
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is not None:
        try:
            dome_scene.tool_settings.image_paint.canvas = image
        except Exception:
            pass
    if mat is not None and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image == image:
                mat.node_tree.nodes.active = node
                break


def tag_all_image_editors_redraw() -> None:
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()


# ── Material texture assignment ───────────────────────────────────────────────

def assign_image_to_target_material(context, image) -> bool:
    mat = context.scene.domeanimatic.target_material
    if mat is None or not mat.use_nodes:
        return False
    tex_node = next((n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'), None)
    if tex_node is None:
        return False
    tex_node.image = image
    try:
        context.scene.domeanimatic.target_image = image
    except Exception:
        pass
    return True

import bpy
import os

# ── Global constants ──────────────────────────────────────────────────────────

LIVE_TEXTURE_NAME = "LiveDomePreview"


# ── Logging ───────────────────────────────────────────────────────────────────

def log(msg):
    print(msg)


def show_labels(context):
    try:
        return bpy.data.window_managers[0].domeanimatic_show_labels
    except Exception:
        return False


# ── Image helpers ─────────────────────────────────────────────────────────────

def get_live_image():
    return bpy.data.images.get(LIVE_TEXTURE_NAME)


def get_or_create_live_image(width=960, height=590):
    img = bpy.data.images.get(LIVE_TEXTURE_NAME)
    if img is None:
        img = bpy.data.images.new(
            LIVE_TEXTURE_NAME, width=width, height=height,
            alpha=False, float_buffer=False,
        )
        img.use_fake_user = True
        log(f"[DomeAnimatic] Created {LIVE_TEXTURE_NAME} at {width}x{height}")
    return img


# ── VSE helpers — general ─────────────────────────────────────────────────────

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


def resolve_strip_image_path(strip, frame):
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
            return os.path.splitext(el.filename)[0], bpy.path.abspath(os.path.join(strip.directory, el.filename))
    elif strip.type == 'MOVIE':
        return os.path.splitext(os.path.basename(strip.filepath))[0], bpy.path.abspath(strip.filepath)
    return None, None


# ── VSE helpers — cel strip operations ───────────────────────────────────────

def vse_get_strip_on_channel(scene, channel, frame, include_muted=False):
    """
    Return the IMAGE strip on exactly `channel` that contains `frame`.
    By default skips muted strips (VSE eye off = muted).
    Pass include_muted=True when you only need the frame range regardless of visibility.
    Returns None if nothing found.
    """
    seq = scene.sequence_editor
    if not seq:
        return None
    for s in seq.strips_all:
        if (s.type == 'IMAGE' and s.channel == channel
                and (include_muted or not s.mute)
                and s.frame_final_start <= frame < s.frame_final_end):
            return s
    return None


def vse_get_channel_end_frame(scene, channel):
    """
    Return the frame_final_end of the last strip on `channel`, or None if empty.
    Includes muted strips — used for range calculation only.
    """
    seq = scene.sequence_editor
    if not seq:
        return None
    strips = [s for s in seq.strips_all if s.channel == channel and s.type == 'IMAGE']
    return max((s.frame_final_end for s in strips), default=None)


def vse_get_channel_start_frame(scene, channel):
    """
    Return the frame_final_start of the first strip on `channel`, or None if empty.
    Includes muted strips — used for range calculation only.
    """
    seq = scene.sequence_editor
    if not seq:
        return None
    strips = [s for s in seq.strips_all if s.channel == channel and s.type == 'IMAGE']
    return min((s.frame_final_start for s in strips), default=None)


def vse_insert_image_strip(scene, channel, abs_filepath, frame_start, frame_end):
    """
    Insert a single-image IMAGE strip on `channel` spanning frame_start→frame_end.
    Deselects all existing strips first, then selects only the new strip.
    Returns the new strip or None on failure.
    """
    seq = scene.sequence_editor
    if not seq:
        return None
    if frame_end <= frame_start:
        log(f"[Utils] vse_insert_image_strip: invalid range {frame_start}→{frame_end}")
        return None

    try:
        rel = bpy.path.relpath(abs_filepath)
    except ValueError:
        rel = abs_filepath

    filename = os.path.basename(abs_filepath)

    # Deselect all strips so only the new one ends up selected
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
    log(f"[Utils] Inserted strip '{strip.name}' ch{channel} {frame_start}→{frame_end}")
    return strip


def vse_get_strip_right_of(scene, channel, frame):
    """
    Return the IMAGE strip on `channel` whose frame_final_start is closest to
    but strictly after `frame`. Returns None if no such strip exists.
    """
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type == 'IMAGE' and s.channel == channel
        and s.frame_final_start > frame
    ]
    return min(candidates, key=lambda s: s.frame_final_start) if candidates else None


def vse_get_strip_left_of_frame(scene, channel, frame):
    """
    Return the IMAGE strip on `channel` whose frame_final_end is closest to
    but not past `frame`. Returns None if no such strip exists.
    """
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type == 'IMAGE' and s.channel == channel
        and s.frame_final_end <= frame
    ]
    return max(candidates, key=lambda s: s.frame_final_end) if candidates else None



    """
    Return the IMAGE strip on `channel` whose frame_final_end is closest to
    (but not past) `strip.frame_final_start`. Returns None if no such strip.
    """
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type == 'IMAGE'
        and s.channel == channel
        and s.frame_final_end <= strip.frame_final_start
        and s is not strip
    ]
    return max(candidates, key=lambda s: s.frame_final_end) if candidates else None

def vse_cut_strip_at_frame(scene, channel, frame, new_abs_filepath):
    """
    Cut the IMAGE strip on `channel` at `frame`:
      - Trim existing strip so it ends at `frame` (left half unchanged).
      - Insert a new IMAGE strip from `frame` to original end pointing to new_abs_filepath.
    Returns the new right-half strip or None.
    """
    existing = vse_get_strip_on_channel(scene, channel, frame)
    if existing is None:
        log(f"[Utils] vse_cut_strip_at_frame: no strip on ch{channel} at frame {frame}")
        return None

    if frame <= existing.frame_final_start:
        log(f"[Utils] vse_cut_strip_at_frame: frame {frame} at or before strip start")
        return None

    orig_end = existing.frame_final_end
    existing.frame_final_end = frame

    new_strip = vse_insert_image_strip(scene, channel, new_abs_filepath, frame, orig_end)
    return new_strip


# ── Strip transform copy ──────────────────────────────────────────────────────

def copy_strip_transform(src, dst):
    dst.transform.offset_x   = src.transform.offset_x
    dst.transform.offset_y   = src.transform.offset_y
    dst.transform.scale_x    = src.transform.scale_x
    dst.transform.scale_y    = src.transform.scale_y
    dst.transform.rotation   = src.transform.rotation
    dst.transform.origin     = src.transform.origin
    dst.crop.min_x           = src.crop.min_x
    dst.crop.min_y           = src.crop.min_y
    dst.crop.max_x           = src.crop.max_x
    dst.crop.max_y           = src.crop.max_y
    dst.blend_type           = src.blend_type
    dst.blend_alpha          = src.blend_alpha
    dst.color_saturation     = src.color_saturation
    dst.color_multiply       = src.color_multiply
    dst.use_flip_x           = src.use_flip_x
    dst.use_flip_y           = src.use_flip_y


# ── Scene matching ────────────────────────────────────────────────────────────

def longest_common_substring(a, b):
    m, n = len(a), len(b)
    longest = 0
    for i in range(m):
        for j in range(n):
            length = 0
            while i + length < m and j + length < n and a[i+length] == b[j+length]:
                length += 1
            longest = max(longest, length)
    return longest


def find_closest_scene(name):
    if not name:
        return None, 0
    best_scene, best_score = None, 0
    for scene in bpy.data.scenes:
        s = scene.name
        if s == name:
            return s, 100
        score = 80 if (s.startswith(name) or name.startswith(s)) else 0
        score = max(score, longest_common_substring(name.lower(), s.lower()))
        if score > best_score:
            best_score, best_scene = score, s
    return best_scene, best_score


# ── Viewport helpers ──────────────────────────────────────────────────────────

_dome_view_state = None


def save_dome_view_state(context):
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


def restore_dome_view_state(context):
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


def switch_all_view3d_to_camera(context):
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.region_3d.view_perspective = 'CAMERA'


def restore_image_editor_to_live(context):
    live_img = get_live_image()
    if live_img is None:
        return
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            for space in area.spaces:
                if space.type == 'IMAGE_EDITOR':
                    space.image = live_img


def set_image_editor_image(context, image):
    """Point all Image Editors to the given image."""
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            for space in area.spaces:
                if space.type == 'IMAGE_EDITOR':
                    space.image = image
                    area.tag_redraw()


def tag_all_image_editors_redraw():
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()


# ── Material texture assignment ───────────────────────────────────────────────

def assign_image_to_target_material(context, image):
    mat = context.scene.domeanimatic_target_material
    if mat is None or not mat.use_nodes:
        return False
    tex_node = next((n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'), None)
    if tex_node is None:
        return False
    tex_node.image = image
    try:
        context.scene.domeanimatic_target_image = image
    except Exception:
        pass
    return True

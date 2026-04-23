import bpy
import os

# ── Global constant ───────────────────────────────────────────────────────────

LIVE_TEXTURE_NAME = "LiveDomePreview"


# ── Logging toggle ────────────────────────────────────────────────────────────

def log(msg):
    """Print debug info unconditionally — verbose_log removed."""
    print(msg)


def show_labels(context):
    """Return True if UI dev info labels should be shown."""
    try:
        return bpy.data.window_managers[0].domeanimatic_show_labels
    except Exception:
        return False


# ── Image helpers ─────────────────────────────────────────────────────────────

def get_live_image():
    """Return LiveDomePreview image or None if it doesn't exist."""
    return bpy.data.images.get(LIVE_TEXTURE_NAME)


def get_or_create_live_image(width=960, height=590):
    """Return LiveDomePreview, creating it if necessary."""
    img = bpy.data.images.get(LIVE_TEXTURE_NAME)
    if img is None:
        img = bpy.data.images.new(
            LIVE_TEXTURE_NAME,
            width=width,
            height=height,
            alpha=False,
            float_buffer=False,
        )
        img.use_fake_user = True
        log(f"[DomeAnimatic] Created {LIVE_TEXTURE_NAME} at {width}x{height}")
    return img


# ── VSE helpers ───────────────────────────────────────────────────────────────

def get_active_strip_at_frame(scene, frame):
    """Return the highest-channel unmuted IMAGE/MOVIE strip at the given frame."""
    seq = scene.sequence_editor
    if not seq:
        return None
    candidates = [
        s for s in seq.strips_all
        if s.type in ('IMAGE', 'MOVIE')
        and not s.mute
        and s.frame_final_start <= frame < s.frame_final_end
    ]
    if not candidates:
        return None
    return max(candidates, key=lambda s: s.channel)


def resolve_strip_image_path(strip, frame):
    """Return the absolute filepath of the image for a strip at a given frame."""
    if strip.type == 'IMAGE':
        el = strip.strip_elem_from_frame(frame)
        if el:
            return bpy.path.abspath(os.path.join(strip.directory, el.filename))
    elif strip.type == 'MOVIE':
        return bpy.path.abspath(strip.filepath)
    return None


def get_dome_animatic_frame_info():
    """
    Return (name_stem, filepath, strip, el) from the Dome Animatic scene VSE
    at its current playhead position.
    """
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
            name     = os.path.splitext(el.filename)[0]
            return name, filepath, strip, el

    elif strip.type == 'MOVIE':
        filepath = bpy.path.abspath(strip.filepath)
        name     = os.path.splitext(os.path.basename(strip.filepath))[0]
        return name, filepath, strip, None

    return None, None, None, None


def get_current_scene_frame_info(scene):
    """
    Return (name_stem, filepath) from the given scene's VSE
    at its current playhead position.
    """
    frame = scene.frame_current
    strip = get_active_strip_at_frame(scene, frame)
    if strip is None:
        return None, None

    if strip.type == 'IMAGE':
        el = strip.strip_elem_from_frame(frame)
        if el:
            filepath = bpy.path.abspath(os.path.join(strip.directory, el.filename))
            name     = os.path.splitext(el.filename)[0]
            return name, filepath

    elif strip.type == 'MOVIE':
        filepath = bpy.path.abspath(strip.filepath)
        name     = os.path.splitext(os.path.basename(strip.filepath))[0]
        return name, filepath

    return None, None


# ── Strip transform copy ──────────────────────────────────────────────────────

def copy_strip_transform(src, dst):
    """Copy all transform/crop/blend properties from src strip to dst strip."""
    dst.transform.offset_x = src.transform.offset_x
    dst.transform.offset_y = src.transform.offset_y
    dst.transform.scale_x  = src.transform.scale_x
    dst.transform.scale_y  = src.transform.scale_y
    dst.transform.rotation = src.transform.rotation
    dst.transform.origin   = src.transform.origin

    dst.crop.min_x = src.crop.min_x
    dst.crop.min_y = src.crop.min_y
    dst.crop.max_x = src.crop.max_x
    dst.crop.max_y = src.crop.max_y

    dst.blend_type  = src.blend_type
    dst.blend_alpha = src.blend_alpha

    dst.color_saturation = src.color_saturation
    dst.color_multiply   = src.color_multiply

    dst.use_flip_x = src.use_flip_x
    dst.use_flip_y = src.use_flip_y


# ── Scene matching ────────────────────────────────────────────────────────────

def longest_common_substring(a, b):
    """Return the length of the longest common substring between a and b."""
    m, n    = len(a), len(b)
    longest = 0
    for i in range(m):
        for j in range(n):
            length = 0
            while i + length < m and j + length < n and a[i + length] == b[j + length]:
                length += 1
            longest = max(longest, length)
    return longest


def find_closest_scene(name):
    """
    Score all scenes against name and return (best_scene_name, score).
    Score 100 = exact, 80 = prefix, otherwise longest common substring length.
    """
    if not name:
        return None, 0

    best_scene = None
    best_score = 0

    for scene in bpy.data.scenes:
        s = scene.name

        if s == name:
            return s, 100

        score = 0
        if s.startswith(name) or name.startswith(s):
            score = max(score, 80)

        lcs   = longest_common_substring(name.lower(), s.lower())
        score = max(score, lcs)

        if score > best_score:
            best_score = score
            best_scene = s

    return best_scene, best_score


# ── Viewport helpers ──────────────────────────────────────────────────────────

# Saved Dome Animatic view state
_dome_view_state = None


def save_dome_view_state(context):
    """Save the current VIEW_3D state from the Dome Animatic scene."""
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
                    log(f"[Utils] Saved Dome view state: {r3d.view_perspective}")
                    return


def restore_dome_view_state(context):
    """Restore the saved VIEW_3D state to the Dome Animatic scene."""
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
                    log(f"[Utils] Restored Dome view state: {r3d.view_perspective}")
                    return


def switch_all_view3d_to_camera(context):
    """Set all VIEW_3D areas in the current screen to camera view."""
    for area in context.screen.areas:
        if area.type == 'VIEW_3D':
            for space in area.spaces:
                if space.type == 'VIEW_3D':
                    space.region_3d.view_perspective = 'CAMERA'


def restore_image_editor_to_live(context):
    """Point all open Image Editors back to LiveDomePreview."""
    live_img = get_live_image()
    if live_img is None:
        return
    for area in context.screen.areas:
        if area.type == 'IMAGE_EDITOR':
            for space in area.spaces:
                if space.type == 'IMAGE_EDITOR':
                    space.image = live_img


# ── Material texture assignment ───────────────────────────────────────────────

def assign_image_to_target_material(context, image):
    """
    Assign the given image to the first Image Texture node
    in the scene's target material. Also updates target_image pointer.
    Returns True if successful.
    """
    mat = context.scene.domeanimatic_target_material
    if mat is None or not mat.use_nodes:
        log("[Utils] No target material set or material has no nodes.")
        return False

    # Find first Image Texture node
    tex_node = next(
        (n for n in mat.node_tree.nodes if n.type == 'TEX_IMAGE'),
        None
    )

    if tex_node is None:
        # Create one linked to Material Output
        nodes = mat.node_tree.nodes
        links = mat.node_tree.links
        tex_node = nodes.new('ShaderNodeTexImage')
        tex_node.location = (-200, 0)
        output = next((n for n in nodes if n.type == 'OUTPUT_MATERIAL'), None)
        if output:
            links.new(tex_node.outputs['Color'], output.inputs['Surface'])

    tex_node.image = image

    # Update the scene pointer too
    try:
        context.scene.domeanimatic_target_image = image
    except Exception:
        pass

    log(f"[Utils] Assigned '{image.name}' to material '{mat.name}'.")
    return True

"""
transparent_cel.py

Per-slot cel layer system. Each slot (BG/CEL_A/CEL_B) owns:
  - A named Image datablock (use_fake_user=True) for painting
  - A VSE channel (2/3/4)
  - Visibility + opacity props (on WindowManager, registered in properties.py)

GPU overlay: one POST_PIXEL handler draws all visible cels in stack order.
Invisible-layer warning: depsgraph_update_post detects painting on hidden cel.
"""

import bpy
import os
import glob

try:
    import numpy as np
except Exception:
    np = None

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except Exception:
    gpu = None
    batch_for_shader = None

from . import utils

# ── Slot definitions ──────────────────────────────────────────────────────────

# slot_id → (VSE channel, Image datablock name, label in filename)
SLOTS = {
    'BG':    (2, "TransparentCel_BG",    "BG"),
    'CEL_A': (3, "TransparentCel_Cel_A", "Cel_A"),
    'CEL_B': (4, "TransparentCel_Cel_B", "Cel_B"),
}

# Draw order bottom→top
SLOT_ORDER = ('BG', 'CEL_A', 'CEL_B')


# ── Image datablock management ────────────────────────────────────────────────

def get_or_create_cel_image(slot_id, width=960, height=590):
    """
    Return the Image datablock for this slot, creating it if needed.
    New datablocks are zero-filled (fully transparent) so they don't
    occlude layers below before a file is loaded.
    Always use_fake_user=True.
    """
    _, name, _ = SLOTS[slot_id]
    img = bpy.data.images.get(name)
    if img is None:
        img = bpy.data.images.new(
            name, width=width, height=height,
            alpha=True, float_buffer=False,
        )
        img.alpha_mode    = 'STRAIGHT'
        img.use_fake_user = True
        # Zero-fill so the datablock is fully transparent until a file is loaded.
        # Without this, new images default to opaque black which blocks layers below.
        if np is not None:
            buf = np.zeros(width * height * 4, dtype=np.float32)
            img.pixels.foreach_set(buf)
            img.update()
        utils.log(f"[TransparentCel] Created datablock '{name}' at {width}x{height}")
    return img


def get_cel_image(slot_id):
    _, name, _ = SLOTS[slot_id]
    return bpy.data.images.get(name)


# ── Filename helpers ──────────────────────────────────────────────────────────

def _track1_stem():
    """
    Return the clean stem from the track-1 (Baked) VSE strip at the current
    playhead — always channel 1, regardless of what's on higher channels.
    Strips trailing _BG, _Cel_A, _Cel_B, _f_NNNNN suffixes.
    """
    import re
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return ""
    frame = dome_scene.frame_current
    strip = utils.vse_get_strip_on_channel(dome_scene, 1, frame, include_muted=True)
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


def _dome_frame():
    dome = bpy.data.scenes.get("Dome Animatic")
    return int(dome.frame_current) if dome else int(bpy.context.scene.frame_current)


def _cel_folder_abs():
    """Absolute path to the cel folder from WM prop."""
    wm  = bpy.data.window_managers[0]
    raw = getattr(wm, "domeanimatic_cel_folder", "//transparent-cels-paintings")
    return bpy.path.abspath(raw)


def cel_filename(slot_id, frame):
    """
    Build the canonical filename for a slot at a given frame.
    All slots: <stem>_<BG|Cel_A|Cel_B>_f_<frame:05d>.png
    Stem always comes from track-1 (Baked) strip — never from cel tracks.
    """
    stem  = _track1_stem()
    _, _, label = SLOTS[slot_id]
    return f"{stem}_{label}_f_{frame:05d}.png" if stem else f"{label}_f_{frame:05d}.png"


def find_closest_cel_file(slot_id):
    """
    Search the cel folder for files matching <stem>_<label>_f_*.png.
    Returns (abs_path, frame_number) of the closest match to the current
    playhead frame, or (None, None) if nothing found.
    Stem AND label must both match exactly.
    """
    folder = _cel_folder_abs()
    if not os.path.isdir(folder):
        return None, None

    stem  = _track1_stem()
    _, _, label = SLOTS[slot_id]
    if not stem:
        return None, None

    pattern = os.path.join(folder, f"{stem}_{label}_f_*.png")
    matches = glob.glob(pattern)
    if not matches:
        return None, None

    current_frame = _dome_frame()
    best_path, best_dist = None, float('inf')
    for path in matches:
        base = os.path.splitext(os.path.basename(path))[0]
        # Extract the 5-digit frame suffix
        parts = base.rsplit('_f_', 1)
        if len(parts) != 2:
            continue
        try:
            file_frame = int(parts[1])
        except ValueError:
            continue
        dist = abs(file_frame - current_frame)
        if dist < best_dist:
            best_dist = dist
            best_path = path

    if best_path is None:
        return None, None
    frame_num = int(os.path.splitext(os.path.basename(best_path))[0].rsplit('_f_', 1)[1])
    return best_path, frame_num


def _ensure_cel_folder():
    folder = _cel_folder_abs()
    os.makedirs(folder, exist_ok=True)
    return folder


def _create_blank_png(abs_path, width, height):
    """Write a fully transparent PNG to abs_path."""
    img = bpy.data.images.new("__cel_tmp__", width=width, height=height,
                               alpha=True, float_buffer=False)
    img.alpha_mode = 'STRAIGHT'
    # Blender defaults new images to opaque black — explicitly zero-fill.
    if np is not None:
        buf = np.zeros(width * height * 4, dtype=np.float32)
        img.pixels.foreach_set(buf)
        img.update()
    img.filepath_raw = abs_path
    img.file_format  = 'PNG'
    img.save()
    bpy.data.images.remove(img)


def _get_reference_size():
    """Return (w, h) from track-1 VSE current frame, fallback (960,590)."""
    name, filepath, _, _ = utils.get_dome_animatic_frame_info()
    if filepath and os.path.exists(filepath):
        ref = bpy.data.images.load(filepath, check_existing=True)
        if ref.size[0] > 0:
            return ref.size[0], ref.size[1]
    return 960, 590


def _copy_track1_to_png(track1_strip, frame, abs_path, w, h):
    """
    Copy the pixels of the track-1 image at `frame` into a new PNG at abs_path.
    Falls back to blank if numpy is unavailable or the image can't be read.
    """
    if np is None:
        _create_blank_png(abs_path, w, h)
        return
    src_path = utils.resolve_strip_image_path(track1_strip, frame)
    if not src_path or not os.path.exists(src_path):
        _create_blank_png(abs_path, w, h)
        return
    src = bpy.data.images.load(src_path, check_existing=True)
    try:
        _ = src.pixels[0]
    except Exception:
        src.reload()
    if src.size[0] == 0:
        _create_blank_png(abs_path, w, h)
        return
    sw, sh = src.size[0], src.size[1]
    buf = np.empty(sw * sh * 4, dtype=np.float32)
    src.pixels.foreach_get(buf)
    # Write out as PNG
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
    utils.log(f"[TransparentCel] Copied track-1 pixels to {abs_path}")


def _copy_image_to_png(src_abs_path, dst_abs_path, w, h):
    """Copy any existing image file's pixels into a new PNG at dst_abs_path."""
    if np is None:
        _create_blank_png(dst_abs_path, w, h)
        return
    src = bpy.data.images.load(src_abs_path, check_existing=True)
    try:
        _ = src.pixels[0]
    except Exception:
        src.reload()
    if src.size[0] == 0:
        _create_blank_png(dst_abs_path, w, h)
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
    utils.log(f"[TransparentCel] Copied {src_abs_path} → {dst_abs_path}")


def _load_abs_into_slot(slot_id, abs_path, w, h):
    """Load abs_path into the cel datablock for slot_id."""
    cel_img = get_or_create_cel_image(slot_id, w, h)
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


def _load_slot_from_vse(slot_id, w, h):
    """
    After a VSE strip operation, read the actual strip path at the playhead
    on the cel's channel and load that into the datablock.
    This ensures the datablock always mirrors what the VSE shows, not what
    filename was constructed locally.
    Falls back to a no-op if no strip found.
    """
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return
    channel, _, _ = SLOTS[slot_id]
    frame         = _dome_frame()
    strip = utils.vse_get_strip_on_channel(dome_scene, channel, frame)
    if strip is None:
        return
    path = utils.resolve_strip_image_path(strip, frame)
    if path and os.path.exists(path):
        _load_abs_into_slot(slot_id, path, w, h)
        wm = bpy.data.window_managers[0]
        setattr(wm, f"domeanimatic_{slot_id.lower()}_filepath", path)
        utils.log(f"[TransparentCel] Loaded from VSE: {path}")


# ── GPU overlay ───────────────────────────────────────────────────────────────

_DRAW_HANDLE   = None
_SHADER        = None
_SHADER_KIND   = None
_DIAG_DONE     = False


def _get_shader():
    global _SHADER, _SHADER_KIND
    if _SHADER is not None:
        return _SHADER, _SHADER_KIND
    if gpu is None:
        return None, None
    for name in ('IMAGE_COLOR', 'IMAGE'):
        try:
            _SHADER      = gpu.shader.from_builtin(name)
            _SHADER_KIND = name
            return _SHADER, _SHADER_KIND
        except Exception:
            continue
    return None, None


def _diag(msg):
    global _DIAG_DONE
    if _DIAG_DONE:
        return
    try:
        if bpy.data.window_managers[0].domeanimatic_show_labels:
            print(f"[TransparentCel] {msg}")
            _DIAG_DONE = True
    except Exception:
        pass


def _draw_quad(shader, kind, tex, verts, uvs, indices, rgba):
    try:
        batch = batch_for_shader(shader, 'TRIS',
                                  {"pos": verts, "texCoord": uvs},
                                  indices=indices)
    except Exception as e:
        _diag(f"batch_for_shader: {e}")
        return
    shader.bind()
    try:
        shader.uniform_sampler("image", tex)
    except Exception as e:
        _diag(f"uniform_sampler: {e}")
    if kind == 'IMAGE_COLOR':
        try:
            shader.uniform_float("color", rgba)
        except Exception as e:
            _diag(f"uniform_float: {e}")
    batch.draw(shader)


def _draw_overlay():
    """
    POST_PIXEL handler on SpaceImageEditor.
    Draws BG → CEL_A → CEL_B in order (if visible).
    If the active cel's eye is off, draws a red warning banner.
    """
    if gpu is None:
        return

    ctx   = bpy.context
    space = ctx.space_data
    if space is None or space.type != 'IMAGE_EDITOR':
        return

    region = ctx.region
    if region is None or region.type != 'WINDOW':
        return

    wm = bpy.data.window_managers[0]

    # Determine rect from the image currently shown
    shown_img = space.image
    if shown_img is None:
        return
    w, h = shown_img.size
    if w == 0 or h == 0:
        return

    try:
        x0, y0 = region.view2d.view_to_region(0.0, 0.0, clip=False)
        x1, y1 = region.view2d.view_to_region(1.0, 1.0, clip=False)
    except Exception as e:
        _diag(f"view_to_region: {e}")
        return

    sc_x = max(0, int(round(x0)))
    sc_y = max(0, int(round(y0)))
    sc_w = min(region.width,  int(round(x1))) - sc_x
    sc_h = min(region.height, int(round(y1))) - sc_y
    if sc_w <= 0 or sc_h <= 0:
        return

    shader, kind = _get_shader()
    if shader is None:
        _diag("no shader available")
        return

    verts   = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    uvs     = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    indices = [(0, 1, 2), (0, 2, 3)]

    try:
        gpu.state.scissor_set(sc_x, sc_y, sc_w, sc_h)
        gpu.state.scissor_test_set(True)
        gpu.state.blend_set('ALPHA')

        for slot_id in SLOT_ORDER:
            slot_key = slot_id.lower()  # 'bg', 'cel_a', 'cel_b'
            visible  = getattr(wm, f"domeanimatic_{slot_key}_visible", True)
            if not visible:
                continue
            img = get_cel_image(slot_id)
            if img is None:
                continue
            try:
                tex = gpu.texture.from_image(img)
            except Exception as e:
                _diag(f"texture.from_image {slot_id}: {e}")
                continue
            opacity = float(getattr(wm, f"domeanimatic_{slot_key}_opacity", 1.0))
            _draw_quad(shader, kind, tex, verts, uvs, indices, (1.0, 1.0, 1.0, opacity))

    finally:
        gpu.state.blend_set('NONE')
        gpu.state.scissor_test_set(False)

    # ── Invisible layer warning banner ────────────────────────────────────────
    active_slot = getattr(wm, "domeanimatic_active_cel", 'CEL_A')
    slot_key    = active_slot.lower()
    if not getattr(wm, f"domeanimatic_{slot_key}_visible", True):
        _draw_invisible_warning(region, x0, y1)


def _draw_invisible_warning(region, x0, y1):
    """Draw a simple red banner at the top of the canvas."""
    # We draw a coloured rect via the existing shader as a tinted quad.
    # The operator buttons in the panel handle the actual actions.
    if gpu is None:
        return
    try:
        import blf
        banner_h = 24
        gpu.state.blend_set('ALPHA')
        # Red semi-transparent bar
        import gpu.types
        vertices = [
            (x0, y1), (region.width, y1),
            (region.width, y1 + banner_h), (x0, y1 + banner_h),
        ]
        shader2d = gpu.shader.from_builtin('UNIFORM_COLOR')
        batch = batch_for_shader(shader2d, 'TRI_FAN', {"pos": vertices})
        shader2d.bind()
        shader2d.uniform_float("color", (0.8, 0.1, 0.1, 0.85))
        batch.draw(shader2d)
        gpu.state.blend_set('NONE')
        # Text label
        blf.position(0, x0 + 8, y1 + 6, 0)
        blf.size(0, 13)
        blf.color(0, 1.0, 1.0, 1.0, 1.0)
        blf.draw(0, "⚠  Painting on invisible layer — use panel to Turn On or Pick Another")
    except Exception:
        pass


def _register_draw_handler():
    global _DRAW_HANDLE
    if gpu is None or _DRAW_HANDLE is not None:
        return
    _DRAW_HANDLE = bpy.types.SpaceImageEditor.draw_handler_add(
        _draw_overlay, (), 'WINDOW', 'POST_PIXEL'
    )


def _unregister_draw_handler():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(_DRAW_HANDLE, 'WINDOW')
        except Exception:
            pass
        _DRAW_HANDLE = None


# ── Invisible-layer warning via depsgraph ─────────────────────────────────────

_warning_shown = False

@bpy.app.handlers.persistent
def _invisible_layer_check(scene, depsgraph=None):
    """
    depsgraph_update_post — fires on brush stroke commit.
    Only warns if the Image Editor is actively in PAINT mode and showing
    an invisible cel. Ignores all other depsgraph updates (mode switches etc).
    """
    global _warning_shown
    if _warning_shown:
        return
    try:
        wm = bpy.data.window_managers[0]
        active_slot = getattr(wm, "domeanimatic_active_cel", 'CEL_A')
        slot_key    = active_slot.lower()
        if getattr(wm, f"domeanimatic_{slot_key}_visible", True):
            return  # visible — nothing to do

        cel_img = get_cel_image(active_slot)

        for window in wm.windows:
            for area in window.screen.areas:
                if area.type != 'IMAGE_EDITOR':
                    continue
                for space in area.spaces:
                    if space.type != 'IMAGE_EDITOR':
                        continue
                    # Only warn when actively painting — not on mode/property changes
                    if space.mode != 'PAINT':
                        continue
                    if space.image != cel_img:
                        continue
                    _warning_shown = True
                    bpy.ops.domeanimatic.cel_invisible_warning('INVOKE_DEFAULT')
                    return
    except Exception:
        pass


# ── Operators ─────────────────────────────────────────────────────────────────

def _activate_slot(slot_id):
    """Set slot as active and switch Image Editor to its datablock."""
    wm = bpy.data.window_managers[0]
    wm.domeanimatic_active_cel = slot_id
    img = get_cel_image(slot_id)
    if img:
        for window in wm.windows:
            for area in window.screen.areas:
                if area.type == 'IMAGE_EDITOR':
                    for space in area.spaces:
                        if space.type == 'IMAGE_EDITOR':
                            space.image = img
                            area.tag_redraw()


class DOMEANIMATIC_OT_cel_set_active(bpy.types.Operator):
    """Set this slot as the active (paintable) cel. If invisible, turns eye on."""
    bl_idname = "domeanimatic.cel_set_active"
    bl_label  = "Set Active Cel"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        wm       = bpy.data.window_managers[0]
        slot_key = self.slot.lower()

        # If invisible → silently turn on
        if not getattr(wm, f"domeanimatic_{slot_key}_visible", True):
            setattr(wm, f"domeanimatic_{slot_key}_visible", True)
            utils.tag_all_image_editors_redraw()

        wm.domeanimatic_active_cel = self.slot
        img = get_cel_image(self.slot)
        if img:
            utils.set_image_editor_image(context, img)
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_toggle_visible(bpy.types.Operator):
    """Toggle visibility of a cel slot."""
    bl_idname = "domeanimatic.cel_toggle_visible"
    bl_label  = "Toggle Cel Visibility"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        wm       = bpy.data.window_managers[0]
        slot_key = self.slot.lower()
        current  = getattr(wm, f"domeanimatic_{slot_key}_visible", True)
        setattr(wm, f"domeanimatic_{slot_key}_visible", not current)
        utils.tag_all_image_editors_redraw()
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_invisible_warning(bpy.types.Operator):
    """Dialog warning that the user is painting on an invisible layer."""
    bl_idname  = "domeanimatic.cel_invisible_warning"
    bl_label   = "Invisible Layer Warning"
    bl_options = {'INTERNAL'}

    def invoke(self, context, event):
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        wm       = bpy.data.window_managers[0]
        active   = getattr(wm, "domeanimatic_active_cel", 'CEL_A')
        col      = self.layout.column(align=True)
        col.label(text=f"⚠  You are painting on an invisible layer ({active}).",
                  icon='ERROR')
        col.separator()
        col.label(text="Choose an action:")
        row = col.row(align=True)
        op = row.operator("domeanimatic.cel_invisible_turn_on", text="A — Turn On This Layer")
        op.slot = active
        col.operator("domeanimatic.cel_invisible_pick_other", text="B — Pick Another Layer (close)")

    def execute(self, context):
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_invisible_turn_on(bpy.types.Operator):
    """Turn on the visibility of the given slot (called from warning dialog)."""
    bl_idname = "domeanimatic.cel_invisible_turn_on"
    bl_label  = "Turn On Layer"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        global _warning_shown
        wm = bpy.data.window_managers[0]
        setattr(wm, f"domeanimatic_{self.slot.lower()}_visible", True)
        _warning_shown = False
        utils.tag_all_image_editors_redraw()
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_invisible_pick_other(bpy.types.Operator):
    """Dismiss the warning so the user can pick another layer."""
    bl_idname = "domeanimatic.cel_invisible_pick_other"
    bl_label  = "Pick Another Layer"

    def execute(self, context):
        global _warning_shown
        _warning_shown = False
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_insert_full(bpy.types.Operator):
    """
    Insert FULL slot.
    Case A — strip at playhead: replace it (confirmation popup).
    Case B — empty space: compute range from neighbours + BG/track-1 bounds.
      start = max(BG.frame_final_start, left_neighbour.frame_final_end)
      end   = min(BG.frame_final_end,   right_neighbour.frame_final_start)
    BG slot always copies track-1 pixels.
    """
    bl_idname  = "domeanimatic.cel_insert_full"
    bl_label   = "Insert Full Slot"
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty()

    def _compute_range(self, dome_scene, channel, frame):
        """Return (start, end) for the new strip."""
        existing = utils.vse_get_strip_on_channel(dome_scene, channel, frame)

        if existing is not None:
            # Case A: strip at playhead — use its full range
            return existing.frame_final_start, existing.frame_final_end

        # Case B: empty space — derive from BG and neighbours
        bg_strip = utils.vse_get_strip_on_channel(dome_scene, 2, frame, include_muted=True)
        if bg_strip is None:
            bg_strip = utils.vse_get_strip_on_channel(dome_scene, 1, frame, include_muted=True)

        left  = utils.vse_get_strip_left_of_frame(dome_scene, channel, frame)
        right = utils.vse_get_strip_right_of(dome_scene, channel, frame)

        if bg_strip is not None:
            bg_start = bg_strip.frame_final_start
            bg_end   = bg_strip.frame_final_end
        else:
            bg_start = frame
            bg_end   = frame + 100

        start = max(bg_start, left.frame_final_end if left else bg_start)
        end   = min(bg_end,   right.frame_final_start if right else bg_end)

        if end <= start:
            end = bg_end  # fallback: use full BG range

        return start, end

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return self.execute(context)
        channel, _, _ = SLOTS[self.slot]
        frame         = _dome_frame()
        existing      = utils.vse_get_strip_on_channel(dome_scene, channel, frame)
        if existing is not None:
            self._existing_name = existing.name
            return context.window_manager.invoke_props_dialog(self, width=380)
        return self.execute(context)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(
            text=f"Strip '{getattr(self, '_existing_name', '?')}' already exists here.",
            icon='ERROR',
        )
        col.separator()
        col.label(text="Replace it with a new Insert Full slot?")

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}

        channel, _, _ = SLOTS[self.slot]
        frame         = _dome_frame()
        w, h          = _get_reference_size()

        track1_strip = utils.vse_get_strip_on_channel(dome_scene, 1, frame, include_muted=True)
        start, end   = self._compute_range(dome_scene, channel, frame)

        # Create image file
        folder   = _ensure_cel_folder()
        filename = cel_filename(self.slot, frame)
        abs_path = os.path.join(folder, filename)

        if self.slot == 'BG' and track1_strip is not None:
            _copy_track1_to_png(track1_strip, frame, abs_path, w, h)
        else:
            _create_blank_png(abs_path, w, h)

        # Remove existing strip if present (user confirmed via dialog)
        existing = utils.vse_get_strip_on_channel(dome_scene, channel, frame)
        if existing is not None:
            dome_scene.sequence_editor.strips.remove(existing)

        utils.vse_insert_image_strip(dome_scene, channel, abs_path, start, end)
        _load_slot_from_vse(self.slot, w, h)
        _activate_slot(self.slot)

        wm = bpy.data.window_managers[0]
        # filepath already updated inside _load_slot_from_vse
        utils.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Full {start}→{end}: {filename}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_insert_cut(bpy.types.Operator):
    """
    Insert CUT slot — Cel_A/B only (disabled for BG). No confirmation popup.
    Case A — strip at playhead: copy left neighbour image (or blank), cut at playhead.
    Case B — empty space at playhead:
      start = playhead
      end   = min(BG.frame_final_end, right_neighbour.frame_final_start)
      image = blank transparent PNG
    Always replaces without asking.
    """
    bl_idname  = "domeanimatic.cel_insert_cut"
    bl_label   = "Insert Cut Slot"
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty()

    def invoke(self, context, event):
        if self.slot == 'BG':
            self.report({'WARNING'}, "BG uses Insert Full only.")
            return {'CANCELLED'}
        return self.execute(context)

    def execute(self, context):
        if self.slot == 'BG':
            self.report({'WARNING'}, "BG uses Insert Full only.")
            return {'CANCELLED'}

        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}

        channel, _, _ = SLOTS[self.slot]
        frame         = _dome_frame()
        w, h          = _get_reference_size()

        current_strip = utils.vse_get_strip_on_channel(dome_scene, channel, frame)

        folder   = _ensure_cel_folder()
        filename = cel_filename(self.slot, frame)
        abs_path = os.path.join(folder, filename)

        if current_strip is not None:
            # Case A: strip at playhead — copy left neighbour image or blank, then cut
            left_strip = utils.vse_get_strip_left_of(dome_scene, channel, current_strip)
            if left_strip is not None:
                left_path = utils.resolve_strip_image_path(
                    left_strip, left_strip.frame_final_start)
                if left_path and os.path.exists(left_path):
                    _copy_image_to_png(left_path, abs_path, w, h)
                else:
                    _create_blank_png(abs_path, w, h)
            else:
                _create_blank_png(abs_path, w, h)

            # Deselect all before cut
            for s in dome_scene.sequence_editor.strips_all:
                s.select = False

            new_strip = utils.vse_cut_strip_at_frame(dome_scene, channel, frame, abs_path)

        else:
            # Case B: empty space — blank image, start=playhead, end=min(BG, right)
            _create_blank_png(abs_path, w, h)

            bg_strip = utils.vse_get_strip_on_channel(dome_scene, 2, frame, include_muted=True)
            if bg_strip is None:
                bg_strip = utils.vse_get_strip_on_channel(
                    dome_scene, 1, frame, include_muted=True)

            right = utils.vse_get_strip_right_of(dome_scene, channel, frame)

            bg_end = bg_strip.frame_final_end if bg_strip else (frame + 100)
            end    = min(bg_end, right.frame_final_start if right else bg_end)
            if end <= frame:
                end = bg_end

            for s in dome_scene.sequence_editor.strips_all:
                s.select = False

            new_strip = utils.vse_insert_image_strip(
                dome_scene, channel, abs_path, frame, end)

        if new_strip is not None:
            new_strip.select = True
            dome_scene.sequence_editor.active_strip = new_strip

        _load_slot_from_vse(self.slot, w, h)
        _activate_slot(self.slot)

        wm = bpy.data.window_managers[0]
        utils.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Cut at frame {frame}: {filename}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_delete(bpy.types.Operator):
    """Delete only the single VSE strip at the playhead on this cel's channel."""
    bl_idname  = "domeanimatic.cel_delete"
    bl_label   = "Delete Strip at Playhead"
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty()

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return self.execute(context)
        channel, _, _ = SLOTS[self.slot]
        frame         = _dome_frame()
        strip = utils.vse_get_strip_on_channel(dome_scene, channel, frame)
        if strip is None:
            self.report({'WARNING'}, f"[{self.slot}] No strip at playhead on channel {channel}.")
            return {'CANCELLED'}
        self._strip_name = strip.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(
            text=f"Delete strip '{getattr(self, '_strip_name', '?')}' at playhead?",
            icon='TRASH',
        )
        col.separator()
        col.label(text="This cannot be undone from the cel panel.")

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}

        channel, _, _ = SLOTS[self.slot]
        frame         = _dome_frame()

        strip = utils.vse_get_strip_on_channel(dome_scene, channel, frame)
        if strip is None:
            self.report({'WARNING'}, f"[{self.slot}] No strip at playhead on channel {channel}.")
            return {'CANCELLED'}

        # Deselect all, then select only this strip before removing
        if dome_scene.sequence_editor:
            for s in dome_scene.sequence_editor.strips_all:
                s.select = False
            strip.select = True
            dome_scene.sequence_editor.active_strip = strip

        _activate_slot(self.slot)
        dome_scene.sequence_editor.strips.remove(strip)
        utils.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Deleted strip at frame {frame}.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_clear(bpy.types.Operator):
    """Clear cel pixels to transparent at playhead strip (keeps VSE strip and file)."""
    bl_idname  = "domeanimatic.cel_clear"
    bl_label   = "Clear Cel"
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty()

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return self.execute(context)
        channel, _, _ = SLOTS[self.slot]
        frame         = _dome_frame()
        strip = utils.vse_get_strip_on_channel(dome_scene, channel, frame)
        if strip is None:
            self.report({'WARNING'}, f"[{self.slot}] No strip at playhead on channel {channel}.")
            return {'CANCELLED'}
        self._strip_name = strip.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(
            text=f"Clear pixels of '{getattr(self, '_strip_name', '?')}' to transparent?",
            icon='TEXTURE',
        )
        col.separator()
        col.label(text="The VSE strip and file are kept, only pixels are zeroed.")

    def execute(self, context):
        if np is None:
            self.report({'ERROR'}, "numpy required for cel_clear.")
            return {'CANCELLED'}

        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene:
            channel, _, _ = SLOTS[self.slot]
            frame         = _dome_frame()
            strip = utils.vse_get_strip_on_channel(dome_scene, channel, frame)
            # Select only this strip
            if strip is not None and dome_scene.sequence_editor:
                for s in dome_scene.sequence_editor.strips_all:
                    s.select = False
                strip.select = True
                dome_scene.sequence_editor.active_strip = strip

        img = get_cel_image(self.slot)
        if img is None:
            self.report({'WARNING'}, f"No datablock for {self.slot}.")
            return {'CANCELLED'}
        w, h = img.size
        buf  = np.zeros(w * h * 4, dtype=np.float32)
        img.pixels.foreach_set(buf)
        img.update()
        _activate_slot(self.slot)
        utils.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Cleared.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_save(bpy.types.Operator):
    """Save cel PNG to disk. Only the painted layer — no background baked in."""
    bl_idname = "domeanimatic.cel_save"
    bl_label  = "Save Cel"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        img = get_cel_image(self.slot)
        if img is None:
            self.report({'WARNING'}, f"No datablock for {self.slot}.")
            return {'CANCELLED'}
        if not img.filepath_raw:
            self.report({'ERROR'}, "Cel has no filepath — use Insert first.")
            return {'CANCELLED'}
        try:
            img.save()
        except Exception as e:
            self.report({'ERROR'}, f"Save failed: {e}")
            return {'CANCELLED'}
        _activate_slot(self.slot)
        self.report({'INFO'}, f"[{self.slot}] Saved → {img.filepath_raw}")
        return {'FINISHED'}


# ── Per-row UI draw ───────────────────────────────────────────────────────────

def draw_row(layout, wm, slot_id):
    """
    Draw one cel row. When active: rendered as a highlighted box block.
    Layout per row:
      [👁] [Cel_X: nearest_filename | empty] [opacity slider] [▶] [✂] [🖌] [🗑] [💾]
    """
    slot_key    = slot_id.lower()
    channel, _, label = SLOTS[slot_id]
    is_active   = wm.domeanimatic_active_cel == slot_id
    visible     = getattr(wm, f"domeanimatic_{slot_key}_visible", True)

    # Check if there is actually a strip at the playhead on this cel's channel
    dome_scene   = bpy.data.scenes.get("Dome Animatic")
    frame        = _dome_frame()
    has_strip    = False
    if dome_scene:
        has_strip = utils.vse_get_strip_on_channel(dome_scene, channel, frame) is not None

    # Label: show current strip name only when a strip exists at playhead
    if has_strip:
        found_path, _ = find_closest_cel_file(slot_id)
        filepath = getattr(wm, f"domeanimatic_{slot_key}_filepath", "")
        # Prefer the WM filepath (most recently loaded) over nearest-found
        display = os.path.splitext(os.path.basename(filepath))[0] if filepath else \
                  (os.path.splitext(os.path.basename(found_path))[0] if found_path else "empty")
    else:
        display = "empty"
    row_label = f"{label}: {display}"

    # Only show dirty state when a strip exists — zero-fill on empty space
    # marks the datablock dirty but that's not a user-actionable save state
    _, img_name, _ = SLOTS[slot_id]
    is_dirty = has_strip and getattr(bpy.data.images.get(img_name), 'is_dirty', False)

    container = layout.box() if is_active else layout
    if is_dirty:
        container.alert = True
    row = container.row(align=True)
    row.scale_y = 1.3

    # ── Eye ───────────────────────────────────────────────────────────────────
    eye_op = row.operator(
        "domeanimatic.cel_toggle_visible", text="",
        icon='HIDE_OFF' if visible else 'HIDE_ON',
        depress=visible,
    )
    eye_op.slot = slot_id

    # ── Label / select ────────────────────────────────────────────────────────
    sel_op = row.operator(
        "domeanimatic.cel_set_active",
        text=row_label,
        depress=is_active,
    )
    sel_op.slot = slot_id

    # ── Opacity slider (inline) ───────────────────────────────────────────────
    row.prop(wm, f"domeanimatic_{slot_key}_opacity", text="", slider=True)

    # ── Fill (was Insert Full) — BG: RENDER_RESULT, Cel_A/B: CENTER_ONLY ─────
    full_icon = 'RENDER_RESULT' if slot_id == 'BG' else 'CENTER_ONLY'
    op = row.operator("domeanimatic.cel_insert_full", text="", icon=full_icon)
    op.slot = slot_id

    # ── Insert (was Insert Cut) — greyed out for BG ───────────────────────────
    cut_sub = row.row(align=True)
    cut_sub.enabled = (slot_id != 'BG')
    op = cut_sub.operator("domeanimatic.cel_insert_cut", text="", icon='TRACKING_FORWARDS_SINGLE')
    op.slot = slot_id

    # ── Clear — greyed out when no strip at playhead ─────────────────────────
    clear_sub = row.row(align=True)
    clear_sub.enabled = has_strip
    op = clear_sub.operator("domeanimatic.cel_clear", text="", icon='TEXTURE')
    op.slot = slot_id

    # ── Delete — greyed out when no strip at playhead ─────────────────────────
    del_sub = row.row(align=True)
    del_sub.enabled = has_strip
    op = del_sub.operator("domeanimatic.cel_delete", text="", icon='TRASH')
    op.slot = slot_id

    # ── Save — greyed out when not dirty or no strip; blue depress when dirty ─
    save_sub = row.row(align=True)
    save_sub.enabled = has_strip and is_dirty
    save_sub.alert   = False
    op = save_sub.operator(
        "domeanimatic.cel_save", text="", icon='FILE_TICK',
        depress=is_dirty,
    )
    op.slot = slot_id


def _count_unused_cel_files():
    """Return the number of cel PNGs on disk not referenced by any VSE strip."""
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    folder     = _cel_folder_abs()
    if not os.path.isdir(folder):
        return 0
    referenced = set()
    if dome_scene and dome_scene.sequence_editor:
        for strip in dome_scene.sequence_editor.strips_all:
            if strip.type == 'IMAGE' and strip.channel in (2, 3, 4):
                for frame in range(int(strip.frame_final_start), int(strip.frame_final_end)):
                    p = utils.resolve_strip_image_path(strip, frame)
                    if p:
                        referenced.add(os.path.normpath(p))
    count = 0
    for fname in os.listdir(folder):
        if not fname.lower().endswith('.png'):
            continue
        if '_BG_f_' not in fname and '_Cel_A_f_' not in fname and '_Cel_B_f_' not in fname:
            continue
        if os.path.normpath(os.path.join(folder, fname)) not in referenced:
            count += 1
    return count


class DOMEANIMATIC_OT_cel_purge_unused(bpy.types.Operator):
    """
    Delete PNG files in the cel folder that match the cel naming pattern
    but are not referenced by any strip on their respective VSE channel.
    Asks for confirmation before deleting.
    """
    bl_idname  = "domeanimatic.cel_purge_unused"
    bl_label   = "Purge Unused Cel Files"
    bl_options = {'REGISTER'}

    _unused: list = []

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        folder     = _cel_folder_abs()
        if not os.path.isdir(folder):
            self.report({'WARNING'}, "Cel folder not found.")
            return {'CANCELLED'}

        # Collect all paths referenced by VSE strips on channels 2/3/4
        referenced = set()
        if dome_scene and dome_scene.sequence_editor:
            for strip in dome_scene.sequence_editor.strips_all:
                if strip.type == 'IMAGE' and strip.channel in (2, 3, 4):
                    for frame in range(
                            int(strip.frame_final_start),
                            int(strip.frame_final_end)):
                        p = utils.resolve_strip_image_path(strip, frame)
                        if p:
                            referenced.add(os.path.normpath(p))

        # Find unused PNGs in the cel folder
        unused = []
        for fname in os.listdir(folder):
            if not fname.lower().endswith('.png'):
                continue
            # Only consider files matching our naming pattern
            if '_BG_f_' not in fname and '_Cel_A_f_' not in fname \
                    and '_Cel_B_f_' not in fname:
                continue
            abs_p = os.path.normpath(os.path.join(folder, fname))
            if abs_p not in referenced:
                unused.append(abs_p)

        self._unused = unused

        if not unused:
            self.report({'INFO'}, "No unused cel files found.")
            return {'CANCELLED'}

        return context.window_manager.invoke_props_dialog(self, width=420)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(
            text=f"Delete {len(self._unused)} unused cel PNG(s)?",
            icon='TRASH',
        )
        col.separator()
        for p in self._unused[:8]:
            col.label(text=os.path.basename(p), icon='IMAGE_DATA')
        if len(self._unused) > 8:
            col.label(text=f"  … and {len(self._unused) - 8} more")

    def execute(self, context):
        deleted = 0
        for p in self._unused:
            try:
                os.remove(p)
                deleted += 1
                utils.log(f"[PurgeUnused] Deleted: {p}")
            except Exception as e:
                utils.log(f"[PurgeUnused] Could not delete {p}: {e}")
        self.report({'INFO'}, f"Purged {deleted} unused cel file(s).")
        return {'FINISHED'}


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_cel_set_active,
    DOMEANIMATIC_OT_cel_toggle_visible,
    DOMEANIMATIC_OT_cel_invisible_warning,
    DOMEANIMATIC_OT_cel_invisible_turn_on,
    DOMEANIMATIC_OT_cel_invisible_pick_other,
    DOMEANIMATIC_OT_cel_insert_full,
    DOMEANIMATIC_OT_cel_insert_cut,
    DOMEANIMATIC_OT_cel_clear,
    DOMEANIMATIC_OT_cel_delete,
    DOMEANIMATIC_OT_cel_save,
    DOMEANIMATIC_OT_cel_purge_unused,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    _register_draw_handler()
    if _invisible_layer_check not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(_invisible_layer_check)


def unregister():
    if _invisible_layer_check in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(_invisible_layer_check)
    _unregister_draw_handler()
    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

"""
transparent_cel_managment.py

Transparent cel system for the Image Editor (no paint_layers required).

How it works
------------
- ONE transparent cel PNG is created on disk, in:
      <blend-dir>/transparent-cels-paintings/<VSE-stem>-cel_###.png
  same dimensions as the current Dome Animatic VSE image.
- The cel is the Image Editor's active image — so the user paints directly
  on it. Saving only ever writes that cel file; the background is NEVER
  baked into the cel.
- The "background" is a separate Image datablock holding the VSE frame's
  pixels. Drawing order in the GPU overlay:
      1) draw BG at `bg_opacity` (ALPHA blend)
      2) draw CEL at 100% on top of BG (ALPHA blend)
  That way cel strokes are ALWAYS visible on top of the reference — even
  when bg_opacity == 1.0. The overlay is registered on SpaceImageEditor
  (WINDOW region, POST_PIXEL).
- Toggle ON/OFF just flips a scene bool. The draw handler reads that bool
  per-draw so there's no handler churn.

Exported:
    classes:
        DOMEANIMATIC_OT_cel_setup
        DOMEANIMATIC_OT_cel_save
        DOMEANIMATIC_OT_cel_refresh_bg

    Scene properties (registered here):
        domeanimatic_active_cel_name  : str
        domeanimatic_cel_bg_on        : bool (toggle)
        domeanimatic_cel_bg_opacity   : float 0..1

    draw_ui(box, context)  — for panels.py
"""

import bpy
import os

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


# ── Config ────────────────────────────────────────────────────────────────────

CEL_FOLDER_NAME = "transparent-cels-paintings"
_BG_SUFFIX      = "__bg"          # sibling datablock holding bg pixels


# ── Path / naming helpers ─────────────────────────────────────────────────────

def _blend_dir():
    """Absolute dir of the current .blend, or None if file is unsaved."""
    fp = bpy.data.filepath
    return os.path.dirname(fp) if fp else None


def _cel_folder():
    d = _blend_dir()
    return os.path.join(d, CEL_FOLDER_NAME) if d else None


def _ensure_cel_folder():
    folder = _cel_folder()
    if folder is None:
        return None
    os.makedirs(folder, exist_ok=True)
    return folder


def _dome_frame():
    """Return the Dome Animatic scene's current frame, or the active scene's."""
    dome = bpy.data.scenes.get("Dome Animatic")
    if dome is not None:
        return int(dome.frame_current)
    return int(bpy.context.scene.frame_current)


def _next_cel_path(stem, folder, frame):
    """
    Return (abs_path, filename) for the next unused
    <stem>_cel_f<frame:04d>[_NN].png in folder.
    """
    base = f"{stem}_cel_f{frame:04d}"
    # First try with no suffix
    candidate_name = base
    candidate_fn   = candidate_name + ".png"
    candidate_fp   = os.path.join(folder, candidate_fn)
    if not os.path.exists(candidate_fp) and candidate_name not in bpy.data.images:
        return candidate_fp, candidate_fn

    # Otherwise append _02, _03, ...
    i = 2
    while True:
        candidate_name = f"{base}_{i:02d}"
        candidate_fn   = candidate_name + ".png"
        candidate_fp   = os.path.join(folder, candidate_fn)
        if (not os.path.exists(candidate_fp)
                and candidate_name not in bpy.data.images):
            return candidate_fp, candidate_fn
        i += 1


# ── VSE frame info ────────────────────────────────────────────────────────────

def _get_vse_frame():
    """
    Return (stem, abs_filepath, w, h) for the Dome Animatic VSE playhead's
    current image/movie frame — or None if there's nothing usable.
    """
    try:
        name, filepath, strip, el = utils.get_dome_animatic_frame_info()
    except Exception:
        return None
    if not name or not filepath:
        return None

    abs_fp = bpy.path.abspath(filepath)
    if not os.path.exists(abs_fp):
        return None

    img = bpy.data.images.load(abs_fp, check_existing=True)
    w, h = img.size[0], img.size[1]
    if w == 0 or h == 0:
        return None

    stem = os.path.splitext(os.path.basename(name))[0]
    return stem, abs_fp, w, h


# ── Image Editor lookup ───────────────────────────────────────────────────────

def _find_image_editor_area(context):
    screen = getattr(context, "screen", None)
    if screen is None:
        return None
    for area in screen.areas:
        if area.type == 'IMAGE_EDITOR':
            return area
    return None


def _set_editor_image(context, image):
    area = _find_image_editor_area(context)
    if area is None:
        return False
    for space in area.spaces:
        if space.type == 'IMAGE_EDITOR':
            space.image = image
            area.tag_redraw()
            return True
    return False


def _tag_all_image_editors_redraw():
    """Force every Image Editor area in every window to redraw."""
    for window in bpy.context.window_manager.windows:
        for area in window.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                area.tag_redraw()


# ── Scene-state helpers ───────────────────────────────────────────────────────

def _get_cel_pair(scene):
    """Return (cel_img, bg_img) for the scene's active cel, or None."""
    name = scene.domeanimatic_active_cel_name
    if not name:
        return None
    cel = bpy.data.images.get(name)
    bg  = bpy.data.images.get(name + _BG_SUFFIX)
    if cel is None:
        return None
    return cel, bg


# ── GPU overlay (BG underneath, CEL always on top) ────────────────────────────

_DRAW_HANDLE = None
_DIAG_PRINTED = False   # one-shot diagnostic on first draw attempt


def _get_overlay_shader():
    """
    Return (shader, kind). Kind is one of:
        'IMAGE_COLOR'  — builtin; supports opacity via color-uniform alpha
        'IMAGE'        — builtin; no opacity, falls back to blend state
        None           — gpu module missing or no shader available
    """
    if gpu is None:
        return None, None
    for name in ('IMAGE_COLOR', 'IMAGE'):
        try:
            return gpu.shader.from_builtin(name), name
        except Exception:
            continue
    return None, None


def _diag(msg):
    """Print a diagnostic once per session when show_labels is on."""
    global _DIAG_PRINTED
    if _DIAG_PRINTED:
        return
    try:
        wm = bpy.data.window_managers[0]
        if getattr(wm, "domeanimatic_show_labels", False):
            print(f"[TransparentCel] {msg}")
            _DIAG_PRINTED = True
    except Exception:
        pass


def _draw_image_quad(shader, kind, tex, verts, uvs, indices, rgba):
    """Issue one textured quad draw with the given color uniform."""
    try:
        batch = batch_for_shader(
            shader, 'TRIS',
            {"pos": verts, "texCoord": uvs},
            indices=indices,
        )
    except Exception as e:
        _diag(f"batch_for_shader failed: {e}")
        return
    shader.bind()
    try:
        shader.uniform_sampler("image", tex)
    except Exception as e:
        _diag(f"uniform_sampler failed: {e}")
    if kind == 'IMAGE_COLOR':
        try:
            shader.uniform_float("color", rgba)
        except Exception as e:
            _diag(f"uniform_float(color) failed: {e}")
    batch.draw(shader)


def _draw_bg_overlay():
    """POST_PIXEL draw handler — draws BG underneath cel, then redraws cel on
    top at 100% so strokes are never covered regardless of bg opacity."""
    if gpu is None:
        _diag("gpu module unavailable")
        return

    ctx = bpy.context
    scene = ctx.scene
    if not getattr(scene, "domeanimatic_cel_bg_on", False):
        return

    pair = _get_cel_pair(scene)
    if pair is None:
        _diag("no active cel pair")
        return
    cel_img, bg_img = pair
    if bg_img is None:
        _diag("bg_img missing from pair")
        return

    space = ctx.space_data
    if space is None or space.type != 'IMAGE_EDITOR':
        return
    if space.image is not cel_img:
        return

    region = ctx.region
    if region is None or region.type != 'WINDOW':
        return

    # Map the cel's image-space rect to region pixel coords via view2d.
    # Image Editor view2d uses UV space: (0,0) at image bottom-left and
    # (1,1) at image top-right.
    w, h = cel_img.size
    if w == 0 or h == 0:
        return
    try:
        x0, y0 = region.view2d.view_to_region(0.0, 0.0, clip=False)
        x1, y1 = region.view2d.view_to_region(1.0, 1.0, clip=False)
    except Exception as e:
        _diag(f"view_to_region failed: {e}")
        return

    shader, kind = _get_overlay_shader()
    if shader is None:
        _diag("no overlay shader available")
        return

    try:
        bg_tex  = gpu.texture.from_image(bg_img)
        cel_tex = gpu.texture.from_image(cel_img)
    except Exception as e:
        _diag(f"gpu.texture.from_image failed: {e}")
        return

    verts   = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    uvs     = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    indices = [(0, 1, 2), (0, 2, 3)]

    opacity = float(getattr(scene, "domeanimatic_cel_bg_opacity", 0.5))
    opacity = max(0.0, min(1.0, opacity))

    # Scissor rect — hard-clip all GPU draws to the UV canvas pixel bounds.
    # This prevents any bleed into the gray area outside the image canvas
    # regardless of floating-point edge cases in the quad vertices.
    sc_x = max(0, int(round(x0)))
    sc_y = max(0, int(round(y0)))
    sc_w = min(region.width,  int(round(x1))) - sc_x
    sc_h = min(region.height, int(round(y1))) - sc_y
    if sc_w <= 0 or sc_h <= 0:
        return

    # Use try/finally so blend_set('NONE') and scissor_test_set(False) are
    # ALWAYS reached, even if a draw call raises an exception.  Leaving
    # blend_set('ALPHA') active would cause Blender to composite the gray
    # editor background against black on the next pass, producing the black
    # bleed visible outside the UV canvas.
    try:
        gpu.state.scissor_set(sc_x, sc_y, sc_w, sc_h)
        gpu.state.scissor_test_set(True)
        gpu.state.blend_set('ALPHA')

        # Pass 1 — background reference at user opacity.
        _draw_image_quad(
            shader, kind, bg_tex, verts, uvs, indices,
            (1.0, 1.0, 1.0, opacity),
        )

        # Pass 2 — cel on top at 100%. Transparent pixels in the cel let the
        # BG below remain visible; painted pixels fully cover the BG.
        _draw_image_quad(
            shader, kind, cel_tex, verts, uvs, indices,
            (1.0, 1.0, 1.0, 1.0),
        )

    finally:
        gpu.state.blend_set('NONE')
        gpu.state.scissor_test_set(False)


def _register_draw_handler():
    global _DRAW_HANDLE
    if gpu is None:
        return
    if _DRAW_HANDLE is not None:
        return
    _DRAW_HANDLE = bpy.types.SpaceImageEditor.draw_handler_add(
        _draw_bg_overlay, (), 'WINDOW', 'POST_PIXEL'
    )


def _unregister_draw_handler():
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(
                _DRAW_HANDLE, 'WINDOW'
            )
        except Exception:
            pass
        _DRAW_HANDLE = None


# ── Toggle / opacity update callbacks ─────────────────────────────────────────

def _on_bg_toggle_update(self, context):
    _tag_all_image_editors_redraw()


def _on_bg_opacity_update(self, context):
    _tag_all_image_editors_redraw()


# ── Background image load (from VSE) ──────────────────────────────────────────

def _load_bg_into(bg_img, vse_abs_path, w, h):
    """Copy the VSE frame's pixels into bg_img (an existing Image datablock)."""
    if np is None:
        raise RuntimeError("numpy not available")

    src = bpy.data.images.load(vse_abs_path, check_existing=True)

    # Force Blender to actually read the pixel data from disk.
    # Newly-loaded images can be lazy — touching .pixels[0] forces the read.
    try:
        if len(src.pixels) == 0:
            src.reload()
        _ = src.pixels[0]
    except Exception:
        try:
            src.reload()
        except Exception:
            pass

    if src.size[0] == 0 or src.size[1] == 0:
        raise RuntimeError(
            f"Source image has zero size after load: {vse_abs_path}")

    if (src.size[0], src.size[1]) != (w, h):
        # Upscale/downscale a copy so we don't mutate the user's source image
        src = src.copy()
        src.scale(w, h)

    sw, sh = src.size[0], src.size[1]
    n = sw * sh * 4
    buf = np.empty(n, dtype=np.float32)
    src.pixels.foreach_get(buf)

    # Sanity check
    if bg_img.size[0] != sw or bg_img.size[1] != sh:
        bg_img.scale(sw, sh)

    bg_img.pixels.foreach_set(buf)
    bg_img.update()

    # Optional diagnostic — prints once per session if dev-info toggle is on
    try:
        nonzero = int((buf != 0.0).sum())
        if nonzero == 0:
            print(f"[TransparentCel] WARNING: bg pixels all zero after load ({vse_abs_path})")
        else:
            wm = bpy.data.window_managers[0]
            if getattr(wm, "domeanimatic_show_labels", False):
                print(f"[TransparentCel] bg loaded: {sw}x{sh}, "
                      f"{nonzero}/{n} non-zero floats from {vse_abs_path}")
    except Exception:
        pass


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_setup(bpy.types.Operator):
    bl_idname      = "domeanimatic.cel_setup"
    bl_label       = "Setup Transparent Cel"
    bl_description = (
        "Create a new transparent cel PNG in <blend-dir>/transparent-cels-"
        "paintings/ sized to the current VSE frame, with that frame loaded "
        "as the background reference"
    )

    @classmethod
    def poll(cls, context):
        return bool(bpy.data.filepath)

    def execute(self, context):
        if np is None:
            self.report({'ERROR'}, "numpy is required.")
            return {'CANCELLED'}

        folder = _ensure_cel_folder()
        if folder is None:
            self.report({'ERROR'},
                "Save your .blend file first — cel folder is relative to it.")
            return {'CANCELLED'}

        vse = _get_vse_frame()
        if vse is None:
            self.report({'ERROR'},
                "No valid VSE image/movie at the Dome Animatic playhead.")
            return {'CANCELLED'}
        stem, bg_abs_path, w, h = vse

        frame = _dome_frame()
        cel_path, cel_fn = _next_cel_path(stem, folder, frame)
        cel_name = os.path.splitext(cel_fn)[0]
        bg_name  = cel_name + _BG_SUFFIX

        # ── Create cel image (transparent, saved to disk immediately) ─────
        cel_img = bpy.data.images.new(
            name=cel_name,
            width=w, height=h,
            alpha=True,
            float_buffer=False,
        )
        cel_img.alpha_mode    = 'STRAIGHT'
        cel_img.generated_color = (0.0, 0.0, 0.0, 0.0)
        cel_img.filepath_raw  = cel_path
        cel_img.file_format   = 'PNG'
        try:
            cel_img.save()
        except Exception as e:
            self.report({'ERROR'}, f"Could not save new cel: {e}")
            bpy.data.images.remove(cel_img)
            return {'CANCELLED'}

        # ── Create bg datablock and fill from VSE ─────────────────────────
        if bg_name in bpy.data.images:
            bpy.data.images.remove(bpy.data.images[bg_name])

        bg_img = bpy.data.images.new(
            name=bg_name,
            width=w, height=h,
            alpha=True,
            float_buffer=False,
        )
        bg_img.alpha_mode = 'STRAIGHT'

        try:
            _load_bg_into(bg_img, bg_abs_path, w, h)
        except Exception as e:
            self.report({'WARNING'}, f"BG load failed: {e}")

        # ── Hook up scene state ───────────────────────────────────────────
        context.scene.domeanimatic_active_cel_name = cel_name
        context.scene.domeanimatic_cel_bg_on       = True

        # Show the cel in the Image Editor (the user paints on this)
        _set_editor_image(context, cel_img)
        _tag_all_image_editors_redraw()

        self.report({'INFO'},
            f"Cel ready: {cel_fn} ({w}x{h}) — bg overlay ON.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_save(bpy.types.Operator):
    bl_idname      = "domeanimatic.cel_save"
    bl_label       = "Save Cel"
    bl_description = (
        "Save the transparent cel PNG. ONLY the painted layer is written — "
        "the background reference is never included"
    )

    @classmethod
    def poll(cls, context):
        pair = _get_cel_pair(context.scene)
        return pair is not None and pair[0].filepath_raw

    def execute(self, context):
        pair = _get_cel_pair(context.scene)
        if pair is None:
            self.report({'WARNING'}, "No active transparent cel.")
            return {'CANCELLED'}
        cel_img, _bg = pair
        if not cel_img.filepath_raw:
            self.report({'ERROR'}, "Cel has no filepath set.")
            return {'CANCELLED'}
        try:
            cel_img.save()
        except Exception as e:
            self.report({'ERROR'}, f"Save failed: {e}")
            return {'CANCELLED'}
        self.report({'INFO'}, f"Saved: {cel_img.filepath_raw}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_refresh_bg(bpy.types.Operator):
    bl_idname      = "domeanimatic.cel_refresh_bg"
    bl_label       = "Refresh Background from VSE"
    bl_description = (
        "Reload the background reference from the CURRENT Dome Animatic VSE "
        "frame (use after you move the playhead)"
    )

    @classmethod
    def poll(cls, context):
        return _get_cel_pair(context.scene) is not None

    def execute(self, context):
        pair = _get_cel_pair(context.scene)
        if pair is None:
            self.report({'WARNING'}, "No active transparent cel.")
            return {'CANCELLED'}
        cel_img, bg_img = pair
        if bg_img is None:
            self.report({'WARNING'}, "Background datablock missing.")
            return {'CANCELLED'}

        vse = _get_vse_frame()
        if vse is None:
            self.report({'ERROR'}, "No valid VSE image at current frame.")
            return {'CANCELLED'}
        _stem, bg_abs_path, w, h = vse

        # Resize bg_img if needed, then repaint its pixels
        if (bg_img.size[0], bg_img.size[1]) != (w, h):
            bg_img.scale(w, h)
        try:
            _load_bg_into(bg_img, bg_abs_path, w, h)
        except Exception as e:
            self.report({'ERROR'}, f"BG reload failed: {e}")
            return {'CANCELLED'}

        _tag_all_image_editors_redraw()
        self.report({'INFO'}, "Background refreshed from VSE.")
        return {'FINISHED'}


# ── UI ────────────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    scene = context.scene
    col = box.column(align=True)

    # Setup button
    row = col.row(align=True)
    row.operator(
        "domeanimatic.cel_setup",
        text="New Cel from VSE Frame",
        icon='FILE_NEW',
    )
    if not bpy.data.filepath:
        col.label(text="Save your .blend first.", icon='ERROR')
        return

    pair = _get_cel_pair(scene)
    if pair is None:
        col.label(text="No active cel.", icon='INFO')
        return

    cel_img, bg_img = pair

    col.separator(factor=0.4)
    col.label(
        text=os.path.basename(cel_img.filepath_raw or cel_img.name),
        icon='IMAGE_RGB_ALPHA',
    )

    # Toggle + opacity
    col.prop(
        scene, "domeanimatic_cel_bg_on",
        text="Background Reference",
        toggle=True,
        icon='HIDE_OFF' if scene.domeanimatic_cel_bg_on else 'HIDE_ON',
    )
    sub = col.column(align=True)
    sub.enabled = scene.domeanimatic_cel_bg_on and bg_img is not None
    sub.prop(scene, "domeanimatic_cel_bg_opacity", text="Opacity", slider=True)

    col.separator(factor=0.3)

    # Refresh bg / save
    row = col.row(align=True)
    row.operator("domeanimatic.cel_refresh_bg",
                 text="Refresh BG", icon='FILE_REFRESH')
    row.operator("domeanimatic.cel_save",
                 text="Save Cel", icon='FILE_TICK')


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_cel_setup,
    DOMEANIMATIC_OT_cel_save,
    DOMEANIMATIC_OT_cel_refresh_bg,
]


def register():
    bpy.types.Scene.domeanimatic_active_cel_name = bpy.props.StringProperty(
        name="Active Cel Name",
        description="Name of the Image datablock currently acting as the active cel",
        default="",
    )
    bpy.types.Scene.domeanimatic_cel_bg_on = bpy.props.BoolProperty(
        name="Background Reference",
        description="Show the VSE frame as a reference underneath the cel",
        default=True,
        update=_on_bg_toggle_update,
    )
    bpy.types.Scene.domeanimatic_cel_bg_opacity = bpy.props.FloatProperty(
        name="Background Opacity",
        description=(
            "Opacity of the background reference. The cel is always drawn "
            "on top at 100%, so strokes stay fully visible regardless of "
            "this value"
        ),
        default=0.5,
        min=0.0,
        max=1.0,
        subtype='FACTOR',
        update=_on_bg_opacity_update,
    )

    for cls in classes:
        bpy.utils.register_class(cls)

    _register_draw_handler()


def unregister():
    _unregister_draw_handler()

    for cls in reversed(classes):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

    # Drop legacy property if it was ever registered by a previous version.
    if hasattr(bpy.types.Scene, "domeanimatic_cel_bg_blend_mode"):
        try:
            del bpy.types.Scene.domeanimatic_cel_bg_blend_mode
        except Exception:
            pass

    for attr in (
        "domeanimatic_cel_bg_opacity",
        "domeanimatic_cel_bg_on",
        "domeanimatic_active_cel_name",
    ):
        if hasattr(bpy.types.Scene, attr):
            try:
                delattr(bpy.types.Scene, attr)
            except Exception:
                pass

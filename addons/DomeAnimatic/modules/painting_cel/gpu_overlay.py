"""
gpu_overlay.py — POST_PIXEL draw handler for the cel layer composite preview.

Draws BG → CEL_A → CEL_B in the Image Editor (bottom-up) using each slot's
visibility and opacity from global props. Also draws a red warning banner when
the active cel is invisible.
"""

import bpy

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except Exception:
    gpu = None
    batch_for_shader = None

from ... import cel_store
from ...global_scene_shared_props import gp


_DRAW_HANDLE = None
_SHADER      = None
_SHADER_KIND = None
_DIAG_DONE   = False

# Cached per-redraw resources (built once, reused every draw — the overlay
# runs on every Image Editor redraw, so nothing should be re-created here).
_BD_SHADER   = None   # UNIFORM_COLOR shader for the opaque backdrop
_UNIT_IMG    = None   # unit-quad batch for the image shader (pos + texCoord)
_UNIT_COLOR  = None   # unit-quad batch for the backdrop shader (pos only)
_CEL_NAMES   = None   # frozenset of cel datablock names


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


_UNIT_VERTS   = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
_UNIT_INDICES = [(0, 1, 2), (0, 2, 3)]


def _get_bd_shader():
    global _BD_SHADER
    if _BD_SHADER is None:
        _BD_SHADER = gpu.shader.from_builtin('UNIFORM_COLOR')
    return _BD_SHADER


def _get_unit_img_batch(shader):
    global _UNIT_IMG
    if _UNIT_IMG is None:
        _UNIT_IMG = batch_for_shader(shader, 'TRIS',
                                     {"pos": _UNIT_VERTS, "texCoord": _UNIT_VERTS},
                                     indices=_UNIT_INDICES)
    return _UNIT_IMG


def _get_unit_color_batch(shader):
    global _UNIT_COLOR
    if _UNIT_COLOR is None:
        _UNIT_COLOR = batch_for_shader(shader, 'TRIS', {"pos": _UNIT_VERTS},
                                       indices=_UNIT_INDICES)
    return _UNIT_COLOR


def _get_cel_names():
    global _CEL_NAMES
    if _CEL_NAMES is None:
        _CEL_NAMES = frozenset(layer.datablock_name for layer in cel_store.LAYERS)
    return _CEL_NAMES


def _diag(msg: str) -> None:
    global _DIAG_DONE
    if _DIAG_DONE:
        return
    try:
        if gp().show_labels:
            print(f"[GPUOverlay] {msg}")
            _DIAG_DONE = True
    except Exception:
        pass


def _draw_overlay() -> None:
    """POST_PIXEL handler: draws all visible cel layers + optional warning banner."""
    if gpu is None:
        return

    ctx   = bpy.context
    space = ctx.space_data
    if space is None or space.type != 'IMAGE_EDITOR':
        return
    region = ctx.region
    if region is None or region.type != 'WINDOW':
        return

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

    g = gp()

    # In CEL_LAYERS mode (viewing a cel) cover the editor's native drawing of
    # space.image with an opaque backdrop first, so the stack below is a clean
    # composite and each layer's eye/opacity reads true — otherwise the native
    # full-opacity image bleeds through wherever the overlay is transparent.
    try:
        synch_mode = ctx.scene.domeanimatic.synch_mode
    except Exception:
        synch_mode = None
    draw_backdrop = (synch_mode == 'CEL_LAYERS'
                     and shown_img.name in _get_cel_names())

    # All quads are the cached unit quad, placed by a model matrix — no
    # per-redraw batch_for_shader / VBO rebuilds.
    try:
        gpu.state.scissor_set(sc_x, sc_y, sc_w, sc_h)
        gpu.state.scissor_test_set(True)
        gpu.state.blend_set('ALPHA')

        with gpu.matrix.push_pop():
            gpu.matrix.translate((x0, y0))
            gpu.matrix.scale((x1 - x0, y1 - y0))

            if draw_backdrop:
                bd_shader = _get_bd_shader()
                bd_batch  = _get_unit_color_batch(bd_shader)
                bd_shader.bind()
                bd_shader.uniform_float("color", (0.0, 0.0, 0.0, 1.0))
                bd_batch.draw(bd_shader)

            batch = _get_unit_img_batch(shader)
            for layer in cel_store.DRAW_ORDER:
                slot_key = layer.slot_id.lower()
                if not getattr(g, f"{slot_key}_visible", True):
                    continue
                img = cel_store.get_cel_image(layer.slot_id)
                if img is None:
                    continue
                try:
                    tex = gpu.texture.from_image(img)
                except Exception as e:
                    _diag(f"texture.from_image {layer.slot_id}: {e}")
                    continue
                opacity = float(getattr(g, f"{slot_key}_opacity", 1.0))
                shader.bind()
                try:
                    shader.uniform_sampler("image", tex)
                except Exception as e:
                    _diag(f"uniform_sampler: {e}")
                if kind == 'IMAGE_COLOR':
                    try:
                        shader.uniform_float("color", (1.0, 1.0, 1.0, opacity))
                    except Exception as e:
                        _diag(f"uniform_float: {e}")
                batch.draw(shader)

    finally:
        gpu.state.blend_set('NONE')
        gpu.state.scissor_test_set(False)

    # Warning banner when painting on hidden layer
    active_slot = g.active_cel
    slot_key    = active_slot.lower()
    if not getattr(g, f"{slot_key}_visible", True):
        _draw_invisible_warning(region, x0, y1)


def _draw_invisible_warning(region, x0: float, y1: float) -> None:
    if gpu is None:
        return
    try:
        import blf
        banner_h = 24
        gpu.state.blend_set('ALPHA')
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
        blf.position(0, x0 + 8, y1 + 6, 0)
        blf.size(0, 13)
        blf.color(0, 1.0, 1.0, 1.0, 1.0)
        blf.draw(0, "Painting on invisible layer — use panel to Turn On or Pick Another")
    except Exception:
        pass


def register() -> None:
    global _DRAW_HANDLE
    if gpu is None or _DRAW_HANDLE is not None:
        return
    _DRAW_HANDLE = bpy.types.SpaceImageEditor.draw_handler_add(
        _draw_overlay, (), 'WINDOW', 'POST_PIXEL'
    )


def unregister() -> None:
    global _DRAW_HANDLE, _SHADER, _SHADER_KIND, _DIAG_DONE
    global _BD_SHADER, _UNIT_IMG, _UNIT_COLOR, _CEL_NAMES
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(_DRAW_HANDLE, 'WINDOW')
        except Exception:
            pass
        _DRAW_HANDLE = None
    _SHADER      = None
    _SHADER_KIND = None
    _DIAG_DONE   = False
    _BD_SHADER   = None
    _UNIT_IMG    = None
    _UNIT_COLOR  = None
    _CEL_NAMES   = None

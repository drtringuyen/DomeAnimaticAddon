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


def _draw_quad(shader, kind, tex, verts, uvs, indices, rgba) -> None:
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

    verts   = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    uvs     = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    indices = [(0, 1, 2), (0, 2, 3)]

    g = gp()

    try:
        gpu.state.scissor_set(sc_x, sc_y, sc_w, sc_h)
        gpu.state.scissor_test_set(True)
        gpu.state.blend_set('ALPHA')

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
            _draw_quad(shader, kind, tex, verts, uvs, indices, (1.0, 1.0, 1.0, opacity))

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
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(_DRAW_HANDLE, 'WINDOW')
        except Exception:
            pass
        _DRAW_HANDLE = None
    _SHADER      = None
    _SHADER_KIND = None
    _DIAG_DONE   = False

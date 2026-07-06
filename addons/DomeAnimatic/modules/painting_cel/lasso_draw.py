"""
lasso_draw.py — GPU draw handlers for the lasso transform preview.

Owns the single SpaceImageEditor POST_PIXEL draw handler and the reference to
the currently-running lasso operator (one at a time). The operator registers
itself here on invoke and clears itself on cleanup; all on-screen drawing —
the live cel composite with the CUT hole, the floating cut-out, the lasso
outline, and the status banner — happens in this module by reading state off
that operator instance.

No pixels are written here: this is pure GPU preview. The committing bake lives
in lasso_raster.composite_float, called from the operator.
"""

import bpy

try:
    import gpu
    from gpu_extras.batch import batch_for_shader
except Exception:
    gpu = None
    batch_for_shader = None

try:
    import blf
except Exception:
    blf = None

from ... import cel_store
from ...global_scene_shared_props import gp


# ── Module-level draw state (one running op at a time) ─────────────────────────

_DRAW_HANDLE = None   # SpaceImageEditor POST_PIXEL handle
_ACTIVE_OP   = None   # the running lasso operator instance
_DIAG_DONE   = False

BANNER_H = 24


def _diag(msg: str) -> None:
    global _DIAG_DONE
    if _DIAG_DONE:
        return
    try:
        if gp().show_labels:
            print(f"[LassoTransform] {msg}")
            _DIAG_DONE = True
    except Exception:
        pass


# ── Active-op / handler lifecycle (called by the operator) ────────────────────

def get_active_op():
    return _ACTIVE_OP


def set_active_op(op) -> None:
    global _ACTIVE_OP
    _ACTIVE_OP = op


def clear_active_op() -> None:
    global _ACTIVE_OP
    _ACTIVE_OP = None


def ensure_handler() -> None:
    global _DRAW_HANDLE
    if _DRAW_HANDLE is None and gpu is not None:
        _DRAW_HANDLE = bpy.types.SpaceImageEditor.draw_handler_add(
            _draw_lasso, (), 'WINDOW', 'POST_PIXEL')


def remove_handler() -> None:
    global _DRAW_HANDLE
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(_DRAW_HANDLE, 'WINDOW')
        except Exception:
            pass
        _DRAW_HANDLE = None


# ── Shaders ───────────────────────────────────────────────────────────────────

_IMG_SHADER      = None
_IMG_SHADER_KIND = None


def _get_image_shader():
    global _IMG_SHADER, _IMG_SHADER_KIND
    if _IMG_SHADER is not None:
        return _IMG_SHADER, _IMG_SHADER_KIND
    if gpu is None:
        return None, None
    for name in ('IMAGE_COLOR', 'IMAGE'):
        try:
            _IMG_SHADER      = gpu.shader.from_builtin(name)
            _IMG_SHADER_KIND = name
            return _IMG_SHADER, _IMG_SHADER_KIND
        except Exception:
            continue
    return None, None


def _get_line_shader():
    for name in ('POLYLINE_UNIFORM_COLOR', 'UNIFORM_COLOR'):
        try:
            return gpu.shader.from_builtin(name), name
        except Exception:
            continue
    return None, None


# ── Draw handler (module-level, one running op at a time) ─────────────────────

def _draw_lasso() -> None:
    op = _ACTIVE_OP
    if op is None or gpu is None:
        return
    ctx   = bpy.context
    space = ctx.space_data
    if space is None or space.type != 'IMAGE_EDITOR':
        return
    region = ctx.region
    if region is None or region.type != 'WINDOW':
        return
    try:
        x0, y0 = region.view2d.view_to_region(0.0, 0.0, clip=False)
        x1, y1 = region.view2d.view_to_region(1.0, 1.0, clip=False)
    except Exception as e:
        _diag(f"view_to_region: {e}")
        return

    def to_region(px, py):
        return (x0 + (px / op._w) * (x1 - x0),
                y0 + (py / op._h) * (y1 - y0))

    try:
        if op._state != 'DRAW':
            _draw_composite(op, region, x0, y0, x1, y1, to_region)
        _draw_outline(op, region, to_region)
        _draw_status(op, region)
    except Exception as e:
        _diag(f"draw: {e}")


def _draw_composite(op, region, x0, y0, x1, y1, to_region) -> None:
    """Redraw the full cel stack with the hole substituted on the active layer
    and the floating cut-out injected at its destination layer's depth."""
    shader, kind = _get_image_shader()
    if shader is None:
        _diag("no image shader")
        return

    sc_x = max(0, int(round(x0)))
    sc_y = max(0, int(round(y0)))
    sc_w = min(region.width,  int(round(x1))) - sc_x
    sc_h = min(region.height, int(round(y1))) - sc_y
    if sc_w <= 0 or sc_h <= 0:
        return

    verts   = [(x0, y0), (x1, y0), (x1, y1), (x0, y1)]
    uvs     = [(0.0, 0.0), (1.0, 0.0), (1.0, 1.0), (0.0, 1.0)]
    indices = [(0, 1, 2), (0, 2, 3)]

    g          = gp()
    float_slot = g.active_cel   # dest follows the active layer (retargetable)

    try:
        gpu.state.scissor_set(sc_x, sc_y, sc_w, sc_h)
        gpu.state.scissor_test_set(True)
        gpu.state.blend_set('ALPHA')

        # Opaque backdrop — covers the editor's native drawing + gpu_overlay so
        # the CUT hole reads as truly transparent.
        bg_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        bg_batch  = batch_for_shader(bg_shader, 'TRI_FAN', {"pos": verts})
        bg_shader.bind()
        bg_shader.uniform_float("color", (0.11, 0.11, 0.11, 1.0))
        bg_batch.draw(bg_shader)

        for layer in cel_store.DRAW_ORDER:
            slot_key = layer.slot_id.lower()
            visible  = getattr(g, f"{slot_key}_visible", True)
            opacity  = float(getattr(g, f"{slot_key}_opacity", 1.0))
            if visible:
                if (layer.slot_id == getattr(op, '_src_slot', None)
                        and op._source_mode == 'CUT'
                        and getattr(op, '_hole_live', False)
                        and op._hole_tex is not None):
                    tex = op._hole_tex
                else:
                    img = cel_store.get_cel_image(layer.slot_id)
                    tex = None
                    if img is not None:
                        try:
                            tex = gpu.texture.from_image(img)
                        except Exception as e:
                            _diag(f"texture.from_image {layer.slot_id}: {e}")
                if tex is not None:
                    _draw_tex_quad(shader, kind, tex, verts, uvs, indices,
                                   (1.0, 1.0, 1.0, opacity))
            # Floating cut-out at its destination layer's depth
            if layer.slot_id == float_slot and op._float_tex is not None:
                corners = op._transformed_bbox_corners()
                fverts  = [to_region(cx, cy) for cx, cy in corners]
                _draw_tex_quad(shader, kind, op._float_tex, fverts, uvs, indices,
                               (1.0, 1.0, 1.0, 1.0))
    finally:
        gpu.state.blend_set('NONE')
        gpu.state.scissor_test_set(False)


def _draw_tex_quad(shader, kind, tex, verts, uvs, indices, rgba) -> None:
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


def _draw_outline(op, region, to_region) -> None:
    """Lasso polygon outline: points + rubber band in DRAW, the transformed
    selection boundary in the floating states."""
    if op._state == 'DRAW':
        if not op._points:
            return
        pts = [to_region(px, py) for px, py in op._points]
        if op._cursor_px is not None:
            pts.append(to_region(*op._cursor_px))
        pts.append(pts[0])   # closing hint back to the first point
        color = (1.0, 1.0, 1.0, 0.9)
    else:
        moved = op._affine_apply_points(op._points)
        pts   = [to_region(px, py) for px, py in moved]
        pts.append(pts[0])
        color = (0.2, 0.8, 1.0, 0.9)

    shader, kind = _get_line_shader()
    if shader is None:
        return
    gpu.state.blend_set('ALPHA')
    batch = batch_for_shader(shader, 'LINE_STRIP', {"pos": pts})
    shader.bind()
    if kind == 'POLYLINE_UNIFORM_COLOR':
        shader.uniform_float("viewportSize", (region.width, region.height))
        shader.uniform_float("lineWidth", 2.0)
    shader.uniform_float("color", color)
    batch.draw(shader)

    # First-point handle so the user can see where clicking closes the lasso
    if op._state == 'DRAW':
        pt_shader = gpu.shader.from_builtin('UNIFORM_COLOR')
        gpu.state.point_size_set(8.0)
        pt_batch = batch_for_shader(pt_shader, 'POINTS', {"pos": [pts[0]]})
        pt_shader.bind()
        pt_shader.uniform_float("color", (1.0, 0.6, 0.1, 1.0))
        pt_batch.draw(pt_shader)
        gpu.state.point_size_set(1.0)
    gpu.state.blend_set('NONE')


_STATUS_TEXT = {
    'DRAW':       "Lasso: click points, Enter to close, Esc cancel",
    'FLOAT_IDLE': "Drag/G move | R/S | Shift+D stamp | Ctrl+J/X dup/cut->above | "
                  "Ctrl+C/V copy/paste | X del | scrub timeline or switch layer, "
                  "then Enter/click-outside apply | Esc",
    'GRAB':       "Grab: move mouse | release/LMB/Enter confirm | RMB/Esc cancel",
    'ROTATE':     "Rotate around selection center | LMB/Enter confirm | RMB/Esc cancel",
    'SCALE':      "Scale around selection center | LMB/Enter confirm | RMB/Esc cancel",
}


def _draw_status(op, region) -> None:
    if blf is None:
        return
    text = _STATUS_TEXT.get(op._state, "")
    if op._state != 'DRAW':
        dest  = gp().active_cel
        dome  = bpy.data.scenes.get("Dome Animatic")
        frame = dome.frame_current if dome else 0
        mode  = ("cut" if op._source_mode == 'CUT'
                 and getattr(op, '_hole_live', False) else "copy")
        text += f"   [{mode} {getattr(op, '_src_slot', op._slot)} -> {dest} @ f{frame}]"
    y = region.height - BANNER_H
    gpu.state.blend_set('ALPHA')
    shader = gpu.shader.from_builtin('UNIFORM_COLOR')
    batch  = batch_for_shader(shader, 'TRI_FAN', {"pos": [
        (0, y), (region.width, y),
        (region.width, region.height), (0, region.height),
    ]})
    shader.bind()
    shader.uniform_float("color", (0.08, 0.08, 0.08, 0.8))
    batch.draw(shader)
    gpu.state.blend_set('NONE')
    blf.position(0, 10, y + 7, 0)
    blf.size(0, 13)
    blf.color(0, 1.0, 1.0, 1.0, 1.0)
    blf.draw(0, f"Lasso Transform [{op._slot}] — {text}")

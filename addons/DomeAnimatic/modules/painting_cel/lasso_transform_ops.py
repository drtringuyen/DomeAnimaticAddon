"""
lasso_transform_ops.py — Photoshop-style lasso transform for the active cel layer.

Modal operator for the Image Editor: draw a polygon lasso on the active cel,
then move / rotate / scale the selected pixels as a floating GPU-textured quad
(live, no image.pixels writes), committing in one vectorized numpy pass on
Enter. Supports duplicating (Ctrl+J) or cutting (Ctrl+X) the selection to the
cel layer above, instant delete (X), and Photoshop-style Shift+D: stamp the
floating piece down where it is, keep the same selection floating as a copy,
and immediately grab it to place the next duplicate.

States: DRAW -> FLOAT_IDLE <-> GRAB / ROTATE / SCALE.
The floating piece carries a single 2D affine  p' = scale * R(angle) * p + t.
"""

import math
import time
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

try:
    import numpy as np
except ImportError:
    np = None

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp


_DRAW_HANDLE = None   # module-level SpaceImageEditor POST_PIXEL handle
_ACTIVE_OP   = None   # the running lasso operator instance (one at a time)
_DIAG_DONE   = False

CLOSE_THRESHOLD_PX  = 12.0   # region pixels — click this close to point 0 closes
DBL_CLICK_DIST_PX   = 6.0    # region pixels — manual double-click fallback
BANNER_H            = 24


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


# ── Numpy helpers ─────────────────────────────────────────────────────────────

def _read_pixels(img) -> "np.ndarray":
    """Full image as (h, w, 4) float32 via foreach_get."""
    w, h = img.size
    buf  = np.empty(w * h * 4, dtype=np.float32)
    img.pixels.foreach_get(buf)
    return buf.reshape(h, w, 4)


def _write_pixels(img, buf) -> None:
    img.pixels.foreach_set(np.ascontiguousarray(buf, dtype=np.float32).ravel())
    img.update()


def _rasterize_polygon(points_px, bx0: int, by0: int, bw: int, bh: int) -> "np.ndarray":
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


def _make_texture(buf_hw4):
    """Upload a (h, w, 4) float32 numpy buffer as a GPUTexture (straight alpha)."""
    h, w = buf_hw4.shape[:2]
    flat = np.ascontiguousarray(buf_hw4, dtype=np.float32).ravel()
    data = gpu.types.Buffer('FLOAT', w * h * 4, flat)
    return gpu.types.GPUTexture((w, h), format='RGBA16F', data=data)


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
    float_slot = op._slot if op._dest_layer == 'ACTIVE' else op._upper_slot()

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
                if layer.slot_id == op._slot and op._source_mode == 'CUT':
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
    'FLOAT_IDLE': "Shift+D duplicate | Ctrl+J dup->above | Ctrl+X cut->above | "
                  "X delete | G/R/S | Enter apply | Esc",
    'GRAB':       "Grab: move mouse | LMB/Enter confirm | RMB/Esc cancel",
    'ROTATE':     "Rotate around selection center | LMB/Enter confirm | RMB/Esc cancel",
    'SCALE':      "Scale around selection center | LMB/Enter confirm | RMB/Esc cancel",
}


def _draw_status(op, region) -> None:
    if blf is None:
        return
    text = _STATUS_TEXT.get(op._state, "")
    if op._dest_layer == 'UPPER':
        mode = "cut" if op._source_mode == 'CUT' else "dup"
        text += f"   [{mode} -> {op._upper_slot()}]"
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


# ── Operator ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_lasso_transform(bpy.types.Operator):
    """Lasso-select pixels on the active cel and move/rotate/scale them.
    Ctrl+J duplicates / Ctrl+X cuts the selection to the layer above."""
    bl_idname  = "domeanimatic.lasso_transform"
    bl_label   = "Lasso Transform"
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        if gpu is None or np is None:
            return False
        space = context.space_data
        if space is None or space.type != 'IMAGE_EDITOR':
            return False
        return cel_store.get_cel_image(gp(context).active_cel) is not None

    # ── Lifecycle ────────────────────────────────────────────────────────────

    def invoke(self, context, event):
        global _ACTIVE_OP, _DRAW_HANDLE
        if _ACTIVE_OP is not None:
            self.report({'WARNING'}, "Lasso Transform is already running.")
            return {'CANCELLED'}
        if gpu is None or np is None:
            self.report({'ERROR'}, "GPU module / numpy not available.")
            return {'CANCELLED'}

        slot = gp(context).active_cel
        img  = cel_store.get_cel_image(slot)
        if img is None:
            self.report({'ERROR'}, f"No image datablock for {slot}.")
            return {'CANCELLED'}
        w, h = img.size
        if w == 0 or h == 0:
            self.report({'ERROR'}, f"[{slot}] image has no pixels.")
            return {'CANCELLED'}
        if getattr(img, 'channels', 4) != 4:
            self.report({'ERROR'}, f"[{slot}] image has no alpha channel — "
                                   "lasso cut needs RGBA.")
            return {'CANCELLED'}

        region = next((r for r in context.area.regions if r.type == 'WINDOW'), None)
        if region is None:
            self.report({'ERROR'}, "No WINDOW region in this Image Editor.")
            return {'CANCELLED'}

        self._slot   = slot
        self._image  = img
        self._w      = w
        self._h      = h
        self._region = region
        self._area   = context.area

        self._state     = 'DRAW'
        self._points    = []      # lasso vertices in image pixel space
        self._cursor_px = None

        # Manual double-click detection — modal handlers don't reliably get
        # DOUBLE_CLICK values, so track (time, window-relative region pos).
        self._last_click = (0.0, None)
        try:
            self._dbl_time = max(0.05,
                context.preferences.inputs.mouse_double_click_time / 1000.0)
        except Exception:
            self._dbl_time = 0.35

        # Floating selection (built on polygon close)
        self._bx0 = self._by0 = 0
        self._pw  = self._ph  = 0
        self._mask      = None    # (ph, pw) bool — inside polygon
        self._patch     = None    # (ph, pw, 4) float32 straight RGBA, alpha=0 outside
        self._float_tex = None
        self._hole_tex  = None

        # Accumulated affine: p' = scale * R(angle) * p + (tx, ty)
        self._angle = 0.0
        self._scale = 1.0
        self._tx    = 0.0
        self._ty    = 0.0

        self._dest_layer  = 'ACTIVE'
        self._source_mode = 'CUT'

        # Sub-mode (G/R/S) working data
        self._snap            = None
        self._sub_start_px    = (0.0, 0.0)
        self._sub_start_angle = 0.0
        self._sub_start_dist  = 1.0
        self._pivot_px        = (0.0, 0.0)

        if _DRAW_HANDLE is None:
            _DRAW_HANDLE = bpy.types.SpaceImageEditor.draw_handler_add(
                _draw_lasso, (), 'WINDOW', 'POST_PIXEL')
        _ACTIVE_OP = self

        context.window.cursor_modal_set('CROSSHAIR')
        context.window_manager.modal_handler_add(self)
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._cleanup(context)

    def _cleanup(self, context) -> None:
        global _ACTIVE_OP, _DRAW_HANDLE
        if _DRAW_HANDLE is not None:
            try:
                bpy.types.SpaceImageEditor.draw_handler_remove(_DRAW_HANDLE, 'WINDOW')
            except Exception:
                pass
            _DRAW_HANDLE = None
        _ACTIVE_OP = None
        self._float_tex = None
        self._hole_tex  = None
        self._mask      = None
        self._patch     = None
        try:
            context.window.cursor_modal_restore()
        except Exception:
            pass
        vse_helpers.tag_all_image_editors_redraw()

    def _cancel_op(self, context):
        self._cleanup(context)
        return {'CANCELLED'}

    # ── Coordinate helpers ───────────────────────────────────────────────────

    def _mouse_px(self, event):
        """Mouse position in image pixel space (via the WINDOW region's view2d)."""
        rx = event.mouse_x - self._region.x
        ry = event.mouse_y - self._region.y
        u, v = self._region.view2d.region_to_view(rx, ry)
        return (u * self._w, v * self._h)

    def _px_to_region(self, px, py):
        return self._region.view2d.view_to_region(
            px / self._w, py / self._h, clip=False)

    def _upper_slot(self):
        z = cel_store.BY_SLOT[self._slot].z_order + 1
        for layer in cel_store.DRAW_ORDER:
            if layer.z_order == z:
                return layer.slot_id
        return None

    # ── Affine helpers  (p' = s * R(a) * p + t) ──────────────────────────────

    def _affine_apply_points(self, points):
        ca = math.cos(self._angle) * self._scale
        sa = math.sin(self._angle) * self._scale
        return [(ca * x - sa * y + self._tx,
                 sa * x + ca * y + self._ty) for x, y in points]

    def _transformed_bbox_corners(self):
        bx1 = self._bx0 + self._pw
        by1 = self._by0 + self._ph
        return self._affine_apply_points([
            (self._bx0, self._by0), (bx1, self._by0),
            (bx1, by1), (self._bx0, by1),
        ])

    # ── Modal dispatch ───────────────────────────────────────────────────────

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}   # keep pan/zoom alive

        self._area.tag_redraw()

        if self._state == 'DRAW':
            return self._modal_draw(context, event)
        if self._state in {'GRAB', 'ROTATE', 'SCALE'}:
            return self._modal_submode(context, event)
        return self._modal_idle(context, event)

    # ── DRAW state ───────────────────────────────────────────────────────────

    def _modal_draw(self, context, event):
        if event.type == 'MOUSEMOVE':
            self._cursor_px = self._mouse_px(event)
            return {'RUNNING_MODAL'}

        if event.type == 'LEFTMOUSE' and event.value in {'PRESS', 'DOUBLE_CLICK'}:
            pt = self._mouse_px(event)
            # Region coords derived from window coords — mouse_region_x/y is
            # relative to the invoking region, which may be the sidebar panel.
            rx = event.mouse_x - self._region.x
            ry = event.mouse_y - self._region.y
            now = time.monotonic()
            prev_t, prev_pos = self._last_click
            self._last_click = (now, (rx, ry))

            is_double = event.value == 'DOUBLE_CLICK' or (
                prev_pos is not None
                and now - prev_t <= self._dbl_time
                and math.hypot(rx - prev_pos[0],
                               ry - prev_pos[1]) <= DBL_CLICK_DIST_PX)
            if is_double:
                self._last_click = (0.0, None)
                if len(self._points) >= 3:
                    # The pair's first click already placed the final vertex
                    return self._close_polygon(context)
                return {'RUNNING_MODAL'}

            if len(self._points) >= 3:
                fx, fy = self._px_to_region(*self._points[0])
                if math.hypot(rx - fx, ry - fy) <= CLOSE_THRESHOLD_PX:
                    return self._close_polygon(context)
            self._points.append(pt)
            return {'RUNNING_MODAL'}

        if event.type in {'RET', 'NUMPAD_ENTER'} and event.value == 'PRESS':
            if len(self._points) >= 3:
                return self._close_polygon(context)
            self.report({'WARNING'}, "Need at least 3 lasso points.")
            return {'RUNNING_MODAL'}

        if event.type == 'RIGHTMOUSE' and event.value == 'PRESS':
            if self._points:
                self._points.pop()   # undo last point
                return {'RUNNING_MODAL'}
            return self._cancel_op(context)

        if event.type == 'ESC' and event.value == 'PRESS':
            return self._cancel_op(context)

        return {'RUNNING_MODAL'}

    # ── Close polygon — build the floating selection (no pixel writes) ───────

    def _close_polygon(self, context):
        pts = np.asarray(self._points, dtype=np.float32)
        bx0 = max(0, int(math.floor(float(pts[:, 0].min()))))
        by0 = max(0, int(math.floor(float(pts[:, 1].min()))))
        bx1 = min(self._w, int(math.ceil(float(pts[:, 0].max()))) + 1)
        by1 = min(self._h, int(math.ceil(float(pts[:, 1].max()))) + 1)
        if bx1 - bx0 < 1 or by1 - by0 < 1:
            self.report({'WARNING'}, "Lasso is outside the image — start again.")
            self._points = []
            return {'RUNNING_MODAL'}

        mask = _rasterize_polygon(self._points, bx0, by0, bx1 - bx0, by1 - by0)
        if not mask.any():
            self.report({'WARNING'}, "Lasso selected no pixels — start again.")
            self._points = []
            return {'RUNNING_MODAL'}

        src_buf = _read_pixels(self._image)

        patch = src_buf[by0:by1, bx0:bx1].copy()
        patch[..., 3] = np.where(mask, patch[..., 3], 0.0)

        hole = src_buf   # full-image copy already; safe to modify in place
        hole[by0:by1, bx0:bx1, 3] = np.where(mask, 0.0,
                                             hole[by0:by1, bx0:bx1, 3])

        try:
            self._float_tex = _make_texture(patch)
            self._hole_tex  = _make_texture(hole)
        except Exception as e:
            self.report({'ERROR'}, f"GPU texture upload failed: {e}")
            return self._cancel_op(context)

        self._bx0, self._by0 = bx0, by0
        self._pw,  self._ph  = bx1 - bx0, by1 - by0
        self._mask  = mask
        self._patch = patch
        # Selection center (mask centroid) — pivot for R/S, tracked through the affine
        ys, xs = np.nonzero(mask)
        self._sel_center = (bx0 + float(xs.mean()) + 0.5,
                            by0 + float(ys.mean()) + 0.5)
        self._state = 'FLOAT_IDLE'
        return {'RUNNING_MODAL'}

    # ── FLOAT_IDLE state ─────────────────────────────────────────────────────

    def _modal_idle(self, context, event):
        if event.value != 'PRESS':
            return {'RUNNING_MODAL'}
        et = event.type

        if et == 'D' and event.shift:
            self._stamp_duplicate(context, event)
        elif et == 'G':
            self._enter_submode('GRAB', event)
        elif et == 'R':
            self._enter_submode('ROTATE', event)
        elif et == 'S':
            self._enter_submode('SCALE', event)
        elif et == 'J' and event.ctrl:
            self._set_dest_upper('COPY')
        elif et == 'X' and event.ctrl:
            self._set_dest_upper('CUT')
        elif et == 'X':
            return self._delete_selection(context)
        elif et in {'RET', 'NUMPAD_ENTER'}:
            return self._confirm(context)
        elif et == 'ESC':
            return self._cancel_op(context)
        return {'RUNNING_MODAL'}

    def _set_dest_upper(self, source_mode: str) -> None:
        upper = self._upper_slot()
        if upper is None:
            self.report({'WARNING'}, "No layer above.")
            return
        cel_store.get_or_create_cel_image(upper, self._w, self._h)
        self._dest_layer  = 'UPPER'
        self._source_mode = source_mode

    def _stamp_duplicate(self, context, event) -> None:
        """Shift+D — commit the floating piece exactly where it is (same bake
        as Enter, hole included on the first CUT), then keep the same
        selection floating as a COPY and start a grab so the new duplicate
        follows the mouse. Repeatable; G/R/S, Ctrl+J/Ctrl+X and Enter/Esc all
        keep working on the new copy. Stamped copies stay if the operator is
        later cancelled — like Photoshop, Esc only drops the floating piece."""
        if not self._bake_current(context):
            return
        # Original committed — the float is a pure copy from here on: no hole
        # on later bakes, and the preview shows the real (stamped) image again.
        self._source_mode = 'COPY'
        vse_helpers.tag_all_image_editors_redraw()
        self._enter_submode('GRAB', event)

    def _enter_submode(self, mode: str, event) -> None:
        self._snap         = (self._angle, self._scale, self._tx, self._ty)
        self._sub_start_px = self._mouse_px(event)
        if mode in {'ROTATE', 'SCALE'}:
            # Pivot = selection center in its CURRENT (transformed) position
            self._pivot_px = self._affine_apply_points([self._sel_center])[0]
            dx = self._sub_start_px[0] - self._pivot_px[0]
            dy = self._sub_start_px[1] - self._pivot_px[1]
            self._sub_start_angle = math.atan2(dy, dx)
            self._sub_start_dist  = max(math.hypot(dx, dy), 1e-3)
        self._state = mode

    # ── G/R/S sub-modes ──────────────────────────────────────────────────────

    def _modal_submode(self, context, event):
        if event.type == 'MOUSEMOVE':
            cur              = self._mouse_px(event)
            a0, s0, tx0, ty0 = self._snap
            cx, cy           = self._pivot_px

            if self._state == 'GRAB':
                self._tx = tx0 + (cur[0] - self._sub_start_px[0])
                self._ty = ty0 + (cur[1] - self._sub_start_px[1])

            elif self._state == 'ROTATE':
                ang = math.atan2(cur[1] - cy, cur[0] - cx)
                da  = ang - self._sub_start_angle
                ca, sa      = math.cos(da), math.sin(da)
                vx, vy      = tx0 - cx, ty0 - cy
                self._angle = a0 + da
                self._tx    = ca * vx - sa * vy + cx
                self._ty    = sa * vx + ca * vy + cy

            elif self._state == 'SCALE':
                d  = math.hypot(cur[0] - cx, cur[1] - cy)
                ds = max(d / self._sub_start_dist, 1e-4)
                self._scale = s0 * ds
                self._tx    = ds * (tx0 - cx) + cx
                self._ty    = ds * (ty0 - cy) + cy
            return {'RUNNING_MODAL'}

        if event.value == 'PRESS':
            if event.type in {'LEFTMOUSE', 'RET', 'NUMPAD_ENTER'}:
                self._state = 'FLOAT_IDLE'        # accept sub-move
                return {'RUNNING_MODAL'}
            if event.type in {'RIGHTMOUSE', 'ESC'}:
                (self._angle, self._scale,
                 self._tx, self._ty) = self._snap  # revert sub-move only
                self._state = 'FLOAT_IDLE'
                return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # ── Commit paths (the only image.pixels writes) ──────────────────────────

    def _apply_hole(self, buf) -> None:
        region = buf[self._by0:self._by0 + self._ph,
                     self._bx0:self._bx0 + self._pw, 3]
        region[self._mask] = 0.0

    def _delete_selection(self, context):
        """X — erase the selected region on the active cel and finish."""
        buf = _read_pixels(self._image)
        self._apply_hole(buf)
        _write_pixels(self._image, buf)
        self._cleanup(context)
        self.report({'INFO'}, f"[{self._slot}] Lasso selection deleted.")
        return {'FINISHED'}

    def _bake_current(self, context) -> bool:
        """One vectorized bake of the current floating state: CUT hole on the
        active cel, then composite the transformed piece into the dest image.
        Shared by Enter (_confirm) and Shift+D (_stamp_duplicate)."""
        if self._dest_layer == 'UPPER':
            dest_slot = self._upper_slot()
            if dest_slot is None:
                self.report({'WARNING'}, "No layer above.")
                return False
            dest_img = cel_store.get_or_create_cel_image(dest_slot,
                                                          self._w, self._h)
        else:
            dest_img = self._image

        act_buf = _read_pixels(self._image)
        if dest_img == self._image:
            dest_buf = act_buf
        else:
            dest_buf = _read_pixels(dest_img)

        if self._source_mode == 'CUT':
            self._apply_hole(act_buf)

        self._composite_float(dest_buf)

        if self._source_mode == 'CUT' or dest_img == self._image:
            _write_pixels(self._image, act_buf)
        if dest_img != self._image:
            _write_pixels(dest_img, dest_buf)
        return True

    def _confirm(self, context):
        """Enter — bake hole (CUT) + composite the transformed floating piece."""
        if not self._bake_current(context):
            return {'RUNNING_MODAL'}
        slot_msg = self._slot if self._dest_layer == 'ACTIVE' else \
            f"{self._slot} -> {self._upper_slot()}"
        self._cleanup(context)
        self.report({'INFO'}, f"[{slot_msg}] Lasso transform applied.")
        return {'FINISHED'}

    def _composite_float(self, dest_buf) -> None:
        """Sample the floating patch through the inverse affine (bilinear,
        premultiplied) and alpha-over it into dest_buf — fully vectorized."""
        dh, dw = dest_buf.shape[:2]

        corners = np.asarray(self._transformed_bbox_corners(), dtype=np.float64)
        dx0 = max(0,  int(math.floor(corners[:, 0].min())) - 1)
        dy0 = max(0,  int(math.floor(corners[:, 1].min())) - 1)
        dx1 = min(dw, int(math.ceil(corners[:, 0].max())) + 1)
        dy1 = min(dh, int(math.ceil(corners[:, 1].max())) + 1)
        if dx1 <= dx0 or dy1 <= dy0:
            return

        # Inverse affine: p = R(-a) * (q - t) / s   at dest pixel centers
        yy, xx = np.mgrid[dy0:dy1, dx0:dx1]
        qx = xx.astype(np.float32) + 0.5 - self._tx
        qy = yy.astype(np.float32) + 0.5 - self._ty
        ca, sa = math.cos(self._angle), math.sin(self._angle)
        inv_s  = 1.0 / max(self._scale, 1e-6)
        u = ( ca * qx + sa * qy) * inv_s - self._bx0 - 0.5
        v = (-sa * qx + ca * qy) * inv_s - self._by0 - 0.5

        patch_pre = self._patch.copy()
        patch_pre[..., :3] *= patch_pre[..., 3:4]
        pw, ph = self._pw, self._ph

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


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [DOMEANIMATIC_OT_lasso_transform]

_KEYMAPS = []   # (keymap, keymap_item) pairs for clean unregister


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)
    kc = bpy.context.window_manager.keyconfigs.addon
    if kc:
        km  = kc.keymaps.new(name='Image', space_type='IMAGE_EDITOR')
        kmi = km.keymap_items.new(DOMEANIMATIC_OT_lasso_transform.bl_idname,
                                  'L', 'PRESS')
        _KEYMAPS.append((km, kmi))


def unregister():
    global _DRAW_HANDLE, _ACTIVE_OP
    for km, kmi in _KEYMAPS:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _KEYMAPS.clear()
    if _DRAW_HANDLE is not None:
        try:
            bpy.types.SpaceImageEditor.draw_handler_remove(_DRAW_HANDLE, 'WINDOW')
        except Exception:
            pass
        _DRAW_HANDLE = None
    _ACTIVE_OP = None
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

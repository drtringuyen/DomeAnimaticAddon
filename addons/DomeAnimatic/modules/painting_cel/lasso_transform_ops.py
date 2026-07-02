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

This module holds only the operator (state machine + modal dispatch + commit
paths). Two siblings carry the rest:
  * lasso_draw.py   — all GPU preview drawing + the draw-handler lifecycle.
  * lasso_raster.py — pure numpy pixel helpers + the affine composite bake.
"""

import math
import time
import bpy

try:
    import gpu
except Exception:
    gpu = None

try:
    import numpy as np
except ImportError:
    np = None

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp
from . import lasso_draw, lasso_raster


CLOSE_THRESHOLD_PX = 12.0   # region pixels — click this close to point 0 closes
DBL_CLICK_DIST_PX  = 6.0    # region pixels — manual double-click fallback


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
        if lasso_draw.get_active_op() is not None:
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

        lasso_draw.set_active_op(self)
        lasso_draw.ensure_handler()

        context.window.cursor_modal_set('CROSSHAIR')
        context.window_manager.modal_handler_add(self)
        self._area.tag_redraw()
        return {'RUNNING_MODAL'}

    def cancel(self, context):
        self._cleanup(context)

    def _cleanup(self, context) -> None:
        lasso_draw.remove_handler()
        lasso_draw.clear_active_op()
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

        mask = lasso_raster.rasterize_polygon(self._points, bx0, by0,
                                              bx1 - bx0, by1 - by0)
        if not mask.any():
            self.report({'WARNING'}, "Lasso selected no pixels — start again.")
            self._points = []
            return {'RUNNING_MODAL'}

        src_buf = lasso_raster.read_pixels(self._image)

        patch = src_buf[by0:by1, bx0:bx1].copy()
        patch[..., 3] = np.where(mask, patch[..., 3], 0.0)

        hole = src_buf   # full-image copy already; safe to modify in place
        hole[by0:by1, bx0:bx1, 3] = np.where(mask, 0.0,
                                             hole[by0:by1, bx0:bx1, 3])

        try:
            self._float_tex = lasso_raster.make_texture(patch)
            self._hole_tex  = lasso_raster.make_texture(hole)
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
        buf = lasso_raster.read_pixels(self._image)
        self._apply_hole(buf)
        lasso_raster.write_pixels(self._image, buf)
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

        act_buf = lasso_raster.read_pixels(self._image)
        if dest_img == self._image:
            dest_buf = act_buf
        else:
            dest_buf = lasso_raster.read_pixels(dest_img)

        if self._source_mode == 'CUT':
            self._apply_hole(act_buf)

        self._composite_float(dest_buf)

        if self._source_mode == 'CUT' or dest_img == self._image:
            lasso_raster.write_pixels(self._image, act_buf)
        if dest_img != self._image:
            lasso_raster.write_pixels(dest_img, dest_buf)
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
        """Alpha-over the transformed floating patch into dest_buf (delegates
        to the pure vectorized bake in lasso_raster)."""
        lasso_raster.composite_float(
            dest_buf, self._patch, self._transformed_bbox_corners(),
            self._tx, self._ty, self._angle, self._scale,
            self._bx0, self._by0)


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
    for km, kmi in _KEYMAPS:
        try:
            km.keymap_items.remove(kmi)
        except Exception:
            pass
    _KEYMAPS.clear()
    lasso_draw.remove_handler()
    lasso_draw.clear_active_op()
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

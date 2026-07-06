"""
lasso_transform_ops.py — Photoshop-style lasso transform for the active cel layer.

Modal operator for the Image Editor: draw a polygon lasso on the active cel,
then move / rotate / scale the selected pixels as a floating GPU-textured quad
(live, no image.pixels writes), committing in one vectorized numpy pass on
Enter (or a click outside the selection).

Photoshop / Toon Boom behavior: while the selection is floating, events the
operator does not use are PASSED THROUGH, so the user can scrub the timeline,
click another cel layer, or select a VSE strip — the float simply retargets.
On confirm the piece is baked into the CURRENT active cel at the CURRENT
frame; if that slot has no VSE strip at the playhead, one is created
automatically (cel_layer_ops.ensure_strip_for_slot). A pending CUT is
committed back to the source file the moment the source strip is scrubbed
away (moving on finalizes the cut, like Photoshop).

Keys while floating (mouse over the invoking Image Editor):
  drag inside selection      move (confirm on release)
  click outside selection    commit + finish
  G / R / S                  move / rotate / scale
  Shift+D                    stamp copy and keep moving
  Ctrl+J / Ctrl+X            duplicate / cut to the layer above
  Ctrl+C                     copy selection to the lasso clipboard
  Ctrl+V                     commit current float, paste clipboard as new float
  L                          commit, immediately start a new lasso
  X                          delete selected pixels
  Enter / Esc                commit / drop the floating piece

Ctrl+V also works with no operator running (Image Editor keymap invokes this
operator with paste=True), so copy → move playhead / change layer → paste
works exactly like Photoshop.

States: DRAW -> FLOAT_IDLE <-> GRAB / ROTATE / SCALE.
The floating piece carries a single 2D affine  p' = scale * R(angle) * p + t.

This module holds only the operator (state machine + modal dispatch + commit
paths). Two siblings carry the rest:
  * lasso_draw.py   — all GPU preview drawing + the draw-handler lifecycle.
  * lasso_raster.py — pure numpy pixel helpers + the affine composite bake.
"""

import math
import os
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
from . import lasso_draw, lasso_raster, image_io, cel_layer_ops


CLOSE_THRESHOLD_PX = 12.0   # region pixels — click this close to point 0 closes
DBL_CLICK_DIST_PX  = 6.0    # region pixels — manual double-click fallback


# ── Lasso clipboard (survives across operator runs, Ctrl+C / Ctrl+V) ──────────

_CLIPBOARD = None   # dict: patch/mask/points/bbox/affine/sel_center


# ── Operator ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_lasso_transform(bpy.types.Operator):
    """Lasso-select pixels on the active cel and move/rotate/scale them.
    While floating you can scrub the timeline or switch layers — the piece
    is applied to the active cel/frame on confirm (strip auto-created)"""
    bl_idname  = "domeanimatic.lasso_transform"
    bl_label   = "Lasso Transform"
    bl_options = {'REGISTER', 'UNDO'}

    paste: bpy.props.BoolProperty(
        name="Paste",
        description="Start directly from the lasso clipboard (Ctrl+V)",
        default=False,
        options={'SKIP_SAVE', 'HIDDEN'},
    )

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
        if self.paste and _CLIPBOARD is None:
            self.report({'WARNING'}, "Lasso clipboard is empty — Ctrl+C a selection first.")
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

        # Source tracking — where the pixels were lifted from. The CUT hole
        # stays "virtual" (GPU-only, Esc restores) while the source datablock
        # still shows the source strip; once the user scrubs away, the cut is
        # committed to the source file and the float becomes a pure COPY.
        self._source_mode = 'CUT'
        self._hole_live   = False
        self._src_slot    = slot
        self._src_frame   = image_io.dome_frame()
        self._src_path    = ""
        self._cur_slot    = slot
        self._cur_frame   = self._src_frame

        # Sub-mode (G/R/S) working data
        self._snap            = None
        self._sub_start_px    = (0.0, 0.0)
        self._sub_start_angle = 0.0
        self._sub_start_dist  = 1.0
        self._pivot_px        = (0.0, 0.0)
        self._sub_drag        = False   # GRAB entered by dragging (confirm on release)

        lasso_draw.set_active_op(self)
        lasso_draw.ensure_handler()

        if self.paste:
            if not self._adopt_clipboard():
                lasso_draw.remove_handler()
                lasso_draw.clear_active_op()
                self.report({'ERROR'}, "Could not build paste preview.")
                return {'CANCELLED'}
        else:
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

    def _mouse_in_region(self, event) -> bool:
        rx = event.mouse_x - self._region.x
        ry = event.mouse_y - self._region.y
        return 0 <= rx < self._region.width and 0 <= ry < self._region.height

    def _point_in_selection(self, px, py) -> bool:
        """Even-odd test against the TRANSFORMED lasso polygon."""
        if not self._points:
            return False
        pts    = self._affine_apply_points(self._points)
        inside = False
        n      = len(pts)
        for i in range(n):
            x1, y1 = pts[i]
            x2, y2 = pts[(i + 1) % n]
            if (y1 > py) != (y2 > py):
                x_at = (x2 - x1) * (py - y1) / (y2 - y1) + x1
                if px < x_at:
                    inside = not inside
        return inside

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

    # ── Source-context tracking ──────────────────────────────────────────────

    def _resolve_src_strip_path(self) -> str:
        """Normalized abs path of the source channel's strip file at the
        current playhead, or ''."""
        dome = bpy.data.scenes.get("Dome Animatic")
        if dome is None:
            return ""
        frame   = image_io.dome_frame()
        channel = cel_store.BY_SLOT[self._src_slot].vse_channel
        strip   = vse_helpers.vse_get_strip_on_channel(dome, channel, frame,
                                                       include_muted=True)
        if strip is None:
            return ""
        path = vse_helpers.resolve_strip_image_path(strip, frame)
        return os.path.normpath(path) if path else ""

    def _src_is_intact(self) -> bool:
        """True while the source slot's datablock still shows the pixels the
        selection was lifted from (same strip file, not blanked/reloaded)."""
        img = cel_store.get_cel_image(self._src_slot)
        if img is None or img.size[0] != self._w or img.size[1] != self._h:
            return False
        if self._src_path:
            cur = (os.path.normpath(bpy.path.abspath(img.filepath_raw))
                   if img.filepath_raw else "")
            return (cur == self._src_path
                    and self._resolve_src_strip_path() == self._src_path)
        # No file backing at lift time — intact only while the frame is unchanged
        return image_io.dome_frame() == self._src_frame

    def _sync_context(self) -> None:
        """Detect frame/layer changes (events pass through, so the user can
        scrub or switch layers mid-float). Once the source strip is scrubbed
        away, commit the pending CUT to the source file."""
        slot  = gp().active_cel
        frame = image_io.dome_frame()
        if slot == self._cur_slot and frame == self._cur_frame:
            return
        self._cur_slot, self._cur_frame = slot, frame
        if self._source_mode == 'CUT' and self._hole_live and not self._src_is_intact():
            self._commit_cut_to_file()
            self._hole_live   = False
            self._source_mode = 'COPY'
        vse_helpers.tag_all_image_editors_redraw()

    # ── Modal dispatch ───────────────────────────────────────────────────────

    def modal(self, context, event):
        if event.type in {'MIDDLEMOUSE', 'WHEELUPMOUSE', 'WHEELDOWNMOUSE'}:
            return {'PASS_THROUGH'}   # keep pan/zoom alive

        try:
            self._area.tag_redraw()
        except Exception:
            return self._cancel_op(context)   # area was closed

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
            if not self._mouse_in_region(event):
                return {'PASS_THROUGH'}   # panel buttons / other editors stay live
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
        # Re-anchor to the CURRENT active cel — the user may have switched
        # layers via the panel while drawing (clicks outside pass through).
        slot = gp(context).active_cel
        img  = cel_store.get_cel_image(slot)
        if img is not None and img.size[0] and getattr(img, 'channels', 4) == 4:
            self._slot, self._image = slot, img
            self._w, self._h        = img.size

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

        # Anchor the source context: the CUT hole belongs to this slot at
        # this strip file until committed or invalidated.
        self._src_slot    = self._slot
        self._src_frame   = image_io.dome_frame()
        self._src_path    = self._resolve_src_strip_path()
        self._cur_slot    = self._src_slot
        self._cur_frame   = self._src_frame
        self._source_mode = 'CUT'
        self._hole_live   = True

        try:
            context.window.cursor_modal_restore()   # normal cursor while floating
        except Exception:
            pass
        self._state = 'FLOAT_IDLE'
        return {'RUNNING_MODAL'}

    # ── FLOAT_IDLE state — events not used here PASS THROUGH ─────────────────

    def _modal_idle(self, context, event):
        self._sync_context()

        if event.value != 'PRESS':
            return {'PASS_THROUGH'}

        et        = event.type
        in_region = self._mouse_in_region(event)

        if et == 'LEFTMOUSE':
            if not in_region:
                return {'PASS_THROUGH'}
            px, py = self._mouse_px(event)
            if self._point_in_selection(px, py):
                self._enter_submode('GRAB', event, drag=True)   # drag to move
                return {'RUNNING_MODAL'}
            return self._confirm(context)   # click outside = commit (Photoshop)

        if not in_region:
            # Let keys reach the editor under the mouse — this is what keeps
            # the timeline / VSE / layer panel usable while the float lives.
            return {'PASS_THROUGH'}

        if et == 'D' and event.shift:
            self._stamp_duplicate(context, event)
        elif et == 'G':
            self._enter_submode('GRAB', event)
        elif et == 'R':
            self._enter_submode('ROTATE', event)
        elif et == 'S':
            self._enter_submode('SCALE', event)
        elif et == 'J' and event.ctrl:
            self._dup_to_upper('COPY')
        elif et == 'X' and event.ctrl:
            self._dup_to_upper('CUT')
        elif et == 'C' and event.ctrl:
            self._copy_to_clipboard()
        elif et == 'V' and event.ctrl:
            return self._paste_over(context)
        elif et == 'X':
            return self._delete_selection(context)
        elif et == 'L':
            return self._restart_draw(context)
        elif et in {'RET', 'NUMPAD_ENTER'}:
            return self._confirm(context)
        elif et == 'ESC':
            return self._cancel_op(context)
        else:
            return {'PASS_THROUGH'}
        return {'RUNNING_MODAL'}

    def _dup_to_upper(self, source_mode: str) -> None:
        """Ctrl+J / Ctrl+X — retarget the float one layer up. Dest is always
        the active cel, so this simply switches the active layer."""
        upper = cel_store.upper_slot(gp().active_cel)
        if upper is None:
            self.report({'WARNING'}, "No layer above.")
            return
        cel_store.get_or_create_cel_image(upper, self._w, self._h)
        if source_mode == 'CUT' and not self._hole_live:
            source_mode = 'COPY'   # original already stamped/committed
        self._source_mode = source_mode
        gp().active_cel = upper   # fires _on_active_cel_changed
        self._cur_slot  = upper

    def _copy_to_clipboard(self) -> None:
        """Ctrl+C — snapshot the floating selection; the float stays live."""
        global _CLIPBOARD
        _CLIPBOARD = {
            'patch':      self._patch.copy(),
            'mask':       self._mask.copy(),
            'points':     list(self._points),
            'bx0':        self._bx0, 'by0': self._by0,
            'pw':         self._pw,  'ph':  self._ph,
            'affine':     (self._angle, self._scale, self._tx, self._ty),
            'sel_center': self._sel_center,
        }
        self.report({'INFO'}, "Lasso selection copied — Ctrl+V pastes it "
                              "(also after moving the playhead / changing layer).")

    def _adopt_clipboard(self) -> bool:
        """Load the clipboard as the current floating selection (paste-in-place)."""
        clip = _CLIPBOARD
        try:
            float_tex = lasso_raster.make_texture(clip['patch'])
        except Exception:
            return False
        self._patch      = clip['patch'].copy()
        self._mask       = clip['mask'].copy()
        self._points     = list(clip['points'])
        self._bx0, self._by0 = clip['bx0'], clip['by0']
        self._pw,  self._ph  = clip['pw'],  clip['ph']
        (self._angle, self._scale,
         self._tx, self._ty) = clip['affine']
        self._sel_center = clip['sel_center']
        self._float_tex  = float_tex
        self._hole_tex   = None
        self._source_mode = 'COPY'
        self._hole_live   = False
        self._src_slot    = gp().active_cel
        self._src_frame   = image_io.dome_frame()
        self._src_path    = ""
        self._cur_slot    = self._src_slot
        self._cur_frame   = self._src_frame
        self._state       = 'FLOAT_IDLE'
        return True

    def _paste_over(self, context):
        """Ctrl+V while floating — commit the current piece, then float the
        clipboard content (Photoshop: paste commits the previous float)."""
        if _CLIPBOARD is None:
            self.report({'WARNING'}, "Lasso clipboard is empty.")
            return {'RUNNING_MODAL'}
        if not self._bake_current(context):
            return {'RUNNING_MODAL'}
        if not self._adopt_clipboard():
            self.report({'ERROR'}, "Could not build paste preview.")
            return self._cancel_op(context)
        vse_helpers.tag_all_image_editors_redraw()
        return {'RUNNING_MODAL'}

    def _restart_draw(self, context):
        """L while floating — commit the current piece and immediately start a
        fresh lasso on the current active cel (Photoshop: a new selection
        commits the floating one)."""
        if not self._bake_current(context):
            return {'RUNNING_MODAL'}
        slot = gp(context).active_cel
        img  = cel_store.get_cel_image(slot)
        if img is None or img.size[0] == 0:
            self._cleanup(context)
            return {'FINISHED'}
        self._slot, self._image = slot, img
        self._w, self._h        = img.size
        self._points    = []
        self._cursor_px = None
        self._mask = self._patch = None
        self._float_tex = self._hole_tex = None
        self._angle, self._scale = 0.0, 1.0
        self._tx, self._ty       = 0.0, 0.0
        self._source_mode = 'CUT'
        self._hole_live   = False
        try:
            context.window.cursor_modal_set('CROSSHAIR')
        except Exception:
            pass
        self._state = 'DRAW'
        vse_helpers.tag_all_image_editors_redraw()
        return {'RUNNING_MODAL'}

    def _stamp_duplicate(self, context, event) -> None:
        """Shift+D — commit the floating piece exactly where it is (same bake
        as Enter, hole included on the first CUT), then keep the same
        selection floating as a COPY and start a grab so the new duplicate
        follows the mouse. Repeatable; stamped copies stay if the operator is
        later cancelled — like Photoshop, Esc only drops the floating piece."""
        if not self._bake_current(context):
            return
        # Original committed — the float is a pure copy from here on: no hole
        # on later bakes, and the preview shows the real (stamped) image again.
        self._source_mode = 'COPY'
        self._hole_live   = False
        vse_helpers.tag_all_image_editors_redraw()
        self._enter_submode('GRAB', event)

    def _enter_submode(self, mode: str, event, drag: bool = False) -> None:
        self._snap         = (self._angle, self._scale, self._tx, self._ty)
        self._sub_start_px = self._mouse_px(event)
        self._sub_drag     = drag
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

        if event.type == 'LEFTMOUSE':
            if event.value == 'RELEASE' and self._sub_drag:
                self._sub_drag = False
                self._state    = 'FLOAT_IDLE'   # drag-move dropped
                return {'RUNNING_MODAL'}
            if event.value == 'PRESS' and not self._sub_drag:
                self._state = 'FLOAT_IDLE'      # accept key-started sub-move
                return {'RUNNING_MODAL'}
            return {'RUNNING_MODAL'}

        if event.value == 'PRESS':
            if event.type in {'RET', 'NUMPAD_ENTER'}:
                self._sub_drag = False
                self._state = 'FLOAT_IDLE'        # accept sub-move
                return {'RUNNING_MODAL'}
            if event.type in {'RIGHTMOUSE', 'ESC'}:
                (self._angle, self._scale,
                 self._tx, self._ty) = self._snap  # revert sub-move only
                self._sub_drag = False
                self._state = 'FLOAT_IDLE'
                return {'RUNNING_MODAL'}
        return {'RUNNING_MODAL'}

    # ── Commit paths (the only image.pixels writes) ──────────────────────────

    def _apply_hole(self, buf) -> None:
        region = buf[self._by0:self._by0 + self._ph,
                     self._bx0:self._bx0 + self._pw, 3]
        region[self._mask] = 0.0

    def _commit_cut_to_file(self) -> None:
        """Burn the CUT hole into the source PNG on disk — used once the
        source datablock has been reloaded with a different strip's pixels."""
        path = self._src_path
        if not path or not os.path.exists(path):
            return
        try:
            tmp = bpy.data.images.load(path, check_existing=False)
        except Exception:
            return
        try:
            if tmp.size[0] == self._w and tmp.size[1] == self._h:
                buf = lasso_raster.read_pixels(tmp)
                self._apply_hole(buf)
                lasso_raster.write_pixels(tmp, buf)
                tmp.filepath_raw = path
                tmp.file_format  = 'PNG'
                tmp.save()
                vse_helpers.log(f"[LassoTransform] Cut committed to {path}")
        finally:
            bpy.data.images.remove(tmp)

    def _commit_cut_now(self) -> None:
        """Make the pending CUT permanent on the source (datablock if it still
        shows the source strip, otherwise the file on disk)."""
        if self._source_mode != 'CUT' or not self._hole_live:
            return
        if self._src_is_intact():
            img = cel_store.get_cel_image(self._src_slot)
            buf = lasso_raster.read_pixels(img)
            self._apply_hole(buf)
            lasso_raster.write_pixels(img, buf)
        else:
            self._commit_cut_to_file()
        self._hole_live   = False
        self._source_mode = 'COPY'

    def _delete_selection(self, context):
        """X — erase the selected pixels from the source and finish. If the
        original was already stamped/committed, just drop the float."""
        if self._source_mode == 'CUT' and self._hole_live and self._src_is_intact():
            img = cel_store.get_cel_image(self._src_slot)
            buf = lasso_raster.read_pixels(img)
            self._apply_hole(buf)
            lasso_raster.write_pixels(img, buf)
            self.report({'INFO'}, f"[{self._src_slot}] Lasso selection deleted.")
        else:
            self.report({'INFO'}, "Floating selection dropped.")
        self._cleanup(context)
        return {'FINISHED'}

    def _bake_current(self, context) -> bool:
        """One vectorized bake of the current floating state into the CURRENT
        active cel at the CURRENT frame. Creates the VSE strip + PNG if the
        target slot has none at the playhead. A pending CUT is applied to the
        source first (combined into one pass when source == dest).
        Shared by Enter/click-outside, Shift+D, Ctrl+V and L-restart."""
        dest_slot = gp(context).active_cel

        # Resolve the source cut BEFORE touching the dest strip — auto-creating
        # a strip reloads the (possibly shared) slot datablock.
        combined = (self._source_mode == 'CUT' and self._hole_live
                    and dest_slot == self._src_slot and self._src_is_intact())
        if self._source_mode == 'CUT' and self._hole_live and not combined:
            self._commit_cut_now()

        strip, created = cel_layer_ops.ensure_strip_for_slot(dest_slot)
        dest_img = cel_store.get_or_create_cel_image(dest_slot, self._w, self._h)
        if dest_img.size[0] == 0 or dest_img.size[1] == 0:
            self.report({'ERROR'}, f"[{dest_slot}] target image has no pixels.")
            return False

        buf = lasso_raster.read_pixels(dest_img)
        if combined:
            self._apply_hole(buf)
            self._hole_live   = False
            self._source_mode = 'COPY'
        self._composite_float(buf)
        lasso_raster.write_pixels(dest_img, buf)

        # Freshly created strips point at a blank PNG — persist immediately so
        # scrubbing away (without auto-save) can't lose the pasted piece.
        if created and dest_img.filepath_raw:
            try:
                dest_img.save()
            except Exception:
                pass
        return True

    def _confirm(self, context):
        """Enter / click outside — bake hole (CUT) + composite the transformed
        floating piece into the active cel at the current frame."""
        dest_slot  = gp(context).active_cel
        dest_frame = image_io.dome_frame()
        if not self._bake_current(context):
            return {'RUNNING_MODAL'}
        if dest_slot == self._src_slot and dest_frame == self._src_frame:
            slot_msg = dest_slot
        else:
            slot_msg = f"{self._src_slot} -> {dest_slot} @ f{dest_frame}"
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
        # Ctrl+V — paste the lasso clipboard as a new floating selection
        kmi_v = km.keymap_items.new(DOMEANIMATIC_OT_lasso_transform.bl_idname,
                                    'V', 'PRESS', ctrl=True)
        kmi_v.properties.paste = True
        _KEYMAPS.append((km, kmi_v))


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

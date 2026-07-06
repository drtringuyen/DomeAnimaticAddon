"""
cel_layer_ops.py — DOMEANIMATIC_OT_cel_* operators + refresh_cel_folder.

All VSE strip / PNG operations for the three-slot transparent cel system.
Ported from transparent_cel.py and transparent_cel_managment.py.
"""

import bpy
import os

try:
    import numpy as np
except ImportError:
    np = None

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp, sp
from . import image_io


# ── Active-slot helper ────────────────────────────────────────────────────────

_CEL_ENUM_SLOTS = {'BG', 'CEL_A', 'CEL_B'}

def activate_slot(slot_id: str) -> None:
    """Set slot as active — triggers _on_active_cel_changed for Image Editor + canvas.
    CEL_Baked is not in the active_cel enum so it is silently skipped."""
    if slot_id in _CEL_ENUM_SLOTS:
        gp().active_cel = slot_id


def compute_slot_range(dome_scene, channel: int, frame: int) -> tuple[int, int]:
    """Frame range for a new strip on `channel` at `frame`.
    Existing strip at frame → its range; empty space → bounded by neighbours
    and the BG/track-1 strip."""
    existing = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
    if existing is not None:
        return existing.frame_final_start, existing.frame_final_end

    bg_strip = vse_helpers.vse_get_strip_on_channel(dome_scene, 2, frame,
                                                     include_muted=True)
    if bg_strip is None:
        bg_strip = vse_helpers.vse_get_strip_on_channel(dome_scene, 1, frame,
                                                         include_muted=True)
    left  = vse_helpers.vse_get_strip_left_of_frame(dome_scene, channel, frame)
    right = vse_helpers.vse_get_strip_right_of(dome_scene, channel, frame)

    if bg_strip is not None:
        bg_start, bg_end = bg_strip.frame_final_start, bg_strip.frame_final_end
    else:
        bg_start, bg_end = frame, frame + 100

    start = max(bg_start, left.frame_final_end  if left  else bg_start)
    end   = min(bg_end,   right.frame_final_start if right else bg_end)
    if end <= start:
        end = bg_end
    return start, end


def ensure_strip_for_slot(slot_id: str, adopt_datablock: bool = False):
    """Make sure a strip exists on this slot's channel at the playhead.

    Returns (strip, created). If no strip exists, a new PNG is written and a
    strip is inserted spanning the empty gap.

    adopt_datablock=False (lasso bake): the new PNG starts from BG/track-1
    pixels or blank and is LOADED into the slot datablock. If a strip exists
    but the datablock points at a different file (sync handler inactive), the
    strip's file is loaded so a bake hits the right pixels.

    adopt_datablock=True (painting on an empty frame): the new PNG is saved
    FROM the datablock's current pixels and the datablock is re-pointed at it
    WITHOUT a reload — in-progress brush strokes are kept and now belong to
    the new strip instead of leaking into the previous strip's file.
    """
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return None, False
    channel = cel_store.BY_SLOT[slot_id].vse_channel
    frame   = image_io.dome_frame()
    w, h    = image_io.get_reference_size()

    strip = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame,
                                                 include_muted=True)
    if strip is not None:
        path = vse_helpers.resolve_strip_image_path(strip, frame)
        img  = cel_store.get_cel_image(slot_id)
        if (not adopt_datablock
                and path and os.path.exists(path) and img is not None
                and os.path.normpath(bpy.path.abspath(img.filepath_raw or ""))
                    != os.path.normpath(path)):
            image_io.load_abs_into_slot(slot_id, path, w, h)
            try:
                from ..live_texture import vse_sync as _vse_sync
                _vse_sync._s.last_path[channel] = path
            except Exception:
                pass
        return strip, False

    start, end = compute_slot_range(dome_scene, channel, frame)
    folder   = image_io.ensure_cel_folder()
    filename = image_io.cel_filename(slot_id, frame)
    abs_path = os.path.join(folder, filename)

    img   = cel_store.get_cel_image(slot_id)
    adopt = adopt_datablock and img is not None and img.size[0] > 0

    track1_strip = vse_helpers.vse_get_strip_on_channel(dome_scene, 1, frame,
                                                         include_muted=True)
    if adopt:
        image_io.save_datablock_to_png(img, abs_path, w, h)
    elif slot_id == 'BG' and track1_strip is not None:
        image_io.copy_track1_to_png(track1_strip, frame, abs_path, w, h)
    else:
        image_io.create_blank_png(abs_path, w, h)

    strip = vse_helpers.vse_insert_image_strip(dome_scene, channel, abs_path,
                                               start, end)
    if adopt:
        # The PNG was just saved FROM the datablock, so loading it back is
        # lossless: the user's strokes stay, the image flips from the gap's
        # GENERATED blank to a FILE properly backed by the new strip, and
        # is_dirty resets (the strokes are on disk).
        image_io.load_abs_into_slot(slot_id, abs_path, w, h)
        try:
            setattr(gp(), f"{slot_id.lower()}_filepath", abs_path)
        except Exception:
            pass
    else:
        image_io.load_slot_from_vse(slot_id, w, h)
    try:
        from ..live_texture import vse_sync as _vse_sync
        _vse_sync._s.last_path[channel] = abs_path
    except Exception:
        pass
    if not adopt:
        _blank_other_empty_channels(dome_scene, channel, frame)
    vse_helpers.tag_all_image_editors_redraw()
    return strip, True


def _blank_other_empty_channels(dome_scene, inserted_channel: int, frame: int) -> None:
    """After inserting a strip, blank every cel channel that has no strip at this frame.

    Without this, channels with stale opaque pixels from a previous frame cover the
    newly inserted content in the GPU overlay and material compositing.
    """
    try:
        from ..live_texture import vse_sync as _vse_sync
        for ch, layer in cel_store.BY_CHANNEL.items():
            if ch == inserted_channel:
                continue
            strip = vse_helpers.vse_get_strip_on_channel(dome_scene, ch, frame, include_muted=True)
            if not strip:
                _vse_sync._blank_cel_datablock(layer.slot_id)
                _vse_sync._s.last_path[ch] = ""
    except Exception:
        pass


# ── Cel folder operator ───────────────────────────────────────────────────────

class DOMEANIMATIC_OT_refresh_cel_folder(bpy.types.Operator):
    """Normalize the cel folder path and create it on disk."""
    bl_idname = "domeanimatic.refresh_cel_folder"
    bl_label  = "Refresh Cel Folder Path"

    def execute(self, context):
        s   = sp(context.scene)
        raw = s.cel_folder
        try:
            abs_path = bpy.path.abspath(raw)
        except Exception:
            abs_path = raw
        os.makedirs(abs_path, exist_ok=True)
        if bpy.data.filepath:
            try:
                rel = bpy.path.relpath(abs_path)
                s.cel_folder = rel
                self.report({'INFO'}, f"Folder: {rel}")
                return {'FINISHED'}
            except ValueError:
                pass
        s.cel_folder = abs_path
        self.report({'INFO'}, f"Folder: {abs_path}")
        return {'FINISHED'}


# ── Visibility operators ──────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_set_active(bpy.types.Operator):
    """Set this slot as the active (paintable) cel and enter Texture Paint."""
    bl_idname = "domeanimatic.cel_set_active"
    bl_label  = "Set Active Cel"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        g = gp(context)   # needed for active_cel and visibility props
        s = sp(context.scene)

        if s.synch_mode == 'BAKED':
            return {'FINISHED'}

        if s.dome_object is None:
            bpy.ops.domeanimatic.dome_object_picker('INVOKE_DEFAULT')
            return {'FINISHED'}

        # Find first VIEW_3D area across all windows
        view3d_window = view3d_area = view3d_region = None
        for window in context.window_manager.windows:
            for area in window.screen.areas:
                if area.type == 'VIEW_3D':
                    for region in area.regions:
                        if region.type == 'WINDOW':
                            view3d_window = window
                            view3d_area   = area
                            view3d_region = region
                            break
                if view3d_area:
                    break
            if view3d_area:
                break

        # Reload/scale to real res BEFORE entering paint mode so the GPU texture
        # is already up-to-date when Texture Paint binds it. Doing this after
        # entering paint causes the first stroke to paint to a stale GPU buffer.
        # Only reload when a strip exists at the playhead — in a gap the
        # datablock's filepath still points at the LAST strip's file, and
        # reloading it would put the previous drawing back on an empty frame.
        rw, rh = image_io.get_reference_size()
        cel_img = cel_store.get_or_create_cel_image(self.slot)
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        channel    = cel_store.BY_SLOT[self.slot].vse_channel
        frame      = image_io.dome_frame()
        has_strip  = (dome_scene is not None and
                      vse_helpers.vse_get_strip_on_channel(
                          dome_scene, channel, frame,
                          include_muted=True) is not None)
        raw = cel_img.filepath_raw
        if has_strip and raw and os.path.exists(bpy.path.abspath(raw)):
            cel_img.reload()
        elif cel_img.size[0] != rw or cel_img.size[1] != rh:
            cel_img.scale(rw, rh)

        # Set active cel — triggers _on_active_cel_changed (Image Editor + canvas + active node)
        g.active_cel = self.slot

        if view3d_area and view3d_region:
            with context.temp_override(window=view3d_window, area=view3d_area, region=view3d_region):
                for obj in context.view_layer.objects:
                    obj.select_set(False)
                s.dome_object.select_set(True)
                context.view_layer.objects.active = s.dome_object
                bpy.ops.object.mode_set(mode='TEXTURE_PAINT')

        # Proactive invisible-layer warning
        slot_key = self.slot.lower()
        if not getattr(g, f"{slot_key}_visible", True):
            bpy.ops.domeanimatic.cel_invisible_warning('INVOKE_DEFAULT')

        return {'FINISHED'}


class DOMEANIMATIC_OT_dome_object_picker(bpy.types.Operator):
    """Auto-assign or pick the dome mesh for texture painting."""
    bl_idname  = "domeanimatic.dome_object_picker"
    bl_label   = "Pick Dome Object"
    bl_options = {'INTERNAL'}

    dome_object: bpy.props.PointerProperty(
        name="Dome Object",
        type=bpy.types.Object,
    )

    _candidates: list = []

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}

        mat        = sp(context.scene).target_material
        candidates = []
        for obj in dome_scene.objects:
            if obj.type != 'MESH':
                continue
            for ms in obj.material_slots:
                if ms.material == mat:
                    candidates.append(obj)
                    break

        DOMEANIMATIC_OT_dome_object_picker._candidates = candidates

        if len(candidates) == 0:
            self.report({'ERROR'},
                        "No mesh object with the Dome Animatic material found in Dome Animatic scene.")
            return {'CANCELLED'}

        if len(candidates) == 1:
            sp(context.scene).dome_object = candidates[0]
            return {'FINISHED'}

        return context.window_manager.invoke_props_dialog(self, width=300)

    def draw(self, context):
        self.layout.prop(self, "dome_object", text="Dome Object")

    def execute(self, context):
        if self.dome_object is None:
            self.report({'WARNING'}, "No object selected.")
            return {'CANCELLED'}
        sp(context.scene).dome_object = self.dome_object
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_show_baked(bpy.types.Operator):
    """Activate LiveDomePreview at real res, set as paint canvas, enter Texture Paint."""
    bl_idname = "domeanimatic.cel_show_baked"
    bl_label  = "Activate: LiveDomePreview"

    def execute(self, context):
        s        = sp(context.scene)
        live_img = cel_store.get_or_create_live_image()

        # Scale to real res (task 10)
        rw, rh = image_io.get_reference_size()
        raw    = live_img.filepath_raw
        if raw and os.path.exists(bpy.path.abspath(raw)):
            live_img.reload()
        elif live_img.size[0] != rw or live_img.size[1] != rh:
            live_img.scale(rw, rh)

        vse_helpers.set_image_editor_image(context, live_img)

        # Set canvas and enter Texture Paint on dome object
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene and s.dome_object:
            try:
                dome_scene.tool_settings.image_paint.canvas = live_img
            except Exception:
                pass
            view3d_window = view3d_area = view3d_region = None
            for window in context.window_manager.windows:
                for area in window.screen.areas:
                    if area.type == 'VIEW_3D':
                        for region in area.regions:
                            if region.type == 'WINDOW':
                                view3d_window = window
                                view3d_area   = area
                                view3d_region = region
                                break
                    if view3d_area:
                        break
                if view3d_area:
                    break
            if view3d_area and view3d_region:
                with context.temp_override(window=view3d_window,
                                           area=view3d_area,
                                           region=view3d_region):
                    for obj in context.view_layer.objects:
                        obj.select_set(False)
                    s.dome_object.select_set(True)
                    context.view_layer.objects.active = s.dome_object
                    bpy.ops.object.mode_set(mode='TEXTURE_PAINT')

        # Pause live sync write to LiveDomePreview while painting (task 14)
        try:
            from ..live_texture import vse_sync
            vse_sync._s.painting_baked = True
        except Exception:
            pass

        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_toggle_visible(bpy.types.Operator):
    """Toggle visibility of a cel slot."""
    bl_idname = "domeanimatic.cel_toggle_visible"
    bl_label  = "Toggle Cel Visibility"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        g        = gp(context)
        slot_key = self.slot.lower()
        current  = getattr(g, f"{slot_key}_visible", True)
        setattr(g, f"{slot_key}_visible", not current)
        vse_helpers.tag_all_image_editors_redraw()
        return {'FINISHED'}


# ── Insert Full ───────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_insert_full(bpy.types.Operator):
    """
    Insert FULL slot.
    Case A — strip at playhead: replace it (confirmation popup).
    Case B — empty space: derive range from neighbours + BG/track-1 bounds.
    BG slot always copies track-1 pixels.
    """
    bl_idname  = "domeanimatic.cel_insert_full"
    bl_label   = "Insert Full Slot"
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty()

    def _compute_range(self, dome_scene, channel: int, frame: int):
        return compute_slot_range(dome_scene, channel, frame)

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return self.execute(context)
        channel = cel_store.BY_SLOT[self.slot].vse_channel
        frame   = image_io.dome_frame()
        if vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame) is not None:
            self._existing_name = vse_helpers.vse_get_strip_on_channel(
                dome_scene, channel, frame).name
            return context.window_manager.invoke_props_dialog(self, width=380)
        return self.execute(context)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text=f"Strip '{getattr(self, '_existing_name', '?')}' already exists.",
                  icon='ERROR')
        col.separator()
        col.label(text="Replace it with a new Insert Full slot?")

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}

        channel = cel_store.BY_SLOT[self.slot].vse_channel
        frame   = image_io.dome_frame()
        w, h    = image_io.get_reference_size()

        track1_strip = vse_helpers.vse_get_strip_on_channel(dome_scene, 1, frame,
                                                             include_muted=True)
        start, end = self._compute_range(dome_scene, channel, frame)

        folder   = image_io.ensure_cel_folder()
        filename = image_io.cel_filename(self.slot, frame)
        abs_path = os.path.join(folder, filename)

        if self.slot == 'BG' and track1_strip is not None:
            image_io.copy_track1_to_png(track1_strip, frame, abs_path, w, h)
        else:
            image_io.create_blank_png(abs_path, w, h)

        existing = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
        if existing is not None:
            dome_scene.sequence_editor.strips.remove(existing)

        vse_helpers.vse_insert_image_strip(dome_scene, channel, abs_path, start, end)
        image_io.load_slot_from_vse(self.slot, w, h)
        # Tell the sync handler this path is already loaded so the first stroke
        # is not wiped by a reload when the user next changes frames.
        try:
            from ..live_texture import vse_sync as _vse_sync
            _vse_sync._s.last_path[channel] = abs_path
        except Exception:
            pass
        activate_slot(self.slot)
        _blank_other_empty_channels(dome_scene, channel, frame)
        vse_helpers.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Full {start}→{end}: {filename}")
        return {'FINISHED'}


# ── Insert Cut ────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_insert_cut(bpy.types.Operator):
    """
    Insert CUT slot — Cel_A/B only (disabled for BG).
    Case A — strip at playhead: copy left neighbour image, then cut.
    Case B — empty space: blank image from playhead to min(BG, right).
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

        channel = cel_store.BY_SLOT[self.slot].vse_channel
        frame   = image_io.dome_frame()
        w, h    = image_io.get_reference_size()

        current_strip = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
        folder        = image_io.ensure_cel_folder()
        filename      = image_io.cel_filename(self.slot, frame)
        abs_path      = os.path.join(folder, filename)

        for s in dome_scene.sequence_editor.strips_all:
            s.select = False

        if current_strip is not None:
            left_strip = vse_helpers.vse_get_strip_left_of(dome_scene, channel, current_strip)
            if left_strip is not None:
                left_path = vse_helpers.resolve_strip_image_path(
                    left_strip, left_strip.frame_final_start)
                if left_path and os.path.exists(left_path):
                    image_io.copy_image_to_png(left_path, abs_path, w, h)
                else:
                    image_io.create_blank_png(abs_path, w, h)
            else:
                image_io.create_blank_png(abs_path, w, h)
            new_strip = vse_helpers.vse_cut_strip_at_frame(dome_scene, channel,
                                                            frame, abs_path)
        else:
            image_io.create_blank_png(abs_path, w, h)
            bg_strip = (vse_helpers.vse_get_strip_on_channel(dome_scene, 2, frame,
                                                              include_muted=True)
                        or vse_helpers.vse_get_strip_on_channel(dome_scene, 1, frame,
                                                                 include_muted=True))
            right  = vse_helpers.vse_get_strip_right_of(dome_scene, channel, frame)
            bg_end = bg_strip.frame_final_end if bg_strip else (frame + 100)
            end    = min(bg_end, right.frame_final_start if right else bg_end)
            if end <= frame:
                end = bg_end
            new_strip = vse_helpers.vse_insert_image_strip(
                dome_scene, channel, abs_path, frame, end)

        if new_strip is not None:
            new_strip.select = True
            dome_scene.sequence_editor.active_strip = new_strip

        image_io.load_slot_from_vse(self.slot, w, h)
        # Tell the sync handler this path is already loaded so the first stroke
        # is not wiped by a reload when the user next changes frames.
        try:
            from ..live_texture import vse_sync as _vse_sync
            _vse_sync._s.last_path[channel] = abs_path
        except Exception:
            pass
        activate_slot(self.slot)
        _blank_other_empty_channels(dome_scene, channel, frame)
        vse_helpers.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Cut at frame {frame}: {filename}")
        return {'FINISHED'}


# ── Delete strip ──────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_delete(bpy.types.Operator):
    """Delete the VSE strip at the playhead on this cel's channel."""
    bl_idname  = "domeanimatic.cel_delete"
    bl_label   = "Delete Strip at Playhead"
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty()

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return self.execute(context)
        channel = cel_store.BY_SLOT[self.slot].vse_channel
        frame   = image_io.dome_frame()
        strip   = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
        if strip is None:
            self.report({'WARNING'}, f"[{self.slot}] No strip at playhead.")
            return {'CANCELLED'}
        self._strip_name = strip.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text=f"Delete strip '{getattr(self, '_strip_name', '?')}'?",
                  icon='TRASH')
        col.separator()
        col.label(text="This cannot be undone from the cel panel.")

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}
        channel = cel_store.BY_SLOT[self.slot].vse_channel
        frame   = image_io.dome_frame()
        strip   = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
        if strip is None:
            self.report({'WARNING'}, f"[{self.slot}] No strip at playhead.")
            return {'CANCELLED'}
        if dome_scene.sequence_editor:
            for s in dome_scene.sequence_editor.strips_all:
                s.select = False
            strip.select = True
            dome_scene.sequence_editor.active_strip = strip
        activate_slot(self.slot)
        dome_scene.sequence_editor.strips.remove(strip)
        vse_helpers.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Deleted strip at frame {frame}.")
        return {'FINISHED'}


# ── Clear (zero pixels) ───────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_clear(bpy.types.Operator):
    """Clear cel pixels to transparent (keeps VSE strip and file)."""
    bl_idname  = "domeanimatic.cel_clear"
    bl_label   = "Clear Cel"
    bl_options = {'REGISTER', 'UNDO'}

    slot: bpy.props.StringProperty()

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return self.execute(context)
        channel = cel_store.BY_SLOT[self.slot].vse_channel
        frame   = image_io.dome_frame()
        strip   = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
        if strip is None:
            self.report({'WARNING'}, f"[{self.slot}] No strip at playhead.")
            return {'CANCELLED'}
        self._strip_name = strip.name
        return context.window_manager.invoke_props_dialog(self, width=360)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text=f"Clear pixels of '{getattr(self, '_strip_name', '?')}' to transparent?",
                  icon='TEXTURE')
        col.separator()
        col.label(text="VSE strip and file are kept — only pixels are zeroed.")

    def execute(self, context):
        if np is None:
            self.report({'ERROR'}, "numpy required for cel_clear.")
            return {'CANCELLED'}
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene:
            channel = cel_store.BY_SLOT[self.slot].vse_channel
            frame   = image_io.dome_frame()
            strip   = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame)
            if strip is not None and dome_scene.sequence_editor:
                for s in dome_scene.sequence_editor.strips_all:
                    s.select = False
                strip.select = True
                dome_scene.sequence_editor.active_strip = strip
        img = cel_store.get_cel_image(self.slot)
        if img is None:
            self.report({'WARNING'}, f"No datablock for {self.slot}.")
            return {'CANCELLED'}
        w, h = img.size
        # CEL_Baked has alpha=False — fill opaque black; others fill transparent
        if self.slot == 'CEL_Baked':
            buf = np.tile(np.array([0.0, 0.0, 0.0, 1.0], dtype=np.float32), w * h)
        else:
            buf = np.zeros(w * h * 4, dtype=np.float32)
        img.pixels.foreach_set(buf)
        img.update()
        activate_slot(self.slot)
        vse_helpers.tag_all_image_editors_redraw()
        self.report({'INFO'}, f"[{self.slot}] Cleared.")
        return {'FINISHED'}


# ── Save PNG ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_save(bpy.types.Operator):
    """Save cel PNG to disk (painted layer only, no background baked in)."""
    bl_idname = "domeanimatic.cel_save"
    bl_label  = "Save Cel"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        img = cel_store.get_cel_image(self.slot)
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
        activate_slot(self.slot)
        self.report({'INFO'}, f"[{self.slot}] Saved → {img.filepath_raw}")
        return {'FINISHED'}


# ── Purge unused PNGs ─────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_purge_unused(bpy.types.Operator):
    """Delete PNG files in the cel folder not referenced by any VSE strip."""
    bl_idname  = "domeanimatic.cel_purge_unused"
    bl_label   = "Purge Unused Cel Files"
    bl_options = {'REGISTER'}

    _unused: list = []

    def invoke(self, context, event):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        folder     = image_io.cel_folder_abs()
        if not os.path.isdir(folder):
            self.report({'WARNING'}, "Cel folder not found.")
            return {'CANCELLED'}

        referenced = set()
        if dome_scene and dome_scene.sequence_editor:
            for strip in dome_scene.sequence_editor.strips_all:
                if strip.type == 'IMAGE' and strip.channel in cel_store.CEL_CHANNELS:
                    for frame in range(int(strip.frame_final_start),
                                       int(strip.frame_final_end)):
                        p = vse_helpers.resolve_strip_image_path(strip, frame)
                        if p:
                            referenced.add(os.path.normpath(p))

        unused = []
        for fname in os.listdir(folder):
            if not fname.lower().endswith('.png'):
                continue
            if ('_BG_f_' not in fname and '_Cel_A_f_' not in fname
                    and '_Cel_B_f_' not in fname):
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
        col.label(text=f"Delete {len(self._unused)} unused cel PNG(s)?", icon='TRASH')
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
            except Exception as e:
                vse_helpers.log(f"[PurgeUnused] Could not delete {p}: {e}")
        self.report({'INFO'}, f"Purged {deleted} unused cel file(s).")
        return {'FINISHED'}


# ── Toon Boom-style drawing duplication ───────────────────────────────────────
# Unlike VSE Shift+D / strip cutting (which keep pointing at the SAME image
# file), these save a brand-new PNG so editing the duplicate never touches
# the original drawing.

def _save_dirty_source(img) -> None:
    """Persist unsaved strokes on the source before duplicating from it."""
    if img is not None and img.is_dirty and img.filepath_raw:
        try:
            img.save()
        except Exception:
            pass


class DOMEANIMATIC_OT_cel_duplicate_up(bpy.types.Operator):
    """Duplicate the active cel's current drawing to the layer above as a new
    independent file (Toon Boom-style: the copy is fully editable and never
    shares pixels with the original)"""
    bl_idname  = "domeanimatic.cel_duplicate_up"
    bl_label   = "Duplicate Up"
    bl_options = {'REGISTER', 'UNDO'}

    def invoke(self, context, event):
        slot  = gp(context).active_cel
        upper = cel_store.upper_slot(slot)
        if upper is None:
            self.report({'WARNING'}, f"[{slot}] No layer above.")
            return {'CANCELLED'}
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'ERROR'}, "Dome Animatic scene not found.")
            return {'CANCELLED'}
        frame    = image_io.dome_frame()
        up_ch    = cel_store.BY_SLOT[upper].vse_channel
        existing = vse_helpers.vse_get_strip_on_channel(dome_scene, up_ch, frame,
                                                        include_muted=True)
        if existing is not None:
            self._existing_name = existing.name
            return context.window_manager.invoke_props_dialog(self, width=380)
        return self.execute(context)

    def draw(self, context):
        col = self.layout.column(align=True)
        col.label(text=f"Strip '{getattr(self, '_existing_name', '?')}' already "
                       f"exists on the layer above.", icon='ERROR')
        col.separator()
        col.label(text="Replace it with the duplicated drawing?")

    def execute(self, context):
        slot  = gp(context).active_cel
        upper = cel_store.upper_slot(slot)
        if upper is None:
            self.report({'WARNING'}, f"[{slot}] No layer above.")
            return {'CANCELLED'}
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None or not dome_scene.sequence_editor:
            self.report({'ERROR'}, "Dome Animatic scene / VSE not found.")
            return {'CANCELLED'}

        src_img = cel_store.get_cel_image(slot)
        if src_img is None or src_img.size[0] == 0:
            self.report({'WARNING'}, f"[{slot}] Nothing to duplicate.")
            return {'CANCELLED'}
        _save_dirty_source(src_img)

        frame  = image_io.dome_frame()
        w, h   = image_io.get_reference_size()
        src_ch = cel_store.BY_SLOT[slot].vse_channel
        up_ch  = cel_store.BY_SLOT[upper].vse_channel

        # Range: mirror the source strip if present, else the empty-gap rules
        src_strip = vse_helpers.vse_get_strip_on_channel(dome_scene, src_ch, frame,
                                                         include_muted=True)
        if src_strip is not None:
            start, end = src_strip.frame_final_start, src_strip.frame_final_end
        else:
            start, end = compute_slot_range(dome_scene, up_ch, frame)

        folder   = image_io.ensure_cel_folder()
        abs_path = os.path.join(folder, image_io.cel_filename(upper, frame))
        image_io.save_datablock_to_png(src_img, abs_path, w, h)

        existing = vse_helpers.vse_get_strip_on_channel(dome_scene, up_ch, frame,
                                                        include_muted=True)
        if existing is not None:
            dome_scene.sequence_editor.strips.remove(existing)

        vse_helpers.vse_insert_image_strip(dome_scene, up_ch, abs_path, start, end)
        image_io.load_slot_from_vse(upper, w, h)
        try:
            from ..live_texture import vse_sync as _vse_sync
            _vse_sync._s.last_path[up_ch] = abs_path
        except Exception:
            pass
        activate_slot(upper)
        vse_helpers.tag_all_image_editors_redraw()
        self.report({'INFO'},
                    f"[{slot} -> {upper}] Duplicated as {os.path.basename(abs_path)}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cel_duplicate_next(bpy.types.Operator):
    """Duplicate the active cel's current drawing into the next slot on the
    same VSE channel as a new independent file, then jump the playhead there
    (Toon Boom-style duplicate drawing)"""
    bl_idname  = "domeanimatic.cel_duplicate_next"
    bl_label   = "Duplicate Next"
    bl_options = {'REGISTER', 'UNDO'}

    def execute(self, context):
        slot       = gp(context).active_cel
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None or not dome_scene.sequence_editor:
            self.report({'ERROR'}, "Dome Animatic scene / VSE not found.")
            return {'CANCELLED'}

        channel = cel_store.BY_SLOT[slot].vse_channel
        frame   = image_io.dome_frame()
        current = vse_helpers.vse_get_strip_on_channel(dome_scene, channel, frame,
                                                       include_muted=True)
        if current is None:
            self.report({'WARNING'}, f"[{slot}] No strip at playhead to duplicate.")
            return {'CANCELLED'}

        src_img = cel_store.get_cel_image(slot)
        if src_img is None or src_img.size[0] == 0:
            self.report({'WARNING'}, f"[{slot}] Nothing to duplicate.")
            return {'CANCELLED'}
        _save_dirty_source(src_img)

        start = int(current.frame_final_end)
        dur   = int(current.frame_final_end - current.frame_final_start)
        end   = start + max(dur, 1)
        right = vse_helpers.vse_get_strip_right_of(dome_scene, channel,
                                                   current.frame_final_start)
        if right is not None and right.frame_final_start < end:
            end = int(right.frame_final_start)
        if end <= start:
            self.report({'WARNING'},
                        f"[{slot}] No room after this strip on channel {channel}.")
            return {'CANCELLED'}

        w, h     = image_io.get_reference_size()
        folder   = image_io.ensure_cel_folder()
        abs_path = os.path.join(folder, image_io.cel_filename(slot, start))
        image_io.save_datablock_to_png(src_img, abs_path, w, h)

        vse_helpers.vse_insert_image_strip(dome_scene, channel, abs_path, start, end)

        # Jump the playhead onto the duplicate and load it for editing
        dome_scene.frame_set(start)
        image_io.load_abs_into_slot(slot, abs_path, w, h)
        try:
            from ..live_texture import vse_sync as _vse_sync
            _vse_sync._s.last_path[channel] = abs_path
        except Exception:
            pass
        activate_slot(slot)
        _blank_other_empty_channels(dome_scene, channel, start)
        vse_helpers.tag_all_image_editors_redraw()
        self.report({'INFO'},
                    f"[{slot}] Duplicated to {start}->{end}: {os.path.basename(abs_path)}")
        return {'FINISHED'}


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [
    DOMEANIMATIC_OT_refresh_cel_folder,
    DOMEANIMATIC_OT_cel_set_active,
    DOMEANIMATIC_OT_cel_toggle_visible,
    DOMEANIMATIC_OT_dome_object_picker,
    DOMEANIMATIC_OT_cel_show_baked,
    DOMEANIMATIC_OT_cel_insert_full,
    DOMEANIMATIC_OT_cel_insert_cut,
    DOMEANIMATIC_OT_cel_delete,
    DOMEANIMATIC_OT_cel_clear,
    DOMEANIMATIC_OT_cel_save,
    DOMEANIMATIC_OT_cel_purge_unused,
    DOMEANIMATIC_OT_cel_duplicate_up,
    DOMEANIMATIC_OT_cel_duplicate_next,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        try:
            bpy.utils.unregister_class(cls)
        except Exception:
            pass

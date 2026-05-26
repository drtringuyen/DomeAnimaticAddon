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
from ...global_scene_shared_props import gp
from . import image_io


# ── Active-slot helper ────────────────────────────────────────────────────────

def activate_slot(slot_id: str) -> None:
    """Set slot as active and switch Image Editor to its datablock."""
    g   = gp()
    g.active_cel = slot_id
    img = cel_store.get_cel_image(slot_id)
    if img:
        vse_helpers.set_image_editor_image(bpy.context, img)


# ── Cel folder operator ───────────────────────────────────────────────────────

class DOMEANIMATIC_OT_refresh_cel_folder(bpy.types.Operator):
    """Normalize the cel folder path and create it on disk."""
    bl_idname = "domeanimatic.refresh_cel_folder"
    bl_label  = "Refresh Cel Folder Path"

    def execute(self, context):
        g   = gp(context)
        raw = g.cel_folder
        try:
            abs_path = bpy.path.abspath(raw)
        except Exception:
            abs_path = raw
        os.makedirs(abs_path, exist_ok=True)
        if bpy.data.filepath:
            try:
                rel = bpy.path.relpath(abs_path)
                g.cel_folder = rel
                self.report({'INFO'}, f"Folder: {rel}")
                return {'FINISHED'}
            except ValueError:
                pass
        g.cel_folder = abs_path
        self.report({'INFO'}, f"Folder: {abs_path}")
        return {'FINISHED'}


# ── Visibility operators ──────────────────────────────────────────────────────

class DOMEANIMATIC_OT_cel_set_active(bpy.types.Operator):
    """Set this slot as the active (paintable) cel. If invisible, turns eye on."""
    bl_idname = "domeanimatic.cel_set_active"
    bl_label  = "Set Active Cel"

    slot: bpy.props.StringProperty()

    def execute(self, context):
        g        = gp(context)
        slot_key = self.slot.lower()
        if not getattr(g, f"{slot_key}_visible", True):
            setattr(g, f"{slot_key}_visible", True)
            vse_helpers.tag_all_image_editors_redraw()
        g.active_cel = self.slot
        img = cel_store.get_cel_image(self.slot)
        if img:
            vse_helpers.set_image_editor_image(context, img)
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
        activate_slot(self.slot)

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
        activate_slot(self.slot)
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
        buf  = np.zeros(w * h * 4, dtype=np.float32)
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


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [
    DOMEANIMATIC_OT_refresh_cel_folder,
    DOMEANIMATIC_OT_cel_set_active,
    DOMEANIMATIC_OT_cel_toggle_visible,
    DOMEANIMATIC_OT_cel_insert_full,
    DOMEANIMATIC_OT_cel_insert_cut,
    DOMEANIMATIC_OT_cel_delete,
    DOMEANIMATIC_OT_cel_clear,
    DOMEANIMATIC_OT_cel_save,
    DOMEANIMATIC_OT_cel_purge_unused,
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

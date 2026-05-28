"""
frame_capture_ops.py — Frame capture and render-to-live operators.

Ported from capture_current_frame.py and collage_texture.py.
Soft-depends on live_texture module for handler blocking and the
live_texture_reload operator.
"""

import bpy
import os
import tempfile

from ... import cel_store, vse_helpers
from ...global_scene_shared_props import gp
from . import collection_ops


# ── Live sync soft-dependency helpers ─────────────────────────────────────────

def _block_live_sync() -> None:
    try:
        from ..live_texture import vse_sync
        vse_sync.block_handler()
    except Exception:
        pass


def _unblock_live_sync() -> None:
    try:
        from ..live_texture import vse_sync
        vse_sync.unblock_handler()
    except Exception:
        pass


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_render_to_live_preview(bpy.types.Operator):
    bl_idname      = "domeanimatic.render_to_live_preview"
    bl_label       = "Render to LiveDomePreview"
    bl_description = "Silently render current scene and load result into LiveDomePreview"

    @classmethod
    def poll(cls, context):
        return gp(context).active_collage != ""

    def execute(self, context):
        try:
            import numpy as np
        except ImportError:
            self.report({'ERROR'}, "numpy required for render-to-live.")
            return {'CANCELLED'}

        live_img = cel_store.get_live_image()
        if live_img is None:
            self.report({'ERROR'}, "LiveDomePreview not found. Run Prepare first.")
            return {'CANCELLED'}

        live_w, live_h = live_img.size[0], live_img.size[1]

        _block_live_sync()

        original_filepath = context.scene.render.filepath
        original_format   = context.scene.render.image_settings.file_format
        original_display  = context.preferences.view.render_display_type

        tmp_path = os.path.join(tempfile.gettempdir(), "domeanimatic_render_preview.png")
        context.scene.render.filepath                    = tmp_path
        context.scene.render.image_settings.file_format = 'PNG'
        context.preferences.view.render_display_type    = 'NONE'

        bpy.ops.render.render(write_still=True)

        context.scene.render.filepath                    = original_filepath
        context.scene.render.image_settings.file_format = original_format
        context.preferences.view.render_display_type    = original_display

        if not os.path.exists(tmp_path):
            _unblock_live_sync()
            self.report({'ERROR'}, "Render output not found.")
            return {'CANCELLED'}

        try:
            tmp_img = bpy.data.images.load(tmp_path, check_existing=False)
        except Exception as e:
            _unblock_live_sync()
            self.report({'ERROR'}, f"Failed to load render result: {e}")
            return {'CANCELLED'}

        try:
            _ = tmp_img.pixels[0]
        except Exception:
            bpy.data.images.remove(tmp_img)
            _unblock_live_sync()
            self.report({'ERROR'}, "Render result has no pixel data.")
            return {'CANCELLED'}

        tmp_w, tmp_h = tmp_img.size[0], tmp_img.size[1]
        if tmp_w == 0 or tmp_h == 0:
            bpy.data.images.remove(tmp_img)
            _unblock_live_sync()
            self.report({'ERROR'}, "Render result has zero size.")
            return {'CANCELLED'}

        full_buf = np.empty(tmp_w * tmp_h * 4, dtype=np.float32)
        tmp_img.pixels.foreach_get(full_buf)

        full_arr  = full_buf.reshape((tmp_h, tmp_w, 4))
        y_indices = (np.arange(live_h) * tmp_h / live_h).astype(int)
        x_indices = (np.arange(live_w) * tmp_w / live_w).astype(int)
        resized   = full_arr[np.ix_(y_indices, x_indices)]
        buf       = resized.flatten().astype(np.float32)

        expected = live_w * live_h * 4
        if len(buf) != expected:
            bpy.data.images.remove(tmp_img)
            _unblock_live_sync()
            self.report({'ERROR'}, f"Buffer size mismatch: {len(buf)} vs {expected}")
            return {'CANCELLED'}

        bpy.data.images.remove(tmp_img)

        live_name = cel_store.BAKED_LAYER.datablock_name
        bpy.data.images.remove(live_img)
        live_img = bpy.data.images.new(live_name, width=live_w, height=live_h,
                                        alpha=False, float_buffer=False)
        live_img.use_fake_user = True
        live_img.pixels.foreach_set(buf)
        live_img.update()
        live_img.pack()

        _unblock_live_sync()

        vse_helpers.restore_image_editor_to_live(context)
        self.report({'INFO'}, "LiveDomePreview updated — ready to paint.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_capture_current_frame(bpy.types.Operator):
    bl_idname      = "domeanimatic.capture_current_frame"
    bl_label       = "Save Current Frame"
    bl_description = "Save the current Dome Animatic VSE frame as an image"

    filepath:  bpy.props.StringProperty(subtype='FILE_PATH')
    filename:  bpy.props.StringProperty()
    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    filter_image:  bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    original_filepath: bpy.props.StringProperty(options={'HIDDEN'})
    has_vse:           bpy.props.BoolProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        name, filepath, strip, el = vse_helpers.get_dome_animatic_frame_info()
        if filepath:
            self.filepath          = filepath
            self.directory         = os.path.dirname(filepath)
            self.filename          = os.path.basename(filepath)
            self.original_filepath = filepath
            self.has_vse           = True
        else:
            frame                  = context.scene.frame_current
            self.directory         = bpy.path.abspath("//")
            self.filename          = f"frame_{frame:04d}.png"
            self.filepath          = os.path.join(self.directory, self.filename)
            self.original_filepath = ""
            self.has_vse           = False
        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        try:
            import numpy as np
        except ImportError:
            self.report({'ERROR'}, "numpy required for capture.")
            return {'CANCELLED'}

        new_filepath      = bpy.path.abspath(self.filepath)
        original_filepath = self.original_filepath

        if not os.path.splitext(new_filepath)[1]:
            new_filepath += ".png"

        live_img = cel_store.get_live_image()
        if live_img is None:
            self.report({'ERROR'}, "LiveDomePreview not found.")
            return {'CANCELLED'}

        live_w, live_h = live_img.size[0], live_img.size[1]

        if self.has_vse:
            _, path, _, _ = vse_helpers.get_dome_animatic_frame_info()
            if path and os.path.exists(path):
                ref = bpy.data.images.load(path, check_existing=True)
                out_w, out_h = ref.size[0], ref.size[1]
            else:
                out_w, out_h = live_w, live_h
        else:
            out_w, out_h = live_w, live_h

        save_img = bpy.data.images.new("__domeanimatic_save_tmp__",
                                        width=live_w, height=live_h, float_buffer=False)
        buf = np.empty(live_w * live_h * 4, dtype=np.float32)
        live_img.pixels.foreach_get(buf)
        save_img.pixels.foreach_set(buf)
        save_img.update()
        if out_w != live_w or out_h != live_h:
            save_img.scale(out_w, out_h)
        save_img.filepath_raw = new_filepath
        save_img.file_format  = 'PNG'
        save_img.save()
        bpy.data.images.remove(save_img)
        self.report({'INFO'}, f"Saved {out_w}x{out_h}: {new_filepath}")

        try:
            rel_filepath = bpy.path.relpath(new_filepath)
        except ValueError:
            rel_filepath = new_filepath

        if not self.has_vse:
            return {'FINISHED'}

        if os.path.basename(new_filepath) == os.path.basename(original_filepath):
            src_img = bpy.data.images.load(original_filepath, check_existing=True)
            src_img.reload()
            return {'FINISHED'}

        # Always in the "Dome Animatic" scene — use context.scene directly
        scene = context.scene
        frame = scene.frame_current
        strip = vse_helpers.get_active_strip_at_frame(scene, frame)
        if strip is None or strip.type not in ('IMAGE', 'MOVIE'):
            return {'FINISHED'}
        seq = scene.sequence_editor
        if frame <= strip.frame_final_start:
            return {'FINISHED'}

        orig_end              = strip.frame_final_end
        channel               = strip.channel
        new_filename          = os.path.splitext(os.path.basename(new_filepath))[0]
        strip.frame_final_end = frame

        new_strip = seq.strips.new_image(
            name=new_filename, filepath=rel_filepath,
            channel=channel, frame_start=frame,
        )
        vse_helpers.copy_strip_transform(strip, new_strip)
        new_strip.frame_final_end = orig_end
        return {'FINISHED'}


class DOMEANIMATIC_OT_switch_dome_collage(bpy.types.Operator):
    bl_idname      = "domeanimatic.switch_dome_collage"
    bl_label       = "Switch Dome / Collage"
    bl_description = "Switch to Nearest Collage or back to overview"

    @classmethod
    def description(cls, context, properties):
        g = gp(context)
        if g.active_collage == "":
            name, _, _, _ = vse_helpers.get_dome_animatic_frame_info()
            closest, score = vse_helpers.find_closest_collage(name) if name else (None, 0)
            if closest:
                return f"Switch to nearest collage: '{closest}'"
            return "No nearest collage found"
        return f"Return to overview (from '{g.active_collage}')"

    def execute(self, context):
        g = gp(context)
        if g.active_collage == "":
            name, _, _, _ = vse_helpers.get_dome_animatic_frame_info()
            closest, score = vse_helpers.find_closest_collage(name) if name else (None, 0)
            if closest:
                collection_ops.solo_collage(context, closest)
                self.report({'INFO'}, f"Switched to '{closest}'.")
            else:
                self.report({'WARNING'}, "No closest collage found.")
        else:
            collection_ops.unsolo_collage(context)
            try:
                bpy.ops.domeanimatic.live_texture_reload()
            except Exception:
                pass
            self.report({'INFO'}, "Returned to overview.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_capture_from_view(bpy.types.Operator):
    bl_idname      = "domeanimatic.capture_from_view"
    bl_label       = "Capture from View"
    bl_description = "Render current scene and load into LiveDomePreview"

    @classmethod
    def poll(cls, context):
        return gp(context).active_collage != ""

    def execute(self, context):
        bpy.ops.domeanimatic.render_to_live_preview()
        return {'FINISHED'}


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [
    DOMEANIMATIC_OT_render_to_live_preview,
    DOMEANIMATIC_OT_capture_current_frame,
    DOMEANIMATIC_OT_switch_dome_collage,
    DOMEANIMATIC_OT_capture_from_view,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

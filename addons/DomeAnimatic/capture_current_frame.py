import bpy
import os
from . import utils


# ── Operator ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_capture_current_frame(bpy.types.Operator):
    bl_idname = "domeanimatic.capture_current_frame"
    bl_label = "Capture Current Frame"
    bl_description = "Save the current Dome Animatic VSE frame as an image"

    filepath: bpy.props.StringProperty(subtype='FILE_PATH')
    filename: bpy.props.StringProperty()
    directory: bpy.props.StringProperty(subtype='DIR_PATH')

    filter_image: bpy.props.BoolProperty(default=True, options={'HIDDEN'})
    filter_folder: bpy.props.BoolProperty(default=True, options={'HIDDEN'})

    original_filepath: bpy.props.StringProperty(options={'HIDDEN'})
    has_vse: bpy.props.BoolProperty(options={'HIDDEN'})

    def invoke(self, context, event):
        name, filepath, strip, el = utils.get_dome_animatic_frame_info()

        if filepath:
            self.filepath           = filepath
            self.directory          = os.path.dirname(filepath)
            self.filename           = os.path.basename(filepath)
            self.original_filepath = filepath
            self.has_vse           = True
        else:
            dome_scene = bpy.data.scenes.get("Dome Animatic")
            frame      = dome_scene.frame_current if dome_scene else context.scene.frame_current
            self.directory          = bpy.path.abspath("//")
            self.filename           = f"frame_{frame:04d}.png"
            self.filepath           = os.path.join(self.directory, self.filename)
            self.original_filepath = ""
            self.has_vse           = False

        context.window_manager.fileselect_add(self)
        return {'RUNNING_MODAL'}

    def execute(self, context):
        import numpy as np

        new_filepath      = bpy.path.abspath(self.filepath)
        original_filepath = self.original_filepath

        if not os.path.splitext(new_filepath)[1]:
            new_filepath += ".png"

        live_img = utils.get_live_image()
        if live_img is None:
            self.report({'ERROR'}, "LiveDomePreview not found.")
            return {'CANCELLED'}

        live_w = live_img.size[0]
        live_h = live_img.size[1]

        # ── Determine full output resolution from VSE source image ────────────
        if self.has_vse:
            name, path, strip, el = utils.get_dome_animatic_frame_info()
            if path and os.path.exists(path):
                ref_img = bpy.data.images.load(path, check_existing=True)
                out_w   = ref_img.size[0]
                out_h   = ref_img.size[1]
            else:
                out_w, out_h = live_w, live_h
        else:
            out_w, out_h = live_w, live_h

        utils.log(f"[CaptureFrame] Saving at {out_w}x{out_h} to {new_filepath}")

        # ── Create a full resolution copy of LiveDomePreview pixels to save ───
        save_img = bpy.data.images.new(
            "__domeanimatic_save_tmp__",
            width=live_w,
            height=live_h,
            float_buffer=False,
        )

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

        self.report({'INFO'}, f"Saved at {out_w}x{out_h}: {new_filepath}")

        # Convert to relative path for all Blender data references
        try:
            rel_filepath = bpy.path.relpath(new_filepath)
        except ValueError:
            rel_filepath = new_filepath  # Different drive — keep absolute

        # ── No VSE — done ─────────────────────────────────────────────────────
        if not self.has_vse:
            return {'FINISHED'}

        # ── Case A: same filename → reload source image ───────────────────────
        if os.path.basename(new_filepath) == os.path.basename(original_filepath):
            src_img = bpy.data.images.load(original_filepath, check_existing=True)
            src_img.filepath = bpy.path.relpath(original_filepath) \
                               if bpy.data.filepath else src_img.filepath
            src_img.reload()
            utils.log(f"[CaptureFrame] Reloaded: {os.path.basename(original_filepath)}")
            self.report({'INFO'}, f"Reloaded: {os.path.basename(original_filepath)}")
            return {'FINISHED'}

        # ── Case B: different filename → split strip in Dome Animatic ─────────
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            self.report({'WARNING'}, "Dome Animatic scene not found — skipping split.")
            return {'FINISHED'}

        frame = dome_scene.frame_current
        strip = utils.get_active_strip_at_frame(dome_scene, frame)

        if strip is None:
            self.report({'WARNING'}, "No strip found at current frame — skipping split.")
            return {'FINISHED'}

        if strip.type not in ('IMAGE', 'MOVIE'):
            self.report({'WARNING'}, "Split only supported for IMAGE or MOVIE strips.")
            return {'FINISHED'}

        seq = dome_scene.sequence_editor

        if frame <= strip.frame_final_start:
            self.report({'WARNING'}, "Cursor is at or before strip start — nothing to split.")
            return {'FINISHED'}

        orig_end         = strip.frame_final_end
        original_channel = strip.channel
        new_filename     = os.path.splitext(os.path.basename(new_filepath))[0]

        strip.frame_final_end = frame

        new_strip = seq.strips.new_image(
            name        = new_filename,
            filepath    = rel_filepath,   # relative path in VSE
            channel     = original_channel,
            frame_start = frame,
        )

        utils.copy_strip_transform(strip, new_strip)
        new_strip.frame_final_end = orig_end

        utils.log(f"[CaptureFrame] Split at {frame}: '{strip.name}' ends, '{new_strip.name}' runs {frame}→{orig_end}")
        self.report({'INFO'}, (
            f"Split at frame {frame}: "
            f"'{strip.name}' ends at {frame}, "
            f"'{new_strip.name}' runs {frame} → {orig_end}"
        ))
        return {'FINISHED'}


# ── Extra operators ───────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_switch_dome_collage(bpy.types.Operator):
    bl_idname = "domeanimatic.switch_dome_collage"
    bl_label = "Switch Dome/Collage"
    bl_description = "Switch to Nearest Collage scene or back to Dome Animatic"

    @classmethod
    def description(cls, context, properties):
        if context.scene.name == "Dome Animatic":
            name, filepath, strip, el = utils.get_dome_animatic_frame_info()
            closest, score = utils.find_closest_scene(name) if name else (None, 0)
            if closest and closest != "Dome Animatic":
                return f"Switch to nearest collage: '{closest}'"
            return "No nearest collage scene found"
        else:
            return "Switch back to 'Dome Animatic'"

    def execute(self, context):
        if context.scene.name == "Dome Animatic":
            # Save view state before leaving
            utils.save_dome_view_state(context)
            name, filepath, strip, el = utils.get_dome_animatic_frame_info()
            closest, score = utils.find_closest_scene(name) if name else (None, 0)
            if closest and closest != "Dome Animatic":
                context.window.scene = bpy.data.scenes[closest]
                utils.switch_all_view3d_to_camera(context)
                self.report({'INFO'}, f"Switched to '{closest}'.")
            else:
                self.report({'WARNING'}, "No closest collage scene found.")
        else:
            target = bpy.data.scenes.get("Dome Animatic")
            if target:
                context.window.scene = target
                # Restore saved view state
                utils.restore_dome_view_state(context)
                bpy.ops.domeanimatic.reload_live_dome_texture()
                self.report({'INFO'}, "Switched to 'Dome Animatic'.")
            else:
                self.report({'ERROR'}, "Dome Animatic scene not found.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_capture_from_view(bpy.types.Operator):
    bl_idname = "domeanimatic.capture_from_view"
    bl_label = "Capture from View"
    bl_description = "Render current scene and load into LiveDomePreview"

    @classmethod
    def poll(cls, context):
        return context.scene.name != "Dome Animatic"

    def execute(self, context):
        bpy.ops.domeanimatic.render_to_live_preview()
        return {'FINISHED'}


# ── UI draw — delegates to frame_snap_shot ────────────────────────────────────

def draw_ui(box, context, space_type=None):
    from . import frame_snap_shot
    frame_snap_shot.draw_ui(box, context, space_type=space_type)


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_capture_current_frame,
    DOMEANIMATIC_OT_switch_dome_collage,
    DOMEANIMATIC_OT_capture_from_view,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

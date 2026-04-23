import bpy
import os
import tempfile
from . import utils


# ── Operator ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_render_to_live_preview(bpy.types.Operator):
    bl_idname = "domeanimatic.render_to_live_preview"
    bl_label = "Render to LiveDomePreview"
    bl_description = "Silently render current scene and load result into LiveDomePreview"

    @classmethod
    def poll(cls, context):
        return context.scene.name != "Dome Animatic"

    def execute(self, context):
        import numpy as np
        from . import synch_VSE_to_LiveDomePreview as synch

        live_img = utils.get_live_image()
        if live_img is None:
            self.report({'ERROR'}, "LiveDomePreview not found. Run Prepare Live Dome Texture first.")
            return {'CANCELLED'}

        live_w = live_img.size[0]
        live_h = live_img.size[1]

        # ── Block handler BEFORE render so it can't interfere ─────────────────
        synch.block_handler()

        # Store original settings
        original_filepath = context.scene.render.filepath
        original_format   = context.scene.render.image_settings.file_format
        original_display  = context.preferences.view.render_display_type

        # Render silently to temp file
        tmp_path = os.path.join(tempfile.gettempdir(), "domeanimatic_render_preview.png")

        context.scene.render.filepath                    = tmp_path
        context.scene.render.image_settings.file_format = 'PNG'
        context.preferences.view.render_display_type    = 'NONE'

        bpy.ops.render.render(write_still=True)

        # Restore original settings
        context.scene.render.filepath                    = original_filepath
        context.scene.render.image_settings.file_format = original_format
        context.preferences.view.render_display_type    = original_display

        if not os.path.exists(tmp_path):
            synch.unblock_handler()
            self.report({'ERROR'}, "Render output not found.")
            return {'CANCELLED'}

        # Load render result
        try:
            tmp_img = bpy.data.images.load(tmp_path, check_existing=False)
        except Exception as e:
            synch.unblock_handler()
            self.report({'ERROR'}, f"Failed to load render result: {e}")
            return {'CANCELLED'}

        # Force pixels into memory
        try:
            _ = tmp_img.pixels[0]
        except Exception:
            bpy.data.images.remove(tmp_img)
            synch.unblock_handler()
            self.report({'ERROR'}, "Render result has no pixel data.")
            return {'CANCELLED'}

        tmp_w = tmp_img.size[0]
        tmp_h = tmp_img.size[1]

        if tmp_w == 0 or tmp_h == 0:
            bpy.data.images.remove(tmp_img)
            synch.unblock_handler()
            self.report({'ERROR'}, "Render result has zero size.")
            return {'CANCELLED'}

        utils.log(f"[RenderToLive] Render size: {tmp_w}x{tmp_h} → downsampling to {live_w}x{live_h}")

        # Read full resolution pixels
        full_buf = np.empty(tmp_w * tmp_h * 4, dtype=np.float32)
        tmp_img.pixels.foreach_get(full_buf)

        # Reshape to (H, W, 4) and resize via nearest-neighbor
        full_arr  = full_buf.reshape((tmp_h, tmp_w, 4))
        y_indices = (np.arange(live_h) * tmp_h / live_h).astype(int)
        x_indices = (np.arange(live_w) * tmp_w / live_w).astype(int)
        resized   = full_arr[np.ix_(y_indices, x_indices)]
        buf       = resized.flatten().astype(np.float32)

        # Verify buffer size
        expected = live_w * live_h * 4
        if len(buf) != expected:
            bpy.data.images.remove(tmp_img)
            synch.unblock_handler()
            self.report({'ERROR'}, f"Buffer size mismatch: got {len(buf)}, expected {expected}")
            return {'CANCELLED'}

        # Clean up temp image
        bpy.data.images.remove(tmp_img)

        # Recreate LiveDomePreview as GENERATED at the correct size
        live_name = utils.LIVE_TEXTURE_NAME
        bpy.data.images.remove(live_img)
        live_img = bpy.data.images.new(
            live_name,
            width=live_w,
            height=live_h,
            alpha=False,
            float_buffer=False,
        )
        live_img.use_fake_user = True

        # Write pixels
        live_img.pixels.foreach_set(buf)
        live_img.update()

        # Pack so image is paintable
        live_img.pack()

        # ── Unblock handler AFTER all pixel work is done ───────────────────────
        synch.unblock_handler()

        # Restore Image Editor to show LiveDomePreview
        utils.restore_image_editor_to_live(context)

        utils.log("[RenderToLive] LiveDomePreview updated and packed.")
        self.report({'INFO'}, "LiveDomePreview updated — ready to paint.")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    col = box.column()
    col.scale_y = 1.5
    col.operator(
        "domeanimatic.render_to_live_preview",
        text="Render to LiveDomePreview",
        icon='RENDER_STILL',
    )


# ── Register ──────────────────────────────────────────────────────────────────

classes = [DOMEANIMATIC_OT_render_to_live_preview]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

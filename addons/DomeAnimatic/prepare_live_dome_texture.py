import bpy
from . import utils, manage_live_dome_preview

TEXTURE_NAME = utils.LIVE_TEXTURE_NAME


# ── Properties ────────────────────────────────────────────────────────────────

class DOMEANIMATIC_PG_texture_settings(bpy.types.PropertyGroup):
    width: bpy.props.IntProperty(
        name="Width",
        default=960,
        min=1,
        max=7680,
    )
    height: bpy.props.IntProperty(
        name="Height",
        default=590,
        min=1,
        max=4320,
    )
    scale: bpy.props.FloatProperty(
        name="Scale",
        default=1.0,
        min=0.0,
        max=2.0,
        step=10,
        precision=2,
    )


# ── Operator ──────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_prepare_live_dome_texture(bpy.types.Operator):
    bl_idname = "domeanimatic.prepare_live_dome_texture"
    bl_label = "Prepare Live Dome Texture"
    bl_description = "Create or resize LiveDomePreview at the specified size and scale"

    def execute(self, context):
        settings = context.scene.domeanimatic_texture_settings
        width    = max(1, int(settings.width  * settings.scale))
        height   = max(1, int(settings.height * settings.scale))

        if TEXTURE_NAME in bpy.data.images:
            img = bpy.data.images[TEXTURE_NAME]
            if img.size[0] != width or img.size[1] != height:
                img.scale(width, height)
                utils.log(f"[DomeAnimatic] Resized {TEXTURE_NAME} to {width}x{height}")
                self.report({'INFO'}, f"'{TEXTURE_NAME}' resized to {width}x{height}.")
            else:
                self.report({'INFO'}, f"'{TEXTURE_NAME}' already at {width}x{height} — skipping.")
            return {'FINISHED'}

        image = bpy.data.images.new(
            name=TEXTURE_NAME,
            width=width,
            height=height,
            alpha=False,
            float_buffer=False,
        )
        image.colorspace_settings.name = 'sRGB'
        utils.log(f"[DomeAnimatic] Created {TEXTURE_NAME} at {width}x{height}")
        self.report({'INFO'}, f"'{TEXTURE_NAME}' created at {width}x{height}.")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    settings = context.scene.domeanimatic_texture_settings
    verbose  = utils.show_labels(context)

    if verbose:
        if TEXTURE_NAME in bpy.data.images:
            img = bpy.data.images[TEXTURE_NAME]
            col = box.column(align=True)
            col.enabled = False
            col.label(text=f"{TEXTURE_NAME} exists", icon='CHECKMARK')
            col.label(text=f"Current size: {img.size[0]}x{img.size[1]}")
        else:
            col = box.column()
            col.enabled = False
            col.label(text=f"{TEXTURE_NAME} not found", icon='ERROR')

        box.separator(factor=0.3)

    # Base size fields
    row = box.row(align=True)
    row.prop(settings, "width")
    row.prop(settings, "height")

    box.prop(settings, "scale", slider=True)

    if verbose:
        final_w = max(1, int(settings.width  * settings.scale))
        final_h = max(1, int(settings.height * settings.scale))
        col = box.column()
        col.enabled = False
        col.label(text=f"Final size: {final_w}x{final_h}", icon='FIXED_SIZE')

    box.separator(factor=0.3)

    # Prepare + Reload in same row
    row = box.row(align=True)
    row.scale_y = 1.5
    row.operator(
        "domeanimatic.prepare_live_dome_texture",
        text="Prepare Live Dome Texture",
        icon='IMAGE_DATA',
    )
    row.operator(
        "domeanimatic.reload_live_dome_texture",
        text="",
        icon='FILE_REFRESH',
    )

    # Status labels only (verbose)
    manage_live_dome_preview.draw_status(box, context)


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_PG_texture_settings,
    DOMEANIMATIC_OT_prepare_live_dome_texture,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)
    bpy.types.Scene.domeanimatic_texture_settings = bpy.props.PointerProperty(
        type=DOMEANIMATIC_PG_texture_settings
    )

def unregister():
    del bpy.types.Scene.domeanimatic_texture_settings
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

import bpy
from . import (
    capture_current_frame,
    collage_manipulation,
    color_palette,
)


def draw_ui(box, context, space_type=None):
    from . import utils
    verbose = utils.show_labels(context)
    is_dome = context.scene.name == "Dome Animatic"

    # ── Verbose info ──────────────────────────────────────────────────────────
    if verbose:
        import os
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        info_col   = box.column(align=True)
        info_col.enabled = False
        if dome_scene is None:
            info_col.label(text="Dome Animatic scene not found", icon='ERROR')
        else:
            frame = dome_scene.frame_current
            name, filepath, strip, el = utils.get_dome_animatic_frame_info()
            if filepath:
                info_col.label(text=f"Frame: {frame}", icon='TIME')
                info_col.label(text=os.path.basename(filepath), icon='IMAGE_DATA')
                info_col.label(text=bpy.path.abspath(os.path.dirname(filepath)), icon='FILE_FOLDER')
            else:
                info_col.label(text=f"Frame: {frame} — no strip at cursor", icon='INFO')
        box.separator(factor=0.3)

    # ── Save Current Frame row ────────────────────────────────────────────────
    row = box.row(align=True)
    row.scale_y = 2.0
    row.operator("domeanimatic.capture_current_frame", text="Save Current Frame", icon='FILE_TICK')
    row.operator("domeanimatic.switch_dome_collage",   text="",                   icon='ARROW_LEFTRIGHT')
    row.operator("domeanimatic.capture_from_view",     text="",                   icon='RESTRICT_RENDER_OFF')
    row.operator("domeanimatic.prepare_collage_scene", text="",                   icon='OUTLINER_DATA_GP_LAYER')

    # ── Handle Selected + layer move row ─────────────────────────────────────
    row2 = box.row(align=True)
    row2.scale_y = 1.5
    row2.enabled = not is_dome
    row2.operator("domeanimatic.recover_face",        text="", icon='RECOVER_LAST')
    row2.label(text="Handle Selected", icon='GREASEPENCIL_LAYER_GROUP')
    sub = row2.row(align=True)
    sub.scale_x = 0.4
    sub.prop(context.scene, "domeanimatic_delete_color", text="")
    row2.operator("domeanimatic.duplicate_as_object", text="", icon='SELECT_DIFFERENCE')
    row2.operator("domeanimatic.cut_fill_black",      text="", icon='SELECT_INTERSECT')
    col2 = row2.column(align=True)
    col2.scale_y = 0.5
    col2.operator("domeanimatic.layer_move_up",   text="", icon='TRIA_UP')
    col2.operator("domeanimatic.layer_move_down", text="", icon='TRIA_DOWN')


def register():
    pass

def unregister():
    pass

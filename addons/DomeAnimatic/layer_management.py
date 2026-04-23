import bpy
from . import collage_manipulation


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_layer_duplicate(bpy.types.Operator):
    bl_idname      = "domeanimatic.layer_duplicate"
    bl_label       = "Duplicate Layer"
    bl_description = "Duplicate the active image paint layer"

    def execute(self, context):
        try:
            bpy.ops.image.paint_layer_duplicate()
        except Exception as e:
            self.report({'WARNING'}, f"Could not duplicate layer: {e}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_layer_cut(bpy.types.Operator):
    bl_idname      = "domeanimatic.layer_cut"
    bl_label       = "Cut / Remove Layer"
    bl_description = "Remove the active image paint layer"

    def execute(self, context):
        try:
            bpy.ops.image.paint_layer_remove()
        except Exception as e:
            self.report({'WARNING'}, f"Could not remove layer: {e}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_layer_move_up(bpy.types.Operator):
    bl_idname      = "domeanimatic.layer_move_up"
    bl_label       = "Move Object Up"
    bl_description = "Move the active object up along global Z by Layer Spacing"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        spacing = context.scene.domeanimatic_layer_spacing
        # Work in object mode to safely set location
        prev_mode = context.mode
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.active_object.location.z += spacing
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=prev_mode.replace('EDIT_MESH', 'EDIT'))
        self.report({'INFO'}, f"Moved up by {spacing}.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_layer_move_down(bpy.types.Operator):
    bl_idname      = "domeanimatic.layer_move_down"
    bl_label       = "Move Object Down"
    bl_description = "Move the active object down along global Z by Layer Spacing"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        spacing = context.scene.domeanimatic_layer_spacing
        prev_mode = context.mode
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.active_object.location.z -= spacing
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=prev_mode.replace('EDIT_MESH', 'EDIT'))
        self.report({'INFO'}, f"Moved down by {spacing}.")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    scene   = context.scene
    is_dome = scene.name == "Dome Animatic"

    col = box.column(align=True)
    col.enabled = not is_dome

    # ── Layer spacing ─────────────────────────────────────────────────────────
    row = col.row(align=True)
    row.prop(scene, "domeanimatic_layer_spacing", text="Layer Spacing")

    col.separator(factor=0.3)

    # ── Mark Face + collage ops ───────────────────────────────────────────────
    collage_manipulation.draw_ui(col, context)


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_layer_duplicate,
    DOMEANIMATIC_OT_layer_cut,
    DOMEANIMATIC_OT_layer_move_up,
    DOMEANIMATIC_OT_layer_move_down,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

"""
ui.py — Extra Tools sub-panel (child of the main DomeAnimatic panel).

Currently provides the color palette for image painting.
"""

import bpy


class DOMEANIMATIC_PT_extra_tools(bpy.types.Panel):
    bl_label       = "Extra Tools"
    bl_idname      = "DOMEANIMATIC_PT_extra_tools"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_parent_id   = "DOMEANIMATIC_PT_main"
    bl_order       = 4
    bl_options     = {'DEFAULT_CLOSED'}

    def draw(self, context):
        layout      = self.layout
        ts          = context.tool_settings
        image_paint = ts.image_paint

        if image_paint is None:
            return

        col = layout.column(align=True)
        col.template_ID(image_paint, "palette", new="palette.new")
        if image_paint.palette:
            col.template_palette(image_paint, "palette", color=True)


CLASSES = [DOMEANIMATIC_PT_extra_tools]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

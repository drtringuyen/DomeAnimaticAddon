"""
panels.py — Root panels for DomeAnimatic.

DOMEANIMATIC_PT_infos  (bl_order=0, DEFAULT_CLOSED)
  Row 1: Build timestamp  |  Reload
  Row 2: Debug  |  Console  |  Clear
  Debug-only block: version, module toggles, material picker

DOMEANIMATIC_PT_main  (bl_order=1)
  Parent panel — module sub-panels attach here via bl_parent_id.
  When no module is loaded the panel body is empty.

Each panel is mirrored for IMAGE_EDITOR via a sibling class that shares the
same draw function. Inheritance from registered Panel subclasses is intentionally
avoided — Blender 5.x cannot resolve inherited draw callbacks on subclasses.
"""

import bpy
from . import module_manager
from .global_scene_shared_props import gp, sp


# ── Shared draw functions ─────────────────────────────────────────────────────

def _draw_infos(self, context):
    layout = self.layout
    g      = gp(context)

    # Single compact row matching the minimal look
    row = layout.row(align=True)
    row.operator("domeanimatic.build_info", icon='DESKTOP', text="")
    row.operator("domeanimatic.build_info")
    row.operator("domeanimatic.reload_addon",  text="", icon='FILE_REFRESH')
    row.prop(g, "show_labels", text="", toggle=True, icon='INFO')
    row.operator("domeanimatic.clear_console", text="", icon='TRASH')

    if not g.show_labels:
        return

    layout.separator(factor=0.3)

    # Debug row: console + module toggles
    row2 = layout.row(align=True)
    row2.operator("domeanimatic.toggle_console", text="Console", icon='CONSOLE')

    layout.separator(factor=0.2)

    row3 = layout.row(align=True)
    row3.label(text="Modules:")
    for m in module_manager.ALL_MODULES:
        sub = row3.row(align=True)
        sub.active_default = module_manager.is_loaded(m["name"])
        sub.operator(m["op"], text=m["name"].replace("_", " ").capitalize(),
                     icon=m["icon"])

    layout.separator(factor=0.3)

    col = layout.column(align=True)
    col.prop(sp(context.scene), "target_material", text="")
    try:
        col.operator("domeanimatic.debug_node_sockets", text="", icon='INFO')
    except Exception:
        pass


def _draw_main(self, context):
    pass  # module sub-panels attach here via bl_parent_id


# ── Infos panels ──────────────────────────────────────────────────────────────

class DOMEANIMATIC_PT_infos(bpy.types.Panel):
    bl_label       = "Infos"
    bl_idname      = "DOMEANIMATIC_PT_infos"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_order       = 0
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_infos


class DOMEANIMATIC_PT_infos_ie(bpy.types.Panel):
    bl_label       = "Infos"
    bl_idname      = "DOMEANIMATIC_PT_infos_ie"
    bl_space_type  = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_order       = 0
    bl_options     = {'DEFAULT_CLOSED'}
    draw           = _draw_infos


# ── Main parent panels ────────────────────────────────────────────────────────

class DOMEANIMATIC_PT_main(bpy.types.Panel):
    bl_label       = "DomeAnimatic"
    bl_idname      = "DOMEANIMATIC_PT_main"
    bl_space_type  = 'VIEW_3D'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_order       = 1
    draw           = _draw_main


class DOMEANIMATIC_PT_main_ie(bpy.types.Panel):
    bl_label       = "DomeAnimatic"
    bl_idname      = "DOMEANIMATIC_PT_main_ie"
    bl_space_type  = 'IMAGE_EDITOR'
    bl_region_type = 'UI'
    bl_category    = "DomeAnimatic"
    bl_order       = 1
    draw           = _draw_main


# ── Register ──────────────────────────────────────────────────────────────────

CLASSES = [
    DOMEANIMATIC_PT_infos,
    DOMEANIMATIC_PT_main,
    DOMEANIMATIC_PT_infos_ie,
    DOMEANIMATIC_PT_main_ie,
]


def register():
    for cls in CLASSES:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(CLASSES):
        bpy.utils.unregister_class(cls)

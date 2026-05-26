"""
global_scene_shared_props.py — Centralized Blender property definitions.

Two PropertyGroups replace all the old flat bpy.types.WindowManager.domeanimatic_*
and bpy.types.Scene.domeanimatic_* registrations:

  DOMEANIMATICGlobalProps  →  WindowManager.domeanimatic  (survives scene switch)
  DOMEANIMATICSceneProps   →  Scene.domeanimatic          (per-scene data)

All modules access shared state through the gp() and sp() accessors.
"""

import bpy


# ── Active cel change callback ────────────────────────────────────────────────

def _on_active_cel_changed(self, context):
    """Switch every open Image Editor to the newly selected cel datablock."""
    from . import cel_store
    layer = cel_store.BY_SLOT.get(self.active_cel)
    if layer is None:
        return
    img = bpy.data.images.get(layer.datablock_name)
    if img is None:
        return
    for window in bpy.data.window_managers[0].windows:
        for area in window.screen.areas:
            if area.type == 'IMAGE_EDITOR':
                for space in area.spaces:
                    if space.type == 'IMAGE_EDITOR':
                        space.image = img
                        area.tag_redraw()


# ── Camera zoom callback (used by collage_collection module) ──────────────────

def _on_camera_zoom_changed(self, context):
    cam = context.scene.camera
    if cam and cam.data and cam.data.type == 'ORTHO':
        cam.data.ortho_scale = self.camera_zoom
    bpy.data.window_managers[0].domeanimatic.last_camera_zoom = self.camera_zoom


# ── Global PropertyGroup (WindowManager) ──────────────────────────────────────

class DOMEANIMATICGlobalProps(bpy.types.PropertyGroup):
    """Stored on WindowManager — persists across scene switches."""

    show_labels: bpy.props.BoolProperty(
        name="Show Development Infos",
        default=False,
    )
    target_material: bpy.props.PointerProperty(
        name="Dome Animatic Material",
        description="The single Dome Animatic material shared across all scenes",
        type=bpy.types.Material,
    )
    synch_mode: bpy.props.EnumProperty(
        name="Sync Mode",
        items=[
            ('BAKED',      "Synch to Baked",      "Channel 1 only -> LiveDomePreview"),
            ('CEL_LAYERS', "Synch to Cel-layers",  "Channels 2/3/4 -> BG/Cel_A/Cel_B"),
            ('OFF',        "Off",                  "No sync"),
        ],
        default='OFF',
    )
    last_camera_zoom: bpy.props.FloatProperty(
        name="Last Camera Zoom",
        default=3.055, min=0.01, max=1000.0,
    )
    cel_folder: bpy.props.StringProperty(
        name="Cel Folder",
        description="Folder for transparent cel PNGs (relative to .blend file)",
        default="//transparent-cels-paintings",
        subtype='DIR_PATH',
    )
    active_cel: bpy.props.EnumProperty(
        name="Active Cel",
        description="Which cel slot is active in the Image Editor for painting",
        items=[
            ('BG',    "BG",    "Background — VSE channel 2"),
            ('CEL_A', "Cel A", "Cel A — VSE channel 3"),
            ('CEL_B', "Cel B", "Cel B — VSE channel 4"),
        ],
        default='CEL_A',
        update=_on_active_cel_changed,
    )
    mat_nodes_expanded: bpy.props.BoolProperty(
        name="Material Nodes Expanded",
        default=False,
    )

    # Texture resolution settings (used by live_texture_prepare operator)
    tex_width: bpy.props.IntProperty(
        name="Width",  default=960,  min=1, max=7680,
    )
    tex_height: bpy.props.IntProperty(
        name="Height", default=590,  min=1, max=4320,
    )
    tex_scale: bpy.props.FloatProperty(
        name="Scale",  default=1.0,  min=0.0, max=2.0, step=10, precision=2,
    )

    # Per-slot: BG
    bg_visible:   bpy.props.BoolProperty(name="BG Visible",   default=True)
    bg_opacity:   bpy.props.FloatProperty(name="BG Opacity",  default=1.0, min=0.0, max=1.0, subtype='FACTOR')
    bg_filepath:  bpy.props.StringProperty(name="BG Filepath", default="", subtype='FILE_PATH')
    bg_mat_image: bpy.props.PointerProperty(name="BG Material Image", type=bpy.types.Image)

    # Per-slot: CEL_A
    cel_a_visible:   bpy.props.BoolProperty(name="Cel A Visible",   default=True)
    cel_a_opacity:   bpy.props.FloatProperty(name="Cel A Opacity",  default=1.0, min=0.0, max=1.0, subtype='FACTOR')
    cel_a_filepath:  bpy.props.StringProperty(name="Cel A Filepath", default="", subtype='FILE_PATH')
    cel_a_mat_image: bpy.props.PointerProperty(name="Cel A Material Image", type=bpy.types.Image)

    # Per-slot: CEL_B
    cel_b_visible:   bpy.props.BoolProperty(name="Cel B Visible",   default=True)
    cel_b_opacity:   bpy.props.FloatProperty(name="Cel B Opacity",  default=1.0, min=0.0, max=1.0, subtype='FACTOR')
    cel_b_filepath:  bpy.props.StringProperty(name="Cel B Filepath", default="", subtype='FILE_PATH')
    cel_b_mat_image: bpy.props.PointerProperty(name="Cel B Material Image", type=bpy.types.Image)


# ── Scene PropertyGroup ───────────────────────────────────────────────────────

class DOMEANIMATICSceneProps(bpy.types.PropertyGroup):
    """Stored on Scene — per-scene data."""

    synch_active:          bpy.props.BoolProperty(name="Synch Active", default=False)
    collage_expanded:      bpy.props.BoolProperty(name="Collage Expanded", default=False)
    manual_scene_expanded: bpy.props.BoolProperty(name="Scene List Expanded", default=False)

    target_object:   bpy.props.PointerProperty(name="Target Object",   type=bpy.types.Object)
    target_material: bpy.props.PointerProperty(name="Target Material", type=bpy.types.Material)
    target_image:    bpy.props.PointerProperty(name="Target Image",    type=bpy.types.Image)

    # Collage camera zoom (persisted per-scene; carried over by last_camera_zoom)
    camera_zoom: bpy.props.FloatProperty(
        name="Camera Zoom",
        description="Orthographic scale carried between collage scenes",
        default=3.055, min=0.01, max=1000.0, step=10, precision=3,
        update=_on_camera_zoom_changed,
    )

    # Fade / color A
    color_a_value:      bpy.props.FloatProperty(name="Color A Value", default=0.0, min=0.0, max=1.0, precision=3)
    color_a_strip_name: bpy.props.StringProperty(name="Color A Strip", default="to_black")
    color_a_color:      bpy.props.FloatVectorProperty(name="Color A", subtype='COLOR',
                                                      default=(0.0, 0.0, 0.0), min=0.0, max=1.0)

    # Fade / color B
    color_b_value:      bpy.props.FloatProperty(name="Color B Value", default=0.0, min=0.0, max=1.0, precision=3)
    color_b_strip_name: bpy.props.StringProperty(name="Color B Strip", default="to_white")
    color_b_color:      bpy.props.FloatVectorProperty(name="Color B", subtype='COLOR',
                                                      default=(1.0, 1.0, 1.0), min=0.0, max=1.0)

    delete_color:  bpy.props.FloatVectorProperty(name="Fill Color", subtype='COLOR',
                                                  default=(0.0, 0.0, 0.0), min=0.0, max=1.0)
    layer_spacing: bpy.props.FloatProperty(name="Layer Spacing", default=0.001,
                                           min=0.0, max=1.0, precision=3, step=1)
    layer_expanded: bpy.props.BoolProperty(name="Layer Mgmt Expanded", default=False)


# ── Accessors ─────────────────────────────────────────────────────────────────

def gp(context=None) -> DOMEANIMATICGlobalProps:
    """Global props from WindowManager — call from any module."""
    wm = context.window_manager if context else bpy.data.window_managers[0]
    return wm.domeanimatic


def sp(scene=None) -> DOMEANIMATICSceneProps:
    """Scene props — defaults to bpy.context.scene."""
    s = scene or bpy.context.scene
    return s.domeanimatic


# ── Register ──────────────────────────────────────────────────────────────────

def register():
    bpy.utils.register_class(DOMEANIMATICGlobalProps)
    bpy.utils.register_class(DOMEANIMATICSceneProps)
    bpy.types.WindowManager.domeanimatic = bpy.props.PointerProperty(
        type=DOMEANIMATICGlobalProps)
    bpy.types.Scene.domeanimatic = bpy.props.PointerProperty(
        type=DOMEANIMATICSceneProps)


def unregister():
    if hasattr(bpy.types.WindowManager, 'domeanimatic'):
        del bpy.types.WindowManager.domeanimatic
    if hasattr(bpy.types.Scene, 'domeanimatic'):
        del bpy.types.Scene.domeanimatic
    bpy.utils.unregister_class(DOMEANIMATICSceneProps)
    bpy.utils.unregister_class(DOMEANIMATICGlobalProps)

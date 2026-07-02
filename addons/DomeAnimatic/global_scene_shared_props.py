"""
global_scene_shared_props.py — Centralized Blender property definitions.

Two PropertyGroups:

  DOMEANIMATICGlobalProps  →  WindowManager.domeanimatic  (UI-only, NOT saved)
  DOMEANIMATICSceneProps   →  Scene.domeanimatic          (per-scene data, saved in .blend)

All modules access shared state through the gp() and sp() accessors.

Properties that must survive file reopen live on Scene (sp()):
  target_material, synch_mode, tex_width/height/scale, cel_folder, *_mat_image.

Properties that are fine resetting on restart live on WindowManager (gp()):
  active_cel, dome_object, mat_nodes_expanded, visibility/opacity, etc.
"""

import bpy


# ── Active cel change callback ────────────────────────────────────────────────

def _on_active_cel_changed(self, context):
    """Switch every open Image Editor to the newly selected cel datablock.
    In CEL_LAYERS mode also makes the matching TEX_IMAGE node active and
    sets the scene paint canvas."""
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
    # synch_mode and target_material are now on Scene props
    scene      = (context.scene if context else None) or bpy.context.scene
    scene_prop = scene.domeanimatic
    if scene_prop.synch_mode != 'CEL_LAYERS':
        return
    mat = scene_prop.target_material
    if mat is not None and mat.use_nodes:
        for node in mat.node_tree.nodes:
            if node.type == 'TEX_IMAGE' and node.image == img:
                mat.node_tree.nodes.active = node
                break
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is not None:
        try:
            dome_scene.tool_settings.image_paint.canvas = img
        except Exception:
            pass


# ── Synch mode change callback ────────────────────────────────────────────────

def _on_synch_mode_changed(self, context):
    """Redirect Image Editors (and 3D paint canvas in CEL_LAYERS) when the
    sync mode is switched.  Also applies VSE track muting and material Menu
    Switch so prop_enum in any panel has the same effect as the operator.
    self = DOMEANIMATICSceneProps; active_cel lives on WindowManager."""
    from . import cel_store
    mode = self.synch_mode

    if mode == 'BAKED':
        live_img = cel_store.get_live_image()
        if live_img is not None:
            for window in bpy.data.window_managers[0].windows:
                for area in window.screen.areas:
                    if area.type == 'IMAGE_EDITOR':
                        for space in area.spaces:
                            if space.type == 'IMAGE_EDITOR':
                                space.image = live_img
                                area.tag_redraw()
            # Activate LiveDomePreview node in material so paint header shows it
            mat = self.target_material
            if mat is not None and mat.use_nodes:
                for node in mat.node_tree.nodes:
                    if node.type == 'TEX_IMAGE' and node.image == live_img:
                        mat.node_tree.nodes.active = node
                        break
            # Set paint canvas and enter Texture Paint on dome object (task 11)
            dome_scene = bpy.data.scenes.get("Dome Animatic")
            if dome_scene:
                try:
                    dome_scene.tool_settings.image_paint.canvas = live_img
                except Exception:
                    pass
            dome_obj = self.dome_object
            if dome_obj and dome_scene:
                try:
                    wm = bpy.data.window_managers[0]
                    for window in wm.windows:
                        for area in window.screen.areas:
                            if area.type == 'VIEW_3D':
                                for region in area.regions:
                                    if region.type == 'WINDOW':
                                        with context.temp_override(window=window,
                                                                   area=area,
                                                                   region=region):
                                            vl = context.view_layer
                                            for obj in vl.objects:
                                                obj.select_set(False)
                                            dome_obj.select_set(True)
                                            vl.objects.active = dome_obj
                                            bpy.ops.object.mode_set(mode='TEXTURE_PAINT')
                                        break  # first VIEW_3D only
                                else:
                                    continue
                                break
                        else:
                            continue
                        break
                except Exception:
                    pass
    elif mode == 'CEL_LAYERS':
        # active_cel is still on WindowManager (UI state)
        active_cel = bpy.data.window_managers[0].domeanimatic.active_cel
        layer      = cel_store.BY_SLOT.get(active_cel)
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
        mat = self.target_material
        if mat is not None and mat.use_nodes:
            for node in mat.node_tree.nodes:
                if node.type == 'TEX_IMAGE' and node.image == img:
                    mat.node_tree.nodes.active = node
                    break
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is not None:
            try:
                dome_scene.tool_settings.image_paint.canvas = img
            except Exception:
                pass
        # Align shader opacity with the current per-slot UI state
        sync_cel_layers_to_material(context)

    # Leaving any mode clears the painting-on-baked guard so scrubbing resumes
    try:
        from .modules.live_texture import vse_sync as _vse_sync
        _vse_sync._s.painting_baked = False
        _vse_sync._apply_track_muting_by_mode(mode)
    except Exception:
        pass
    try:
        from .modules.live_texture.live_texture_ops import _set_menu_switch
        socket = 'Cels' if mode == 'CEL_LAYERS' else 'Baked'
        _set_menu_switch(self, socket)
    except Exception:
        pass


# ── Cel layer visibility/opacity callback ─────────────────────────────────────

def sync_cel_layers_to_material(context=None) -> None:
    """Push per-slot visibility*opacity into the cel-mix node group of the
    target material so the shader matches the Image Editor composite.
    The group exposes one '<layer>.opacity' input per cel slot."""
    g     = gp(context)
    scene = (context.scene if context else None) or bpy.context.scene
    mat   = scene.domeanimatic.target_material
    if mat is None:
        for name in ("Dome_Animatic", "Dome Animatic", "DomeAnimatic"):
            mat = bpy.data.materials.get(name)
            if mat:
                break
    if mat is None or not mat.use_nodes:
        return
    group = None
    for node in mat.node_tree.nodes:
        if node.type == 'GROUP' and 'Cel_A.opacity' in node.inputs:
            group = node
            break
    if group is None:
        return
    for slot_key, sock in (('bg',    'Cel_BG.opacity'),
                           ('cel_a', 'Cel_A.opacity'),
                           ('cel_b', 'Cel_B.opacity')):
        inp = group.inputs.get(sock)
        if inp is None:
            continue
        visible = getattr(g, f"{slot_key}_visible", True)
        value   = float(getattr(g, f"{slot_key}_opacity", 1.0)) if visible else 0.0
        if inp.default_value != value:
            inp.default_value = value


def _on_cel_layer_prop_changed(self, context):
    """Visibility eye / opacity slider changed — refresh the Image Editor
    composite live and mirror the value into the material shader."""
    sync_cel_layers_to_material(context)
    try:
        from . import vse_helpers
        vse_helpers.tag_all_image_editors_redraw()
    except Exception:
        pass


# ── Global PropertyGroup (WindowManager) ──────────────────────────────────────

class DOMEANIMATICGlobalProps(bpy.types.PropertyGroup):
    """Stored on WindowManager — UI state only, NOT saved in .blend.
    Reset to defaults on every file open; that is intentional."""

    show_labels: bpy.props.BoolProperty(
        name="Show Development Infos",
        default=False,
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
    synch_expanded: bpy.props.BoolProperty(
        name="Synch Section Expanded",
        default=True,
    )

    # Per-slot visibility/opacity/filepath — pure UI state, OK to reset on reload.
    # visible/opacity updates propagate to Image Editor overlay + material shader.
    bg_visible:  bpy.props.BoolProperty(name="BG Visible",   default=True,
                                        update=_on_cel_layer_prop_changed)
    bg_opacity:  bpy.props.FloatProperty(name="BG Opacity",  default=1.0, min=0.0, max=1.0,
                                         subtype='FACTOR', update=_on_cel_layer_prop_changed)
    bg_filepath: bpy.props.StringProperty(name="BG Filepath", default="", subtype='FILE_PATH')

    cel_a_visible:  bpy.props.BoolProperty(name="Cel A Visible",   default=True,
                                           update=_on_cel_layer_prop_changed)
    cel_a_opacity:  bpy.props.FloatProperty(name="Cel A Opacity",  default=1.0, min=0.0, max=1.0,
                                            subtype='FACTOR', update=_on_cel_layer_prop_changed)
    cel_a_filepath: bpy.props.StringProperty(name="Cel A Filepath", default="", subtype='FILE_PATH')

    cel_b_visible:  bpy.props.BoolProperty(name="Cel B Visible",   default=True,
                                           update=_on_cel_layer_prop_changed)
    cel_b_opacity:  bpy.props.FloatProperty(name="Cel B Opacity",  default=1.0, min=0.0, max=1.0,
                                            subtype='FACTOR', update=_on_cel_layer_prop_changed)
    cel_b_filepath: bpy.props.StringProperty(name="Cel B Filepath", default="", subtype='FILE_PATH')


# ── Scene PropertyGroup ───────────────────────────────────────────────────────

class DOMEANIMATICSceneProps(bpy.types.PropertyGroup):
    """Stored on Scene — per-scene data, saved in .blend."""

    synch_active:          bpy.props.BoolProperty(name="Synch Active", default=False)
    manual_scene_expanded: bpy.props.BoolProperty(name="Scene List Expanded", default=False)

    target_object:   bpy.props.PointerProperty(name="Target Object",   type=bpy.types.Object)
    target_image:    bpy.props.PointerProperty(name="Target Image",    type=bpy.types.Image)

    # ── Moved from WindowManager so they survive file reopen ──────────────────
    dome_object: bpy.props.PointerProperty(
        name="Dome Object",
        description="The mesh object to enter Texture Paint on when activating a cel slot",
        type=bpy.types.Object,
    )
    target_material: bpy.props.PointerProperty(
        name="Dome Animatic Material",
        description="The single Dome Animatic material used by this scene",
        type=bpy.types.Material,
    )
    synch_mode: bpy.props.EnumProperty(
        name="Sync Mode",
        items=[
            ('BAKED',      "Synch to Baked",     "Channel 1 only -> LiveDomePreview"),
            ('CEL_LAYERS', "Synch to Cel-layers", "Channels 2/3/4 -> BG/Cel_A/Cel_B"),
            ('OFF',        "Off",                 "No sync"),
        ],
        default='OFF',
        update=_on_synch_mode_changed,
    )
    cel_folder: bpy.props.StringProperty(
        name="Cel Folder",
        description="Folder for transparent cel PNGs (relative to .blend file)",
        default="//transparent-cels-paintings",
        subtype='DIR_PATH',
    )
    tex_width: bpy.props.IntProperty(
        name="Width",  default=960, min=1, max=7680,
    )
    tex_height: bpy.props.IntProperty(
        name="Height", default=590, min=1, max=4320,
    )
    tex_scale: bpy.props.FloatProperty(
        name="Scale",  default=1.0, min=0.0, max=2.0, step=10, precision=2,
    )
    cel_auto_save: bpy.props.BoolProperty(
        name="Auto-save on strip change",
        description="Silently save dirty cel images when the playhead crosses a strip boundary during playback",
        default=False,
    )

    # Node image pointers — survive file reopen as long as the Image datablock exists
    bg_mat_image:    bpy.props.PointerProperty(name="BG Material Image",    type=bpy.types.Image)
    cel_a_mat_image: bpy.props.PointerProperty(name="Cel A Material Image", type=bpy.types.Image)
    cel_b_mat_image: bpy.props.PointerProperty(name="Cel B Material Image", type=bpy.types.Image)

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

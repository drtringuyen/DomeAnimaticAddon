import bpy


def register():
    # ── Show dev info labels — on WindowManager so it persists ────────────────
    bpy.types.WindowManager.domeanimatic_show_labels = bpy.props.BoolProperty(
        name="Show Development Infos",
        description="Show status and info labels in all panels",
        default=False,
    )

    # ── Target material for LiveDomePreview relink — on WindowManager so it
    # never changes on scene switch ───────────────────────────────────────────
    bpy.types.WindowManager.domeanimatic_target_material = bpy.props.PointerProperty(
        name="Target Material",
        description="Material to relink LiveDomePreview into",
        type=bpy.types.Material,
    )

    # ── Target object/material/image for collage scene — per scene ────────────
    bpy.types.Scene.domeanimatic_target_object = bpy.props.PointerProperty(
        name="Target Object",
        description="Object whose material will receive the collage image",
        type=bpy.types.Object,
    )

    bpy.types.Scene.domeanimatic_target_material = bpy.props.PointerProperty(
        name="Target Material",
        description="Material of the collage scene image plane",
        type=bpy.types.Material,
    )

    bpy.types.Scene.domeanimatic_target_image = bpy.props.PointerProperty(
        name="Target Image",
        description="Image assigned to the collage material texture node",
        type=bpy.types.Image,
    )

    # ── VSE synch state ───────────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_synch_active = bpy.props.BoolProperty(
        name="Synch Active",
        default=False,
    )

    # ── Collage panel states ──────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_collage_expanded = bpy.props.BoolProperty(
        name="Collage Scene Expanded",
        default=False,
    )
    bpy.types.Scene.domeanimatic_manual_scene_expanded = bpy.props.BoolProperty(
        name="Scene List Expanded",
        default=False,
    )

    # ── Fade to Color ─────────────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_fade_value = bpy.props.FloatProperty(
        name="Fade Value",
        description="Current blend opacity of the fade strip (read from VSE)",
        default=0.0,
        min=0.0,
        max=1.0,
        precision=3,
    )
    bpy.types.Scene.domeanimatic_fade_strip_name = bpy.props.StringProperty(
        name="Fade Strip Name",
        description="Name of the color strip to track for fade",
        default="to_black",
    )
    bpy.types.Scene.domeanimatic_fade_color = bpy.props.FloatVectorProperty(
        name="Fade Color",
        description="Color of the fade strip",
        subtype='COLOR',
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
    )

    # ── Delete/fill color ─────────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_delete_color = bpy.props.FloatVectorProperty(
        name="Fill Color",
        description="Color used for the DELETE material fill",
        subtype='COLOR',
        default=(0.0, 0.0, 0.0),
        min=0.0,
        max=1.0,
    )

    # ── Layer spacing ─────────────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_layer_spacing = bpy.props.FloatProperty(
        name="Layer Spacing",
        description="Spacing between layers",
        default=0.001,
        min=0.0,
        max=1.0,
        precision=3,
        step=1,
    )

    # ── Layer management panel expanded state ─────────────────────────────────
    bpy.types.Scene.domeanimatic_layer_expanded = bpy.props.BoolProperty(
        name="Layer Management Expanded",
        default=False,
    )

    # ── Camera zoom carried over between scenes ───────────────────────────────
    bpy.types.WindowManager.domeanimatic_last_camera_zoom = bpy.props.FloatProperty(
        name="Last Camera Zoom",
        default=3.055,
        min=0.01,
        max=1000.0,
    )


def unregister():
    del bpy.types.WindowManager.domeanimatic_last_camera_zoom
    del bpy.types.WindowManager.domeanimatic_target_material
    del bpy.types.Scene.domeanimatic_manual_scene_expanded
    del bpy.types.Scene.domeanimatic_collage_expanded
    del bpy.types.Scene.domeanimatic_synch_active
    del bpy.types.Scene.domeanimatic_layer_spacing
    del bpy.types.Scene.domeanimatic_layer_expanded
    del bpy.types.Scene.domeanimatic_delete_color
    del bpy.types.Scene.domeanimatic_fade_value
    del bpy.types.Scene.domeanimatic_fade_strip_name
    del bpy.types.Scene.domeanimatic_fade_color
    del bpy.types.Scene.domeanimatic_target_image
    del bpy.types.Scene.domeanimatic_target_object
    del bpy.types.Scene.domeanimatic_target_material
    del bpy.types.WindowManager.domeanimatic_show_labels

import bpy





def register():

    # ── Dev labels ────────────────────────────────────────────────────────────
    bpy.types.WindowManager.domeanimatic_show_labels = bpy.props.BoolProperty(
        name="Show Development Infos",
        default=False,
    )

    # ── Dome Animatic material (global, survives scene switch) ────────────────
    bpy.types.WindowManager.domeanimatic_target_material = bpy.props.PointerProperty(
        name="Dome Animatic Material",
        description="The single Dome Animatic material — shared across all scenes",
        type=bpy.types.Material,
    )

    # ── VSE sync mode (replaces old synch_active bool) ────────────────────────
    bpy.types.WindowManager.domeanimatic_synch_mode = bpy.props.EnumProperty(
        name="Sync Mode",
        description="Which VSE tracks to sync to live image datablocks",
        items=[
            ('BAKED',      "Synch to Baked",      "Track 1 only → LiveDomePreview"),
            ('CEL_LAYERS', "Synch to Cel-layers",  "Tracks 2/3/4 → BG/Cel_A/Cel_B"),
            ('OFF',        "Off",                  "No sync"),
        ],
        default='OFF',
    )

    # ── Per-scene synch_active (kept for backward compat, driven by mode) ─────
    bpy.types.Scene.domeanimatic_synch_active = bpy.props.BoolProperty(
        name="Synch Active",
        default=False,
    )

    # ── Collage scene panel states ────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_collage_expanded = bpy.props.BoolProperty(
        name="Collage Scene Expanded",
        default=False,
    )
    bpy.types.Scene.domeanimatic_manual_scene_expanded = bpy.props.BoolProperty(
        name="Scene List Expanded",
        default=False,
    )

    # ── Collage target object / material / image — per scene ─────────────────
    bpy.types.Scene.domeanimatic_target_object = bpy.props.PointerProperty(
        name="Target Object", type=bpy.types.Object,
    )
    bpy.types.Scene.domeanimatic_target_material = bpy.props.PointerProperty(
        name="Target Material", type=bpy.types.Material,
    )
    bpy.types.Scene.domeanimatic_target_image = bpy.props.PointerProperty(
        name="Target Image", type=bpy.types.Image,
    )

    # ── Fade Color A ──────────────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_color_a_value = bpy.props.FloatProperty(
        name="Color A Value", default=0.0, min=0.0, max=1.0, precision=3,
    )
    bpy.types.Scene.domeanimatic_color_a_strip_name = bpy.props.StringProperty(
        name="Color A Strip Name", default="to_black",
    )
    bpy.types.Scene.domeanimatic_color_a_color = bpy.props.FloatVectorProperty(
        name="Color A", subtype='COLOR', default=(0.0, 0.0, 0.0), min=0.0, max=1.0,
    )

    # ── Fade Color B ──────────────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_color_b_value = bpy.props.FloatProperty(
        name="Color B Value", default=0.0, min=0.0, max=1.0, precision=3,
    )
    bpy.types.Scene.domeanimatic_color_b_strip_name = bpy.props.StringProperty(
        name="Color B Strip Name", default="to_white",
    )
    bpy.types.Scene.domeanimatic_color_b_color = bpy.props.FloatVectorProperty(
        name="Color B", subtype='COLOR', default=(1.0, 1.0, 1.0), min=0.0, max=1.0,
    )

    # ── Delete / fill color ───────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_delete_color = bpy.props.FloatVectorProperty(
        name="Fill Color", subtype='COLOR', default=(0.0, 0.0, 0.0), min=0.0, max=1.0,
    )

    # ── Layer spacing ─────────────────────────────────────────────────────────
    bpy.types.Scene.domeanimatic_layer_spacing = bpy.props.FloatProperty(
        name="Layer Spacing", default=0.001, min=0.0, max=1.0, precision=3, step=1,
    )
    bpy.types.Scene.domeanimatic_layer_expanded = bpy.props.BoolProperty(
        name="Layer Management Expanded", default=False,
    )

    # ── Camera zoom ───────────────────────────────────────────────────────────
    bpy.types.WindowManager.domeanimatic_last_camera_zoom = bpy.props.FloatProperty(
        name="Last Camera Zoom", default=3.055, min=0.01, max=1000.0,
    )

    # ── Cel system — folder (global, relative to blend file) ─────────────────
    bpy.types.WindowManager.domeanimatic_cel_folder = bpy.props.StringProperty(
        name="Cel Folder",
        description="Folder where transparent cel PNGs are saved/loaded (relative to .blend)",
        default="//transparent-cels-paintings",
        subtype='DIR_PATH',
    )

    # ── Cel system — active cel selection ────────────────────────────────────
    bpy.types.WindowManager.domeanimatic_active_cel = bpy.props.EnumProperty(
        name="Active Cel",
        description="Which cel is active in the Image Editor for painting",
        items=[
            ('BG',    "BG",    "Background — VSE channel 2"),
            ('CEL_A', "Cel A", "Cel A — VSE channel 3"),
            ('CEL_B', "Cel B", "Cel B — VSE channel 4"),
        ],
        default='CEL_A',
    )

    # ── Cel system — per-slot props (BG / CEL_A / CEL_B) ─────────────────────
    # Each slot: visible (bool), opacity (float), filepath (str on disk),
    #            mat_image (Image pointer → the material's tex node image)

    for slot in ('bg', 'cel_a', 'cel_b'):
        setattr(bpy.types.WindowManager, f"domeanimatic_{slot}_visible",
            bpy.props.BoolProperty(
                name=f"{slot.upper()} Visible",
                description=f"Show {slot} layer in GPU overlay",
                default=True,
            ))
        setattr(bpy.types.WindowManager, f"domeanimatic_{slot}_opacity",
            bpy.props.FloatProperty(
                name=f"{slot.upper()} Opacity",
                default=1.0, min=0.0, max=1.0, subtype='FACTOR',
            ))
        setattr(bpy.types.WindowManager, f"domeanimatic_{slot}_filepath",
            bpy.props.StringProperty(
                name=f"{slot.upper()} Filepath",
                description=f"Path to the {slot} PNG on disk",
                default="",
                subtype='FILE_PATH',
            ))
        # Image pointer for the Dome Animatic material's tex node for this slot
        setattr(bpy.types.WindowManager, f"domeanimatic_{slot}_mat_image",
            bpy.props.PointerProperty(
                name=f"{slot.upper()} Material Image",
                description=(
                    f"Image Texture node image in the Dome Animatic material "
                    f"assigned to the {slot} slot. Link this once; the sync "
                    f"handler updates it every frame."
                ),
                type=bpy.types.Image,
            ))


def unregister():
    for slot in ('bg', 'cel_a', 'cel_b'):
        for suffix in ('visible', 'opacity', 'filepath', 'mat_image'):
            attr = f"domeanimatic_{slot}_{suffix}"
            if hasattr(bpy.types.WindowManager, attr):
                delattr(bpy.types.WindowManager, attr)

    for attr in (
        'domeanimatic_active_cel',
        'domeanimatic_cel_folder',
        'domeanimatic_synch_mode',
        'domeanimatic_last_camera_zoom',
        'domeanimatic_target_material',
        'domeanimatic_show_labels',
    ):
        if hasattr(bpy.types.WindowManager, attr):
            delattr(bpy.types.WindowManager, attr)

    for attr in (
        'domeanimatic_manual_scene_expanded',
        'domeanimatic_collage_expanded',
        'domeanimatic_synch_active',
        'domeanimatic_layer_spacing',
        'domeanimatic_layer_expanded',
        'domeanimatic_delete_color',
        'domeanimatic_color_a_value',
        'domeanimatic_color_a_strip_name',
        'domeanimatic_color_a_color',
        'domeanimatic_color_b_value',
        'domeanimatic_color_b_strip_name',
        'domeanimatic_color_b_color',
        'domeanimatic_target_image',
        'domeanimatic_target_object',
        'domeanimatic_target_material',
    ):
        if hasattr(bpy.types.Scene, attr):
            delattr(bpy.types.Scene, attr)

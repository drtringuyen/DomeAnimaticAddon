bl_info = {
    "name": "DomeAnimatic",
    "author": "Your Name",
    "version": (1, 4, 0),
    "blender": (5, 1, 0),
    "location": "Sidebar > DomeAnimatic",
    "description": "DomeAnimatic addon",
    "category": "Animation",
}

from . import (
    utils,
    properties,
    manage_live_dome_preview,
    prepare_live_dome_texture,
    synch_VSE_to_LiveDomePreview,
    capture_current_frame,
    collage_texture,
    prepare_collage_scene,
    color_palette,
    collage_manipulation,
    transparent_cel,
    transparent_cel_managment,
    frame_snap_shot,
    fade_in_fade_out,
    panels,
)

def register():
    print("\n" + "="*70)
    print(f"[DomeAnimatic v{'.'.join(str(v) for v in bl_info['version'])}] Registering...")
    print("="*70)
    properties.register()
    manage_live_dome_preview.register()
    prepare_live_dome_texture.register()
    synch_VSE_to_LiveDomePreview.register()
    capture_current_frame.register()
    collage_texture.register()
    prepare_collage_scene.register()
    color_palette.register()
    collage_manipulation.register()
    transparent_cel_managment.register()   # registers transparent_cel inside
    frame_snap_shot.register()
    fade_in_fade_out.register()
    panels.register()
    print("[DomeAnimatic] ✅ Loaded.")
    print("="*70 + "\n")

def unregister():
    panels.unregister()
    fade_in_fade_out.unregister()
    frame_snap_shot.unregister()
    transparent_cel_managment.unregister()  # unregisters transparent_cel inside
    collage_manipulation.unregister()
    color_palette.unregister()
    prepare_collage_scene.unregister()
    collage_texture.unregister()
    capture_current_frame.unregister()
    synch_VSE_to_LiveDomePreview.unregister()
    prepare_live_dome_texture.unregister()
    manage_live_dome_preview.unregister()
    properties.unregister()

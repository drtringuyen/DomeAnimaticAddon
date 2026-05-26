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
    global_scene_shared_props,
    cel_store,
    vse_helpers,
    infos,
    panels,
    module_manager,
)


def register():
    print("\n" + "=" * 70)
    print(f"[DomeAnimatic v{'.'.join(str(v) for v in bl_info['version'])}] Registering...")
    print("=" * 70)
    global_scene_shared_props.register()
    infos.register()
    panels.register()
    module_manager.load_all()
    print("[DomeAnimatic] Loaded.")
    print("=" * 70 + "\n")


def unregister():
    module_manager.unload_all()
    panels.unregister()
    infos.unregister()
    global_scene_shared_props.unregister()

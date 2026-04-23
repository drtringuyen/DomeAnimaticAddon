import bpy
import os
from bpy.app.handlers import persistent
from . import utils

# Cache last loaded path to avoid redundant reloads
_last_loaded_path = ""

# Flag to block handler during collage render
_handler_blocked = False

# Cache last known Dome Animatic frame to detect changes
_last_dome_frame = -1


# ── Handler: image sync (frame_change_pre on Dome Animatic) ───────────────────

@persistent
def dome_live_preview_handler(scene, depsgraph=None):
    """Fired by frame_change_pre — only processes Dome Animatic."""
    global _last_loaded_path, _handler_blocked

    if _handler_blocked:
        return

    # Always read from Dome Animatic directly
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return

    frame = dome_scene.frame_current
    strip = utils.get_active_strip_at_frame(dome_scene, frame)

    if strip is None:
        return

    path = utils.resolve_strip_image_path(strip, frame)
    if not path or not os.path.exists(path):
        return

    if path == _last_loaded_path:
        return

    live_img = utils.get_or_create_live_image()

    if live_img.packed_file is not None:
        live_img.unpack(method='USE_ORIGINAL')

    try:
        rel_path = bpy.path.relpath(path)
    except ValueError:
        rel_path = path

    live_img.filepath = rel_path
    live_img.source   = 'FILE'
    live_img.reload()
    _last_loaded_path = path
    utils.log(f"[DomeLivePreview] Loaded: {path}")


# ── Handler: playhead sync (depsgraph_update_post) ────────────────────────────

@persistent
def dome_playhead_sync_handler(scene, depsgraph=None):
    """
    Syncs all collage scene playheads to Dome Animatic's frame.
    Uses depsgraph_update_post to catch animated strip evaluation.
    Guards against interfering with scrubbing via _last_dome_frame cache.
    """
    global _last_dome_frame, _handler_blocked

    if _handler_blocked:
        return

    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return

    dome_frame = dome_scene.frame_current

    # Only act when frame actually changed
    if dome_frame == _last_dome_frame:
        return

    _last_dome_frame = dome_frame

    utils.log(f"[PlayheadSync] Dome frame → {dome_frame}")

    # Push to all collage scenes without triggering recursion
    for s in bpy.data.scenes:
        if s is not dome_scene and s.frame_current != dome_frame:
            s.frame_current = dome_frame


# ── Handler: auto stop/start on scene switch ─────────────────────────────────

@persistent
def dome_scene_change_handler(scene, depsgraph=None):
    """Auto stop/start VSE sync when switching between scenes."""
    try:
        current = bpy.context.scene
        if current is None:
            return

        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None:
            return

        is_dome        = current.name == "Dome Animatic"
        handler_active = dome_live_preview_handler in bpy.app.handlers.frame_change_pre

        if is_dome and not handler_active:
            _register_image_handler()
            global _last_loaded_path
            _last_loaded_path = ""
            dome_scene.domeanimatic_synch_active = True
            utils.log("[DomeLivePreview] Auto-resumed VSE sync on Dome Animatic.")

        elif not is_dome and handler_active:
            _unregister_image_handler()
            utils.log("[DomeLivePreview] Auto-paused VSE sync on non-Dome scene.")

    except Exception as e:
        utils.log(f"[DomeLivePreview] Scene change handler error: {e}")


# ── Handler helpers ───────────────────────────────────────────────────────────

def _unregister_image_handler():
    bpy.app.handlers.frame_change_pre[:] = [
        h for h in bpy.app.handlers.frame_change_pre
        if getattr(h, '__name__', '') != 'dome_live_preview_handler'
    ]


def _register_image_handler():
    _unregister_image_handler()
    bpy.app.handlers.frame_change_pre.append(dome_live_preview_handler)


def _unregister_playhead_handler():
    bpy.app.handlers.frame_change_post[:] = [
        h for h in bpy.app.handlers.frame_change_post
        if getattr(h, '__name__', '') != 'dome_playhead_sync_handler'
    ]
    bpy.app.handlers.depsgraph_update_post[:] = [
        h for h in bpy.app.handlers.depsgraph_update_post
        if getattr(h, '__name__', '') != 'dome_playhead_sync_handler'
    ]


def _register_playhead_handler():
    _unregister_playhead_handler()
    bpy.app.handlers.frame_change_post.append(dome_playhead_sync_handler)


def unregister_handler():
    global _last_loaded_path, _last_dome_frame
    _unregister_image_handler()
    _unregister_playhead_handler()
    _last_loaded_path = ""
    _last_dome_frame  = -1
    utils.log("[DomeLivePreview] Handler stopped.")


def register_handler():
    global _last_loaded_path, _last_dome_frame
    _last_loaded_path = ""
    _last_dome_frame  = -1

    img = utils.get_or_create_live_image()
    if img.packed_file is not None:
        img.unpack(method='USE_ORIGINAL')
    img.source = 'FILE'

    _register_image_handler()
    _register_playhead_handler()
    utils.log("[DomeLivePreview] Handler ready (image + playhead sync).")


def block_handler():
    global _handler_blocked
    _handler_blocked = True
    utils.log("[DomeLivePreview] Handler blocked.")


def unblock_handler():
    global _handler_blocked, _last_loaded_path, _last_dome_frame
    _handler_blocked  = False
    _last_loaded_path = ""
    _last_dome_frame  = -1
    utils.log("[DomeLivePreview] Handler unblocked.")


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_synch_vse(bpy.types.Operator):
    bl_idname      = "domeanimatic.synch_vse"
    bl_label       = "Synch VSE"
    bl_description = "Start live sync: VSE image → LiveDomePreview + all scene playheads"

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None or not dome_scene.sequence_editor:
            self.report({'ERROR'}, "No Sequence Editor found in Dome Animatic scene.")
            return {'CANCELLED'}

        register_handler()

        # Fire immediately on current frame
        dome_live_preview_handler(dome_scene)
        dome_playhead_sync_handler(dome_scene)

        context.scene.domeanimatic_synch_active = True
        self.report({'INFO'}, "VSE sync started — image + playhead sync active.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_stop_synch_vse(bpy.types.Operator):
    bl_idname      = "domeanimatic.stop_synch_vse"
    bl_label       = "Stop Synch"
    bl_description = "Stop live syncing VSE to LiveDomePreview"

    def execute(self, context):
        unregister_handler()
        context.scene.domeanimatic_synch_active = False
        self.report({'INFO'}, "VSE sync stopped.")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    is_active = getattr(context.scene, "domeanimatic_synch_active", False)
    verbose   = utils.show_labels(context)

    if verbose:
        col = box.column(align=True)
        col.enabled = False
        col.label(
            text="Live sync active" if is_active else "Live sync inactive",
            icon='RADIOBUT_ON' if is_active else 'RADIOBUT_OFF'
        )

        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene and dome_scene.sequence_editor:
            frame = dome_scene.frame_current
            strip = utils.get_active_strip_at_frame(dome_scene, frame)
            if strip:
                col.label(text=f"Strip: {strip.name}", icon='STRIP_COLOR_01')
                col.label(text=f"Dome frame: {frame}")
            else:
                col.label(text="No strip at current frame", icon='INFO')
        else:
            col.label(text="No Sequence Editor found in Dome Animatic", icon='ERROR')

        box.separator(factor=0.3)

    row = box.row(align=True)
    row.scale_y = 1.5
    split = row.split(factor=0.85, align=True)
    if not is_active:
        split.operator("domeanimatic.synch_vse",      text="Synch VSE",  icon='PLAY')
    else:
        split.operator("domeanimatic.stop_synch_vse", text="Stop Synch", icon='SNAP_FACE')
    split.prop(bpy.data.window_managers[0], "domeanimatic_target_material", text="")


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_synch_vse,
    DOMEANIMATIC_OT_stop_synch_vse,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

    if dome_scene_change_handler not in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.append(dome_scene_change_handler)


def unregister():
    unregister_handler()

    if dome_scene_change_handler in bpy.app.handlers.depsgraph_update_post:
        bpy.app.handlers.depsgraph_update_post.remove(dome_scene_change_handler)

    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

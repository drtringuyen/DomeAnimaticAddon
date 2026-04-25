import bpy
import os
from bpy.app.handlers import persistent
from . import utils

_last_path       = {1: "", 2: "", 3: "", 4: ""}
_handler_blocked = False
_last_dome_frame = -1

_CH_TO_SLOT = {2: "BG", 3: "CEL_A", 4: "CEL_B"}


# ── Strip resolver ────────────────────────────────────────────────────────────

def get_strip_on_channel(scene, channel, frame):
    """Return unmuted IMAGE/MOVIE strip on exact channel at frame."""
    seq = scene.sequence_editor
    if not seq:
        return None
    for s in seq.strips_all:
        if (s.type in ('IMAGE', 'MOVIE') and s.channel == channel
                and not s.mute
                and s.frame_final_start <= frame < s.frame_final_end):
            return s
    return None


# ── Material node socket helper ───────────────────────────────────────────────

def _set_baked_cels_node_socket(socket_name):
    """
    Set the 'Menu Switch' node's Menu input to 'Baked' or 'Cels'.
    socket_name must be exactly 'Baked' or 'Cels'.
    """
    wm  = bpy.data.window_managers[0]
    mat = getattr(wm, "domeanimatic_target_material", None)
    if mat is None or not mat.use_nodes:
        return

    node = mat.node_tree.nodes.get("Menu Switch")
    if node is None:
        utils.log("[Synch] 'Menu Switch' node not found in material.")
        return

    try:
        node.inputs[0].default_value = socket_name
        utils.log(f"[Synch] Menu Switch → {socket_name}")
    except Exception as e:
        utils.log(f"[Synch] Could not set Menu Switch: {e}")


# ── Image load helper ─────────────────────────────────────────────────────────

def _load_path_into_image(datablock, abs_path):
    if datablock.packed_file is not None:
        datablock.unpack(method='USE_ORIGINAL')
    try:
        rel = bpy.path.relpath(abs_path)
    except ValueError:
        rel = abs_path
    datablock.filepath = rel
    datablock.source   = 'FILE'
    datablock.reload()


# ── Main frame-change handler ─────────────────────────────────────────────────

@persistent
def dome_live_preview_handler(scene, depsgraph=None):
    global _last_path, _handler_blocked

    if _handler_blocked:
        return

    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return

    wm   = bpy.data.window_managers[0]
    mode = getattr(wm, "domeanimatic_synch_mode", 'OFF')
    if mode == 'OFF':
        return

    frame = dome_scene.frame_current

    # ── BAKED mode: only track 1 → LiveDomePreview ────────────────────────────
    if mode == 'BAKED':
        strip1 = get_strip_on_channel(dome_scene, 1, frame)
        if strip1:
            path1 = utils.resolve_strip_image_path(strip1, frame)
            if path1 and os.path.exists(path1) and path1 != _last_path[1]:
                _load_path_into_image(utils.get_or_create_live_image(), path1)
                _last_path[1] = path1
                utils.log(f"[Synch] Ch1 → LiveDomePreview: {os.path.basename(path1)}")
        return

    # ── CEL_LAYERS mode: tracks 2/3/4 → cel datablocks ───────────────────────
    if mode == 'CEL_LAYERS':
        from . import transparent_cel
        for ch, slot in _CH_TO_SLOT.items():
            strip = get_strip_on_channel(dome_scene, ch, frame)
            if not strip:
                continue
            path = utils.resolve_strip_image_path(strip, frame)
            if not path or not os.path.exists(path):
                continue
            if path == _last_path[ch]:
                continue
            cel_img = transparent_cel.get_or_create_cel_image(slot)
            _load_path_into_image(cel_img, path)
            _last_path[ch] = path
            utils.log(f"[Synch] Ch{ch} ({slot}) → {os.path.basename(path)}")


# ── Playhead sync ─────────────────────────────────────────────────────────────

@persistent
def dome_playhead_sync_handler(scene, depsgraph=None):
    global _last_dome_frame, _handler_blocked
    if _handler_blocked:
        return
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None:
        return
    dome_frame = dome_scene.frame_current
    if dome_frame == _last_dome_frame:
        return
    _last_dome_frame = dome_frame
    for s in bpy.data.scenes:
        if s is not dome_scene and s.frame_current != dome_frame:
            s.frame_current = dome_frame


# ── Auto pause/resume on scene switch ────────────────────────────────────────

@persistent
def dome_scene_change_handler(scene, depsgraph=None):
    try:
        current    = bpy.context.scene
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if current is None or dome_scene is None:
            return
        is_dome        = current.name == "Dome Animatic"
        handler_active = dome_live_preview_handler in bpy.app.handlers.frame_change_pre
        if is_dome and not handler_active:
            _register_image_handler()
            global _last_path
            _last_path = {1: "", 2: "", 3: "", 4: ""}
            dome_scene.domeanimatic_synch_active = True
        elif not is_dome and handler_active:
            _unregister_image_handler()
    except Exception as e:
        utils.log(f"[Synch] Scene change handler error: {e}")


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
    for lst in (bpy.app.handlers.frame_change_post, bpy.app.handlers.depsgraph_update_post):
        lst[:] = [h for h in lst if getattr(h, '__name__', '') != 'dome_playhead_sync_handler']

def _register_playhead_handler():
    _unregister_playhead_handler()
    bpy.app.handlers.frame_change_post.append(dome_playhead_sync_handler)

def block_handler():
    global _handler_blocked
    _handler_blocked = True

def unblock_handler():
    global _handler_blocked, _last_path, _last_dome_frame
    _handler_blocked = False
    _last_path       = {1: "", 2: "", 3: "", 4: ""}
    _last_dome_frame = -1

def unregister_handler():
    global _last_path, _last_dome_frame
    _unregister_image_handler()
    _unregister_playhead_handler()
    _last_path       = {1: "", 2: "", 3: "", 4: ""}
    _last_dome_frame = -1

def register_handler():
    global _last_path, _last_dome_frame
    _last_path       = {1: "", 2: "", 3: "", 4: ""}
    _last_dome_frame = -1
    live = utils.get_or_create_live_image()
    if live.packed_file is not None:
        live.unpack(method='USE_ORIGINAL')
    live.source = 'FILE'
    _register_image_handler()
    _register_playhead_handler()


# ── Operators ─────────────────────────────────────────────────────────────────

def _set_vse_track_visibility(mode):
    """
    BAKED:      unmute track 1, mute tracks 2/3/4 (cel tracks)
    CEL_LAYERS: mute track 1,   unmute tracks 2/3/4
    OFF:        leave tracks unchanged
    """
    dome_scene = bpy.data.scenes.get("Dome Animatic")
    if dome_scene is None or not dome_scene.sequence_editor:
        return
    seq = dome_scene.sequence_editor
    for strip in seq.strips_all:
        if strip.channel == 1:
            strip.mute = (mode == 'CEL_LAYERS')
        elif strip.channel in (2, 3, 4):
            strip.mute = (mode == 'BAKED')


class DOMEANIMATIC_OT_set_synch_mode(bpy.types.Operator):
    """Set sync mode and immediately update the material node socket."""
    bl_idname = "domeanimatic.set_synch_mode"
    bl_label  = "Set Sync Mode"

    mode: bpy.props.StringProperty()  # 'BAKED', 'CEL_LAYERS', 'OFF'

    def execute(self, context):
        wm = bpy.data.window_managers[0]
        wm.domeanimatic_synch_mode = self.mode
        if self.mode == 'BAKED':
            _set_baked_cels_node_socket('Baked')
        elif self.mode == 'CEL_LAYERS':
            _set_baked_cels_node_socket('Cels')
        else:
            _set_baked_cels_node_socket('Baked')
        _set_vse_track_visibility(self.mode)
        return {'FINISHED'}


class DOMEANIMATIC_OT_debug_node_sockets(bpy.types.Operator):
    """Print all node names, types, inputs and outputs of the Dome Animatic material to the console."""
    bl_idname      = "domeanimatic.debug_node_sockets"
    bl_label       = "Debug: Print Node Sockets"
    bl_description = "Print node tree info to console — use this to find the correct socket names"

    def execute(self, context):
        wm  = bpy.data.window_managers[0]
        mat = getattr(wm, "domeanimatic_target_material", None)
        if mat is None or not mat.use_nodes:
            self.report({'ERROR'}, "No material set or no node tree.")
            return {'CANCELLED'}
        print(f"\n{'='*60}")
        print(f"Material: '{mat.name}' — node tree:")
        for node in mat.node_tree.nodes:
            print(f"  NODE '{node.name}'  type={node.type}")
            for i, inp in enumerate(node.inputs):
                val = getattr(inp, 'default_value', '<no default>')
                print(f"    IN  [{i}] '{inp.name}'  type={inp.type}  val={val}")
            for i, out in enumerate(node.outputs):
                print(f"    OUT [{i}] '{out.name}'  type={out.type}")
        print(f"{'='*60}\n")
        self.report({'INFO'}, "Node info printed to console (Window > Toggle System Console).")
        return {'FINISHED'}


class DOMEANIMATIC_OT_synch_vse(bpy.types.Operator):
    bl_idname      = "domeanimatic.synch_vse"
    bl_label       = "Start Synch"
    bl_description = "Start VSE sync in the selected mode"

    def execute(self, context):
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene is None or not dome_scene.sequence_editor:
            self.report({'ERROR'}, "No Sequence Editor in Dome Animatic.")
            return {'CANCELLED'}
        register_handler()
        dome_live_preview_handler(dome_scene)
        dome_playhead_sync_handler(dome_scene)
        context.scene.domeanimatic_synch_active = True
        mode = bpy.data.window_managers[0].domeanimatic_synch_mode
        if mode == 'BAKED':
            _set_baked_cels_node_socket('Baked')
        elif mode == 'CEL_LAYERS':
            _set_baked_cels_node_socket('Cels')
        self.report({'INFO'}, f"VSE sync started — mode: {mode}")
        return {'FINISHED'}


class DOMEANIMATIC_OT_stop_synch_vse(bpy.types.Operator):
    bl_idname      = "domeanimatic.stop_synch_vse"
    bl_label       = "Stop Synch"
    bl_description = "Stop VSE sync"

    def execute(self, context):
        unregister_handler()
        context.scene.domeanimatic_synch_active = False
        bpy.data.window_managers[0].domeanimatic_synch_mode = 'OFF'
        _set_baked_cels_node_socket('Baked')   # keep node on Baked when off
        self.report({'INFO'}, "VSE sync stopped.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_link_cel_nodes(bpy.types.Operator):
    """
    Find Image Texture nodes named 'BG', 'Cel_A', 'Cel_B' in the Dome Animatic
    material and assign TransparentCel_* datablocks to them.
    Also updates the three mat_image WM pointers.
    Node names are checked case-insensitively as a fallback.
    """
    bl_idname      = "domeanimatic.link_cel_nodes"
    bl_label       = "Link Cel Nodes"
    bl_description = (
        "Assign TransparentCel BG/Cel_A/Cel_B datablocks to the matching "
        "Image Texture nodes in the Dome Animatic material. "
        "Nodes must be named 'BG', 'Cel_A', 'Cel_B'."
    )

    def execute(self, context):
        from . import transparent_cel

        wm  = bpy.data.window_managers[0]
        mat = getattr(wm, "domeanimatic_target_material", None)
        if mat is None:
            self.report({'ERROR'}, "No Dome Animatic material set.")
            return {'CANCELLED'}
        if not mat.use_nodes:
            self.report({'ERROR'}, f"Material '{mat.name}' has no node tree.")
            return {'CANCELLED'}

        # Try named nodes first (BG, Cel_A, Cel_B), then fall back to
        # positional assignment: Image Texture.001=BG, .002=Cel_A, .003=Cel_B
        NAMED_MAP = {
            'BG':    ('BG',    'bg'),
            'Cel_A': ('CEL_A', 'cel_a'),
            'Cel_B': ('CEL_B', 'cel_b'),
        }
        POSITIONAL_MAP = [
            ('Image Texture.001', 'BG',    'bg'),
            ('Image Texture.002', 'CEL_A', 'cel_a'),
            ('Image Texture.003', 'CEL_B', 'cel_b'),
        ]

        nodes = mat.node_tree.nodes
        tex_lower = {n.name.lower(): n for n in nodes if n.type == 'TEX_IMAGE'}

        linked, missing = [], []

        for node_name, (slot_id, wm_suffix) in NAMED_MAP.items():
            node = nodes.get(node_name) or tex_lower.get(node_name.lower())
            if node is not None and node.type == 'TEX_IMAGE':
                cel_img    = transparent_cel.get_or_create_cel_image(slot_id)
                node.image = cel_img
                setattr(wm, f"domeanimatic_{wm_suffix}_mat_image", cel_img)
                linked.append(node.name)
                utils.log(f"[LinkCelNodes] '{node.name}' → '{cel_img.name}'")
            else:
                missing.append(node_name)

        # Positional fallback for any still-missing slots
        for node_name, slot_id, wm_suffix in POSITIONAL_MAP:
            if slot_id in [s for _, s, _ in [(n, NAMED_MAP[n][0], NAMED_MAP[n][1])
                           for n in NAMED_MAP] if n not in missing]:
                continue  # already linked by name
            node = nodes.get(node_name)
            if node is not None and node.type == 'TEX_IMAGE':
                cel_img    = transparent_cel.get_or_create_cel_image(slot_id)
                node.image = cel_img
                setattr(wm, f"domeanimatic_{wm_suffix}_mat_image", cel_img)
                if node.name not in linked:
                    linked.append(node.name)
                if slot_id in [NAMED_MAP[m][0] for m in missing]:
                    missing = [m for m in missing if NAMED_MAP[m][0] != slot_id]
                utils.log(f"[LinkCelNodes] Positional '{node.name}' → '{cel_img.name}'")

        if missing:
            self.report({'WARNING'}, f"Linked: {linked}. Still missing: {missing}")
        else:
            self.report({'INFO'}, f"All cel nodes linked: {linked}")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(box, context):
    wm        = bpy.data.window_managers[0]
    is_active = getattr(context.scene, "domeanimatic_synch_active", False)
    verbose   = utils.show_labels(context)

    if verbose:
        col = box.column(align=True)
        col.enabled = False
        col.label(
            text="Live sync active" if is_active else "Live sync inactive",
            icon='RADIOBUT_ON' if is_active else 'RADIOBUT_OFF',
        )
        dome_scene = bpy.data.scenes.get("Dome Animatic")
        if dome_scene and dome_scene.sequence_editor:
            frame = dome_scene.frame_current
            for ch, label in ((1, "Baked"), (2, "BG"), (3, "Cel_A"), (4, "Cel_B")):
                s = get_strip_on_channel(dome_scene, ch, frame)
                col.label(
                    text=f"Ch{ch} ({label}): {s.name}" if s else f"Ch{ch} ({label}): empty",
                    icon='STRIP_COLOR_01' if s else 'INFO',
                )
        box.separator(factor=0.3)

    # ── Label row — centered ──────────────────────────────────────────────────
    cur_mode  = wm.domeanimatic_synch_mode
    label_row = box.row()
    label_row.alignment = 'CENTER'
    label_row.label(text="Synch VSE as:", icon='SEQ_SPLITVIEW')

    # ── Mode buttons + Start/Stop + Refresh ───────────────────────────────────
    mode_row = box.row(align=True)
    mode_row.scale_y = 1.4

    btn = mode_row.operator(
        "domeanimatic.set_synch_mode",
        text="Baked Frame",
        icon='OUTLINER_OB_IMAGE',
        depress=(cur_mode == 'BAKED'),
    )
    btn.mode = 'BAKED'

    btn = mode_row.operator(
        "domeanimatic.set_synch_mode",
        text="Unbaked Cels",
        icon='RENDERLAYERS',
        depress=(cur_mode == 'CEL_LAYERS'),
    )
    btn.mode = 'CEL_LAYERS'

    if not is_active:
        mode_row.operator("domeanimatic.synch_vse",      text="", icon='PLAY')
    else:
        mode_row.operator("domeanimatic.stop_synch_vse", text="", icon='SNAP_FACE')

    mode_row.operator("domeanimatic.synch_vse", text="", icon='FILE_REFRESH')

    # ── Material node setup — collapsible ─────────────────────────────────────
    mat_box = box.box()
    mat_header = mat_box.row()
    mat_header.prop(
        wm, "domeanimatic_mat_nodes_expanded",
        icon='TRIA_DOWN' if wm.domeanimatic_mat_nodes_expanded else 'TRIA_RIGHT',
        icon_only=True, emboss=False,
    )
    mat_header.label(text="Dome Animatic Material", icon='MATERIAL')

    if wm.domeanimatic_mat_nodes_expanded:
        col = mat_box.column(align=True)
        col.prop(wm, "domeanimatic_target_material", text="")
        col.separator(factor=0.3)
        col.label(text="Material Tex Node Images:", icon='NODE_TEXTURE')
        for slot, label in (("bg", "BG  "), ("cel_a", "Cel A"), ("cel_b", "Cel B")):
            row = col.row(align=True)
            row.label(text=label)
            row.prop(wm, f"domeanimatic_{slot}_mat_image", text="")
        col.separator(factor=0.3)
        col.operator(
            "domeanimatic.link_cel_nodes",
            text="Link Cel Nodes to Material",
            icon='LINKED',
        )


class DOMEANIMATIC_OT_clear_console(bpy.types.Operator):
    """Clear the system console by printing blank lines."""
    bl_idname = "domeanimatic.clear_console"
    bl_label  = "Clear Console"

    def execute(self, context):
        print("\n" * 60)
        print("=" * 60)
        print("  Console cleared")
        print("=" * 60)
        return {'FINISHED'}


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_set_synch_mode,
    DOMEANIMATIC_OT_debug_node_sockets,
    DOMEANIMATIC_OT_clear_console,
    DOMEANIMATIC_OT_synch_vse,
    DOMEANIMATIC_OT_stop_synch_vse,
    DOMEANIMATIC_OT_link_cel_nodes,
]

def register():
    bpy.types.WindowManager.domeanimatic_mat_nodes_expanded = bpy.props.BoolProperty(
        name="Material Nodes Expanded", default=False,  # closed by default
    )
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
    if hasattr(bpy.types.WindowManager, 'domeanimatic_mat_nodes_expanded'):
        del bpy.types.WindowManager.domeanimatic_mat_nodes_expanded

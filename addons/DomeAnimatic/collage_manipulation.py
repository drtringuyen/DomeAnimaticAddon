import bpy
import bmesh


# ── Poll helper ───────────────────────────────────────────────────────────────

def _poll_edit_face(context):
    obj = context.active_object
    if obj is None or obj.type != 'MESH':
        return False
    if context.mode != 'EDIT_MESH':
        return False
    bm = bmesh.from_edit_mesh(obj.data)
    return any(f.select for f in bm.faces)


# ── Material helper ───────────────────────────────────────────────────────────

def ensure_delete_material(color=(0.0, 0.0, 0.0)):
    mat = bpy.data.materials.get("DELETE")
    if mat is None:
        mat = bpy.data.materials.new(name="DELETE")
    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links
    nodes.clear()
    output   = nodes.new('ShaderNodeOutputMaterial')
    output.location = (300, 0)
    emission = nodes.new('ShaderNodeEmission')
    emission.location = (100, 0)
    emission.inputs['Color'].default_value = (*color, 1.0)
    emission.inputs['Strength'].default_value = 1.0
    links.new(emission.outputs['Emission'], output.inputs['Surface'])
    return mat


# ── Face selection save/restore ───────────────────────────────────────────────

TEMP_GROUP = "__domeanimatic_sel__"

def save_face_selection(obj):
    mesh = obj.data
    vg = obj.vertex_groups.get(TEMP_GROUP)
    if vg:
        obj.vertex_groups.remove(vg)
    vg = obj.vertex_groups.new(name=TEMP_GROUP)
    bpy.ops.object.mode_set(mode='OBJECT')
    for poly in mesh.polygons:
        if poly.select:
            for vi in poly.vertices:
                vg.add([vi], 1.0, 'REPLACE')
    bpy.ops.object.mode_set(mode='EDIT')

def restore_face_selection(obj):
    vg = obj.vertex_groups.get(TEMP_GROUP)
    if vg is None:
        return
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh    = obj.data
    vg_idx  = vg.index
    marked  = {v.index for v in mesh.vertices for g in v.groups if g.group == vg_idx and g.weight > 0.5}
    for poly in mesh.polygons:
        poly.select = all(vi in marked for vi in poly.vertices)
    bpy.ops.object.mode_set(mode='EDIT')
    obj.vertex_groups.remove(vg)


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_duplicate_as_object(bpy.types.Operator):
    bl_idname      = "domeanimatic.duplicate_as_object"
    bl_label       = "Duplicate as new Object"
    bl_description = "Duplicate selected faces, offset on Z by layer_spacing, separate as new object"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        spacing       = context.scene.domeanimatic_layer_spacing
        original_obj  = context.active_object
        original_name = original_obj.name
        objects_before = set(bpy.data.objects.keys())

        bpy.ops.mesh.duplicate_move(
            TRANSFORM_OT_translate={"value": (0, 0, spacing)}
        )
        bpy.ops.mesh.separate(type='SELECTED')
        bpy.ops.object.mode_set(mode='OBJECT')

        objects_after = set(bpy.data.objects.keys())
        new_names     = objects_after - objects_before
        if not new_names:
            self.report({'WARNING'}, "Could not find new object after separation.")
            return {'CANCELLED'}

        new_obj = None
        for name in new_names:
            obj = bpy.data.objects.get(name)
            if obj is None:
                continue
            base     = original_name
            new_name = base + ".collage"
            counter  = 1
            while new_name in bpy.data.objects and bpy.data.objects[new_name] is not obj:
                new_name = f"{base}.collage.{counter:03d}"
                counter += 1
            obj.name = new_name
            if obj.data:
                obj.data.name = new_name
            new_obj = obj
            break

        if new_obj is None:
            self.report({'WARNING'}, "Could not resolve new object.")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')
        self.report({'INFO'}, f"Duplicated as: '{new_obj.name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_content_aware_delete(bpy.types.Operator):
    bl_idname      = "domeanimatic.content_aware_delete"
    bl_label       = "Content-aware Delete"
    bl_description = "Extrude selected faces to zero then collapse"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        bpy.ops.mesh.extrude_faces_move(TRANSFORM_OT_shrink_fatten={"value": 0.0})
        bpy.ops.transform.resize(value=(0, 0, 0))
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        self.report({'INFO'}, "Content-aware delete applied.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_content_aware_cut(bpy.types.Operator):
    bl_idname      = "domeanimatic.content_aware_cut"
    bl_label       = "Content-aware Cut"
    bl_description = "Duplicate selected faces as new object, then content-aware delete from original"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        original_obj   = context.active_object
        objects_before = set(bpy.data.objects.keys())
        save_face_selection(original_obj)
        bpy.ops.domeanimatic.duplicate_as_object()

        objects_after = set(bpy.data.objects.keys())
        new_names     = objects_after - objects_before
        new_obj       = bpy.data.objects.get(next(iter(new_names))) if new_names else None
        if new_obj is None:
            self.report({'WARNING'}, "Could not find new object after cut.")
            return {'CANCELLED'}

        bpy.ops.object.select_all(action='DESELECT')
        original_obj.select_set(True)
        context.view_layer.objects.active = original_obj
        bpy.ops.object.mode_set(mode='EDIT')
        restore_face_selection(original_obj)
        bpy.ops.mesh.extrude_faces_move(TRANSFORM_OT_shrink_fatten={"value": 0.0})
        bpy.ops.transform.resize(value=(0, 0, 0))
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj
        self.report({'INFO'}, f"Cut to: '{new_obj.name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cut_fill_black(bpy.types.Operator):
    bl_idname      = "domeanimatic.cut_fill_black"
    bl_label       = "Cut and Fill with selected Color"
    bl_description = "Duplicate selected faces as new object, fill originals with DELETE material"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        original_obj   = context.active_object
        objects_before = set(bpy.data.objects.keys())
        save_face_selection(original_obj)
        bpy.ops.domeanimatic.duplicate_as_object()

        objects_after = set(bpy.data.objects.keys())
        new_names     = objects_after - objects_before
        new_obj       = bpy.data.objects.get(next(iter(new_names))) if new_names else None
        if new_obj is None:
            self.report({'WARNING'}, "Could not find new object.")
            return {'CANCELLED'}

        color   = tuple(context.scene.domeanimatic_delete_color)
        del_mat = ensure_delete_material(color=color)

        bpy.ops.object.select_all(action='DESELECT')
        original_obj.select_set(True)
        context.view_layer.objects.active = original_obj
        bpy.ops.object.mode_set(mode='EDIT')
        restore_face_selection(original_obj)

        if del_mat.name not in [m.name for m in original_obj.data.materials]:
            original_obj.data.materials.append(del_mat)
        mat_idx = list(original_obj.data.materials).index(del_mat)
        original_obj.active_material_index = mat_idx
        bpy.ops.object.material_slot_assign()

        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj
        self.report({'INFO'}, f"Cut '{new_obj.name}', filled with DELETE material.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_recover_face(bpy.types.Operator):
    bl_idname      = "domeanimatic.recover_face"
    bl_label       = "Recover Face"
    bl_description = "Assign the first material slot to the selected faces"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        obj = context.active_object
        if not obj.data.materials:
            self.report({'WARNING'}, "Object has no materials.")
            return {'CANCELLED'}
        obj.active_material_index = 0
        bpy.ops.object.material_slot_assign()
        self.report({'INFO'}, f"Recovered faces to '{obj.data.materials[0].name}'.")
        return {'FINISHED'}


# ── UI draw — used by frame_snap_shot only (no panel of its own) ──────────────

def draw_handle_selected(layout, context):
    """Compact face-op row for frame_snap_shot. No mark_face."""
    is_dome = context.scene.name == "Dome Animatic"
    row = layout.row(align=True)
    row.scale_y = 1.5
    row.enabled = not is_dome
    row.operator("domeanimatic.recover_face",        text="", icon='RECOVER_LAST')
    row.label(text="Handle Selected", icon='GREASEPENCIL_LAYER_GROUP')
    sub = row.row(align=True)
    sub.scale_x = 0.4
    sub.prop(context.scene, "domeanimatic_delete_color", text="")
    row.operator("domeanimatic.duplicate_as_object", text="", icon='SELECT_DIFFERENCE')
    row.operator("domeanimatic.cut_fill_black",      text="", icon='SELECT_INTERSECT')


# ── Layer move operators ──────────────────────────────────────────────────────

class DOMEANIMATIC_OT_layer_move_up(bpy.types.Operator):
    bl_idname      = "domeanimatic.layer_move_up"
    bl_label       = "Move Object Up"
    bl_description = "Move the active object up along global Z by Layer Spacing"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        spacing   = context.scene.domeanimatic_layer_spacing
        prev_mode = context.mode
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.active_object.location.z += spacing
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=prev_mode.replace('EDIT_MESH', 'EDIT'))
        return {'FINISHED'}


class DOMEANIMATIC_OT_layer_move_down(bpy.types.Operator):
    bl_idname      = "domeanimatic.layer_move_down"
    bl_label       = "Move Object Down"
    bl_description = "Move the active object down along global Z by Layer Spacing"

    @classmethod
    def poll(cls, context):
        return context.active_object is not None

    def execute(self, context):
        spacing   = context.scene.domeanimatic_layer_spacing
        prev_mode = context.mode
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode='OBJECT')
        context.active_object.location.z -= spacing
        if prev_mode != 'OBJECT':
            bpy.ops.object.mode_set(mode=prev_mode.replace('EDIT_MESH', 'EDIT'))
        return {'FINISHED'}


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_duplicate_as_object,
    DOMEANIMATIC_OT_content_aware_delete,
    DOMEANIMATIC_OT_content_aware_cut,
    DOMEANIMATIC_OT_cut_fill_black,
    DOMEANIMATIC_OT_recover_face,
    DOMEANIMATIC_OT_layer_move_up,
    DOMEANIMATIC_OT_layer_move_down,
]

def register():
    for cls in classes:
        bpy.utils.register_class(cls)

def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

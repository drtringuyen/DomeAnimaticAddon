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
    """
    Get or create the DELETE material with a Color Attribute node
    plugged into Material Output Surface. Sets the default color value.
    """
    mat = bpy.data.materials.get("DELETE")
    if mat is None:
        mat = bpy.data.materials.new(name="DELETE")

    mat.use_nodes = True
    nodes = mat.node_tree.nodes
    links = mat.node_tree.links

    nodes.clear()

    output = nodes.new('ShaderNodeOutputMaterial')
    output.location = (300, 0)

    # Emission shader so the color is visible without lighting
    emission = nodes.new('ShaderNodeEmission')
    emission.location = (100, 0)
    emission.inputs['Color'].default_value = (*color, 1.0)
    emission.inputs['Strength'].default_value = 1.0

    links.new(emission.outputs['Emission'], output.inputs['Surface'])

    return mat


# ── Face selection save/restore via temp vertex group ─────────────────────────

TEMP_GROUP = "__domeanimatic_sel__"


def save_face_selection(obj):
    """Save selected faces to a temp vertex group so it survives mode switches."""
    mesh = obj.data
    # Remove old temp group if exists
    vg = obj.vertex_groups.get(TEMP_GROUP)
    if vg:
        obj.vertex_groups.remove(vg)
    vg = obj.vertex_groups.new(name=TEMP_GROUP)

    # Switch to object mode briefly to read selection
    bpy.ops.object.mode_set(mode='OBJECT')
    for poly in mesh.polygons:
        if poly.select:
            for vi in poly.vertices:
                vg.add([vi], 1.0, 'REPLACE')
    bpy.ops.object.mode_set(mode='EDIT')


def restore_face_selection(obj):
    """Re-select faces from the temp vertex group."""
    vg = obj.vertex_groups.get(TEMP_GROUP)
    if vg is None:
        return

    # Switch to object mode to manipulate selection
    bpy.ops.object.mode_set(mode='OBJECT')
    mesh = obj.data

    # Build set of vertices in the group
    vg_idx     = vg.index
    marked_verts = set()
    for v in mesh.vertices:
        for g in v.groups:
            if g.group == vg_idx and g.weight > 0.5:
                marked_verts.add(v.index)

    # Deselect all faces, then select faces where all verts are in group
    for poly in mesh.polygons:
        poly.select = all(vi in marked_verts for vi in poly.vertices)

    bpy.ops.object.mode_set(mode='EDIT')

    # Clean up temp group
    obj.vertex_groups.remove(vg)


# ── Operators ─────────────────────────────────────────────────────────────────

class DOMEANIMATIC_OT_mark_face(bpy.types.Operator):
    bl_idname      = "domeanimatic.mark_face"
    bl_label       = "Mark Face"
    bl_description = "Assign selected faces to the 'marked_face' boolean attribute"
    bl_options     = {'REGISTER', 'UNDO'}

    GROUP_NAME = "marked_face"

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        obj       = context.active_object
        mesh      = obj.data
        attr_name = self.GROUP_NAME

        if attr_name not in mesh.attributes:
            mesh.attributes.new(name=attr_name, type='BOOLEAN', domain='FACE')

        bpy.ops.object.mode_set(mode='OBJECT')
        attr  = mesh.attributes[attr_name]
        count = 0
        for i, poly in enumerate(mesh.polygons):
            if poly.select:
                attr.data[i].value = True
                count += 1

        bpy.ops.object.mode_set(mode='EDIT')
        self.report({'INFO'}, f"Marked {count} face(s) in '{attr_name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_duplicate_as_object(bpy.types.Operator):
    bl_idname      = "domeanimatic.duplicate_as_object"
    bl_label       = "Duplicate as new Object"
    bl_description = (
        "Duplicate selected faces, offset on Z by layer_spacing, "
        "separate as a new object, reset origin to center"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        spacing       = context.scene.domeanimatic_layer_spacing
        original_obj  = context.active_object
        original_name = original_obj.name

        objects_before = set(bpy.data.objects.keys())

        # 1. Duplicate selected faces and translate on Z
        bpy.ops.mesh.duplicate_move(
            TRANSFORM_OT_translate={"value": (0, 0, spacing)}
        )

        # 2. Separate as new object
        bpy.ops.mesh.separate(type='SELECTED')

        # 3. Object mode
        bpy.ops.object.mode_set(mode='OBJECT')

        # 4. Find new object by diff
        objects_after = set(bpy.data.objects.keys())
        new_names     = objects_after - objects_before

        if not new_names:
            self.report({'WARNING'}, "Could not find new object after separation.")
            return {'CANCELLED'}

        # 5. Rename with .collage suffix
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

        # 6. Deselect all, select only new object, reset origin
        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj
        bpy.ops.object.origin_set(type='ORIGIN_GEOMETRY', center='MEDIAN')

        self.report({'INFO'}, f"Duplicated as: '{new_obj.name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_content_aware_delete(bpy.types.Operator):
    bl_idname      = "domeanimatic.content_aware_delete"
    bl_label       = "Content-aware Delete"
    bl_description = "Extrude selected faces to zero then collapse to fill the hole"
    bl_options     = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        bpy.ops.mesh.extrude_faces_move(
            TRANSFORM_OT_shrink_fatten={"value": 0.0}
        )
        bpy.ops.transform.resize(value=(0, 0, 0))
        bpy.ops.mesh.remove_doubles(threshold=0.0001)
        self.report({'INFO'}, "Content-aware delete applied.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_content_aware_cut(bpy.types.Operator):
    bl_idname      = "domeanimatic.content_aware_cut"
    bl_label       = "Content-aware Cut"
    bl_description = (
        "Duplicate selected faces as new object, "
        "then content-aware delete them from the original"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        original_obj   = context.active_object
        objects_before = set(bpy.data.objects.keys())

        # 1. Save face selection before duplicate changes things
        save_face_selection(original_obj)

        # 2. Duplicate as object
        bpy.ops.domeanimatic.duplicate_as_object()

        # 3. Find new object by diff
        objects_after = set(bpy.data.objects.keys())
        new_names     = objects_after - objects_before
        new_obj       = bpy.data.objects.get(next(iter(new_names))) if new_names else None

        if new_obj is None:
            self.report({'WARNING'}, "Could not find new object after cut.")
            return {'CANCELLED'}

        # 4. Switch back to original, enter Edit mode
        bpy.ops.object.select_all(action='DESELECT')
        original_obj.select_set(True)
        context.view_layer.objects.active = original_obj
        bpy.ops.object.mode_set(mode='EDIT')

        # 5. Restore the saved face selection
        restore_face_selection(original_obj)

        # 6. Content-aware delete on restored selection
        bpy.ops.mesh.extrude_faces_move(
            TRANSFORM_OT_shrink_fatten={"value": 0.0}
        )
        bpy.ops.transform.resize(value=(0, 0, 0))
        bpy.ops.mesh.remove_doubles(threshold=0.0001)

        # 7. Object mode, select only new object
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj

        self.report({'INFO'}, f"Cut to: '{new_obj.name}'.")
        return {'FINISHED'}


class DOMEANIMATIC_OT_cut_fill_black(bpy.types.Operator):
    bl_idname      = "domeanimatic.cut_fill_black"
    bl_label       = "Cut and Fill with selected Color"
    bl_description = (
        "Duplicate selected faces as new object, "
        "then assign the DELETE material to those faces on the original"
    )
    bl_options = {'REGISTER', 'UNDO'}

    @classmethod
    def poll(cls, context):
        return _poll_edit_face(context)

    def execute(self, context):
        original_obj   = context.active_object
        objects_before = set(bpy.data.objects.keys())

        # 1. Save face selection
        save_face_selection(original_obj)

        # 2. Duplicate as object
        bpy.ops.domeanimatic.duplicate_as_object()

        # 3. Find new object by diff
        objects_after = set(bpy.data.objects.keys())
        new_names     = objects_after - objects_before
        new_obj       = bpy.data.objects.get(next(iter(new_names))) if new_names else None

        if new_obj is None:
            self.report({'WARNING'}, "Could not find new object.")
            return {'CANCELLED'}

        # 4. Ensure DELETE material exists with chosen color
        color   = tuple(context.scene.domeanimatic_delete_color)
        del_mat = ensure_delete_material(color=color)

        # 5. Switch back to original, enter Edit mode
        bpy.ops.object.select_all(action='DESELECT')
        original_obj.select_set(True)
        context.view_layer.objects.active = original_obj
        bpy.ops.object.mode_set(mode='EDIT')

        # 6. Restore face selection
        restore_face_selection(original_obj)

        # 7. Add DELETE material to original if not present, get its slot index
        if del_mat.name not in [m.name for m in original_obj.data.materials]:
            original_obj.data.materials.append(del_mat)
        mat_idx = list(original_obj.data.materials).index(del_mat)

        # 8. Assign DELETE material to selected faces
        original_obj.active_material_index = mat_idx
        bpy.ops.object.material_slot_assign()

        # 9. Object mode, select only new object
        bpy.ops.object.mode_set(mode='OBJECT')
        bpy.ops.object.select_all(action='DESELECT')
        new_obj.select_set(True)
        context.view_layer.objects.active = new_obj

        self.report({'INFO'}, f"Cut '{new_obj.name}', original faces filled with DELETE material.")
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

        # Assign slot 0 — the first material in the list
        obj.active_material_index = 0
        bpy.ops.object.material_slot_assign()

        self.report({'INFO'}, f"Recovered faces to '{obj.data.materials[0].name}'.")
        return {'FINISHED'}


# ── UI draw ───────────────────────────────────────────────────────────────────

def draw_ui(layout, context):
    obj = context.active_object

    col = layout.column(align=True)

    row = col.row(align=True)
    row.scale_y = 1.5
    row.operator("domeanimatic.mark_face",           text="Mark Face",              icon='FACE_MAPS')

    row = col.row(align=True)
    row.scale_y = 1.5
    row.operator("domeanimatic.duplicate_as_object",   text="Duplicate as new Object",          icon='DUPLICATE')

    row = col.row(align=True)
    row.scale_y = 1.5
    row.operator("domeanimatic.content_aware_delete",  text="Content-aware Delete",              icon='SELECT_INTERSECT')
    row.operator("domeanimatic.content_aware_cut",     text="Cut",                               icon='SELECT_DIFFERENCE')

    row = col.row(align=True)
    row.scale_y = 1.5
    row.operator("domeanimatic.recover_face",           text="",                                  icon='RECOVER_LAST')
    row.prop(context.scene, "domeanimatic_delete_color", text="")
    row.operator("domeanimatic.cut_fill_black",         text="Cut and Fill with selected Color",  icon='BRUSH_DATA')

    # Verbose
    if bpy.data.window_managers[0].domeanimatic_show_labels:
        if obj and obj.type == 'MESH' and "marked_face" in obj.data.attributes:
            attr  = obj.data.attributes["marked_face"]
            count = sum(1 for d in attr.data if d.value)
            info  = layout.row()
            info.enabled = False
            info.label(text=f"marked_face: {count} face(s)", icon='CHECKMARK')


# ── Register ──────────────────────────────────────────────────────────────────

classes = [
    DOMEANIMATIC_OT_mark_face,
    DOMEANIMATIC_OT_duplicate_as_object,
    DOMEANIMATIC_OT_content_aware_delete,
    DOMEANIMATIC_OT_content_aware_cut,
    DOMEANIMATIC_OT_cut_fill_black,
    DOMEANIMATIC_OT_recover_face,
]


def register():
    for cls in classes:
        bpy.utils.register_class(cls)


def unregister():
    for cls in reversed(classes):
        bpy.utils.unregister_class(cls)

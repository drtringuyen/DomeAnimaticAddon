from . import collection_ops, mesh_edit_ops, frame_capture_ops, ui


def register():
    collection_ops.register()
    mesh_edit_ops.register()
    frame_capture_ops.register()
    ui.register()


def unregister():
    ui.unregister()
    frame_capture_ops.unregister()
    mesh_edit_ops.unregister()
    collection_ops.unregister()

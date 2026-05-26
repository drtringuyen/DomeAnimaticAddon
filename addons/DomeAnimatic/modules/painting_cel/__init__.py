from . import gpu_overlay, paint_guard, cel_layer_ops, ui


def register():
    gpu_overlay.register()
    paint_guard.register()
    cel_layer_ops.register()
    ui.register()


def unregister():
    ui.unregister()
    cel_layer_ops.unregister()
    paint_guard.unregister()
    gpu_overlay.unregister()

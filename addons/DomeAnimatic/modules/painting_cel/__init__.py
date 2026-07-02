from . import (gpu_overlay, paint_guard, cel_layer_ops,
               lasso_raster, lasso_draw, lasso_transform_ops, ui)


def register():
    gpu_overlay.register()
    paint_guard.register()
    cel_layer_ops.register()
    lasso_transform_ops.register()
    ui.register()


def unregister():
    ui.unregister()
    lasso_transform_ops.unregister()
    cel_layer_ops.unregister()
    paint_guard.unregister()
    gpu_overlay.unregister()

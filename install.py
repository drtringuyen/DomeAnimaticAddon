import shutil
import os

ADDON_NAME = "DomeAnimatic"

BLENDER_ADDONS = os.path.join(
    os.environ["APPDATA"],
    "Blender Foundation", "Blender", "5.1", "scripts", "addons"
)

src = os.path.join(os.path.dirname(__file__), "addons", "DomeAnimatic")  # ← match your actual folder name
dst = os.path.join(BLENDER_ADDONS, ADDON_NAME)

os.makedirs(BLENDER_ADDONS, exist_ok=True)
shutil.copytree(src, dst, dirs_exist_ok=True)
print(f"✓ Deployed to: {dst}")
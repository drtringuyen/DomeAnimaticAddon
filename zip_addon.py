import shutil
import os
import zipfile

ADDON_NAME = "DomeAnimatic"
PROJECT_ROOT = os.path.dirname(__file__)
SRC_FOLDER = os.path.join(os.path.dirname(__file__), "addons", "DomeAnimatic")
OUTPUT_ZIP = os.path.join(PROJECT_ROOT, ADDON_NAME + ".zip")

# Step 1 — Remove old zip if exists
if os.path.exists(OUTPUT_ZIP):
    os.remove(OUTPUT_ZIP)
    print("✓ Removed old zip")

# Step 2 — Manually zip with DomeAnimatic\ as the root folder inside the zip
with zipfile.ZipFile(OUTPUT_ZIP, "w", zipfile.ZIP_DEFLATED) as zf:
    for file in os.listdir(SRC_FOLDER):
        full_path = os.path.join(SRC_FOLDER, file)
        if os.path.isfile(full_path):
            # This puts files under DomeAnimatic\ inside the zip
            zf.write(full_path, arcname=os.path.join(ADDON_NAME, file))
            print(f"  + {ADDON_NAME}/{file}")

print(f"\n✓ Created: {OUTPUT_ZIP}")
print(f"\n🎉 Done! Install in Blender via:")
print("   Edit → Preferences → Add-ons → Install → pick DomeAnimatic.zip")
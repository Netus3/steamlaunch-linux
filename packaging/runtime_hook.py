# User runtime hooks run before PyInstaller's Qt hook changes these variables.
import json
import os

keys = ("QT_PLUGIN_PATH", "QT_QPA_PLATFORM_PLUGIN_PATH", "QML2_IMPORT_PATH", "QML_IMPORT_PATH",
        "QT_QPA_PLATFORM")
os.environ["_STEAMLAUNCH_QT_ENV"] = json.dumps({key: os.environ[key] for key in keys if key in os.environ})

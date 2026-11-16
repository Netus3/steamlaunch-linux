from pathlib import Path
import runpy
import sys
from unittest.mock import patch

from tests.helpers import Fixture


class ReleaseSourceTests(Fixture):
    def test_source_allowlist_excludes_runtime_data_and_local_notes(self):
        root = Path(__file__).resolve().parents[1]
        with patch.object(sys, "path", [str(root / "scripts"), *sys.path]):
            module = runpy.run_path(str(root / "scripts/build_release.py"))
        files = module["source_files"]
        for name in ["steamlaunch/code.py", "steamlaunch/assets/icon.svg", "steamlaunch/.env",
                     "steamlaunch/debug.log", "steamlaunch/profile.vdf", "steamlaunch/__pycache__/code.pyc",
                     "packaging/example.spec", "docs/README.md", "PROGRESS.md", "README.md",
                     ".venv/secret.py", "build/secret.py", "dist/secret.py"]:
            path = self.base / name
            path.parent.mkdir(parents=True, exist_ok=True)
            path.write_text("sample")
        with patch.dict(files.__globals__, {"ROOT": self.base}):
            selected = {str(path.relative_to(self.base)) for path in files()}
        self.assertEqual(selected, {"steamlaunch/code.py", "steamlaunch/assets/icon.svg",
                                    "packaging/example.spec", "docs/README.md", "README.md"})

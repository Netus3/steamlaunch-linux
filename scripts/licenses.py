"""Record actual binary dependencies and retain redistributable license notices."""
import hashlib
import json
import shutil
import subprocess
import sysconfig
from pathlib import Path
from urllib.request import urlopen

# Downloaded license text is data only, validated before including it. Runtime
# never downloads anything. Exact upstream text changes fail the build.
TEXTS = {
    "LGPL-3.0-only": "996af0513df21f7496288951c41428a03c174e9e4a9d63665c57d670f845ccb1",
    "GPL-3.0-only": "fb981668c18a279e285fc4d83fba1e836cc84dd4daa73c9697d3cfd2d8aca6e0",
    "LGPL-2.1-only": "5749785c8bdefafcb5d798270ed0a967036fe2ca63dcedade1627565dfef81d2",
}


def collect_native_notices(bundle: Path, origins_file: Path) -> None:
    licenses = bundle / "licenses"
    licenses.mkdir(exist_ok=True)
    for name, digest in TEXTS.items():
        url = f"https://raw.githubusercontent.com/spdx/license-list-data/main/text/{name}.txt"
        with urlopen(url, timeout=40) as response:
            data = response.read()
        if hashlib.sha256(data).hexdigest() != digest:
            raise RuntimeError(f"License checksum changed: {name}; review before updating the recipe")
        (licenses / f"{name}.txt").write_bytes(data)
    stdlib = Path(sysconfig.get_path("stdlib"))
    python_license = next((path for path in [stdlib / "LICENSE.txt", stdlib.parent.parent / "LICENSE.txt"]
                           if path.is_file()), None)
    if not python_license:
        raise RuntimeError("CPython LICENSE.txt not found; do not distribute without its notices")
    shutil.copy2(python_license, licenses / "CPython-LICENSE.txt")
    inventory = []
    copied = set()
    for item in json.loads(origins_file.read_text()):
        path = Path(item["source"]).resolve()
        entry = {"file": item["name"], "sha256": hashlib.sha256(path.read_bytes()).hexdigest()}
        if "site-packages" in path.parts:
            entry["provider"] = "Python wheel (see dependencies.json)"
        elif shutil.which("pacman"):
            result = subprocess.run(["pacman", "-Qoq", str(path)], capture_output=True, text=True)
            package = result.stdout.strip() if result.returncode == 0 else ""
            if package:
                entry["provider"] = package
                notice_dir = Path("/usr/share/licenses") / package
                if notice_dir.is_dir() and package not in copied:
                    shutil.copytree(notice_dir, licenses / "system" / package, symlinks=False)
                    copied.add(package)
        elif shutil.which("dpkg-query"):
            result = subprocess.run(["dpkg-query", "-S", str(path)], capture_output=True, text=True)
            # Some /usr-merged packages record /lib paths rather than /usr/lib.
            if result.returncode and str(path).startswith("/usr/lib/"):
                result = subprocess.run(["dpkg-query", "-S", str(path)[4:]], capture_output=True, text=True)
            package = result.stdout.split(": ", 1)[0].strip() if result.returncode == 0 else ""
            if package:
                entry["provider"] = package
                notice = Path("/usr/share/doc") / package.split(":", 1)[0] / "copyright"
                if notice.is_file() and package not in copied:
                    destination = licenses / "system" / package
                    destination.mkdir(parents=True)
                    shutil.copy2(notice, destination / "copyright")
                    copied.add(package)
        inventory.append(entry)
    common = Path("/usr/share/common-licenses")
    if common.is_dir():
        shutil.copytree(common, licenses / "system/common-licenses", symlinks=False)
    (bundle / "native-libraries.json").write_text(json.dumps(inventory, indent=2) + "\n")
    # Keep the publisher's source availability/audit requirements prominent.
    (licenses / "README.txt").write_text(
        "Qt/PySide/Shiboken: Copyright The Qt Company Ltd and contributors.\n"
        "Used under applicable LGPLv3 terms; see LGPL/GPL texts and THIRD_PARTY_NOTICES.md.\n"
        "Unmodified dynamic libraries in _internal may be replaced by interface-compatible builds.\n"
        "Exact versions: dependencies.json and bundle.json. System library inventory: native-libraries.json.\n"
        "Corresponding upstream sources and redistribution checklist: THIRD_PARTY_NOTICES.md, docs/BUILDING.md\n")

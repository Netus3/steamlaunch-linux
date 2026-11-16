"""Build into a new directory; never recursively delete an existing build."""
import argparse
import hashlib
import importlib.metadata
import json
import os
import platform
import shutil
import subprocess
import sys
import tarfile
import uuid
from pathlib import Path
from licenses import collect_native_notices

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from steamlaunch import __version__  # noqa: E402 - also usable before editable installation


def source_files():
    # Explicit allowlist, independent of a developer's gitignore or untracked files.
    allowed = {"steamlaunch": {".py", ".svg"}, "tests": {".py"}, "scripts": {".py", ".sh"},
               "packaging": {".py", ".spec", ".txt", ".sh", ".desktop"}, "docs": {".md"},
               ".github": {".yml", ".yaml", ".md"}}
    for name, extensions in allowed.items():
        for path in (ROOT / name).rglob("*"):
            if path.is_file() and "__pycache__" not in path.parts and path.suffix in extensions:
                yield path
    for name in ["pyproject.toml", "README.md", "README.ru.md", "LICENSE", "CHANGELOG.md",
                 "THIRD_PARTY_NOTICES.md", "CONTRIBUTING.md", "MANIFEST.in", ".gitignore", "run.sh"]:
        path = ROOT / name
        if path.is_file():
            yield path


def archive(output: Path, entries):
    temporary = output.with_name(f".{output.name}.{uuid.uuid4().hex}")
    with tarfile.open(temporary, "w:gz") as tar:
        for path, name in entries:
            tar.add(path, arcname=name, recursive=False)
    os.replace(temporary, output)


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--label", default="local", choices=["local", "release"])
    args = parser.parse_args()
    if platform.machine() not in {"x86_64", "amd64"}:
        raise SystemExit("This release recipe currently targets Linux x86_64 only")
    out = ROOT / "dist"
    out.mkdir(exist_ok=True)
    work = ROOT / "build" / uuid.uuid4().hex
    work.mkdir(parents=True)
    subprocess.run([sys.executable, "-m", "PyInstaller", "--noconfirm", "--clean",
                    "--distpath", str(work / "dist"), "--workpath", str(work / "work"),
                    str(ROOT / "packaging/SteamLaunch.spec")], cwd=ROOT, check=True)
    bundle = work / "dist/SteamLaunch"
    manifest = {"app": "steamlaunch-linux", "version": __version__,
                "architecture": platform.machine(), "libc": platform.libc_ver(),
                "python": platform.python_version(), "label": args.label}
    (bundle / "bundle.json").write_text(json.dumps(manifest, indent=2) + "\n")
    for name in ["LICENSE", "README.md", "README.ru.md", "THIRD_PARTY_NOTICES.md", "CHANGELOG.md"]:
        shutil.copy2(ROOT / name, bundle / name)
    shutil.copy2(ROOT / "packaging/install.sh", bundle / "install.sh")
    (bundle / "install.sh").chmod(0o755)
    # Include the unmodified licensing files distributed with the actual wheels.
    licenses = bundle / "licenses"
    for dependency in ["PySide6-Essentials", "shiboken6", "PyInstaller"]:
        dist = importlib.metadata.distribution(dependency)
        for item in dist.files or []:
            if (any(part.lower() in {"licenses", "license", "copying"} for part in item.parts)
                    or item.name.lower().startswith(("license", "copying"))):
                source = Path(dist.locate_file(item))
                if source.is_file():
                    dest = licenses / dependency / str(item).replace("../", "")
                    dest.parent.mkdir(parents=True, exist_ok=True)
                    shutil.copy2(source, dest)
    # Useful for redistribution/source-offer auditing; no installed user data.
    versions = {name: importlib.metadata.version(name) for name in
                ["PySide6-Essentials", "shiboken6", "PyInstaller", "pyinstaller-hooks-contrib"]}
    (bundle / "dependencies.json").write_text(json.dumps(versions, indent=2) + "\n")
    shutil.copytree(ROOT / "docs", bundle / "docs")
    collect_native_notices(bundle, work / "work/SteamLaunch/native-origins.json")
    name = f"SteamLaunch-{__version__}-linux-x86_64"
    if args.label == "local":
        name += "-local"
    binary = out / f"{name}.tar.gz"
    entries = [(bundle, "SteamLaunch")] + [(p, str(Path("SteamLaunch") / p.relative_to(bundle)))
                                          for p in sorted(bundle.rglob("*"))]
    archive(binary, entries)
    source = out / f"SteamLaunch-{__version__}-source.tar.gz"
    archive(source, [(p, str(Path(f"SteamLaunch-{__version__}") / p.relative_to(ROOT)))
                     for p in sorted(set(source_files()))])
    checksums = out / f"{name}.sha256"
    checksums.write_text("".join(f"{hashlib.sha256(p.read_bytes()).hexdigest()}  {p.name}\n"
                                 for p in [binary, source]))
    print(f"\nBundle: {bundle}\nArchive: {binary}\nSource: {source}\nSHA256: {checksums}")


if __name__ == "__main__":
    main()

#!/usr/bin/env python3
"""Собирает реестр установленных закрепленных пакетов и их исходные лицензии."""

from __future__ import annotations

import email
import json
import re
import shutil
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "shared/licenses"
TEXTS = OUT / "texts"


def license_files(package: Path, name: str) -> list[str]:
    files = [p for p in package.iterdir() if p.is_file() and
             p.name.lower().startswith(("license", "licence", "copying", "notice"))]
    if (package / "licenses").is_dir():
        files.extend(p for p in (package / "licenses").rglob("*") if p.is_file())
    copied = []
    for source in sorted(files):
        target = TEXTS / name / source.relative_to(package)
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copyfile(source, target)
        copied.append(str(target.relative_to(OUT)))
    return copied


def main() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    components = []
    frontend = ROOT / "frontend"
    lock = json.loads((frontend / "package-lock.json").read_text())
    direct = json.loads((frontend / "package.json").read_text())
    for relative, info in sorted(lock["packages"].items()):
        if not relative or info.get("link"):
            continue
        package = frontend / relative
        if not (package / "package.json").is_file():
            continue  # Платформенные optional-пакеты, не установленные на этой ОС.
        meta = json.loads((package / "package.json").read_text())
        name = meta["name"]
        repo = meta.get("repository", {})
        license_value = meta.get("license", info.get("license", "UNKNOWN"))
        if isinstance(license_value, dict):
            license_value = license_value.get("type", "UNKNOWN")
        safe = re.sub(r"[^A-Za-z0-9_.-]", "_", name) + "-" + info["version"]
        components.append({
            "ecosystem": "npm", "name": name, "version": info["version"],
            "direct": name in direct.get("dependencies", {}) or name in direct.get("devDependencies", {}),
            "development": info.get("dev", False), "license": license_value,
            "author": meta.get("author", meta.get("contributors", "See license text")),
            "source": repo.get("url") if isinstance(repo, dict) else repo,
            "registry": "https://www.npmjs.com/package/" + name,
            "texts": license_files(package, safe),
        })

    locks = "\n".join(p.read_text() for p in (ROOT / "backend").glob("requirements*.lock"))
    locked = {re.sub(r"[-_.]+", "-", x.lower()) for x in
              re.findall(r"^([A-Za-z0-9_.-]+)==", locks, flags=re.MULTILINE)}
    pyproject = __import__("tomllib").loads((ROOT / "backend/pyproject.toml").read_text())
    py_direct = {re.split(r"[<>=!~\[]", x)[0].lower() for x in pyproject["project"]["dependencies"]}
    sites = list((ROOT / "backend/.venv/lib").glob("python*/site-packages"))
    if not sites:
        raise SystemExit("Install backend dependencies in backend/.venv first")
    for dist in sorted(sites[0].glob("*.dist-info")):
        meta = email.message_from_string((dist / "METADATA").read_text())
        name = str(meta["Name"])
        if re.sub(r"[-_.]+", "-", name.lower()) not in locked:
            continue
        safe = name + "-" + str(meta["Version"])
        components.append({
            "ecosystem": "pypi", "name": name, "version": meta["Version"],
            "direct": name.lower() in py_direct,
            "license": meta["License-Expression"] or meta["License"] or
                       meta.get_all("Classifier", []),
            "author": meta["Author-email"] or meta["Author"] or "See license text",
            "source": meta.get_all("Project-URL", []) or meta["Home-page"],
            "registry": "https://pypi.org/project/" + name + "/",
            "texts": license_files(dist, safe),
        })
    (OUT / "components.json").write_text(json.dumps({
        "note": "Generated from installed locked packages; original license texts retained. "
                "Optional packages for other operating systems are recorded in package-lock.json.",
        "components": components,
    }, ensure_ascii=False, indent=2) + "\n")
    print(f"Recorded {len(components)} installed components")


if __name__ == "__main__":
    main()

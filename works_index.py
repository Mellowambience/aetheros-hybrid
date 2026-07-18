#!/usr/bin/env python3
"""
works_index.py — converge the user's life's work into one registry.

Scans C:\\Users\\nator for real project repos (git / package.json / pyproject.toml /
README.md / SKILL.md), extracts a name + path + one-line description, and writes
works.json. Local-only. No cloud, no secrets.

This is the "final seal": every project you've built becomes addressable from the
single console. The console reads works.json and exposes `works` / `open <name>`.
"""
from __future__ import annotations
import json, re, os
from pathlib import Path

HOME = Path.home()                       # C:\Users\nator
OUT = Path(__file__).resolve().parent / "works.json"

# Directories that are system / not projects — never index these.
SKIP = {
    "AppData", "Application Data", "Contacts", "Cookies", "Desktop", "Documents",
    "Downloads", "Links", "Music", "Pictures", "Videos", "Saved Games",
    "Searches", "Favorites", "3D Objects", "Creative Cloud Files",
    "Creative Cloud Files Personal Account natorretti11@gmail.com 23BD0DFF561E64067F000101@AdobeID",
    "Claude", "bin", "cargo", "clones", "archive", "catfish-scanner", "chim-sd",
    "dataconnect", "dataconnect-generated", "analysis", "ansel", "beaconwatch",
    "bountyops", "clawd_backups", "clawd-dev", "creative-hub", "~", "__pycache__",
    "7zip", "AndroidStudioProjects", "DisneyCraftFinal", "temp_eas", "tools",
    "x-grok-sidebar", "grok-gaze-extension", "our-own-citewise", "skills-inspect",
    "functions", "UE58_Atlas", "agentic_mmo_world", "forgekit", "mist-clone-forge",
    "little_lamb_lantern", "self-prompting-agent", "hybrid-vault-lint", "opencut-inspect",
    "sonic-screwdriver-v2", "sovereign-agent", "first-spark", "G0DM0D3", "Game-untold",
}

MARKERS = (".git/config", "package.json", "pyproject.toml", "README.md", "SKILL.md", "Cargo.toml", "go.mod")


def is_project(d: Path) -> bool:
    if d.name in SKIP or d.name.startswith("."):
        return False
    if not d.is_dir():
        return False
    if any((d / m).exists() for m in MARKERS):
        return True
    # also treat dirs that contain a skills/ folder as projects
    if (d / "skills").is_dir():
        return True
    return False


def describe(d: Path) -> str:
    # Prefer the first non-empty line of README / SKILL as a description.
    for fn in ("README.md", "SKILL.md", "ABOUT.md", "ABOUT.txt"):
        p = d / fn
        if p.exists():
            try:
                for line in p.read_text(encoding="utf-8", errors="ignore").splitlines():
                    s = line.strip().lstrip("#").strip()
                    if len(s) > 12 and not s.lower().startswith(("##", "===", "```")):
                        return s[:120]
            except Exception:
                pass
    # fall back to a humanized dir name
    name = d.name.replace("-", " ").replace("_", " ")
    return name[:120]


def main():
    items = []
    for d in sorted(HOME.iterdir()):
        if not is_project(d):
            continue
        try:
            git = (d / ".git" / "config").exists()
            items.append({
                "name": d.name,
                "path": str(d),
                "git": git,
                "desc": describe(d),
            })
        except Exception:
            pass
    items.sort(key=lambda x: x["name"].lower())
    OUT.write_text(json.dumps({"count": len(items), "generated": True, "projects": items}, indent=2), encoding="utf-8")
    print(f"indexed {len(items)} projects -> {OUT}")


if __name__ == "__main__":
    main()

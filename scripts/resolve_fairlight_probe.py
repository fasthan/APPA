#!/usr/bin/env python3
"""Probe DaVinci Resolve Studio and verify basic Fairlight scripting access."""

from __future__ import annotations

import json
import os
import sys
from pathlib import Path


DEFAULT_SCRIPT_API = (
    "/Library/Application Support/Blackmagic Design/DaVinci Resolve/Developer/Scripting"
)
DEFAULT_MODULES = f"{DEFAULT_SCRIPT_API}/Modules"


def load_resolve():
    module_path = os.environ.get("RESOLVE_SCRIPT_API", DEFAULT_SCRIPT_API)
    modules_dir = os.environ.get("RESOLVE_SCRIPT_MODULES", f"{module_path}/Modules")
    if modules_dir not in sys.path:
        sys.path.append(modules_dir)

    try:
        import DaVinciResolveScript as dvr  # type: ignore
    except ImportError as exc:
        raise SystemExit(
            "Could not import DaVinciResolveScript.\n"
            f"Tried module path: {modules_dir}\n"
            "Set RESOLVE_SCRIPT_API or RESOLVE_SCRIPT_MODULES if your install differs."
        ) from exc

    resolve = dvr.scriptapp("Resolve")
    if not resolve:
        raise SystemExit(
            "DaVinci Resolve is not reachable. Start Resolve Studio and enable\n"
            "Preferences > General > External scripting using > Local."
        )
    return resolve


def main() -> int:
    resolve = load_resolve()

    project_manager = resolve.GetProjectManager()
    project = project_manager.GetCurrentProject() if project_manager else None
    timeline = project.GetCurrentTimeline() if project else None

    page_before = resolve.GetCurrentPage()
    open_fairlight_ok = resolve.OpenPage("fairlight")
    page_after = resolve.GetCurrentPage()

    fairlight_presets = resolve.GetFairlightPresets()
    if isinstance(fairlight_presets, dict):
        fairlight_presets = list(fairlight_presets.keys())

    payload = {
        "product": resolve.GetProductName(),
        "version": resolve.GetVersionString(),
        "page_before": page_before,
        "open_fairlight_ok": open_fairlight_ok,
        "page_after": page_after,
        "project_name": project.GetName() if project else None,
        "timeline_name": timeline.GetName() if timeline else None,
        "audio_track_count": timeline.GetTrackCount("audio") if timeline else None,
        "fairlight_preset_count": len(fairlight_presets or []),
        "fairlight_presets": fairlight_presets or [],
        "script_api_root": os.environ.get("RESOLVE_SCRIPT_API", DEFAULT_SCRIPT_API),
        "modules_dir": os.environ.get("RESOLVE_SCRIPT_MODULES", DEFAULT_MODULES),
    }
    print(json.dumps(payload, ensure_ascii=False, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

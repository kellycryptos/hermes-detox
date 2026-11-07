"""File listing content-aware extractor for Hermes Detox.

Parses outputs from find, ls -laR, tree, and dir /s:
- Total file and directory counts
- Top-level directory branches and distribution
- Notable file matches (e.g. package.json, Cargo.toml, .env, Dockerfile)
"""

from __future__ import annotations

import re
from typing import Any, Dict, List, Optional, Set

_NOTABLE_FILES = {
    "package.json", "tsconfig.json", "cargo.toml", "pyproject.toml",
    "requirements.txt", "dockerfile", "docker-compose.yml", "makefile",
    "cmakelists.txt", ".gitignore", ".env", "readme.md", "license",
    "go.mod", "pom.xml", "build.gradle",
}

_PATH_LINE_RE = re.compile(r"^(?:\./|[a-zA-Z]:[\\/]|/|[d\-]r[w\-][x\-]).+")


def extract_file_listing_summary(raw_output: str) -> Optional[Dict[str, Any]]:
    """Detect and summarize file and directory listings."""
    lines = raw_output.splitlines()
    if len(lines) < 15:
        return None

    path_matches = 0
    notable_found: List[str] = []
    top_dirs: Dict[str, int] = {}
    total_entries = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        # Check for ls -l style or find style paths
        parts = stripped.split()
        entry_path = parts[-1] if len(parts) >= 8 and parts[0].startswith(("-", "d", "l")) else stripped

        if "/" in entry_path or "\\" in entry_path:
            path_matches += 1
            total_entries += 1

            # Extract top folder
            norm = entry_path.replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            top = norm.split("/")[0] if "/" in norm else "."
            top_dirs[top] = top_dirs.get(top, 0) + 1

            filename = norm.split("/")[-1].lower()
            if filename in _NOTABLE_FILES and norm not in notable_found:
                notable_found.append(norm)

    # Confidence check: at least 40% of lines should match file path shapes
    if path_matches < len(lines) * 0.4:
        return None

    sorted_dirs = sorted(top_dirs.items(), key=lambda kv: kv[1], reverse=True)[:8]

    summary_lines = [
        "Category: File / Directory Listing",
        f"Total Entries: {total_entries:,}",
        f"Top Directories: " + ", ".join(f"{d} ({c})" for d, c in sorted_dirs),
    ]

    if notable_found:
        summary_lines.append("")
        summary_lines.append(f"Notable Files ({len(notable_found)} detected):")
        for f in notable_found[:15]:
            summary_lines.append(f"  • {f}")

    return {
        "content_type": "text/x-file-listing",
        "total_entries": total_entries,
        "notable_files": notable_found,
        "summary_text": "\n".join(summary_lines),
    }

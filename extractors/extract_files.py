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
    "cmakelists.txt", ".gitignore", ".env", ".env.example", "readme.md", "license",
    "go.mod", "pom.xml", "build.gradle",
}

_PATH_LINE_RE = re.compile(r"^(?:\./|[a-zA-Z]:[\\/]|/|[d\-]r[w\-][x\-]).+")
_TREE_PREFIX_RE = re.compile(r"^[│├└─\|\s\+\`\-]+")


def extract_file_listing_summary(raw_output: str) -> Optional[Dict[str, Any]]:
    """Detect and summarize file and directory listings."""
    lines = raw_output.splitlines()
    if len(lines) < 15:
        return None

    is_tree_format = any(m in raw_output for m in ("├──", "└──", "directories,", "files"))
    path_matches = 0
    notable_found: List[str] = []
    top_dirs: Dict[str, int] = {}
    total_entries = 0

    for line in lines:
        stripped = line.strip()
        if not stripped:
            continue

        has_tree_prefix = bool(_TREE_PREFIX_RE.match(stripped))
        clean_entry = _TREE_PREFIX_RE.sub("", stripped).strip()
        if not clean_entry:
            continue

        # Check for ls -l style or find style paths
        parts = stripped.split()
        entry_path = parts[-1] if len(parts) >= 8 and parts[0].startswith(("-", "d", "l")) else clean_entry

        filename = clean_entry.split("/")[-1].split("\\")[-1].lower()
        is_path_or_notable = (
            has_tree_prefix
            or ("/" in entry_path)
            or ("\\" in entry_path)
            or (filename in _NOTABLE_FILES)
            or filename.startswith(".env")
            or (is_tree_format and ("." in clean_entry or "/" in clean_entry))
        )

        if is_path_or_notable:
            path_matches += 1
            total_entries += 1

            # Extract top folder
            norm = clean_entry.replace("\\", "/")
            if norm.startswith("./"):
                norm = norm[2:]
            top = norm.split("/")[0] if "/" in norm else "."
            if top != "." and not top.startswith("."):
                top_dirs[top] = top_dirs.get(top, 0) + 1

            if (filename in _NOTABLE_FILES or filename.startswith(".env")) and clean_entry not in notable_found:
                notable_found.append(clean_entry)

    # Confidence check: at least 40% of lines should match file path shapes
    if path_matches < len(lines) * 0.4 and not is_tree_format:
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

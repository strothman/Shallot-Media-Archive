"""
Automated Documentation and Changelog Updater
Inspects recent git commits, updates the last-updated date badges in README.md,
and synchronizes changelog entries.
"""

import os
import re
import subprocess
from datetime import datetime

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
README_PATH = os.path.join(REPO_ROOT, "README.md")
CHANGELOG_PATH = os.path.join(REPO_ROOT, "CHANGELOG.md")


def get_git_commits(limit: int = 30):
    """Fetches recent git commits formatted as (hash, date, message)."""
    try:
        cmd = ["git", "log", f"-n{limit}", "--pretty=format:%h|%ad|%s", "--date=short"]
        res = subprocess.run(cmd, cwd=REPO_ROOT, capture_output=True, text=True, check=True)
        lines = res.stdout.strip().split("\n")
        commits = []
        for line in lines:
            if not line:
                continue
            parts = line.split("|", 2)
            if len(parts) == 3:
                commits.append({"hash": parts[0], "date": parts[1], "msg": parts[2]})
        return commits
    except Exception as e:
        print(f"Error reading git log: {e}")
        return []


def update_readme_date():
    """Updates the Last Updated badge in README.md with today's date."""
    if not os.path.exists(README_PATH):
        return False

    today_str = datetime.now().strftime("%Y--%m--%d")
    with open(README_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Pattern matches [![Last Updated](...)]
    new_badge = f"[![Last Updated](https://img.shields.io/badge/last%20updated-{today_str}-success.svg)](CHANGELOG.md)"
    updated_content = re.sub(
        r'\[\!\[Last Updated\]\(https://img\.shields\.io/badge/last%20updated-[^)]+\)\]\(CHANGELOG\.md\)',
        new_badge,
        content
    )

    if updated_content != content:
        with open(README_PATH, "w", encoding="utf-8") as f:
            f.write(updated_content)
        print(f"Updated README.md badge date to: {today_str}")
        return True
    return False


def sync_unreleased_changelog():
    """Appends recent unreleased commits into CHANGELOG.md if not present."""
    if not os.path.exists(CHANGELOG_PATH):
        return False

    commits = get_git_commits(limit=20)
    if not commits:
        return False

    with open(CHANGELOG_PATH, "r", encoding="utf-8") as f:
        content = f.read()

    # Look for [Unreleased] section or create one
    feats = []
    fixes = []
    others = []

    for c in commits:
        msg = c["msg"]
        # Skip automated doc sync commits
        if "[skip ci]" in msg or "docs: auto-update changelog" in msg:
            continue
        # Check if commit message is already in changelog
        if msg in content or c["hash"] in content:
            continue

        if msg.lower().startswith("feat"):
            clean_msg = re.sub(r'^[a-zA-Z]+(\([^)]+\))?!?:', '', msg).strip()
            feats.append(f"- {clean_msg} ({c['hash']})")
        elif msg.lower().startswith("fix"):
            clean_msg = re.sub(r'^[a-zA-Z]+(\([^)]+\))?!?:', '', msg).strip()
            fixes.append(f"- {clean_msg} ({c['hash']})")
        else:
            others.append(f"- {msg} ({c['hash']})")

    if not feats and not fixes and not others:
        print("CHANGELOG is already up to date with recent commits.")
        return False

    new_entries = []
    if feats:
        new_entries.append("### Added\n" + "\n".join(feats))
    if fixes:
        new_entries.append("### Fixed\n" + "\n".join(fixes))
    if others:
        new_entries.append("### Changed\n" + "\n".join(others))

    entry_block = "\n\n".join(new_entries)

    if "## [Unreleased]" in content:
        updated = content.replace("## [Unreleased]\n", f"## [Unreleased]\n\n{entry_block}\n")
    else:
        # Insert [Unreleased] right after the header
        insert_pos = content.find("## [")
        if insert_pos != -1:
            updated = content[:insert_pos] + f"## [Unreleased]\n\n{entry_block}\n\n---\n\n" + content[insert_pos:]
        else:
            updated = content + f"\n\n## [Unreleased]\n\n{entry_block}\n"

    with open(CHANGELOG_PATH, "w", encoding="utf-8") as f:
        f.write(updated)

    print(f"Updated CHANGELOG.md with {len(feats) + len(fixes) + len(others)} new items.")
    return True


if __name__ == "__main__":
    readme_updated = update_readme_date()
    changelog_updated = sync_unreleased_changelog()
    if readme_updated or changelog_updated:
        print("Documentation sync completed successfully.")
    else:
        print("All documentation is currently up to date.")

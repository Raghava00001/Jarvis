import fnmatch
import os
import subprocess
import zipfile

# Never ship these, even if they are present on disk or accidentally tracked:
# personal databases, face photos/biometrics, logs, secrets, caches.
EXCLUDE_PATTERNS = [
    "*.db", "*.db-journal", "*.sqlite", "*.pkl", "*.log",
    ".env", "*.env", "client_secret_*.json", "*credentials*.json", "token*.json",
    "jarvis/data/faces/*", "jarvis/data/memory/*.db", "jarvis/logs/*",
    "jarvis_data/*", "jarvis/tests/jarvis_data/*",
    "*.wav", "*.mp3", "*.zip", "recovered_chat_history.md",
    "*/__pycache__/*", "*.pyc", ".pytest_cache/*", ".venv/*", ".git/*",
]

# Top-level items to ship (directories recursively).
INCLUDES = [
    "jarvis", "tests", ".github", "docs",
    "requirements.txt", "README.md", "LICENSE", "RELEASE_SUMMARY.md",
    "START_HERE.md", "start_jarvis.bat", "COMPLETE_PROJECT_JOURNEY.md",
    "JARVIS_Project_Documentation.md", ".env.example", ".gitignore",
]


def is_excluded(rel_path: str) -> bool:
    rel_path = rel_path.replace("\\", "/")
    name = rel_path.rsplit("/", 1)[-1]
    return any(fnmatch.fnmatch(rel_path, p) or fnmatch.fnmatch(name, p)
               for p in EXCLUDE_PATTERNS)


def tracked_files(root_dir: str):
    """Files tracked by git (so local user data never sneaks in), or None."""
    try:
        # Tracked files plus new, not-yet-committed files that .gitignore allows.
        out = subprocess.run(["git", "ls-files", "--cached", "--others", "--exclude-standard"],
                             cwd=root_dir, capture_output=True, text=True, check=True).stdout
        return [line for line in out.splitlines() if line]
    except (OSError, subprocess.CalledProcessError):
        return None


def candidate_files(root_dir: str):
    tracked = tracked_files(root_dir)
    if tracked is not None:
        for rel in tracked:
            top = rel.split("/", 1)[0]
            if top in INCLUDES and os.path.isfile(os.path.join(root_dir, rel)):
                yield rel
        return
    # Fallback when git is unavailable: walk the include list.
    for item in INCLUDES:
        path = os.path.join(root_dir, item)
        if os.path.isfile(path):
            yield item
        elif os.path.isdir(path):
            for dirpath, _, files in os.walk(path):
                for f in files:
                    yield os.path.relpath(os.path.join(dirpath, f), root_dir).replace("\\", "/")


def create_release_zip(output_filename="jarvis-v2.6.0.zip"):
    """
    Package the repository into a clean release ZIP for a GitHub release.
    Only git-tracked files are included, and EXCLUDE_PATTERNS is applied on top
    so personal data (chat/memory databases, face data, logs, keys) is never shipped.
    """
    root_dir = os.path.dirname(os.path.abspath(__file__))
    zip_path = os.path.join(root_dir, output_filename)

    print("==================================================")
    print(" J.A.R.V.I.S. Release Packaging Utility")
    print("==================================================")
    print(f"Bundling files into: {output_filename}...\n")

    count = skipped = 0
    with zipfile.ZipFile(zip_path, "w", zipfile.ZIP_DEFLATED) as zipf:
        for rel in candidate_files(root_dir):
            if is_excluded(rel):
                skipped += 1
                print(f"  [Excluded] {rel}")
                continue
            zipf.write(os.path.join(root_dir, rel), rel)
            count += 1

    print(f"\nSuccessfully packaged {count} files ({skipped} excluded).")
    print(f"Output ZIP: {zip_path}")
    print(f"File Size:  {os.path.getsize(zip_path) / (1024 * 1024):.2f} MB")
    print("==================================================")


if __name__ == "__main__":
    create_release_zip()

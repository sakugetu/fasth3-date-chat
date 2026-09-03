from __future__ import annotations

import argparse
import re
import sys
import tarfile
import zipfile
from pathlib import Path, PurePosixPath


TEXT_SUFFIXES = {
    "",
    ".bat",
    ".css",
    ".html",
    ".ini",
    ".js",
    ".json",
    ".md",
    ".ps1",
    ".py",
    ".sh",
    ".toml",
    ".txt",
    ".yaml",
    ".yml",
}
RUNTIME_PREFIXES = (
    PurePosixPath("data/characters"),
    PurePosixPath("data/scenarios"),
    PurePosixPath("data/sessions"),
    PurePosixPath("logs"),
    PurePosixPath("media/turns"),
    PurePosixPath("work"),
)
PATTERNS = {
    "private IPv4 address": re.compile(
        r"(?<!\d)(?:10(?:\.\d{1,3}){3}|192\.168(?:\.\d{1,3}){2}|172\.(?:1[6-9]|2\d|3[01])(?:\.\d{1,3}){2})(?!\d)"
    ),
    "Windows absolute path": re.compile(r"(?i)(?<![A-Za-z0-9])[A-Z]:[\\/](?:[^\s'\"<>|]+)"),
    "UNC path": re.compile(r"\\\\[A-Za-z0-9_.-]+\\[A-Za-z0-9_$.-]+"),
    "probable API secret": re.compile(
        r"(?i)(?:api[_-]?key|access[_-]?token|secret[_-]?key)\s*[:=]\s*['\"]?[A-Za-z0-9_./+\-=]{16,}"
    ),
    "probable hosted-service token": re.compile(r"\b(?:gh[pousr]_[A-Za-z0-9]{20,}|sk-[A-Za-z0-9]{20,})\b"),
}


def is_runtime_file(relative: PurePosixPath) -> bool:
    return any(relative == prefix or prefix in relative.parents for prefix in RUNTIME_PREFIXES)


def inspect_text(label: str, text: str, forbidden: list[str], issues: list[str]) -> None:
    folded = text.casefold()
    for value in forbidden:
        if value.casefold() in folded:
            issues.append(f"{label}: forbidden text found")
    for description, pattern in PATTERNS.items():
        if pattern.search(text):
            issues.append(f"{label}: {description}")


def inspect_name(label: str, forbidden: list[str], issues: list[str]) -> None:
    folded = label.casefold()
    for value in forbidden:
        if value.casefold() in folded:
            issues.append(f"{label}: forbidden text found in path")


def inspect_archive(path: Path, relative: str, forbidden: list[str], issues: list[str]) -> None:
    try:
        if zipfile.is_zipfile(path):
            with zipfile.ZipFile(path) as archive:
                for member in archive.infolist():
                    inspect_name(f"{relative}!{member.filename}", forbidden, issues)
                    if Path(member.filename).suffix.lower() in TEXT_SUFFIXES and member.file_size <= 2_000_000:
                        data = archive.read(member).decode("utf-8", errors="replace")
                        inspect_text(f"{relative}!{member.filename}", data, forbidden, issues)
        elif tarfile.is_tarfile(path):
            with tarfile.open(path) as archive:
                for member in archive.getmembers():
                    inspect_name(f"{relative}!{member.name}", forbidden, issues)
                    if member.isfile() and Path(member.name).suffix.lower() in TEXT_SUFFIXES and member.size <= 2_000_000:
                        handle = archive.extractfile(member)
                        if handle is not None:
                            inspect_text(
                                f"{relative}!{member.name}",
                                handle.read().decode("utf-8", errors="replace"),
                                forbidden,
                                issues,
                            )
    except (OSError, tarfile.TarError, zipfile.BadZipFile) as exc:
        issues.append(f"{relative}: archive inspection failed: {exc}")


def audit(root: Path, forbidden: list[str]) -> list[str]:
    issues: list[str] = []
    for path in sorted(root.rglob("*")):
        if ".git" in path.relative_to(root).parts:
            continue
        relative_path = path.relative_to(root)
        relative = relative_path.as_posix()
        inspect_name(relative, forbidden, issues)
        if not path.is_file():
            continue
        if is_runtime_file(PurePosixPath(relative)):
            issues.append(f"{relative}: runtime/private file must not be released")
        suffix = path.suffix.lower()
        if suffix in {".zip", ".tar", ".tgz", ".gz"}:
            inspect_archive(path, relative, forbidden, issues)
        if suffix in TEXT_SUFFIXES and path.stat().st_size <= 2_000_000:
            inspect_text(relative, path.read_text(encoding="utf-8", errors="replace"), forbidden, issues)
    return issues


def main() -> int:
    parser = argparse.ArgumentParser(description="Audit a release tree for local or private data")
    parser.add_argument("root", nargs="?", default=".")
    parser.add_argument("--forbid", action="append", default=[], help="additional text to reject")
    args = parser.parse_args()
    root = Path(args.root).resolve()
    if not root.is_dir():
        print(f"ERROR: not a directory: {root}", file=sys.stderr)
        return 2
    issues = audit(root, [value for value in args.forbid if value])
    if issues:
        print("RELEASE_AUDIT=FAIL")
        for issue in issues:
            print(f"- {issue}")
        return 1
    files = sum(1 for path in root.rglob("*") if path.is_file() and ".git" not in path.relative_to(root).parts)
    print("RELEASE_AUDIT=PASS")
    print(f"FILES_SCANNED={files}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

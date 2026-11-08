"""ini-validator-cli: check INI files parse cleanly, fail CI on a bad line.

Reads one or more INI files (or folders of them), checks each one the
way Python's configparser reads it, and reports every problem with
file, line number, and reason. Report-only: it never rewrites a file.
Exit 0 when every file is clean, 1 when any problem is found,
2 for a usage error.
"""

import argparse
import fnmatch
import json
import os
import re
import sys
from pathlib import Path

__version__ = "1.0.0"

INI_EXTENSIONS = {".ini", ".cfg", ".conf"}
SECTION_RE = re.compile(r"\[([^\]]*)\]")


class Problem:
    """One problem in one file: path, line number, plain reason."""

    def __init__(self, path, line, reason):
        self.path = path
        self.line = line
        self.reason = reason

    def text(self):
        return f"{self.path}:{self.line}: {self.reason}"

    def as_dict(self):
        return {"file": self.path, "line": self.line, "reason": self.reason}


def scan_text(text, label, allow_no_value=False):
    """Check one INI document (as text) and return its problems.

    Follows the rules of configparser.RawConfigParser with strict=True:
    a line is blank, a comment (# or ;), a section header, a key line,
    or a continuation of the previous value. Anything else is a
    problem. Every problem is reported, not just the first.
    """
    problems = []
    sections = {}  # section name -> set of lower-cased option names
    current_section = None
    current_option = None

    for lineno, raw in enumerate(text.splitlines(), start=1):
        stripped = raw.strip()
        if not stripped:
            continue
        if stripped[0] in "#;":
            continue
        if raw[0].isspace() and current_option is not None:
            continue  # continuation of the previous value
        if stripped.startswith("["):
            match = SECTION_RE.match(stripped)
            if match is None:
                problems.append(Problem(label, lineno,
                    "section header is missing its closing ']'"))
                current_option = None
                continue
            name = match.group(1)
            if name == "":
                problems.append(Problem(label, lineno,
                    "section header is empty"))
                current_option = None
                continue
            if name in sections:
                problems.append(Problem(label, lineno,
                    f"section '{name}' already exists"))
            else:
                sections[name] = set()
            current_section = name
            current_option = None
            continue
        if current_section is None:
            problems.append(Problem(label, lineno,
                "key or value appears before any section header"))
            continue
        # Find the first value delimiter, = or :.
        equals = stripped.find("=")
        colon = stripped.find(":")
        if equals == -1 and colon == -1:
            cut = -1
        elif equals == -1:
            cut = colon
        elif colon == -1:
            cut = equals
        else:
            cut = min(equals, colon)
        if cut == -1:
            if allow_no_value:
                option = stripped
                if option.lower() in sections[current_section]:
                    problems.append(Problem(label, lineno,
                        f"option '{option}' in section "
                        f"'{current_section}' already exists"))
                else:
                    sections[current_section].add(option.lower())
                current_option = option
            else:
                problems.append(Problem(label, lineno,
                    f"key '{stripped}' has no value"))
            continue
        option = stripped[:cut].rstrip()
        if option == "":
            problems.append(Problem(label, lineno, "key name is empty"))
            continue
        if option.lower() in sections[current_section]:
            problems.append(Problem(label, lineno,
                f"option '{option}' in section '{current_section}' "
                "already exists"))
        else:
            sections[current_section].add(option.lower())
        current_option = option
    return problems


def check_file(path, allow_no_value=False):
    """Check one file on disk.

    Returns (problems, error). problems is a list of Problem; error is
    a message string when the file cannot be read at all, else None.
    """
    try:
        raw = Path(path).read_bytes()
    except OSError as exc:
        return None, f"cannot read {path}: {exc.strerror or exc}"
    if b"\x00" in raw:
        line = raw[:raw.index(b"\x00")].count(b"\n") + 1
        return [Problem(str(path), line,
            "file contains a null byte, it is not a text file")], None
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        line = raw[:exc.start].count(b"\n") + 1
        return [Problem(str(path), line,
            "file is not valid UTF-8")], None
    return scan_text(text, str(path), allow_no_value), None


def collect(paths, recursive=True, exclude=()):
    """Expand files and folders into a sorted list of INI files.

    A file given directly is always checked, whatever its name. A
    folder is walked for .ini, .cfg, and .conf files. .git folders
    are never walked, and directory links are never followed.
    """
    found = []
    seen = set()
    for given in paths:
        path = Path(given)
        if path.is_file():
            if path not in seen:
                seen.add(path)
                found.append(path)
        elif path.is_dir():
            for root, dirs, files in os.walk(path, followlinks=False):
                dirs[:] = [d for d in dirs
                           if d != ".git"
                           and not any(fnmatch.fnmatch(d, pat)
                                       for pat in exclude)]
                if not recursive:
                    dirs[:] = []
                for name in files:
                    if any(fnmatch.fnmatch(name, pat) for pat in exclude):
                        continue
                    candidate = Path(root) / name
                    if candidate.suffix.lower() in INI_EXTENSIONS:
                        if candidate not in seen:
                            seen.add(candidate)
                            found.append(candidate)
        else:
            raise FileNotFoundError(given)
    return sorted(found, key=str)


def check_paths(paths, recursive=True, exclude=(), allow_no_value=False):
    """Check every file found under paths. Returns (problems, checked)."""
    problems = []
    try:
        files = collect(paths, recursive, exclude)
    except FileNotFoundError as exc:
        return None, None, f"no such file or folder: {exc}"
    for path in files:
        file_problems, error = check_file(path, allow_no_value)
        if error is not None:
            return None, None, error
        problems.extend(file_problems)
    return problems, len(files), None


def format_report(problems, checked):
    """Human-readable report lines and the summary line."""
    lines = [problem.text() for problem in problems]
    bad_files = len({problem.path for problem in problems})
    if problems:
        summary = (f"Checked {checked} file(s), {len(problems)} "
                   f"problem(s) in {bad_files} file(s).")
    else:
        summary = (f"OK — {checked} file(s) checked, "
                   "all INI files are valid.")
    return lines, summary


def main(argv=None):
    parser = argparse.ArgumentParser(
        prog="ini-validator-cli",
        description="Check INI files parse cleanly, fail CI on a bad line.")
    parser.add_argument("paths", nargs="*",
                        help="INI files or folders to check")
    parser.add_argument("--stdin", action="store_true",
                        help="check one INI file read from standard input")
    parser.add_argument("--json", action="store_true",
                        help="print the result as JSON "
                        "(human-readable lines go to standard error)")
    parser.add_argument("--no-recursive", action="store_true",
                        help="do not walk into subfolders")
    parser.add_argument("--exclude", action="append", default=[],
                        metavar="PATTERN",
                        help="skip files and folders whose name matches "
                        "PATTERN (repeatable)")
    parser.add_argument("--allow-no-value", action="store_true",
                        help="allow keys with no value, like "
                        "configparser's allow_no_value")
    parser.add_argument("--version", action="version",
                        version=f"ini-validator-cli {__version__}")
    args = parser.parse_args(argv)

    if not args.paths and not args.stdin:
        parser.error("give at least one file or folder, or --stdin")

    problems = []
    checked = 0
    if args.stdin:
        text = sys.stdin.read()
        problems.extend(scan_text(text, "<stdin>", args.allow_no_value))
        checked += 1
    if args.paths:
        found, count, error = check_paths(
            args.paths, not args.no_recursive, args.exclude,
            args.allow_no_value)
        if error is not None:
            print(error, file=sys.stderr)
            return 2
        problems.extend(found)
        checked += count

    lines, summary = format_report(problems, checked)
    if args.json:
        for line in lines:
            print(line, file=sys.stderr)
        print(json.dumps({
            "files_checked": checked,
            "problems": [problem.as_dict() for problem in problems],
            "files_with_problems": len({p.path for p in problems}),
        }, indent=2))
    else:
        for line in lines:
            print(line)
        print(summary)
    return 1 if problems else 0


if __name__ == "__main__":
    sys.exit(main())

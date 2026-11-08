"""Tests for ini-validator-cli. Standard library only."""

import ast
import configparser
import io
import json
import os
import re
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
ROOT = HERE.parent
SRC = ROOT / "src" / "ini_validator.py"

sys.path.insert(0, str(ROOT / "src"))
import ini_validator
from ini_validator import Problem, check_file, collect, scan_text


def problems_as_tuples(text, **kwargs):
    return [(p.line, p.reason) for p in scan_text(text, "test.ini", **kwargs)]


def configparser_error_line(exc):
    """Line number configparser reports for a parse failure, or None."""
    lineno = getattr(exc, "lineno", None)
    if lineno is not None:
        return lineno
    errors = getattr(exc, "errors", None)
    if errors:
        return errors[0][0]
    match = re.search(r"\[line\s+(\d+)\]", str(exc))
    return int(match.group(1)) if match else None


# Every snippet the scanner was probed against with configparser.
# (name, text) — validity and first error line must agree with
# configparser.RawConfigParser(strict=True) on every one.
CROSS_CHECK_CORPUS = [
    ("clean", "[sec]\nkey = 1\n"),
    ("unclosed header", "[sec\nkey = 1\n"),
    ("header trailing junk", "[sec] junk\nkey = 1\n"),
    ("empty header", "[]\nkey = 1\n"),
    ("bare key", "[sec]\nbarekey\n"),
    ("empty value", "[sec]\nkey =\n"),
    ("colon delimiter", "[sec]\nkey: value\n"),
    ("key before section", "key = 1\n[sec]\na = 1\n"),
    ("duplicate section", "[s]\na=1\n[s]\nb=2\n"),
    ("duplicate key", "[s]\na=1\na=2\n"),
    ("duplicate key case", "[s]\nKey=1\nkey=2\n"),
    ("same key other section", "[s]\na=1\n[t]\na=2\n"),
    ("continuation", "[s]\nkey = one\n  two\n"),
    ("indented stray line", "[s]\n  stray\n"),
    ("bad line", "[s]\n@@@\n"),
    ("empty file", ""),
    ("only comments", "# hi\n; yo\n"),
    ("section with spaces", "[ my sec ]\nkey = 1\n"),
    ("key with spaces", "[s]\nmy key = 1\n"),
    ("percent value", "[s]\nkey = 100%\n"),
    ("colon no value", "[s]\nkey:\n"),
    ("line starts with equals", "[s]\n= 1\n"),
    ("tab continuation", "[s]\nkey = one\n\ttwo\n"),
    ("indented key line", "[s]\n  key = 1\n"),
    ("continuation after blank", "[s]\nkey = one\n\n  two\n"),
    ("continuation after comment", "[s]\nkey = one\n# note\n  two\n"),
    ("indented line after new section", "[s]\nkey = one\n[t]\n  two\n"),
    ("indented comment", "[s]\n  # note\nkey = 1\n"),
    ("indented section", "  [s]\nkey = 1\n"),
    ("tab key", "[s]\n\tkey = 1\n"),
    ("equals in value", "[s]\nkey = a=b\n"),
    ("colon in key", "[s]\nmy:key = 1\n"),
    ("equals in section", "[s=x]\nkey = 1\n"),
    ("empty key name", "[s]\n = 1\n"),
    ("spaces only value", "[s]\nkey =   \n"),
    ("unclosed header after section", "[a]\nx=1\n[bad\n"),
    ("duplicate section trailing junk", "[s]\na=1\n[s] junk\nb=2\n"),
    ("header bracket junk", "[a]b\nkey=1\n"),
    ("sections differ by case", "[S]\na=1\n[s]\nb=2\n"),
    ("duplicate key after blank", "[s]\na=1\n\na=2\n"),
    ("duplicate key after comment", "[s]\na=1\n# c\na=2\n"),
    ("continuation looks like key", "[s]\nkey = one\n  key2 = two\n"),
    ("indented comment after key", "[s]\nkey = one\n  # note\n"),
    ("indented semicolon after key", "[s]\nkey = one\n  ; note\n"),
    ("whitespace line then continuation", "[s]\nkey = one\n   \n  two\n"),
    ("indented section after key", "[s]\nkey = one\n  [t]\n"),
    ("indented empty header after key", "[s]\nkey = one\n  []\n"),
    ("header extra bracket", "[a]b]c\nkey=1\n"),
]


class TestScanValid(unittest.TestCase):
    def test_clean_file(self):
        self.assertEqual(scan_text("[server]\nhost = x\nport = 1\n", "f"), [])

    def test_empty_and_comments_only(self):
        self.assertEqual(scan_text("", "f"), [])
        self.assertEqual(scan_text("# note\n; also\n\n", "f"), [])

    def test_both_delimiters(self):
        self.assertEqual(scan_text("[s]\na = 1\nb: 2\n", "f"), [])

    def test_empty_values(self):
        self.assertEqual(scan_text("[s]\na =\nb:\n", "f"), [])

    def test_key_with_spaces(self):
        self.assertEqual(scan_text("[s]\nmy key = 1\n", "f"), [])

    def test_section_with_spaces(self):
        self.assertEqual(scan_text("[ my sec ]\nkey = 1\n", "f"), [])

    def test_multiline_value(self):
        self.assertEqual(scan_text("[s]\nkey = one\n  two\n\ttwo\n", "f"), [])

    def test_continuation_across_blank_and_comment(self):
        self.assertEqual(
            scan_text("[s]\nkey = one\n\n# note\n  two\n", "f"), [])

    def test_indented_key_and_section(self):
        self.assertEqual(scan_text("  [s]\n  key = 1\n", "f"), [])

    def test_percent_value(self):
        self.assertEqual(scan_text("[s]\nkey = 100%\n", "f"), [])

    def test_header_trailing_junk(self):
        self.assertEqual(scan_text("[s] junk\nkey = 1\n", "f"), [])

    def test_same_key_in_other_section(self):
        self.assertEqual(scan_text("[s]\na=1\n[t]\na=2\n", "f"), [])

    def test_sections_differ_by_case(self):
        self.assertEqual(scan_text("[S]\na=1\n[s]\nb=2\n", "f"), [])

    def test_equals_in_value(self):
        self.assertEqual(scan_text("[s]\nkey = a=b\n", "f"), [])

    def test_indented_bracket_after_key_is_continuation(self):
        self.assertEqual(scan_text("[s]\nkey = one\n  [t]\n", "f"), [])

    def test_indented_comment_after_key_is_comment(self):
        self.assertEqual(scan_text("[s]\nkey = one\n  # note\n", "f"), [])


class TestScanProblems(unittest.TestCase):
    def test_key_before_section(self):
        got = problems_as_tuples("port = 8080\n[server]\nhost = x\n")
        self.assertEqual(got, [(1,
            "key or value appears before any section header")])

    def test_unclosed_header(self):
        got = problems_as_tuples("[sec\nkey = 1\n")
        # The header is broken, so the key line is also orphaned:
        # the file has no valid section at all.
        self.assertEqual(got, [(1,
            "section header is missing its closing ']'"),
            (2, "key or value appears before any section header")])

    def test_unclosed_header_after_section(self):
        got = problems_as_tuples("[a]\nx=1\n[bad\n")
        self.assertEqual(got, [(3,
            "section header is missing its closing ']'")])

    def test_empty_header(self):
        got = problems_as_tuples("[]\nkey = 1\n")
        # The header is empty, so the key line is also orphaned:
        # the file has no valid section at all.
        self.assertEqual(got, [(1, "section header is empty"),
            (2, "key or value appears before any section header")])

    def test_bare_key(self):
        got = problems_as_tuples("[sec]\ndebug\n")
        self.assertEqual(got, [(2, "key 'debug' has no value")])

    def test_bad_line(self):
        got = problems_as_tuples("[s]\n@@@\n")
        self.assertEqual(got, [(2, "key '@@@' has no value")])

    def test_line_starting_with_equals(self):
        got = problems_as_tuples("[s]\n= 1\n")
        self.assertEqual(got, [(2, "key name is empty")])

    def test_duplicate_section(self):
        got = problems_as_tuples("[s]\na=1\n[s]\nb=2\n")
        self.assertEqual(got, [(3, "section 's' already exists")])

    def test_duplicate_key(self):
        got = problems_as_tuples("[s]\na=1\na=2\n")
        self.assertEqual(got, [(3,
            "option 'a' in section 's' already exists")])

    def test_duplicate_key_case_insensitive(self):
        got = problems_as_tuples("[s]\nKey=1\nkey=2\n")
        self.assertEqual(got, [(3,
            "option 'key' in section 's' already exists")])

    def test_duplicate_key_after_blank_and_comment(self):
        got = problems_as_tuples("[s]\na=1\n\na=2\n")
        self.assertEqual(got, [(4,
            "option 'a' in section 's' already exists")])
        got = problems_as_tuples("[s]\na=1\n# c\na=2\n")
        self.assertEqual(got, [(4,
            "option 'a' in section 's' already exists")])

    def test_indented_stray_line(self):
        got = problems_as_tuples("[s]\n  stray\n")
        self.assertEqual(got, [(2, "key 'stray' has no value")])

    def test_indented_line_after_new_section(self):
        got = problems_as_tuples("[s]\nkey = one\n[t]\n  two\n")
        self.assertEqual(got, [(4, "key 'two' has no value")])

    def test_every_problem_reported(self):
        text = ("; problems\nport = 8080\n[server]\nhost = x\n"
                "host = y\n[server]\ndebug\n[database]\n"
                "user = admin\nbad line here\n")
        got = problems_as_tuples(text)
        self.assertEqual(got, [
            (2, "key or value appears before any section header"),
            (5, "option 'host' in section 'server' already exists"),
            (6, "section 'server' already exists"),
            (7, "key 'debug' has no value"),
            (10, "key 'bad line here' has no value"),
        ])


class TestAllowNoValue(unittest.TestCase):
    def test_bare_key_passes(self):
        self.assertEqual(
            scan_text("[server]\ndebug\n", "f", allow_no_value=True), [])

    def test_bare_key_still_dup_checked(self):
        got = problems_as_tuples("[s]\ndebug\ndebug\n",
                                 allow_no_value=True)
        self.assertEqual(got, [(3,
            "option 'debug' in section 's' already exists")])


class TestConfigparserAgreement(unittest.TestCase):
    def test_scanner_agrees_with_configparser(self):
        for name, text in CROSS_CHECK_CORPUS:
            with self.subTest(name=name):
                problems = scan_text(text, "test.ini")
                parser = configparser.RawConfigParser(strict=True)
                try:
                    parser.read_string(text)
                    configparser_ok = True
                    configparser_line = None
                except Exception as exc:  # noqa: BLE001 - any parse error
                    configparser_ok = False
                    configparser_line = configparser_error_line(exc)
                self.assertEqual(len(problems) == 0, configparser_ok,
                                 f"validity disagrees on {name!r}")
                if not configparser_ok:
                    self.assertIsNotNone(configparser_line,
                                         f"no line for {name!r}")
                    self.assertEqual(problems[0].line, configparser_line,
                                     f"first error line differs on {name!r}")


class TestCheckFile(unittest.TestCase):
    def test_not_utf8(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.ini"
            path.write_bytes(b"[s]\nkey = \xff\xfe\n")
            problems, error = check_file(path)
            self.assertIsNone(error)
            self.assertEqual(len(problems), 1)
            self.assertEqual(problems[0].line, 2)
            self.assertIn("UTF-8", problems[0].reason)

    def test_null_byte(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "bad.ini"
            path.write_bytes(b"[s]\nkey = a\x00b\n")
            problems, error = check_file(path)
            self.assertIsNone(error)
            self.assertEqual(len(problems), 1)
            self.assertEqual(problems[0].line, 2)
            self.assertIn("null byte", problems[0].reason)

    def test_missing_file(self):
        problems, error = check_file(Path("/nonexistent-ini-54.ini"))
        self.assertIsNone(problems)
        self.assertIn("cannot read", error)


class TestCollect(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.root = Path(self.tmp.name)
        (self.root / "a.ini").write_text("[s]\nkey = 1\n")
        (self.root / "b.cfg").write_text("[s]\nkey = 1\n")
        (self.root / "c.txt").write_text("not ini\n")
        (self.root / "sub").mkdir()
        (self.root / "sub" / "d.conf").write_text("[s]\nkey = 1\n")
        (self.root / "sub" / "e.ini").write_text("[s]\nkey = 1\n")
        (self.root / ".git").mkdir()
        (self.root / ".git" / "hooks.ini").write_text("[s]\nkey = 1\n")

    def tearDown(self):
        self.tmp.cleanup()

    def test_folder_walk(self):
        got = collect([str(self.root)])
        self.assertEqual([p.name for p in got],
                         ["a.ini", "b.cfg", "d.conf", "e.ini"])

    def test_no_recursive(self):
        got = collect([str(self.root)], recursive=False)
        self.assertEqual([p.name for p in got], ["a.ini", "b.cfg"])

    def test_git_skipped(self):
        got = collect([str(self.root)])
        self.assertNotIn("hooks.ini", [p.name for p in got])

    def test_exclude(self):
        got = collect([str(self.root)], exclude=["sub", "b.*"])
        self.assertEqual([p.name for p in got], ["a.ini"])

    def test_direct_file_any_name(self):
        got = collect([str(self.root / "c.txt")])
        self.assertEqual([p.name for p in got], ["c.txt"])

    def test_dedupe_and_sorted(self):
        got = collect([str(self.root / "a.ini"),
                       str(self.root), str(self.root / "a.ini")])
        self.assertEqual([p.name for p in got],
                         ["a.ini", "b.cfg", "d.conf", "e.ini"])

    def test_missing_path(self):
        with self.assertRaises(FileNotFoundError):
            collect([str(self.root / "nope.ini")])


def run_cli(*args, input_text=None):
    return subprocess.run(
        [sys.executable, str(SRC), *args],
        input=input_text, capture_output=True, text=True, cwd=str(ROOT))


class TestCli(unittest.TestCase):
    def test_clean_file_exit_zero(self):
        result = run_cli("examples/good.ini")
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK — 1 file(s) checked", result.stdout)

    def test_broken_file_exit_one(self):
        result = run_cli("examples/bad.ini")
        self.assertEqual(result.returncode, 1)
        self.assertIn("examples/bad.ini:5:", result.stdout)
        self.assertIn("5 problem(s) in 1 file(s)", result.stdout)

    def test_folder_exit_one(self):
        result = run_cli("examples")
        self.assertEqual(result.returncode, 1)
        self.assertIn("Checked 4 file(s), 6 problem(s) in 2 file(s).",
                      result.stdout)

    def test_missing_path_exit_two(self):
        result = run_cli("no-such-file.ini")
        self.assertEqual(result.returncode, 2)
        self.assertIn("no such file or folder", result.stderr)

    def test_no_args_exit_two(self):
        result = run_cli()
        self.assertEqual(result.returncode, 2)

    def test_stdin(self):
        result = run_cli("--stdin", input_text="[server]\nport = 8080\n")
        self.assertEqual(result.returncode, 0)
        self.assertIn("OK — 1 file(s) checked", result.stdout)
        result = run_cli("--stdin", input_text="[server]\ndebug\n")
        self.assertEqual(result.returncode, 1)
        self.assertIn("<stdin>:2: key 'debug' has no value", result.stdout)

    def test_json(self):
        result = run_cli("examples/configs/app.ini", "--json")
        self.assertEqual(result.returncode, 1)
        data = json.loads(result.stdout)
        self.assertEqual(data["files_checked"], 1)
        self.assertEqual(data["files_with_problems"], 1)
        self.assertEqual(data["problems"][0]["line"], 5)
        self.assertIn("already exists", data["problems"][0]["reason"])
        self.assertIn("examples/configs/app.ini:5:", result.stderr)

    def test_version(self):
        result = run_cli("--version")
        self.assertEqual(result.returncode, 0)
        self.assertIn("ini-validator-cli 1.0.0", result.stdout)

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as tmp:
            result = run_cli(tmp)
            self.assertEqual(result.returncode, 0)
            self.assertIn("OK — 0 file(s) checked", result.stdout)

    def test_bad_flag_exit_two(self):
        result = run_cli("--nope")
        self.assertEqual(result.returncode, 2)

    def test_input_files_unchanged(self):
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "x.ini"
            path.write_text("[s]\na=1\na=2\n")
            before = path.read_bytes()
            run_cli(str(path))
            self.assertEqual(path.read_bytes(), before)


class TestExamples(unittest.TestCase):
    def test_sample_output_byte_for_byte(self):
        result = subprocess.run(
            ["sh", "examples/run-example.sh"],
            capture_output=True, text=True, cwd=str(ROOT))
        self.assertEqual(result.returncode, 0)
        sample = (ROOT / "examples" / "sample-output.md").read_text()
        fenced = sample.split("```text\n", 1)[1].split("```", 1)[0]
        self.assertEqual(result.stdout, fenced)

    def test_readme_quotes_real_output(self):
        readme = (ROOT / "README.md").read_text()
        self.assertIn("OK — 1 file(s) checked, all INI files are valid.",
                      readme)
        self.assertIn("examples/bad.ini:5: option 'host' in section "
                      "'server' already exists", readme)
        self.assertIn("Checked 4 file(s), 6 problem(s) in 2 file(s).",
                      readme)
        self.assertIn('"files_checked": 1', readme)


class TestHygiene(unittest.TestCase):
    def test_stdlib_only_imports(self):
        allowed_src = {"argparse", "fnmatch", "json", "os", "re", "sys",
                       "pathlib"}
        allowed_tests = {"ast", "configparser", "ini_validator", "io",
                         "json", "os", "re", "subprocess", "sys",
                         "tempfile", "unittest", "pathlib"}
        for path, allowed in [(SRC, allowed_src),
                              (Path(__file__), allowed_tests)]:
            tree = ast.parse(path.read_text())
            imported = set()
            for node in ast.walk(tree):
                if isinstance(node, ast.Import):
                    imported.update(a.name.split(".")[0]
                                    for a in node.names)
                elif isinstance(node, ast.ImportFrom):
                    if node.module:
                        imported.add(node.module.split(".")[0])
            self.assertTrue(imported <= allowed,
                            f"{path.name} imports non-stdlib: "
                            f"{imported - allowed}")
            self.assertNotIn("yaml", imported)

    def test_gitignore_env_first_line(self):
        lines = (ROOT / ".gitignore").read_text().splitlines()
        self.assertEqual(lines[0], ".env")

    def test_no_banned_words_outside_tests(self):
        banned = ["TODO", "FIXME", "XXX", "lorem", "coming soon"]
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            for word in banned:
                self.assertNotIn(word, text,
                                 f"{word} in {path.relative_to(ROOT)}")
                self.assertNotIn(word.lower(), text.lower(),
                                 f"{word} in {path.relative_to(ROOT)}")

    def test_no_absolute_paths(self):
        for path in ROOT.rglob("*"):
            if not path.is_file():
                continue
            if ".git" in path.parts or "__pycache__" in path.parts:
                continue
            if "tests" in path.parts:
                continue
            text = path.read_text(errors="ignore")
            self.assertNotIn("/home/hatch", text)
            self.assertNotIn("/tmp/", text)

    def test_no_yaml_anywhere_in_source(self):
        text = SRC.read_text()
        self.assertNotIn("yaml", text)


if __name__ == "__main__":
    unittest.main()

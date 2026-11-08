# ini-validator-cli

Validate INI files, fail CI on a bad line.

[![CI](https://github.com/haiderstudio/ini-validator-cli/actions/workflows/ci.yml/badge.svg)](https://github.com/haiderstudio/ini-validator-cli/actions/workflows/ci.yml) [![Licence: MIT](https://img.shields.io/badge/Licence-MIT-yellow.svg)](LICENSE)

## What it does

`ini_validator` reads an INI file and checks it the way Python's
`configparser` reads it — sections, keys, and values — and reports
every problem with the file, the line number, and the exact reason.
It exits 1 when any problem is found, so it can fail a CI run.
A clean file exits 0.

- A bad INI file breaks the app that reads it at startup, with a
  cryptic error. This tool catches the break before the file ships,
  and points at the exact line.
- Every problem is reported, not just the first: a file with a
  duplicate key *and* a duplicate section lists both.
- Checks: a key or value before any section header, a section
  header missing its closing `]`, an empty section header, a key
  with no value, a line that is not a section, a key, a comment,
  or a blank line, a section that appears twice, and a key that
  appears twice in one section (keys are matched without regard
  to case, the way `configparser` reads them — `Key` and `key`
  are the same key).
- Keys may use `=` or `:` as the delimiter, and a value may be
  empty (`key =` is fine). A key with spaces in its name
  (`my key = 1`) is fine. A section name keeps its spaces.
- A line that starts with spaces or a tab after a key is a
  continuation of that value, the way `configparser` reads it —
  even across a blank line or a comment. An indented line with
  no key before it is a problem.
- A file that is not valid UTF-8, or that contains a null byte,
  is reported as a problem — neither can be a real INI file.
- `--allow-no-value` allows bare keys with no value, like
  `configparser`'s `allow_no_value`. Without it, a bare key
  is a problem.
- A file given directly on the command line is always checked,
  whatever its name. A folder is walked for `.ini`, `.cfg`,
  and `.conf` files, recursively by default (`--no-recursive`
  stops at the top level). `.git` folders are never walked,
  and directory links are never followed. `--exclude` skips
  files and folders by name pattern.
- `--json` prints the result as JSON (the human-readable
  lines go to standard error), and `--stdin` checks one
  INI file read from standard input.

## Who it is for

Anyone who ships `.ini` or `.cfg` files — app developers, teams
that keep config in version control, and anyone who has ever
stared at a startup crash that turned out to be one bad line
in a config file.

## What it does NOT do

- It does not check whether a value is *right* — a valid file
  can still hold a wrong port number. Checking values against
  a schema is a different job.
- It does not convert or rewrite anything. It is report-only,
  and it never touches the network.
- It does not check any other format. TOML is Day 36's
  toml-validator-cli, JSON is Day 19's
  json-formatter-validator-cli — INI is a different format.

## How this differs

- kingtusks/INI-validator (3 stars) is a C++ command-line tool
  that validates INI files with syntax, required-field, and
  type checks. This tool is Python standard library only —
  nothing to build, nothing to install — and checks syntax
  only, with a line number for every problem.
- SemaiCZE/inicpp (65 stars) is a C++ parser library with
  schema validation. A library you code against is not a
  file checker you run in CI.
- Boeing/config-file-validator (518 stars) is a Go toolchain
  that validates 18 configuration file types. It is broad;
  this tool is INI only, one format, one job.
- There is no exact-name rival: a GitHub search for
  `"ini-validator-cli"` returns 0 results (checked Nov 8, 2026).

## Install

Python 3.10 or newer, nothing else to install.

```sh
git clone https://github.com/haiderstudio/ini-validator-cli.git
cd ini-validator-cli
```

## Usage

Check one file:

```sh
python3 src/ini_validator.py examples/good.ini
```

```text
OK — 1 file(s) checked, all INI files are valid.
```

Check a broken file:

```sh
python3 src/ini_validator.py examples/bad.ini
```

```text
examples/bad.ini:2: key or value appears before any section header
examples/bad.ini:5: option 'host' in section 'server' already exists
examples/bad.ini:6: section 'server' already exists
examples/bad.ini:7: key 'debug' has no value
examples/bad.ini:10: key 'bad line here' has no value
Checked 1 file(s), 5 problem(s) in 1 file(s).
```

The exit code is 1, so a CI run fails.

Check a whole folder:

```sh
python3 src/ini_validator.py examples
```

```text
examples/bad.ini:2: key or value appears before any section header
examples/bad.ini:5: option 'host' in section 'server' already exists
examples/bad.ini:6: section 'server' already exists
examples/bad.ini:7: key 'debug' has no value
examples/bad.ini:10: key 'bad line here' has no value
examples/configs/app.ini:5: option 'name' in section 'app' already exists
Checked 4 file(s), 6 problem(s) in 2 file(s).
```

Check one file from standard input:

```sh
printf '[server]\nport = 8080\n' | python3 src/ini_validator.py --stdin
```

```text
OK — 1 file(s) checked, all INI files are valid.
```

Machine-readable output:

```sh
python3 src/ini_validator.py examples/configs/app.ini --json
```

```json
{
  "files_checked": 1,
  "problems": [
    {
      "file": "examples/configs/app.ini",
      "line": 5,
      "reason": "option 'name' in section 'app' already exists"
    }
  ],
  "files_with_problems": 1
}
```

Allow bare keys with no value:

```sh
printf '[server]\ndebug\n' | python3 src/ini_validator.py --stdin --allow-no-value
```

```text
OK — 1 file(s) checked, all INI files are valid.
```

## Examples

- `examples/good.ini` — a clean app config. Passes.
- `examples/bad.ini` — five problems in one file: a key before
  any section, a duplicate key, a duplicate section, a bare key,
  and a line that is not a key at all. Fails with exit 1.
- `examples/server.cfg` — a clean `.cfg` file. Passes, and
  shows that `.cfg` files are checked when a folder is walked.
- `examples/configs/app.ini` — one duplicate key, in a
  subfolder. Fails with exit 1.
- `sh examples/run-example.sh` runs the checker on the whole
  `examples/` folder. Its output is in
  `examples/sample-output.md`.

## How it is tested

```sh
python3 tests/test_ini_validator.py
```

The tests cover: every problem type with exact line numbers,
valid files that must pass (both delimiters, empty values,
keys with spaces, sections with spaces, multiline values,
indented keys and sections), duplicate keys across blank
lines and comments, duplicate keys in different sections
passing, sections that differ only by case passing, keys
that differ only by case failing, `--allow-no-value`,
folder walking (extensions only, `.git` skipped,
`--no-recursive`, `--exclude`), `--stdin`, `--json`,
exit codes 0/1/2, and the bundled examples (the sample
output is compared byte-for-byte against a fresh run).

The tests also cross-check the scanner against Python's
own `configparser`: on a corpus of INI snippets, the
scanner reports a problem exactly when `configparser`
refuses to parse the file, and its first reported line
matches `configparser`'s error line.

## Contributing

See [CONTRIBUTING.md](CONTRIBUTING.md).

## Licence

MIT — see [LICENSE](LICENSE).

## Original work

This tool was written from scratch for this repo. The INI
rules it checks are the rules of Python's standard library
`configparser` module, verified against that module's own
behaviour. The idea of validating config files is a common
one; the code, the wording, and the tests are original.

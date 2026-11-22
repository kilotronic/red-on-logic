# red-on-logic

A CI check that proves a pull request's new tests test something. It runs the tests the pull request adds or
changes against the base branch's code, and at least one of them must fail there with a wrong answer: an assertion,
or a crash in the code under test. A test that fails only because a module, a name or an argument is missing is red
on import, not on logic, and proves nothing.

Nothing failing is ever committed or merged. The check swaps the old code in inside its own job, runs the tests,
and puts the checkout back; everything in the repository stays green.

## How it works

1. It finds the files the pull request changed, from the merge base to the head.
2. It runs the changed test files on the head, as they are.
3. It puts every changed source file back to the base's version and removes source files the pull request added,
   then runs the same test files again. Everything else stays at the pull request's version:
   - the test files, `conftest.py`, and anything under a `tests`, `test`, `__tests__`, `spec`, `testdata`,
     `testing`, `__fixtures__`, `__mocks__` or `__snapshots__` folder;
   - every file that is not source code: data, snapshots, docs, lockfiles, `pyproject.toml`, `package.json`;
   - test and build config: dot files, `<tool>.config.*` for the usual tools (jest, vitest, vite, babel, eslint,
     ...), `jest.setup.*`, `vitest.setup.*`, `setupTests.*`, and `setup.py` or `noxfile.py` at the root.

   A missing data file or an older runner config would fail the base for a reason that is not the code under test.
   Behaviour kept outside source files (SQL, templates, rules) goes back too when the `code-paths` input names it.

4. It puts the checkout back (`git reset --hard` to the head). It refuses to start with uncommitted changes to
   tracked files, or when an untracked file sits where the base run would write one; it does not reset when HEAD
   or the branch moved during the run, and says which files to put back. Ctrl-C, a cancelled job (SIGTERM) and a
   closed terminal (SIGHUP) all put the checkout back first.

A test is **judged** when it is new or its own lines changed. A changed line inside no test (an import, a constant,
a helper or fixture, a class attribute, a `describe` line) judges every test in that file; a blank or comment-only
line judges nothing. Unchanged tests in a changed file run too but are not judged. A test that did not finish on
the head (its process ended) did not run.

Each judged test gets one verdict:

| Verdict                                   | Means                                                                                         |
| ----------------------------------------- | --------------------------------------------------------------------------------------------- |
| **fails on the base (proves the change)** | Passes on the head; fails on the base with an assertion, or the code under test raised        |
| passes on the base (proves nothing)       | Green on the old code: it does not test this change                                           |
| red on import, not logic                  | Fails on the base at collection, import or setup, or on a missing name, attribute or argument |
| fails on this branch too                  | Red on the head as well (an `assert False`), so its failure on the base proves nothing        |
| did not run                               | Skipped on either side, or the runner reported no tests in the file                           |

The check **passes** when at least one judged test proves the change, and **fails** when none does or there are no
new or changed tests. Exit codes: 0 proven or skipped, 1 not proven, 2 the check could not run.

### Examples

A bug fix whose new test fails on the old code: **passes**.

```text
red-on-logic: proven. 1 of 1 new or changed test fails on the base's code with a wrong answer.

  fails on the base (proves the change)  tests/test_calc.py::test_add
                                           AssertionError: assert -1 == 3
```

A new test that passes on the old code too: **fails**.

```text
red-on-logic: not proven. The new or changed test does not fail on the base's code with a wrong answer.

  passes on the base (proves nothing)  tests/test_calc.py::test_add_zero

A test that passes on the old code does not test this change: make it fail on the old code with a wrong answer.
```

A new test of a function the base does not have: **fails** (red on import).

```text
red-on-logic: not proven. The new or changed test does not fail on the base's code with a wrong answer.

  red on import, not logic  tests/test_mul.py::test_mul
                              ImportError: cannot import name 'mul' from 'calc'
```

A shared helper (a `conftest.py` and what it imports) that fails to load on the base makes the files under it red
on import; files under other folders are run alone and judged as usual.

A test of a new command-line option or subcommand fails on the old code because the old command line refuses it.
That reads as a wrong answer unless the project names its command line's words for it in `import-patterns`, one
regular expression per line, for example:

```yaml
import-patterns: |
  unrecognized arguments
  invalid choice
  ^unknown service
  ^SystemExit: 2$
```

A pattern is tried on the failure's first line (up to 300 characters) as stored, `AssertionError: unknown
service: b`, and on the text after its type, so `^` anchors work. A test that calls `main([...])` directly sees
only argparse's exit (`SystemExit: 2`; the "unrecognized arguments" text goes to stderr), hence the last line. A test that checks only an exit code (`assert
r.returncode == 0`) never shows the command line's words, so it reads as proof: assert on the output too.

A pull request that only adds a new function, with no change to existing behaviour, is red on import by nature.
Either test behaviour the old code gets wrong, land the new name first (with a wrong answer) in its own pull
request, or skip the check with a reason.

## Skipping it, with a reason

A pure refactor, a test-only or a docs-only pull request has nothing to prove. Say so on a line of its own, not
indented, in any commit message (a trailer), or as a label:

```text
red-on-logic: not applicable (pure refactor, no behaviour change)
```

The reason is printed, and a skip with no reason (or the placeholder `<reason>`) fails. A label is read when the job runs: add `labeled` and
`unlabeled` to the workflow's `pull_request` types so adding one re-runs the check.

## Use as a GitHub Action

```yaml
on:
  pull_request:
    types: [opened, synchronize, reopened, labeled, unlabeled]

permissions:
  contents: read

jobs:
  red-on-logic:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@<commit> # fetch-depth: 0 for the base and the commit messages
        with:
          persist-credentials: false
          fetch-depth: 0
      # ... set up the project so its tests run, as the test job does ...
      - uses: kilotronic/red-on-logic@<commit of the release> # v1.0.0
        # with:
        #   pytest: uv run --no-sync pytest
        #   runner: command
        #   command: make test-junit FILES="{files}" OUT={junit}
        #   test-paths: checks/*.check
```

It needs no secrets and no write permission, and runs on GitHub's runners (Linux and macOS; it uses bash and the
runner's `python3`, 3.10 or later). Run it on `pull_request`, never `pull_request_target`: it runs the pull request's
code. On a pull request's merge checkout (the default) it judges against the merge's first parent, so commits that
landed on the base branch since the event are never swapped or read for a skip. On any other event with no `base`
input it does nothing. The result also goes to the job summary.

| Input               | Default                                                                      |
| ------------------- | ---------------------------------------------------------------------------- |
| `base`              | the pull request's base commit                                               |
| `runner`            | `auto`: per file, see below                                                  |
| `pytest`            | `.venv/bin/python -m pytest` when there is a .venv, else `python3 -m pytest` |
| `vitest`            | `npx --no-install vitest run`                                                |
| `jest`              | `npx --no-install jest`                                                      |
| `node`              | `node`                                                                       |
| `command`           | with `runner: command`: runs `{files}`, writes JUnit to `{junit}`            |
| `test-paths`        | more test-file globs; with `runner: command`, the only ones                  |
| `working-directory` | with a fixed `runner`, where it runs                                         |
| `labels`            | the pull request's labels                                                    |

## Runners

`auto` picks one per test file:

- **pytest** for `test_*.py` and `*_test.py`, run from the nearest folder with a `pyproject.toml`, `pytest.ini`,
  `setup.cfg` or `tox.ini`. A small plugin records each test's exception type; `--continue-on-collection-errors` is
  added so one file's import error does not hide the rest. Bytecode caching is off for both runs, so the base run
  never reuses the head's compiled files.
- **node:test** for a JavaScript or TypeScript test file that imports `node:test`.
- **vitest** or **jest** for other test files (`*.test.*`, `*.spec.*`, `*-test.*`, `test-*.*`, anything under
  `__tests__`), chosen from the nearest `package.json`'s dependencies, run from that folder.
- **command** for anything else: any command that writes JUnit XML. A `<failure>` is a wrong answer, an `<error>` is
  red on import. A case belongs to the file its `file` attribute names, else the file its dotted `classname` names
  (`checks.test_calc` is `checks/test_calc.py`), else, for a case with no classname, the run's only file. JUnit has no line numbers, so every test
  in a changed file is judged.

## Use as a command

```bash
pip install git+https://github.com/kilotronic/red-on-logic.git@v1.0.0
red-on-logic                          # this branch against origin/HEAD, origin/main or main
red-on-logic --base main --pytest "uv run --no-sync pytest"
red-on-logic --json report.json --summary summary.md
```

It changes and restores files in the checkout it runs in, so commit or stash first; it refuses to start otherwise.
Do not edit files while it runs: the restore resets every tracked file to the head.

## What it cannot see

- A test that fails on the base by chance (a flake) reads as proof: each side runs once. The head run catches a test
  that always fails, and a timeout on the base never counts.
- In JavaScript, a name the base does not export usually imports as `undefined` instead of failing, so
  `expect(MAX).toBe(10)` against a new `export const MAX` fails with an assertion and reads as proof. Calling a
  missing function is caught (`is not a function`).
- A changed data, template, SQL or config file stays at the head's version unless `code-paths` names it, so a test
  that pins only such a change reads as proving nothing.
- Code installed into the environment as a copy (not editable) is not swapped, so its tests pass on the base and
  read as proving nothing. Install the project editable, or run from source.
- A build step between the code and the tests (a compiled extension, a bundle the tests import) is not re-run on the
  base. Use `runner: command` with the build in the command.
- "At least one": a pull request with one real test and several vacuous ones passes; the vacuous ones are listed.
  A changed helper at the top of a test file judges every test in it, so an old test there that fails on the base
  can carry an empty new one.
- Dependency-bot pull requests have no tests and cannot add a trailer: skip the job for them in the workflow
  (`if: github.actor != 'dependabot[bot]'`).

## Development

```bash
uv sync
npm ci --ignore-scripts --prefix tests/js   # the JavaScript runners the planted examples use
uv run pytest
uv run ruff check . && uv run pyright
```

## License

MIT. See [LICENSE](LICENSE).

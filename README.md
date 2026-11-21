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
3. It puts every changed code file back to the base's version, keeps the test files and their support files at the
   head's (anything under a `tests`, `test`, `__tests__`, `spec`, `testdata` or `testing` folder, and `conftest.py`),
   removes code files the pull request added, and runs the same test files again.
4. It puts the checkout back (`git reset --hard` to the head; it refuses to start with uncommitted changes).

A test is **judged** when it is new or its own lines changed. A changed line outside every test (an import, a
constant, a helper at the top of the file) judges every test in that file; a blank or comment-only line judges
nothing. Unchanged tests in a changed file run too but are not judged.

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

A pull request that only adds a new function, with no change to existing behaviour, is red on import by nature.
Either test behaviour the old code gets wrong, land the new name first (with a wrong answer) in its own pull
request, or skip the check with a reason.

## Skipping it, with a reason

A pure refactor, a test-only or a docs-only pull request has nothing to prove. Say so on a line of its own in any
commit message (a trailer), or as a label:

```text
red-on-logic: not applicable (pure refactor, no behaviour change)
```

The reason is printed, and a skip with no reason fails. A label is read when the job runs: add `labeled` and
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
code. On any other event with no `base` input it does nothing. The result also goes to the job summary.

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
  red on import. JUnit has no line numbers, so every test in a changed file is judged.

## Use as a command

```bash
pip install git+https://github.com/kilotronic/red-on-logic.git@v1.0.0
red-on-logic                          # this branch against origin/HEAD, origin/main or main
red-on-logic --base main --pytest "uv run --no-sync pytest"
red-on-logic --json report.json --summary summary.md
```

It changes and restores files in the checkout it runs in, so commit or stash first; it refuses to start otherwise.

## What it cannot see

- A test that fails on the base by chance (a flake) reads as proof. The head run catches a test that always fails.
- Code installed into the environment as a copy (not editable) is not swapped, so its tests pass on the base and
  read as proving nothing. Install the project editable, or run from source.
- A build step between the code and the tests (a compiled extension, a bundle the tests import) is not re-run on the
  base. Use `runner: command` with the build in the command.
- Data outside a test folder is code: a golden file kept elsewhere goes back to the base's version too.
- "At least one": a pull request with one real test and several vacuous ones passes; the vacuous ones are listed.

## Development

```bash
uv sync
npm ci --ignore-scripts --prefix tests/js   # the JavaScript runners the planted examples use
uv run pytest
uv run ruff check . && uv run pyright
```

## License

MIT. See [LICENSE](LICENSE).

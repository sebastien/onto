# Command line

`onto` is the command-line interface to the formats of specs
[01](spec-01-ontology.md) to [05](spec-05-identities.md). It checks, formats and
converts files, prints observations and coverage, reverses mappings, derives
inventories and runs function examples. It is written for people at a terminal
and for agents and editors reading its output: results go to standard output,
diagnostics to standard error in `file:line:` form, and every command can answer
in JSON instead.

Files refer to each other by namespace, never by path (`@use Finance as F`,
`@mapping Exchange -> Finance`). The CLI therefore works over a **workspace**: it
indexes the files below the project root by their header, and finds whatever a
file needs without being told.

## Concepts

| Concept | Meaning |
| --- | --- |
| Workspace | The onto files under the search path, indexed by kind and namespace |
| Search path | The directories scanned for the workspace: the project root, `-I` directories and `ONTO_PATH` |
| Project root | The nearest ancestor of a directory holding `.git`, `.hg` or `.jj`; else the directory itself |
| Kind | What a file is (`ontology`, `observations`, `binding`, ...), from its extension or JSON `format` |
| Context | What a file is loaded against: the ontologies, libraries and referentials it names |
| Carrier | An ontology that `@use`s a namespace, and so carries declarations of it |
| Diagnostic | An error or warning: level, code, message and location |
| Sidecar | A headerless file attached to a binding by name (`.inv`, `.formats`) |

## Example

A workspace holding the examples of spec-01, spec-02 and spec-04:

```text
project/
  .git/
  finance/
    finance.onto           @ontology Finance
    exchange.onto          @ontology Exchange
    exchange-extra.onto    @ontology Exchange   (same namespace: one ontology)
    sheet.onto             @ontology Sheet
    markets.fn             @functions Markets
    market-ids.ref         @referential MarketIds
    exchange.bind          @binding Exchange
    exchange.inv           (inventory of the binding's documents)
    exchange.formats       (value formats of the binding's documents)
    exchange-finance.map   @mapping Exchange -> Finance
    statement.obs          @obs Finance
```

```text
$ onto ls
binding       Exchange           2026-11-10  finance/exchange.bind
formats       exchange                       finance/exchange.formats
functions     Markets            2026-11-10  finance/markets.fn
inventory     exchange                       finance/exchange.inv
mapping       Exchange->Finance              finance/exchange-finance.map
observations  Finance            2026-11-10  finance/statement.obs
ontology      Exchange           2026-11-10  finance/exchange-extra.onto finance/exchange.onto
ontology      Finance            2026-11-10  finance/finance.onto
ontology      Sheet              2026-11-10  finance/sheet.onto
referential   MarketIds          2026-11-10  finance/market-ids.ref

$ onto check finance/exchange-finance.map
finance/exchange-finance.map:1: error cli.context: ontology Finance has errors
finance/finance.onto:83: error reference: Finance/Broken.Thing: unknown 'Finance/NoSuchType'
2 errors in 1 file (2 read)

$ onto fmt --check
finance/sheet.bind
1 file not laid out; run 'onto fmt -w' to rewrite it
```

`check` resolved the mapping's `From` and `To` ontologies from the workspace and
reported the error where it is: in `finance.onto`, with a `cli.context` error on
the mapping's header saying why the mapping could not be checked. `fmt --check`
found a hand-edited binding whose docs are not aligned.

## Invocation

```text
onto [-I DIR]... [--color WHEN] [--json] [-q] <command> [ARGS]
python -m onto ...
```

| Option | Meaning |
| --- | --- |
| `-I`, `--path DIR` | Add `DIR` to the search path; repeatable |
| `--no-workspace` | Use only the files named on the command line and `-I` directories |
| `--color auto\|always\|never` | Color human output (default `auto`, [Colors](#colors)) |
| `--json` | Write the result and diagnostics as JSON ([JSON output](#json-output)) |
| `-q`, `--quiet` | Suppress results and summaries; diagnostics remain |
| `-h`, `--help` | Show help ([Help](#help)) |
| `--version` | Print `onto <version>` |

Global options may also follow the command (`onto check --json x.onto`).
Abbreviated long options are rejected. A `FILE` argument of `-` reads standard
input; `--kind KIND` then says what it is.

| Environment | Meaning |
| --- | --- |
| `ONTO_PATH` | More search-path directories, separated by `:` (after `-I`) |
| `NO_COLOR`, `NOCOLOR` | Any non-empty value disables color under `auto` |
| `ONTO_DEBUG=1` | Show the Python traceback of an internal error |

## Workspace

### Kinds

| Extension | Kind | Header | Namespace key | JSON `format` |
| --- | --- | --- | --- | --- |
| `.onto` | `ontology` | `@ontology` | `Namespace` | `onto.ontology/1` |
| `.obs` | `observations` | `@obs` | `Namespace` | `onto.observations/1` |
| `.fn` | `functions` | `@functions` | `Namespace` | `onto.functions/1` |
| `.bind` | `binding` | `@binding` | `Namespace` | `onto.binding/1` |
| `.map` | `mapping` | `@mapping` | `From->To` | `onto.mapping/1` |
| `.ref` | `referential` | `@referential` | `Name` | `onto.referential/1` |
| `.inv` | `inventory` | none | file stem | none |
| `.formats` | `formats` | none | file stem | none |

- A file's kind is its extension. A header that disagrees is an error
  (`cli.kind`): `wrong.fn:1: error cli.kind: a .fn file must start with
  @functions, not @ontology`. A missing header is left to the format's parser.
- A `.json` file's kind is its `format` member, and its namespaces come from its
  members (`namespace`, `obs.ontology`, `ontology`, `from` and `to`, `uses`).
  JSON files are never indexed: they are read only when named.
- An inventory is the sidecar of the binding with the same name in the same
  directory (`exchange.inv` for `exchange.bind`); `coverage` reads it.

### Indexing

The workspace scans the search path recursively, skipping hidden directories,
and parses only the header and `@use` lines of each file. It is built for each
command, when the command first needs it, and is never cached on disk. A search
path entry that is not a directory is a warning.

- The search path is the project root of the working directory, then the `-I`
  directories, then `ONTO_PATH`. A file named on the command line adds its own
  project root, so `onto check ../other/x.map` sees `../other`'s files.
  `--no-workspace` keeps only the named files and the `-I` directories.
- Files of an ontology, a library or a referential sharing a namespace are
  loaded together as one model (spec-01: "An ontology may span several files").
  Their parsers check that the files agree (`rev`, duplicate declarations).
- Bindings, mappings and observations are loaded file by file; several may share
  a namespace key.
- Indexing problems (`cli.kind`, `cli.read`) are reported for the files a
  command names or reads; `ls` reports them all. A broken file elsewhere in the
  project does not fail `onto state statement.obs`.

### Context

To load a file, the CLI first loads its context from the workspace:

| Kind | Context |
| --- | --- |
| `ontology` | None. An ontology declares what it uses of other namespaces itself (spec-01) |
| `observations` | The `@obs` ontology |
| `functions` | The `@use` ontologies (a library does not load other libraries) |
| `binding` | The `@binding` ontology; the `@use` ontologies and libraries |
| `mapping` | `From` and `To`; the `@use` ontologies and libraries; the `referential=` referential |
| `referential` | The `@use` ontologies and the policies' `from=` ontologies |

- A required ontology or referential (the `@obs`, `@binding` and `@mapping`
  namespaces, `referential=`) that the workspace lacks is an error on the
  file's header (`cli.unresolved`): `exchange.bind:1: error cli.unresolved: no
  ontology Exchange in the workspace (searched: .)`.
- Other namespaces (`@use`, `from=`) are loaded when the workspace has an
  ontology or a library of that name. When it has neither, its **carriers**
  are loaded instead: the ontologies that `@use` it, and so declare what they
  use of it (`@use Dimensions as D` in `finance.onto` declares `D/Money`). A
  namespace found nowhere is left to the format's own validation.
- When a context file has errors, they are reported in that file, and the
  dependent file gets `cli.context` on its header: `ontology Finance has errors`.
- An ontology and a library may share a namespace; each kind is resolved apart.
- A file that would be part of its own context is an error (`cli.cycle`).

## Commands

`onto help` lists them by group. Where `FILE...` may be omitted, the command
applies to every indexed file.

### Files

#### `onto check [FILE...]`

Parse and validate files with their context; print diagnostics, then a summary.
Without files, checks the whole workspace.

| Option | Meaning |
| --- | --- |
| `--lenient` | Read observations in lenient mode (spec-02) |
| `--kind KIND` | Kind of a `-` argument |

#### `onto fmt [-w|--check|--diff] [FILE...]`

Fix the layout of hand-edited files, keeping what they say and how they say it.
`fmt` changes only:

- trailing ` -- doc`s, aligned as normal form aligns them (spec-01: column 48,
  or one space after longer code), in the formats that have docs;
- trailing whitespace, line endings (LF) and the end of the file (one newline).

Declaration order, comments, blank lines, record or log forms and spelling are
kept as written. The normal forms of the specs are what `onto text` prints, and
what `onto json` encodes; `onto state` and `onto log` print the observation forms.

| Option | Meaning |
| --- | --- |
| `-w`, `--write` | Rewrite files whose layout changes; list them |
| `--check` | List files whose layout would change; write nothing; exit 1 if any |
| `--diff` | Print a unified diff per file whose layout would change; exit 1 if any |

The three options are exclusive and, without files, apply to the workspace;
plain `fmt` requires files. Files with errors are reported and left unchanged.
JSON files are rejected (`onto text` prints their text form).

#### `onto json FILE`

Print the JSON form of a file, with its context. A file of a multi-file model
prints the whole model. Inventories and formats files have no JSON form.

#### `onto text FILE.json`

Print the normal text form of a JSON file; `-` reads JSON from standard input.
Context comes from the workspace, as for text files.

#### `onto ls [KIND...]`

List the workspace, one row per model: kind, namespace key, `rev` and files,
sorted by kind then namespace. Index diagnostics (`cli.kind`) are reported.

#### `onto meta [--decl] FILE.onto`

Print the ontology as observations of its own
[`Meta` domain](spec-01-ontology.md#meta-domain): its concepts, attributes and
dimensions, so that data can refer to them. Files sharing the namespace are
described together. With `--decl`, print the `Meta` domain declarations instead,
as an ontology file with the same header as `FILE.onto`, to keep among the files
of the ontology. Without the domain, the observations are still printed, with a
hint: they validate once the declarations are added.

### Observations

#### `onto state FILE.obs`

Print the reconciled **state form** (spec-02): retractions applied, superseded
claims removed, conflicts marked, identity links resolved.

#### `onto log FILE.obs`

Print the **log form**: every statement, ordered by `at`.

Both accept `--lenient` and `--kind`.

### Mappings

#### `onto coverage FILE [--view VIEW] [--inventory FILE.inv]`

Print a coverage table, tab-separated:

- **Mapping**: the static coverage of `From` (spec-04,
  [Coverage](spec-04-mapping.md#coverage)), with columns `source`, `target`,
  `status` and `note`, sorted by source; then a row with status `unassigned`
  for each `To` element no line assigns.
- **Binding**: the same columns for the document fields of its inventory (the
  sidecar, or `--inventory`); `uninventoried` rows for fields read but not
  inventoried; `unassigned` rows for the ontology elements no line assigns.
  Without an inventory, only the ontology side.
- **Observations**: the coverage of `--view VIEW` (required), with columns
  `path`, `subject`, `ctx`, `status` and `note` (`conflict`, `partial`).

#### `onto reverse FILE.map [--referential NAME]`

Print the reversed mapping (`To -> From`). Lines that cannot be reversed are
omitted and reported as warnings at their own line (`LossyLine.loc`): `exchange-finance.map:19:
warning map.lossy: Exchange/Instrument -> Finance/Instrument: 'AssetClass' is
not reversed: @map 'AssetClassFromCode' is not exact and one-to-one`.

#### `onto inventory DOCUMENT... [--csv] [--binding NAMESPACE]`

Print the inventory of sample documents (JSON, or CSV with a header row with
`--csv`), sorted by path. With `--binding NAMESPACE`, print the default binding
instead (spec-04, [Default bindings](spec-04-mapping.md#default-bindings)).
Needs no workspace.

### Functions

#### `onto fn test [FILE.fn...] [--impl MODULE]...`

Run the examples of libraries, and the round trips through their inverses
(spec-04, [Contract for implementations](spec-04-mapping.md#contract-for-implementations));
without files, of every library of the workspace.

Library functions are code. `--impl MODULE` (repeatable) imports a Python
module, from the working directory or the Python path, whose `IMPLEMENTATIONS`
maps fully qualified names to callables:

```python
IMPLEMENTATIONS = {
	"Markets/FrequencyFromInterval": frequencyFromInterval,
	"Markets/IntervalFromFrequency": intervalFromFrequency,
}
```

A function without an implementation (or whose inverse has none) is skipped,
with a `fn.unimplemented` warning. Prints one row per library: namespace,
`passed` or `failed`, examples run and functions skipped. Failing examples are
`conformance` errors at the example's line; the command then exits 1. A module
that cannot be imported, or lacks `IMPLEMENTATIONS`, is a usage error.

#### `onto fn ls [FILE.fn...]`

List functions: fully qualified name, signature and doc, sorted by name.

### Help

#### `onto help [COMMAND]`

Same as `onto --help` and `onto COMMAND --help`.

## Output

Results go to standard output, diagnostics and summaries to standard error, so
`onto fmt x.onto > y.onto` and `onto json x.onto | jq` are safe.

### Diagnostics

One diagnostic per line, as `str(Diagnostic)` prints it:

```text
<file>:<line>: <level> <code>: <message>
```

- `file` is relative to the working directory. Diagnostics about a whole file
  (unreadable, wrong kind) omit `<line>:`, and have a `null` line in JSON;
  diagnostics about no file omit the location.
- Diagnostics are sorted by file, then line, then level (errors first).
- Codes are those of the formats (`reference`, `header`, `conformance`, ...); the
  CLI's own are `cli.*`, `map.lossy` and `fn.unimplemented`. A format operation
  rejecting its input outside loading (a `ValueError`) is `cli.failed`, not an
  internal error.
- Then, unless `--quiet`, a summary: `2 errors, 1 warning in 3 files (5 read)`,
  where zero counts are omitted, the files are those named or selected and
  `read` counts every file read, context included (shown when larger). `check`
  always prints it (`no problems in 12 files`); other commands only when there
  are diagnostics.

The form is the one compilers print, so editors read it unchanged (Vim:
`errorformat=%f:%l:\ %t%*[^ ]\ %m`).

### Tables

`ls`, `coverage` and `fn` print tables: tab-separated values, every row with
every column (empty cells included), with a header row for `coverage` and
`fn test`. On a colored terminal, columns are aligned with spaces instead.

### Colors

Under `--color auto`, standard output and standard error are each colored when
they are a terminal, `TERM` is not `dumb`, and neither `NO_COLOR` nor `NOCOLOR`
is set. JSON output is never colored, nor are file texts (`fmt`, `json`,
`text`, `state`, `log`, `reverse`, `inventory`), so that they can be copied back
into files.

| Element | Style |
| --- | --- |
| `error` | bold red |
| `warning` | bold yellow |
| Location `file:line:` | bold |
| Diagnostic code | dim |
| Namespace part of a path (`Finance/`) | magenta |
| Element name (`Instrument.Isin`) | green |
| Kind in `ls` | cyan |
| Help headings | bold cyan |
| Command names in help | bold |
| Hints, summaries with problems, `rev`, notes | dim |
| Summary of a clean `check` | green |
| Status `direct`, `passed` | green |
| Status `transformed` | cyan |
| Status `condition`, `ambiguous` | yellow |
| Status `ignore`, `out-of-scope` | dim |
| Status `unmapped`, `unassigned`, `uninventoried`, `failed` | red |

### JSON output

With `--json`, a command prints one JSON document on standard output and nothing
on standard error (usage errors excepted):

```json
{
  "format": "onto.cli/1",
  "command": "check",
  "ok": false,
  "result": null,
  "diagnostics": [
    {"level": "error", "code": "reference", "message": "Finance/Broken.Thing: unknown 'Finance/NoSuchType'",
     "file": "finance/finance.onto", "line": 83}
  ],
  "files": {"checked": 1, "read": 2}
}
```

`ok` is `true` when the exit status is 0. `result` is:

| Command | Result |
| --- | --- |
| `check` | `null` |
| `fmt` | The text; an object by file when several files are named (files with errors are absent); the diff for `--diff`; the list of files for `--write` and `--check` |
| `json` | The JSON form |
| `text`, `state`, `log`, `reverse`, `inventory` | The text |
| `ls`, `coverage`, `fn` | The rows, as objects keyed by column |

## Help

Help is written for someone who does not know the formats yet:

- `onto`, `onto --help` and `onto help` print a one-line description, the
  usage, how the workspace is found, the commands by group with their synopsis
  and summary, the global options, the terms used in synopses, and a
  getting-started sequence:

  ```text
  Getting started:
    onto ls                     see what the workspace holds
    onto check                  validate every file
    onto fmt --diff             see what layout fixes fmt would make
    onto state statement.obs    read the current state of observations
  ```

- `onto COMMAND --help`, `onto -h COMMAND` and `onto help COMMAND` print the usage, a description,
  the command's options, the global options and examples.
- Usage errors suggest the closest command or option, and say where to look:

  ```text
  onto: error: unknown command 'chek'. Did you mean 'check'?
  Run 'onto --help' for examples and argument descriptions.
  ```

- Help wraps to the terminal width.

### Terms

| Term | Meaning |
| --- | --- |
| `FILE` | A path to an onto file; `-` reads standard input, with `--kind` |
| `KIND` | `ontology`, `observations`, `functions`, `binding`, `mapping`, `referential`, `inventory`, `formats` |
| `DIR` | A directory added to the search path |
| `VIEW` | An ontology view path, e.g. `Finance/PortfolioReview` |
| `NAMESPACE` | An ontology namespace, e.g. `Exchange` |
| `DOCUMENT` | A sample source document: JSON, or CSV with `--csv` |
| `MODULE` | A Python module name, e.g. `markets_impl` |

## Exit status

| Status | Meaning |
| --- | --- |
| `0` | Success; warnings may have been reported |
| `1` | Errors were reported, `fmt --check` or `--diff` found files to format, `fn test` failed, or an internal error |
| `2` | Usage error: unknown command or option, missing or conflicting arguments |

An internal error prints `onto: internal error: <message>` and a hint to rerun
with `ONTO_DEBUG=1`, which shows the traceback.

## Deferred

- `onto bind` and `onto map`: running bindings and mappings, with run modes,
  approval and re-running, belong to the hexa integration
  ([spec-06](spec-06-hexa.md#run)), and come with it.
- `onto diff OLD NEW`: the semantic diff of spec-01 [Changes](spec-01-ontology.md#changes).
- `onto overlay`: overlays (spec-03).
- `onto formats update`: learning value formats from documents (spec-04,
  [Formats](spec-04-mapping.md#formats)), which needs a binding run.
- Identity sidecars (`.ids`, spec-01) and registries (`.reg`, spec-05), which
  have no readers yet.
- A workspace configuration file: the search path and headers suffice until a
  project shows otherwise.
- A watch mode and a language server.

## Implementation

- `src/py/onto/cli/`: `workspace.py` (indexing, context, loading), `usage.py`
  (command catalog, parsing, help), `commands.py` (one method per command),
  `ui.py` (colors, diagnostics, tables) and `__init__.py` (`run`, `main`,
  output). `src/py/onto/__main__.py` runs `main`.
- `pyproject.toml`: `[project.scripts] onto = "onto.cli:main"`.
- Standard library only: `argparse` (with `suggest_on_error`, Python 3.14),
  `difflib`, `textwrap`, `shutil`, `csv`, `importlib`.
- Commands call the public operations of the formats and turn `FormatError`s
  into diagnostics; the CLI adds no format semantics of its own.
- `tests/T07-*` run `onto.cli.run` in process on a temporary project built from
  the spec examples (`tests/_cli.py`), checking standard output, standard error
  and the exit status.

<!-- EOF -->

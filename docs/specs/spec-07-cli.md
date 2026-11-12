# Command line

`onto` is the command-line interface to the formats of specs
[01](spec-01-ontology.md) to [05](spec-05-identities.md). It checks, formats and
converts files, prints observations and coverage, reverses mappings and derives
inventories. It is written for people at a terminal and for agents and editors
reading its output: results go to standard output, diagnostics to standard
error in `file:line:` form, and every command can answer in JSON instead.

Files refer to each other by namespace, never by path (`@use Finance as F`,
`@mapping Exchange -> Finance`). The CLI therefore works over a **workspace**: it
indexes the files below the project root by their header namespace, and finds
whatever a file needs without being told.

## Concepts

| Concept | Meaning |
| --- | --- |
| Workspace | The onto files under the search path, indexed by kind and namespace |
| Search path | The directories scanned for the workspace: the project root, plus `-I` and `ONTO_PATH` |
| Project root | The nearest ancestor of the working directory holding `.git`, `.hg` or `.jj`; else the working directory |
| Kind | What a file is (`ontology`, `observations`, `binding`, ...), from its extension or JSON `format` |
| Context | The files a file needs to be read: the ontologies, libraries and referentials it names |
| Diagnostic | An error or warning: level, code, message and location |
| Sidecar | A file attached to another by name rather than header (`.ids`, `.reg`, `.formats`, `.inv`) |

## Example

A workspace holding the examples of spec-01 to spec-05:

```text
finance/
  dimensions.onto        @ontology Dimensions
  finance.onto           @ontology Finance
  finance-funds.onto     @ontology Finance          (same namespace: one ontology)
  exchange.onto          @ontology Exchange
  markets.fn             @functions Markets
  market-ids.ref         @referential MarketIds
  market-ids.reg
  exchange.bind          @binding Exchange
  exchange.formats
  exchange-finance.map   @mapping Exchange -> Finance
  statement.obs          @obs Finance
```

```text
$ onto ls
ontology      Dimensions          2026-11-10  finance/dimensions.onto
ontology      Exchange            2026-11-10  finance/exchange.onto
ontology      Finance             2026-11-10  finance/finance.onto finance/finance-funds.onto
functions     Markets             2026-11-10  finance/markets.fn
referential   MarketIds           2026-11-10  finance/market-ids.ref (+ market-ids.reg)
binding       Exchange            2026-11-10  finance/exchange.bind (+ exchange.formats)
mapping       Exchange->Finance   2026-11-10  finance/exchange-finance.map
observations  Finance             2026-11-12  finance/statement.obs

$ onto check finance/exchange-finance.map
finance/exchange-finance.map:14: error map.unknown-target: Finance/Instrument.Ticker is not declared
finance/finance.onto:41: warning ontology.unused-alias: alias D is never used
1 error, 1 warning in 1 file (5 read)

$ onto fmt --check
finance/statement.obs
1 file not in normal form; run 'onto fmt -w' to rewrite it

$ onto state finance/statement.obs
@obs Finance at=2026-11-12 by=curator:review
...
```

`check` read the mapping's context (`Exchange`, `Finance`, their `@use`
dependencies, the `Markets` library and the `MarketIds` referential) from the
workspace, and reported diagnostics in the files where they occur.

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
| `--json` | Write results and diagnostics as JSON ([JSON output](#json-output)) |
| `-q`, `--quiet` | Suppress results and summaries; diagnostics remain |
| `-h`, `--help` | Show help ([Help](#help)) |
| `--version` | Print `onto <version>` |

Global options may also follow the command (`onto check --json x.onto`).
Abbreviated long options are rejected. `FILE` arguments accept `-` for standard
input, with `--kind KIND` stating what it is.

| Environment | Meaning |
| --- | --- |
| `ONTO_PATH` | Extra search-path directories, separated by `:` (after `-I`) |
| `NO_COLOR`, `NOCOLOR` | Any non-empty value disables color under `auto` |
| `ONTO_DEBUG=1` | Show the Python traceback of an internal error |

## Workspace

### Kinds

| Extension | Kind | Header | Namespace key | JSON `format` |
| --- | --- | --- | --- | --- |
| `.onto` | `ontology` | `@ontology` | `Namespace` | `onto.ontology/1` |
| `.obs` | `observations` | `@obs` | `Namespace` (not indexed) | `onto.observations/1` |
| `.fn` | `functions` | `@functions` | `Namespace` | `onto.functions/1` |
| `.bind` | `binding` | `@binding` | `Namespace` | `onto.binding/1` |
| `.map` | `mapping` | `@mapping` | `From->To` | `onto.mapping/1` |
| `.ref` | `referential` | `@referential` | `Name` | `onto.referential/1` |
| `.ids` | `ids` | sidecar of an ontology | — | — |
| `.reg` | `registry` | sidecar of a referential | — | — |
| `.formats` | `formats` | sidecar of a binding | — | — |
| `.inv` | `inventory` | sidecar of a binding | — | — |

- A file's kind is its extension. A header that disagrees with the extension is
  an error (`cli.kind`). A `.json` file's kind is its `format` member.
- A sidecar belongs to the file with the same stem in the same directory
  (`market-ids.reg` to `market-ids.ref`, `exchange.formats` to `exchange.bind`),
  and to `<Namespace>.ids` for ontologies (spec-01).
- JSON files are never indexed; they are read only when named on the command
  line.

### Indexing

The workspace scans the search path recursively, skipping hidden directories,
and reads only the header of each file. It is built for every command that needs
it and never cached on disk.

- Ontology files sharing a namespace form one ontology (spec-01); differing
  `rev`s are an error (`cli.rev`).
- Two bindings, mappings, libraries or referentials with the same namespace key
  are an error (`cli.duplicate`), naming both files, unless one of them is
  named on the command line, which then wins.
- Observations are indexed by kind only: several documents may describe the same
  namespace.

### Context

To read a file, the CLI loads its context from the workspace, transitively:

| Kind | Context |
| --- | --- |
| `ontology` | The ontologies its `@use` lines name |
| `observations` | The `@obs` ontology, its context, and the referential it names |
| `functions` | The ontologies its `@use` lines name |
| `binding` | The `@binding` ontology, `@use` ontologies and libraries, its sidecars |
| `mapping` | `From`, `To`, `@use` ontologies and libraries, the `referential=` named |
| `referential` | The ontologies its `@use` lines name, its registry |

A namespace that the workspace cannot supply is an error at the line naming it
(`cli.unresolved`): `exchange-finance.map:3: error cli.unresolved: no ontology
Markets in the workspace (searched: ., ../shared)`. Context files are checked
too; their diagnostics are reported in their own files.

## Commands

Commands are grouped as in `onto help`. `FILE...` defaults, where stated, to
every indexed file of the workspace.

### Files

#### `onto check [FILE...]`

Parse and validate files with their context; print diagnostics and a summary.
Without files, checks the whole workspace (including duplicates and unresolved
namespaces across it).

| Option | Meaning |
| --- | --- |
| `--lenient` | Validate observations in lenient mode (spec-02) |
| `--kind KIND` | Kind of a `-` or ambiguous input |

Exits 1 when any error was reported.

#### `onto fmt [FILE...]`

Print files in their normal form. Observations keep their **log form**, which is
lossless; `onto state` prints the state form.

| Option | Meaning |
| --- | --- |
| `-w`, `--write` | Rewrite files in place instead of printing them |
| `--check` | List files not in normal form; write nothing; exit 1 if any |
| `--diff` | Print a unified diff per file not in normal form |

Without files, `--write`, `--check` and `--diff` apply to the workspace; plain
`fmt` requires files. Only files that parse and validate are formatted; the
others are reported and left unchanged. A file is written only when its content
changes.

#### `onto json FILE`

Print the JSON form of a text file, with its context resolved.

#### `onto text FILE.json`

Print the normal text form of a JSON file. Context comes from the workspace, as
for text files.

#### `onto ls [KIND...]`

List the workspace: kind, namespace key, `rev`, files and sidecars, sorted by
kind then namespace. Diagnostics found while indexing are reported. Useful to see
what the CLI will resolve.

### Observations

#### `onto state FILE.obs`

Print the reconciled **state form** (spec-02): retractions applied, identity
links resolved.

#### `onto log FILE.obs`

Print the **log form**: every statement, ordered by `at`.

Both accept `--lenient`.

### Mappings

#### `onto coverage FILE --view VIEW` / `onto coverage FILE.bind|FILE.map`

Print the coverage table (spec-04, [Coverage](spec-04-mapping.md#coverage)),
tab-separated, sorted by source path.

- For observations, `--view VIEW` names the ontology view to cover.
- For a binding, the inventory sidecar, if present, adds the document fields
  the binding never reads. `--inventory FILE.inv` names another one.
- For a mapping, the static coverage of the `From` ontology.

#### `onto reverse FILE.map`

Print the reversed mapping (`To -> From`) in normal form. Lines that cannot be
reversed are reported as warnings (`map.lossy`) and omitted.

#### `onto inventory DOCUMENT...`

Print the inventory of sample documents (JSON, or CSV with `--csv`), sorted by
path. With `--binding NAMESPACE`, print the default binding instead
(spec-04, [Default bindings](spec-04-mapping.md#default-bindings)).

### Functions

#### `onto fn test [FILE.fn...]`

Run the examples of the libraries (spec-04, [Contract for
implementations](spec-04-mapping.md#contract-for-implementations)); without
files, of every library of the workspace. Prints one line per failing example
and a summary; `-v` also prints passing ones. Exits 1 on any failure.

#### `onto fn ls [FILE.fn...]`

List functions with their signatures, sorted by fully qualified name.

### Help

#### `onto help [COMMAND [SUBCOMMAND]]`

Same as `onto [COMMAND] --help`.

## Output

Results go to standard output, diagnostics and summaries to standard error, so
`onto fmt x.onto > y.onto` and `onto json x.onto | jq` are safe.

### Diagnostics

One diagnostic per line, as `str(Diagnostic)` already prints it:

```text
<file>:<line>: <level> <code>: <message>
```

- `file` is relative to the working directory; `line` is 1-based. A diagnostic
  without location omits the `<file>:<line>: ` prefix.
- Diagnostics are sorted by file, line, then level (errors first).
- Codes are the stage's codes (`ontology.*`, `obs.*`, `map.*`, ...); the CLI's
  own are `cli.*`.
- A summary follows, unless `--quiet`: `N errors, M warnings in K files (R read)`,
  where `K` counts the files named or selected and `R` those read for context.
  A clean run prints nothing more than its result.

This form is what compilers print, so editors parse it unchanged (Vim's
`errorformat` `%f:%l: %t%*[^ ] %m`).

### Colors

Under `--color auto`, color is used when the stream is a terminal, `TERM` is not
`dumb`, and neither `NO_COLOR` nor `NOCOLOR` is set. Standard output and
standard error are decided separately. Color is never written to files
(`fmt -w`) nor used in JSON.

| Element | Style |
| --- | --- |
| `error` | bold red |
| `warning` | bold yellow |
| Location `file:line:` | bold |
| Diagnostic code | dim |
| Namespace in a path (`Finance/`) | magenta |
| Element name (`Instrument.Isin`) | green |
| Kind in `ls` | cyan |
| Help headings | bold cyan |
| Hints and summaries | dim |
| Coverage status: `direct` / `transformed` / `condition` / `out-of-scope` / `missing` | green / cyan / yellow / dim / red |

Text printed in a normal form (`fmt`, `state`, `log`, `reverse`) is not
colored, so that it can be copied back into files.

### JSON output

With `--json`, a command prints one JSON document on standard output and nothing
on standard error (except usage errors):

```json
{
  "format": "onto.cli/1",
  "command": "check",
  "ok": false,
  "result": null,
  "diagnostics": [
    {"level": "error", "code": "map.unknown-target", "message": "Finance/Instrument.Ticker is not declared",
     "file": "finance/exchange-finance.map", "line": 14}
  ],
  "files": {"checked": 1, "read": 5}
}
```

`result` is the command's result: the JSON form of a file for `json`, the text
for `fmt`, `state`, `log`, `reverse` and `text` (a string, or an object by file
for several files), rows (objects keyed by the table's columns) for `ls`,
`coverage`, `inventory` and `fn`. `ok` is `true` when the exit status is 0.

## Help

Help is written for someone who does not know the formats yet, as in `memo`:

- `onto` and `onto --help` print a one-line description, the global options,
  the commands grouped as [above](#commands) with their synopsis, the
  [terms](#terms) used in synopses, and a getting-started sequence:

  ```text
  Getting started:
    onto ls                       see what the workspace holds
    onto check                    validate every file
    onto fmt --diff               see what normal form would change
    onto state statement.obs      read the current state of observations
  ```

- `onto COMMAND --help` prints the synopsis, a description of a few
  sentences, each option with its default, and examples.
- Errors suggest corrections: `onto chek` → `unknown command 'chek'. Did you
  mean 'check'?`; an unknown option suggests the closest option. Every usage
  error ends with `Run 'onto COMMAND --help' for examples.`
- Help text wraps to the terminal width.

### Terms

| Term | Meaning |
| --- | --- |
| `FILE` | A path to an onto file; `-` reads standard input (with `--kind`) |
| `KIND` | `ontology`, `observations`, `functions`, `binding`, `mapping`, `referential`, `inventory`, `formats` |
| `DIR` | A directory to add to the search path |
| `VIEW` | An ontology view path, e.g. `Finance/PortfolioReview` |
| `NAMESPACE` | An ontology namespace, e.g. `Exchange` |
| `DOCUMENT` | A sample source document (JSON, or CSV with `--csv`) |

## Exit status

| Status | Meaning |
| --- | --- |
| `0` | Success; warnings may have been reported |
| `1` | Errors in inputs, `fmt --check` found files to format, `fn test` failed, or an internal error |
| `2` | Usage error: unknown command or option, missing argument |

An internal error prints `onto: internal error: <message>` and a hint to rerun
with `ONTO_DEBUG=1`.

## Deferred

- `onto bind` and `onto map`: running bindings and mappings, with run modes,
  approval and re-running, belong to the hexa integration
  ([spec-06](spec-06-hexa.md#run)), and come with it.
- `onto diff OLD NEW`: the semantic diff of spec-01 [Changes](spec-01-ontology.md#changes).
- `onto overlay`: overlays (spec-03).
- `onto formats update`: learning value formats from documents (spec-04,
  [Formats](spec-04-mapping.md#formats)), which needs a binding run.
- A workspace configuration file. The search path and header namespaces are
  enough until a project shows otherwise.
- A watch mode and a language server.

## Implementation

- `src/py/onto/cli/`: `workspace.py` (indexing and context), `ui.py` (colors and
  diagnostics), `usage.py` (help text and catalog), `commands.py` (one function
  per command), `__init__.py` (`main(argv) -> int`, parsing and dispatch).
  `src/py/onto/__main__.py` calls `main`.
- `pyproject.toml`: `[project.scripts] onto = "onto.cli:main"`.
- Standard library only: `argparse` (with `suggest_on_error` and `color` from
  Python 3.14), `difflib` for `--diff`, `shutil` for terminal width.
- Commands call the public operations (`load*`, `format*`, `*ToJson`,
  `*FromJson`, `*Coverage`, `mappingReverse`, `inventoryFromDocuments`,
  `defaultBinding`) and convert `FormatError` into diagnostics; the CLI adds no
  format semantics of its own.
- Tests `tests/T07-*` call `main([...])` in process on a temporary workspace
  built from the spec examples, and check standard output, standard error and the
  exit status.

<!-- EOF -->

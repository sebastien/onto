---
identity: "onto:component:cli"
created: 2026-11-25T19:44:10.961159+00:00
updated: 2026-11-25T19:44:26.179766+00:00
title: CLI component
---
# CLI component

**Owns** the `onto` command line (spec-07): indexing a workspace by header,
loading each file with the files it depends on, one command per task, human or
`--json` output, `file:line:` diagnostics and exit status.

- *Package*: `src/py/onto/cli/`: `workspace.py` (indexing, context, loading),
  `ignore.py` (`.gitignore` then `.ontoignore` per directory), `usage.py`
  (command catalogue, parsing, help), `commands.py` (one method per command)
  and `ui.py` (styles, diagnostics, tables). `main.py` and `__main__.py` run it;
  `bin/onto` adds a sibling `../hexa/src/py` when present.
- *Commands*: `check`, `fmt`, `json`, `text`, `snap`, `diff`, `ls`, `meta`,
  `state`, `log`, `coverage`, `reverse`, `run`, `inventory`, `fn test`,
  `fn ls` and `help`.
- *Workspace*: the onto files under the project root, plus `-I` and
  `ONTO_PATH`, indexed by header namespace. Named files are read even when
  excluded.
- *Boundaries*: commands call the formats' public operations and turn
  `FormatError` into diagnostics; the CLI adds no format semantics. `onto run`
  executes one binding or mapping run through the hexa integration and is
  one-shot: without a store, it neither retracts nor holds for approval.
- *Deferred* (spec-07): re-running against a store, `onto overlay`,
  `onto formats update`, `.reg` readers, a workspace configuration file, a
  watch mode and a language server.

Sources: `docs/specs/spec-07-cli.md`, `src/py/onto/cli/`

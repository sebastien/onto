```
   ▄▄▄▄▄▄▄▄▄    ▄▄▄▄▄▄▄▄▄▄▄    ▄▄▄▄▄▄▄▄▄▄▄▄▄▄▄    ▄▄▄▄▄▄▄▄▄
 ▄▀░▓░      ▀▄  █   ▓░     ▀▄  █     ░▓░     ▓  ▄▀░▓░      ▀▄
▐▌  ▒        ▐▌ ▓   ▒       ▐▌ █      ▒      ▒ ▐▌  ▒        ▐▌
█   ░  ░      █ ▒   ░        ▓ █▄▄▄   ░  ▄▄▄▄░ █   ░  ░      █
█      ▓      █ ░            ▒    █      █     █      ▓      █
▓      █      █ ░      ░     ░    ▓      █     ▓      █      █
░      █      ▓ ░      ▒    ░▒    █      █     ░      █      ▓
▒░     ▓      ▒ ▒░     ▓   ░▒░    ▒░     █     ▒░     ▓      ▒
▐▓▒░   ▀     ▐▌ ▓▒░   ░█  ░▒▓▒    ░▓▒░   █     ▐▓▒░   ▀     ▐▌
 ▀▓▒░       ▄▀  █▓▒░  ▒█ ░▒▓█▓    ██▓▒░  █      ▀▓▒░       ▄▀
   ▀▀▀▀▀▀▀▀▀    ▀▀▀▀▀▀▀▀ ▀▀▀▀▀    ▀▀▀▀▀▀▀▀        ▀▀▀▀▀▀▀▀▀
```

*onto* is a format (JSON & text) to represent conceptual models (ontologies)
and instance data (observations), as well the mapping between systems and
the records they describe.

*onto*'s goal is to:
- Provide a format to describe data that is compact and expressive
- Can we read and edited by humans and machines/agents efficiently
- Facilitate data management and systems integration

Onto is implemented in Python.

Onto offers the following formats:

- `.onto` for ontologies

And the following CLI operations ([spec-07](docs/specs/spec-07-cli.md)):

- `onto check [FILE...]` validates files with their context, found in the workspace by namespace
- `onto fmt [-w|--check|--diff] [FILE...]` prints or rewrites files in normal form
- `onto json FILE` / `onto text FILE.json` convert between text and JSON forms
- `onto ls` lists the workspace: kinds, namespaces, revisions and files
- `onto state FILE.obs` / `onto log FILE.obs` print observations in state or log form
- `onto coverage`, `onto reverse FILE.map`, `onto inventory DOCUMENT...` for bindings and mappings
- `onto fn test` / `onto fn ls` run and list function libraries

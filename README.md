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

Onto offers the following formats, each with a text and a JSON form:

- `.onto` for ontologies ([spec-01](docs/specs/spec-01-ontology.md))
- `.obs` for observations ([spec-02](docs/specs/spec-02-observations.md))
- `.bind`, `.map` and `.fn` for bindings, mappings and function libraries
  ([spec-04](docs/specs/spec-04-mapping.md))
- `.ref` for identity referentials ([spec-05](docs/specs/spec-05-identities.md))

## Get started

Onto needs Python 3.14 or later and has no other dependencies. From a
checkout, `pip install .` installs the `onto` command; `uv run onto` runs it
without installing.

## In a nutshell

Files name each other by namespace (`@use Finance as F`), so `onto` indexes
the files of your project by their header and finds what each one needs:

```
$ onto ls ontology mapping
mapping   Exchange->Finance              finance/exchange-finance.map
ontology  Exchange           2026-11-10  finance/exchange.onto
ontology  Finance            2026-11-10  finance/finance.onto

$ onto check finance/exchange-finance.map    # loads Exchange, Finance, Markets, MarketIds
no problems in 1 file (5 read)

$ onto fmt --check                           # lists files whose layout would change

$ onto coverage finance/exchange-finance.map
source                target                 status       note
Dividend.Amount       Dividend.Amount        direct
Dividend.Currency                            condition
Instrument.Class      Instrument.AssetClass  transformed

$ onto reverse finance/exchange-finance.map > finance-exchange.map
finance/exchange-finance.map:19: warning map.lossy: ... 'AssetClass' is not
reversed: @map 'AssetClassFromCode' is not exact and one-to-one
```

`onto help` lists every command; [spec-07](docs/specs/spec-07-cli.md)
describes them.

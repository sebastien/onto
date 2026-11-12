# Overlay format

A reviewed curation layer applied to an imported [ontology](spec-01-ontology.md).
The schema source stays flat and authoritative for what it holds; the overlay
adds explicit interpretations: value types, structures, attribute types, facets,
attribute moves and renames. These change schema meaning, never instance values.
Overlays are authored by people (or agents, then reviewed) and kept in version
control next to the generated ontology.

## Example

```text
@overlay Finance rev=2026-11-10
@use Dimensions as D
@use Reference as R

D/PersonName = {status=inferred}
  GivenNames Text
  Surname Text
R/Company = Company {status=inferred}
@refine Person.Name D/PersonName {status=inferred}
@refine Dividend.PayerCode R/Company {status=inferred} -- The code identifies the issuer

Bond of Instrument                              -- Fixed-income terms
  BondCouponRate => CouponRate
  BondMaturityDate => MaturityDate
  InterestFrequency

Derivative of Instrument                        -- Option and future terms
  DerivativeExpiryDate => ExpiryDate
  OptionType
  StrikePrice

Investing/Investor of Person
  InvestmentHorizon => Horizon
  RiskTolerance
```

## Format

- Lexical rules follow the ontology format: two-space bodies, `//` comments,
  ` -- doc` strings, names and paths.
- `@overlay <Namespace> {key=value ...}` comes first. `rev` names the ontology
  revision the overlay was reviewed against. `@use` aliases are allowed.
- A facet block `F of E [{annotations}] [-- doc]` declares the facet in the
  output ontology, with the given annotations and doc.
- Body lines move attributes from `E`'s own body into the facet:

  | Line | Effect |
  | --- | --- |
  | `Attr` | Move `E.Attr` to `E.F.Attr` |
  | `Attr => NewName` | Move and rename to `E.F.NewName` |
  | `Attr [annotations] [-- doc]` | Move; annotations/doc are added to or replace the source's |

- Facet blocks for the same facet in several overlay files are combined.

### Value types and structures

Type declarations use ontology syntax unchanged: `T = Text`, `T = Entity`,
vocabularies, aliases, measurement qualifiers, and `T =` with a field body.
They add a type or replace an existing type's definition and fields. Replacing
an entity, facet or relation with a type is invalid. A type may be defined only
once across the supplied overlays.

Existing type IDs survive refinement. Supplied annotations override the original
keys; omitted keys and docs are preserved. New types and fields use `(overlay)`
in the identity sidecar. Type replacement is deliberate, not an inferred merge:
include all fields you intend to retain.

### Attribute retyping

```text
@refine Owner.Attribute Type {status=inferred}  -- Rationale
```

The target must already exist. `Owner.Facet.Attribute` and structure-field paths
are also supported. The type uses the ontology's type-position syntax, including
entity references and inline vocabularies. Retyping preserves the attribute's
identity, cardinality and derivation; it merges annotations and replaces its doc
only when a doc is supplied. A target may be refined only once per overlay batch.
Role slots cannot be retyped this way.

Refinements address paths **before facet moves**, regardless of file order. To
refine and move `Instrument.BondCouponRate`, target that original path, not the
future `Instrument.Bond.CouponRate`. Aliases introduced in an overlay are included
in the output ontology; conflicting alias meanings are errors.

Changing scalar text to a structure, or an identifier to a reference, is a semantic
proposal. It does not parse names, convert values, resolve entity identity, merge
flat fields, or make old observation payloads valid against the new shape.

## Application

`OverlayApply` runs after the source import and before normalisation:

1. Add/refine value types; apply attribute retyping against pre-move paths.
2. Resolve each facet subject and attribute; declare each facet and move (and
   rename) its attributes, keeping type,
   cardinality, annotations and derivation.
3. Rewrite derived-attribute dependencies and `Owner.Attr` type references that
   point to moved attributes.
4. Carry each moved attribute's source identifier to its new path in the sidecar.
   Authored facets, types and fields are marked `(overlay)`. Existing IDs remain.

Run `OntologyValidate` on the complete result before writing it. Type references,
alias cycles, field names and qualifier annotations use the same checks as any
other ontology; overlays do not bypass those checks.

Errors (the import fails, nothing is written):

- unknown subject entity or attribute;
- an attribute moved twice;
- a facet name colliding with an attribute or another facet of the subject;
- a renamed attribute colliding within the facet;
- duplicate type definitions or retyping the same target twice;
- an unknown retyping target, or replacing a non-type with a type;
- conflicting namespace aliases or invalid resulting ontology references.

Warnings (reported in diagnostics):

- the overlay `rev` differs from the imported ontology's `rev`;
- an empty facet block.

Because moves keep source identifiers, `OntologyDiff` reports them as
`> Instrument.BondCouponRate => Instrument.Bond.CouponRate`, not as removal and
addition. When the schema source later models the facet itself, the overlay
entry is deleted and the diff shows no change.

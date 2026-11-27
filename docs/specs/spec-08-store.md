# Observation store

A protocol for keeping [observations](spec-02-observations.md) durably in an
online system, and serving them to the people and processes allowed to see
them. It keeps the claims, retractions, metadata and reconciliation of spec-02
unchanged, and adds what an online store needs:

- concurrent writers, with preconditions per slot;
- authorization of every request, and an audit of who appended and read what;
- lifecycle states, retention, redaction and erasure.

A store groups statements into **partitions**. A partition holds everything a
scope knows about one **key entity** instance (a client, a household, an
engagement) and the instances that belong to it. The partition is the unit of
authorization, isolation, retention, redaction and erasure: removing what is
known about a person is one operation on one partition.

A **store file** (`.store`) says what a store holds and how. It declares the
partitions, the systems that hold other slots, the lifecycle policies and the
indexes. It is to a store what a referential (spec-05) is to identities: a
separate file over an ontology, which the ontology does not need to know
about.

The store keeps observations; it does not produce them. Bindings, mappings and
views ([spec-04](spec-04-mapping.md), [spec-06](spec-06-hexa.md)) run in the
host or the client, and a client combines a store's partitions with other
sources in its own session. The store reconciles within a partition only and,
as spec-02 requires, reports conflicts rather than resolving them.

## Concepts

| Concept | Meaning |
| --- | --- |
| Store | A deployment of this protocol |
| Store file | `.store`: the partitions a store holds, the systems that hold the other slots, lifecycle policies and indexes |
| Scope | An isolated set of partitions whose handles are stable within it (spec-02 `@scope`); authorization returns it, and nothing crosses scopes |
| Key entity | An entity type whose instances each get a partition |
| Partition | Every statement a scope holds about one key entity instance and its members |
| Anchor | The key entity instance a partition is about |
| Member | An instance whose home is a partition: its anchor, or an instance its declaration reaches |
| Statement | A claim or retraction (spec-02) as stored: with a sequence number, a record time and a principal |
| Record | An entry of a partition's log that is not a statement: a lifecycle change, a redaction, a merge |
| Batch | The statements appended by one request, atomically, under one request ID |
| Slot version | The sequence number of the latest log entry that changed a slot, used as a precondition |
| Held slots | The slots a store holds for an instance, decided by the instance's origin; claims on the slots other systems hold are rejected |
| Principal | Who makes a request, as authorization reports it: a person, an agent or a process |
| Lifecycle state | `active`, `orphaned`, `archived` or `deletion`, of a partition, a subject or a statement |
| Index | Declared held slots of a partition kind, kept across its partitions, which servers query for the partitions matching a filter |
| Redaction | Destroying the values of statements, keeping their place in the log |
| Purge | Destroying a partition, keeping only a record that it was purged |
| Store bundle | What a store runs with, compiled by Python: model facts, partition kinds, held slots and policies |

## Example

A financial adviser's application records identity checks, which the
practice's other systems do not hold. It adds two types to the
[spec-01](spec-01-ontology.md#example) `Finance` ontology:

```text
@ontology Finance rev=2026-11-26

Document                                        -- A file seen as evidence
  Digest Text {key}
  Title Text

IdentityCheck(Person, Document) {kind=event}    -- A check of a person's identity against a document
  Confirmed Boolean
  Method InPerson|Electronic|CertifiedCopy
```

Its store file, `adviser-app.store`, does four things:
- declares two partition kinds;
- leaves to the exchange what the [spec-04](spec-04-mapping.md#example) import
  fills;
- archives clients' partitions for seven years before deletion;
- indexes the outcome of identity checks:

```text
@store AdviserApp rev=2026-11-26 edit=edit:adviser-app
@use Finance as F
@system Exchange -> Finance                     -- The exchange holds what its import fills

@partition Client(client: F/Person) {archived=P7Y} -- Everything the application holds about one person
  checks: F/IdentityCheck = client <- Person
  documents: F/Document = checks -> Document

@partition Household(household: F/Household)

@index ClientChecks Client                      -- Clients by the outcome of their identity checks
  checks.Confirmed
  checks.Method
```

An adviser records a check. The application appends this batch to partition
`Client/Person_U1`, in the store's scope `adviser-app`:

```text
@obs Finance by=app:intake
@src e=edit:adviser-app
@src e
@scope adviser-app

IdentityCheck_C41:IdentityCheck {valid=2026-11-26}
  Person Person_U1
  Document Document_D9
  Method InPerson
  Confirmed true
Document_D9:Document
  Digest sha256:9f2c41
  Title Passport
```

The request carries its JSON form (spec-02), a request ID and the slot versions
the adviser saw:

```json
{
  "requestId": "3fe1c31e-24ad-4ca1-88d9-729045834e51",
  "expect": [{ "s": "IdentityCheck_C41", "exists": true, "version": 0 }],
  "observations": { "format": "onto.observations/1", "obs": { "ontology": "Finance", "scope": "adviser-app" }, "…": "…" }
}
```

- **Membership.** `IdentityCheck_C41` belongs to the partition because its
  `Person` is the anchor, `Person_U1`. `Document_D9` belongs because the check
  refers to it.
- **Stamping.** The store gives the eight statements sequence numbers, the
  record time and the adviser as principal. Their `at` defaults to the record
  time.
- **Retries.** A retry with the same request ID returns the same answer.
- **Concurrency.** Had another writer created `IdentityCheck_C41` first, its
  existence slot would no longer be at version 0, and the batch would be
  rejected whole.
- **Lifecycle.**
  - When the person stops being a client, a reviewer archives the partition.
  - Seven years later its policy schedules it for deletion.
  - After the default grace period the store purges it: the check and the
    document are destroyed.
- **References.** Partitions that only refer to `Person_U1` keep a handle that
  resolves to nothing personal.
- **Index.** The application's server queries `ClientChecks` for the clients
  with a confirmed check. To list the clients without one, it asks the system
  that holds clients for all of them except those.

## Store files

### Format

```text
@store <Name> key=value ...
@use <Namespace>[/<Domain>] as <Alias>
@system <From> -> <To> {scope=<token>} -- doc
@partition <Kind>(<alias>: <Type>) {key=value ...} -- doc
  <alias>: <Type> = <parent> -> <member> {key=value ...} -- doc
  <alias>: <Type> = <parent> <- <member> {key=value ...} -- doc
- <Type>.<Path> {reason=<token>} -- doc
@index <Name> <Kind> -- doc
  <alias>.<Path> -- doc
```

The [ontology lexical rules](spec-01-ontology.md#lexical-rules) apply. A store
file holds one store; a store may span several files with the same `@store`
header, as a mapping may.

**`@store`** comes first.
- `rev` is the file's revision.
- `edit` is the source token of the application's interactive edits. Clients
  use it ([Sources and supersession](#sources-and-supersession)), and the store
  uses it for the links it makes itself.

**`@use`** names the ontology whose observations the store holds; every alias
names that ontology or one of its domains.

**`@system From -> To`** names a mapping into the store's ontology, by its
header ([spec-04](spec-04-mapping.md#mappings)). The slots it fills for the
instances it produces belong to the system `From` describes, which is their
system of record, so the store does not hold them ([Held slots](#held-slots)).
`scope` is the `@scope` of that system's observations, which its
source-qualified handles carry (spec-05); it defaults to `From`.

**`@partition`** declares a partition kind:
- `<Kind>` names it, unique in the store, and prefixes partition IDs.
- The root population declares the key entity: anchors are its instances,
  including those of its specialisations.
- Member populations each follow a verb, a reference-valued attribute or an
  association role from the root or another member, with the population lines
  of a [rooted view](spec-01-ontology.md#rooted-views), without `where`
  filters or projections.
- A member's facets, structures and attribute values are claims about it, so
  they live where it lives.
- A binary relation claim lives in the home of its subject. Its object may live
  elsewhere; only its handle is stored.

Keys on a partition line or a population line:

| Key | Value | Means |
| --- | --- | --- |
| `orphaned` | Duration or `never` (the default) | How long a subject stays `orphaned` before the store archives it |
| `archived` | Duration or `never` (the default) | How long a subject stays `archived` before the store schedules it for deletion |
| `grace` | Duration, `P30D` by default | How long `deletion` waits before the store destroys the subject |
| `privacy` | `kept` | On a population line: accept personal values about another key entity ([Checks](#checks)) |

- Durations use the spec-02 syntax.
- A population line's keys override its partition's for the subjects of that
  population.

**`- <Type>.<Path>`** excludes a slot the store must not hold, although no
`@system` mapping fills it. `reason` is a token, as in mapping exclusions.

**`@index`** declares an [index](#indexes) over the partitions of a kind. Each
line names a column: a population of the kind and a slot of its type, with the
path syntax of rooted-view projections (`checks.Confirmed`, `client.Notes`).

### Checks

`onto check` checks store files against their ontology and the `@system`
mappings:

- **Resolution.** Every type, path, role and mapping resolves, and population
  lines follow the rooted-view rules.
- **One kind per type.** A key entity type roots one kind, and is never a
  member population of another kind. A member type appears in at most one kind.
- **Personal facts stay home.**
  - An attribute with a `privacy` annotation (spec-01) is personal.
  - A member population is reported when its type has personal attributes and
    a role or reference to the key entity of another kind. An interaction
    holding a participant's address as written is one example.
  - The population line accepts such values with `{privacy=kept}`. Erasing the
    other key entity then redacts them through the
    [reference index](#references).
- **Policies.** Durations are valid, and keys apply where they are written.
- **Indexes.** An index names an existing kind, its columns are held slots of
  that kind's populations, and index names are unique in the store.

### Normal and JSON forms

- **Normal form.** In order:
  1. `@store`;
  2. `@use` lines, sorted by alias;
  3. `@system` lines, sorted by header;
  4. partitions, sorted by kind, with their populations in declared order;
  5. exclusions, sorted by slot;
  6. indexes, sorted by name, with their columns in declared order.
- **JSON form.** `onto.store/1` holds the header keys, `uses`, `systems`,
  ordered `partitions` (`kind`, `root`, `populations` in the rooted-view JSON,
  and their keys), `exclusions` and `indexes` (`name`, `kind`, ordered
  `columns`). Text and JSON convert losslessly, comments excepted.

## Partitions

### Homes

Every statement a store accepts is about a member of the partition it is
appended to.

- **Partition IDs.** A partition is named `<Kind>/<anchor handle>`, as in
  `Client/Person_U1`. The anchor's type must be the kind's root type or a
  specialisation of it.
- **Anchors.** A partition exists from its first batch. An anchor that comes
  from another system has no existence claim in it, since that system holds
  its existence; in the partition's state it is implicit (spec-02). An anchor
  created in the store states its existence like any member.
- **Origins.** A subject's handle tells which system it comes from
  ([spec-09](spec-09-sessions.md#origins)). Statements about a subject of a
  type that a system produces, whose handle has no origin, are rejected as
  `origin.unknown`.
- **Members.** A subject other than the anchor is a member when the
  partition's statements, or the batch, state the link that the kind's
  population lines follow back to the anchor. Otherwise:
  - an unstated link is rejected as `home.unlinked`;
  - a link to another anchor is rejected as `home.mismatch`;
  - a type no population of the kind reaches is rejected as `home.none`.
- **Home links.** A member that comes from another system may hang on a link
  that system holds, such as a CRM group membership's `Group`. The store
  cannot state such a link, so the batch carries it in `links`, as the system
  states it:
  - the store accepts a link only on a slot it does not hold, and only where a
    population line of the kind follows it (`link`);
  - it uses the link to home the member, and records it in the log, as a record
    with its own `seq`;
  - it never reconciles the link into the state, whose source of the link stays
    the system.

  The store cannot check a link against the system that holds it, so a client
  can file a member only in a partition it may append to.
- **Parents.** The subjects through which a member's links reach the anchor
  are its parents. In the example, a check is the parent of its document.
- **No moves.** A member never changes partition. Re-anchoring happens only by
  [merging](#merges) partitions.

### Held slots

A store holds the slots of its partitions' members by their origin
([spec-09](spec-09-sessions.md#holders)):

| Member's origin | Slots the store holds |
| --- | --- |
| The store | Every slot of its type |
| A system | Every slot that system's `@system` mapping does not fill, existence included |
| Shared | Every slot no `@system` mapping fills |

The store file's exclusions are never held. The store rejects claims on any
other slot as `slot.not-held`. A person created in the store thus holds its
name, while a person from a system that fills names does not.

- **Recompiling.** When a recompiled bundle stops holding a slot, for instance
  because a new mapping fills it, the store orphans the statements on that
  slot (reason `not-held`) instead of dropping them ([Lifecycle](#lifecycle)).
- **Deferred.** Claims a store keeps as evidence on slots another system holds
  are [deferred](#deferred).

## Statements

### Batches

An append carries:

- `requestId`, required: the identity of the request (see
  [Retries](#retries)).
- `observations`: an `onto.observations/1` document in log form (spec-02), with
  claims and retractions. Its `scope` must be the store's scope, its handles
  are scope-stable, and it has no `gaps`.
- `expect`, optional: the slot versions the batch was prepared against.
- `links`, optional: the [home links](#homes) of members that come from
  another system, as spec-02 JSON claims.

The batch is validated whole, in strict mode, against the store bundle:

- spec-02 validation: types, attributes, values, vocabularies, facets,
  contexts, identity links;
- homes, origins, held slots, lifecycle states, the preconditions and the
  [limits](#limits).

On the first error nothing is appended, and the answer names the statement
(`n`) and the check that failed.

### Stamping

The store adds to each accepted statement:

- `seq`: the next sequence number of the partition's log, consecutive from 1;
- `recorded`: the time the store accepted the batch;
- `principal`: who made the request, from authorization;
- `requestId`: the batch's request ID;
- `bundle`: the revision of the store bundle that validated it.

Producers keep their own metadata:

- `src` is required, explicitly or from `obs.src`.
- `at` defaults to `recorded`. A producer sets an earlier `at` only to report
  an earlier observation, as an import does. An `at` later than `recorded`
  is rejected.
- `by`, `valid`, `ctx`, `conf` and qualifiers are as in spec-02.

### Sources and supersession

Reconciliation is spec-02's, with the log order (`seq`) as statement order:

- **Within one source**, a later `at` supersedes; for equal `at`, the higher
  `seq` does.
- **Across sources**, differing claims on a slot are conflicts, kept and
  reported.

Hence a convention:

- **Interactive edits share one source per application**, the store file's
  `edit` token (`edit:adviser-app`). One adviser's correction then supersedes
  another's, and preconditions catch concurrent edits.
- **Imports and agents reading documents use their own sources**
  (`upload:document/123`). Their disagreements with edits surface as
  conflicts instead of overwriting.

### Preconditions

A slot is identified as in the JSON form: a subject `s` with one of `p` (an
attribute path, keyed elements included), `facet` or `exists`, or a relation's
`rel` and `roles`; plus `ctx` when contextual.

- **Versions.** A slot's version is the `seq` of the latest log entry that
  changed it: a claim or retraction on it, or a lifecycle change or redaction
  of its statements. A slot never changed is at version `0`.
- **Retractions.** A retraction moves the versions of the slots it withdraws;
  `- h` moves every slot of `h`.
- **Checks.** `expect` lists slots and the versions the writer saw. If any slot
  moved, the batch is rejected with `409 precondition`, and the answer gives
  the slots' current versions.
- **Granularity.** Preconditions are per slot, not per partition: writers
  editing different facts about one person do not collide.

### Retries

A request ID identifies one batch in its partition:

- the same ID with the same payload returns the original answer, even after
  later batches;
- the same ID with another payload is rejected as `409 request_reused`.

Retry records are kept 7 days. After that, a retried batch is checked again
like a new one, and normally fails its preconditions rather than being applied
twice. A transport failure means the batch may have been accepted, so the
client retries the same payload with the same ID.

## Lifecycle

A lifecycle state flags data that its system of record has left behind, or
that people have set aside or scheduled for destruction, without changing what
the data says. It is a record of the store, not a claim about the world: a
retraction says a claim should not have been made, while archiving keeps a
correct claim out of the way.

### Levels and states

States apply at three levels:

| Level | Target | Covers |
| --- | --- | --- |
| Partition | One partition | Everything in it |
| Subject | One member | Its statements, and those of the members whose every parent it covers |
| Statement | Chosen statements, or all statements of a slot | Those statements |

- **The anchor.** A subject-level state on the anchor covers the anchor's own
  statements only. The partition level covers the rest.
- **Shared members.** A member with several parents is covered only when all
  of them are. A document shared by two checks stays active while one check
  does.

| State | Means |
| --- | --- |
| `active` | Normal; the default |
| `orphaned` | Its system of record left it behind: the anchor was deleted or merged away there, a parent was orphaned, or its slot stopped being held. Kept as it was, for review |
| `archived` | Set aside by a person or a policy; kept, readable on request |
| `deletion` | Scheduled for destruction at `purgeAfter`; restorable until then |

**Effective state.** A statement's effective state is the most advanced of its
own state, the states of the subjects that cover it, and its partition's
state, in this order: `active`, `orphaned`, `archived`, `deletion`.

### Transitions

| From | To | By | When |
| --- | --- | --- | --- |
| `active` | `orphaned` | The host, the store | The system of record dropped the anchor or merged it away; the store, for slots no longer held |
| `orphaned` | `active` | The host, a reviewer | The anchor is back in its system of record (undeleted), or a reviewer keeps the data |
| `active`, `orphaned` | `archived` | A reviewer, the `orphaned` policy | Set aside |
| `archived` | `active` | A reviewer | Brought back |
| `active`, `orphaned`, `archived` | `deletion` | A reviewer, the `archived` policy, an erasure request | `purgeAfter` is now plus the grace period, or now for an erasure request |
| `deletion` | The state before it | A reviewer | Before `purgeAfter` |
| `deletion` | Destroyed | The store | At `purgeAfter` |

- **Destruction.** At `purgeAfter` the store destroys what `deletion` covers:
  - a partition is [purged](#purge);
  - a subject's or statement's values are [redacted](#redaction).

  Destruction is irreversible.
- **Policies.** The store applies the `orphaned`, `archived` and `grace`
  durations of the store file itself, counted from the moment the current state
  was entered. It records them under its own principal, `store:policy`.
- **Who decides.** The authorization callback decides who may change which
  states (access `lifecycle`). For example, the host lets reviewers archive and
  delete, and keeps `orphaned` for its own processes.

### Effects

| | `active` | `orphaned`, `archived`, `deletion` |
| --- | --- | --- |
| State reads | Included | Included only when the read asks for that state |
| Log reads | Included, with their states | Included, with their states |
| Appends | Accepted | Rejected as `409 lifecycle` when the batch states anything about a covered subject; a new claim on a slot whose only statements are covered is accepted |
| Reconciliation | Takes part | Takes part only in reads that include it |

- **Records.** A lifecycle change is a record in the partition's log, with its
  own `seq`. It names its level and target, the previous and new state, the
  principal, the time, the reason and `purgeAfter`, so sync and audit see it.
- **Versions.** A subject- or statement-level change moves the versions of the
  slots whose default state it changes. A partition-level change moves none:
  appends are refused while the partition is not `active`, and restoring it
  brings back the state as it was.
- **Feed.** Every change moves the partition's entry in the change feed.
- **Marking.** Reads mark each subject and statement they return with its
  effective state when it is not `active`.

### Erasure

An erasure request for a key entity:

1. sets its partition to `deletion` with `purgeAfter` now;
2. sets to `deletion`, also with `purgeAfter` now, the populations that keep
   personal values about it in other partitions (`{privacy=kept}`), as the
   reference index lists them.

The store records the request and reports its progress. It is complete when the
partition is purged and every partition the reference index listed is redacted.
The index is eventually consistent, so the store keeps checking until the index
has caught up with every batch accepted before the request.

## Reading

### State

A state read takes a selection and returns the partition's spec-02 state form
restricted to it:

```json
{ "select": [{ "s": "Person_U1", "slots": ["DateOfBirth", "Name.Surname"] }, { "population": "checks" }],
  "include": ["orphaned"] }
```

- **Selection.**
  - An entry names subjects (`s`) or populations of the kind, and optionally
    the slots to keep.
  - A slot without keys keeps each of its keyed elements: `Phones.Number`
    keeps `Phones[Mobile].Number` and `Phones[Home].Number`, while
    `Phones[Home].Number` keeps only that element.
  - Without `select`, the read returns the whole partition.
- **Pages.** A population entry may ask for a page:
  `{ "population": "checks", "page": { "size": 10, "after": "…" } }`.
  - Members come the most recently added first: by the `seq` of their first
    statement, latest first.
  - The answer gives a cursor to the next page while more remain.
- **Reconciliation.** The state is reconciled over the partition's statements
  whose effective state the read includes (`active`, plus `include`):
  retractions applied, superseded claims removed, conflicts flagged, identity
  links applied and implicit instances listed.
- **Answer.**
  - `head`, the partition's last `seq`;
  - `generation`;
  - the partition's lifecycle state;
  - `versions`, the version of every selected slot, for preconditions;
  - `observations`, the state document, marked as in [Effects](#effects).
- **History.** `asOf` reads the state as of a `seq`, from the log up to it.

### Log

A log read returns the statements and records after a `seq`, in order, with
their stamps and current lifecycle states.
- Pages are bounded. An answer gives `after`, `through`, `head` and `hasMore`;
  continue from `through`.
- A cursor beyond `head` is rejected.
- Redacted statements appear redacted.

**Proposed: newest-first history (DEC0036).** A separate log read takes a
selection, as state reads do, and an optional opaque `cursor`. Without a
cursor it includes eligible statements through the current `head`, including
the head itself. It orders them by the instant `recorded`, newest first, using
descending `seq` to break ties within the partition. Unlike the forward log,
this order still follows record times after a partition merge assigns new
sequence numbers.

- Each claim and retraction gives `was`: its slot's reconciled value just
  before its `seq`, absent for a first value. Sequence still determines
  reconciliation; recorded time only orders the page.
- The answer gives a continuation cursor while more entries remain. It binds
  the selection, generation, initial `head` and the last position in the
  history order. The next page starts strictly after that position, without
  including statements appended after the first page's head. A cursor does
  not preserve access or redacted values.
- [Session histories](spec-09-sessions.md#history) use this read.

### Several partitions

A batch read takes selections in several partitions and answers each
separately, with its state or its error. Each partition is authorized on its
own, so one denial does not fail the others.

```json
{ "reads": [{ "partition": "Client/Person_U1", "select": [{ "population": "checks" }] }, { "partition": "Household/Household_H1" }] }
```

The answer's `results` follow the order of `reads`: a state read's answer, or
the partition with the `status`, `error` and `message` of its refusal.

### References

The store indexes, per scope, the partitions whose statements refer to a
handle: as a reference value, a relation participant or an identity link. The
index is updated after each batch, at least once and eventually, and serves
two purposes:
- erasure, to find what to redact elsewhere;
- following references backwards, such as the households that refer to a
  person.

It is read by servers only, since it reveals which partitions exist.

### Changes

Each scope has a change feed: one entry per partition, moved to a new,
increasing position whenever the partition's log, generation or state
changes.

- A cursor is `{epoch, seq}`, and a new epoch restarts the feed from `0`.
- Entries give the partition, its generation and head, its lifecycle state and
  whether it was purged.
- The feed is coalesced: it points at each partition's latest state, not at
  every batch. Readers fetch what they need from the partition.
- It is read by servers only, to notify watching clients and to build indexes.

## Indexes

An index keeps, for every partition of its kind, the values of its columns, so
that a server can find the partitions matching a filter without reading them
all.

- **Rows.** An index has one row per partition of its kind. A row holds:
  - the partition ID and its anchor;
  - the partition's lifecycle state;
  - for each column, the set of values that the population's `active`
    subjects hold at that slot. A population may have several subjects, such
    as a client's checks.
- **Maintenance.** The store updates rows from the scope's change feed, at
  least once and eventually, as it updates the reference index. An index can
  be rebuilt from its partitions at any time, and a new or changed declaration
  builds a new index.
- **Queries.** A query takes a filter over the columns, with the shape of
  Storelight's filters and a column name in place of a path. Only `eq`, `in`,
  `exists` and `and` are allowed:

  ```json
  { "filter": { "and": [{ "eq": ["checks.Confirmed", true] }, { "in": ["checks.Method", ["InPerson", "CertifiedCopy"]] }] } }
  ```

  - `eq` holds when the column's values contain the value, and `in` when they
    contain one of the values. Values compare in their spec-02 JSON encoding,
    with numbers as canonical decimal strings.
  - `exists` holds when the column has any value.
  - Queries return `active` partitions unless they ask for other states, as
    reads do.
- **Answers.**
  - The matching partitions, as IDs and anchors, ordered by partition ID and
    paged.
  - `through`, the position of the change feed the index has reached, so the
    caller knows how fresh the answer is.
- **Coverage.** An index knows only the partitions that exist. An instance the
  store holds nothing about has no partition, so "the clients without a
  confirmed check" means:
  - all the clients the clients' system of record lists,
  - minus the clients the index returns.

  The host composes the two. Negation, ranges and sorting are
  [deferred](#deferred).
- **Access.** Queries are for servers only (`authorizeServer`), since answers
  reveal which partitions exist and what they hold. The host narrows them to
  what each principal may see before returning anything.

## Redaction

A redaction destroys the values of chosen statements: claim values,
qualifiers and retraction values.
- It keeps their place in the log: `seq`, subject, slot, `src`, `at`, `by`,
  `recorded`, `principal` and `requestId`.
- It is a log record: who redacted what, when and why, without the values.

- **Reading.** A redacted claim keeps its slot and supersession order, and
  its value reads `{"redacted": true}`. It takes part in no conflict.
- **Selection.** A redaction selects subjects, slots or statements, or the
  whole partition. It moves the versions of the slots it changes.
- **Copies.** The store destroys the values everywhere it keeps them: in
  statements, in retry records, and in the logs it writes itself. Backups are
  the deployment's concern, which must honour redactions on restore.

## Purge

A purge destroys a partition: its log, retry records and read records, and its
entries in the reference index.

- **Tombstone.** The store keeps only the partition ID, its last generation,
  the time, the principal and the reason. Requests naming the purged
  generation are answered `410 purged`.
- **Recreation.** An append to a purged partition starts a new generation.
  Cursors of the old one are void.
- **Limits of the index.** The reference index finds only handles. Values that
  identify a person without naming their handle are the store file's
  responsibility (`{privacy=kept}`).

## Merges

When two anchors turn out to be the same instance, a merge moves the absorbed
partition into the survivor:

1. **Copy.** Copy the absorbed partition's statements into the survivor, in
   their order, with new `seq`s. They keep their metadata, stamps and
   lifecycle states, and record where they came from.
2. **Link.** Append the identity link `survivor = absorbed` between the two
   anchors (spec-05), with the store file's `edit` source and
   `by=store:merge`.
3. **Orphan.** Mark the absorbed partition `orphaned` with the reason `merged`,
   naming the survivor.

The two partitions share no transaction, so a merge is identified by its
request ID and resumes where it stopped. Members keep their handles: the link
makes their references to the absorbed anchor resolve to the survivor.

## Authorization and audit

The host supplies the authorization callbacks; there is no default access.

- **`authorize(request, partition, access)`** returns the request's `scope` and
  `principal`. It answers `null` for an unauthenticated request (`401`) and
  raises for a denied one (`403`). `access` is `read`, `append`,
  `lifecycle`, `redact`, `purge`, `merge` or `erase`. The callback decides what
  each principal may do, for instance by asking the system that holds the
  anchor whether the principal may see it.
- **`authorizeServer(request)`** guards the change feed and the reference
  index.

Audit:

- **Appends.** Every statement keeps its principal and record time for its
  lifetime.
- **Reads.** The store records each read with its principal, partition,
  selection and time, kept as long as the scope's policy says and purged with
  the partition.
- **Records.** Lifecycle changes, redactions, merges, erasures and purges are
  recorded with their principal, time and reason.
- **No values in logs.** The store's own logs carry identifiers and counts.

## Protocol

JSON over HTTPS, as [Storelight](https://github.com/sebastien/storelight.js)
does:

| Endpoint | Purpose |
| --- | --- |
| `POST /v1/partitions/{id}/statements` | Append a batch |
| `POST /v1/partitions/{id}/state` | Read the state of a selection |
| `GET /v1/partitions/{id}/log?after={seq}` | Read the log after a sequence number |
| `POST /v1/partitions/{id}/log` | Proposed: read a selection's history by recorded time, newest first, with an optional cursor |
| `POST /v1/state` | Read selections of several partitions |
| `POST /v1/partitions/{id}/lifecycle` | Change lifecycle states |
| `POST /v1/partitions/{id}/redactions` | Redact statements |
| `POST /v1/partitions/{id}/purge` | Purge the partition |
| `POST /v1/partitions/{id}/merge` | Merge another partition into this one |
| `POST /v1/erasures` | Erase a key entity; answers with the erasure's progress |
| `GET /v1/erasures/{id}` | An erasure's progress |
| `GET /v1/changes?after={seq}&epoch={epoch}` | The scope's change feed; servers only |
| `GET /v1/references/{handle}` | Partitions referring to a handle; servers only |
| `POST /v1/indexes/{name}/query` | Partitions matching a filter; servers only |

Partition IDs and handles are percent-encoded as one path segment. Errors have
a JSON body with a stable `error` code and a `message`:

| Status | `error` | When |
| --- | --- | --- |
| `400` | `invalid`, with `check` and `n` | A malformed request, or a statement failing validation, homes or held slots |
| `401`, `403` | `unauthorized`, `forbidden` | From the authorization callbacks |
| `404` | `not_found` | A partition never appended to, on read |
| `409` | `precondition` | A slot moved; the answer gives current versions |
| `409` | `request_reused` | A request ID with another payload |
| `409` | `lifecycle` | A batch stating something about a subject that is not `active` |
| `410` | `purged` | A purged generation |
| `413` | `too_large` | A request or statement beyond the limits |

A failure before an answer may leave a batch accepted: retry the same request
ID and payload.

### Limits

| Boundary | Default |
| --- | --- |
| Request body | 8 MiB |
| Statements per batch | 1,024 |
| One statement, serialized | 1 MiB |
| Partition ID, handle | 256 UTF-8 bytes |
| Log page | 1,000 entries |
| Retry records | 7 days |
| Indexes per store, columns per index | 16, 8 |
| Values in one `in` | 64 |
| Index answer page | 1,000 partitions |

Binary content is not stored: a claim refers to it, by digest or location.

## Store bundle

`onto store bundle FILE.store` compiles an `onto.store-bundle/1` document:

- the model facts claim validation and reconciliation consult, as the `target`
  of a view bundle ([spec-06](spec-06-hexa.md#bundles-and-the-javascript-runtime))
  holds them, with what spec-02's strict validation adds:
  - the ontology's `rev`, and the vocabularies, once each, with their values
    (extensions and hierarchical ancestors included), openness, hierarchy and
    order;
  - per attribute, its cardinality (`card`), its value type (a builtin, a
    vocabulary by path, a reference, a structure, or a range of one of these)
    and its exclusive group (`one`);
  - per structure, its key field; per facet, its `when`; per entity,
    association and binary relation, whether it is an event;
- the partition kinds, with their populations compiled to the links that make a
  subject a member, and their parents;
- the held slots, from the populations, the `@system` mappings and the
  exclusions;
- the lifecycle policies, the `edit` source and the limits;
- the indexes, with their columns compiled to the slots they read.

Stores load bundles and never parse text. A bundle changes only by
recompilation; the store records its revision with each batch, and orphans the
statements of slots a new revision no longer holds.

## Implementations

- **JavaScript** (`src/js/onto/store/`):
  - the core (validation, stamping, preconditions, lifecycle and
    reconciliation, reusing the runtime's observations code) and an HTTP
    handler, which runs anywhere;
  - a client for browsers, with an injected `fetch`;
  - a Cloudflare adapter (`server/cloudflare.js`), kept separate so that
    browsers never import `cloudflare:workers`. It runs one SQLite-backed
    Durable Object per partition, routed by scope and partition ID, and one
    object per scope for the change feed, the reference index and erasures,
    updated by alarms after each batch. Alarms also apply lifecycle policies.
  - Each index is one object per scope and index, holding its rows in SQLite,
    updated by alarms from the scope's change feed.
  - It follows Storelight's server design: the authorization callback,
    routing, retry records, chunked payloads and alarms.
  - **Validation.** The core validates a batch as spec-02's strict JSON
    reading does, from the bundle's model facts alone: it accepts a batch
    exactly as written, and rejects one whose values are not already canonical
    (`3.0` for `3`, `3` for the range `3..3`). It answers what Python answers:
    the same acceptance, status, `error`, `check` and `n`. Messages may differ,
    and so may which of several reference-type errors is reported first.
- **Python** (`src/py/onto/store/`): the same operations over one SQLite
  database, using the standard library only. It is the reference: conformance
  tests run each case on both implementations and compare the answers.
- **Store files**: the parser, formatter, checks and JSON form in
  `src/py/onto/store/`, with a schema in `src/json/store.schema.json`.
- **CLI**: `onto check` and `onto fmt` accept `.store` files, `onto ls` lists
  them, and `onto store bundle` compiles them ([spec-07](spec-07-cli.md)).
- **Tests** follow `tests/T08-<n>-store-<name>.py`; the JavaScript side
  replays them like the runtime's conformance tests.

## Correctness checks

- **Store files.** Text and JSON round-trip, and the checks of
  [Checks](#checks) report what they describe.
- **Batches.** A batch is appended whole or not at all; a retried request ID
  is applied once.
- **Preconditions.** A batch whose expected versions moved changes nothing.
  Writers of different slots of one partition do not conflict.
- **State.** The state of a partition equals spec-02 reconciliation of its
  included statements, in `seq` order, minus redacted values.
- **Homes.** Unlinked, mismatched and unknown subjects are rejected; a member
  never changes partition.
- **Home links.** A link on a slot the store holds, or that no population line
  follows, is rejected; an accepted one homes its member but never enters the
  state.
- **Held slots.**
  - A claim on a slot an `@system` mapping fills for a system's instance, or
    that the file excludes, is rejected. The same slot of an instance created
    in the store is accepted.
  - A statement about a handle without origin is rejected.
  - A recompiled bundle that stops holding a slot orphans its statements.
- **Pages.** Population pages cover every member once, the most recently
  added first.
- **Log (proposed history).** The first page can include the head. An absorbed
  partition's statements keep their recorded-time order after a merge.
  Pages include every selected statement through the starting head exactly
  once, each with its slot's value just before its sequence number.
- **Lifecycle.**
  - Effective states follow the levels and the order of states.
  - A shared member stays active while one of its parents does.
  - Appends about covered subjects are refused.
  - Policies apply on time.
  - Restoring from `deletion` returns the previous state.
- **Erasure.** It purges the partition, redacts the `{privacy=kept}` values the
  reference index lists, and reports completion only once the index has caught
  up.
- **Redaction.** It leaves no value in statements, retry records or the
  store's logs, and keeps the log's order and stamps.
- **Purge.** It leaves only the tombstone; old cursors are void.
- **Merges.** A merge is idempotent and resumable, and the absorbed anchor's
  references resolve to the survivor.
- **Feeds.** The feed never skips a partition whose log or state changed. The
  reference index converges after each batch.
- **Indexes.**
  - Once the feed has caught up, a row holds exactly the indexed values of its
    partition's `active` subjects.
  - A rebuilt index equals the incrementally maintained one.
  - A query returns exactly the matching partitions, in order.
- **Authorization.** Every request is authorized, and every append and read is
  attributed.

## Deferred

1. **Richer indexes.**
   - Negation, ranges and sorting by values.
   - Registering anchors, so that an index covers every instance of a key
     entity, not only those with a partition.
2. **Evidence.** Claims a store keeps as evidence on slots another system
   holds (a date of birth read from a scanned passport), reported as conflicts
   against that system's claims.
3. **Moving a member** to another partition without merging.
4. **Reads by time.** `asOf` by `at` or `valid` time, beyond `asOf` by `seq`.
5. **Registry-backed identities** (spec-05) inside a store.
6. **Meta handles in the JavaScript store.** spec-02's `meta.unresolved` and
   `meta.path` checks need the generated Meta records; the JavaScript store
   does not make them yet.

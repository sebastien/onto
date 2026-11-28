# Sessions

A **session** combines what several systems know into one state, and sends
each change to the system that holds it. It is the client side of an
application built on onto, over an [observation store](spec-08-store.md) and
the systems its store file names:

- it plans views across those systems, choosing for each fact the system that
  holds it;
- it runs their reads, as [rooted retrieval](spec-06-hexa.md#rooted-retrieval)
  does, and reconciles their observations into one state in which every claim
  keeps its source;
- it lists instances through **list views**, composing a system's list reads
  with the store's indexes, a page at a time, within limits the views hint;
- it refreshes what it shows when a system or the store reports a change;
- it reads who changed what it shows, and when, from each holder;
- it appends changes to the slots the store holds, and refuses changes to the
  slots no one can write.

Changes to the slots another system holds are written through that system's
operations ([spec-10](spec-10-operations.md)). Python compiles sessions'
bundles; the JavaScript runtime runs sessions, in browsers and on servers.

## Concepts

| Concept | Meaning |
| --- | --- |
| System | A system of record a session reads: a source system that an `@system` mapping of the store file reads, or the store itself |
| Origin | The system an instance comes from, told by its handle |
| Holder | The system that holds a slot of an instance: the only one whose claims on it a session reconciles, and the one changes go to |
| Session | A client's runtime over one bundle: it keeps the latest output of every read it made, and their reconciled state |
| Store read | A read of selected subjects and slots of partitions (spec-08), a step of a plan like a system's read |
| List view | A rooted view whose parameter is every key a query selects |
| List read | A system's list endpoint: rows of a source type, selected by declared parameters |
| Key query | A list view's filter, sort and page, compiled to a list read, index queries or both |
| Page | A bounded slice of a list view's rows, or of a population's instances, with a cursor to the next |
| Limit hint | A view's annotation bounding what one query or population reads: its page size and largest page |
| Notice | A report that source records or partitions changed, without their content |
| Change | A new claim or a retraction on one slot of one instance, made against the slot's version |
| History | The changes holders recorded to the facts a view shows, newest first, each with its time, its author, and its values before and after |
| History read | A system's endpoint giving its records' changes: each with its time, its actor, and the record before and after |

## Example

The adviser application of [spec-08](spec-08-store.md#example) now takes its
clients from a CRM. A source ontology describes the CRM's contacts, and a
mapping brings them into `Finance`:

```text
@ontology Crm rev=2026-11-26

Contact                                         -- A person on the adviser's books
  BirthDate Date
  FamilyName Text
  GivenNames Text
  Id Text {key}
```

```text
@mapping Crm -> Finance

Contact -> Person
  DateOfBirth <- BirthDate
  Name.GivenNames <- GivenNames
  Name.Surname <- FamilyName

- Contact.Id {reason=ignore}                    -- Carried by the handles
```

The store file names the CRM as a system:

```text
@store AdviserApp rev=2026-11-26 edit=edit:adviser-app
@use Finance as F
@system Crm -> Finance                          -- The CRM holds what its mapping fills
@system Exchange -> Finance

@partition Client(client: F/Person) {archived=P7Y}
  checks: F/IdentityCheck = client <- Person
  documents: F/Document = checks -> Document

@partition Household(household: F/Household)

@index ClientChecks Client
  checks.Confirmed
  checks.Method
```

The CRM's contact `c-21` is the person `Person_Crm_2FContact_2Fc_2D21`, a
source-qualified handle (spec-05), and the slots of that person and of its
checks have these holders:

| Slot | Holder | Because |
| --- | --- | --- |
| `Person.Name.Surname`, `Person.DateOfBirth` | `Crm` | The person comes from the CRM, whose mapping fills them |
| `Person.Investor.RiskTolerance` | `AdviserApp` | No mapping fills it |
| Every slot of an `IdentityCheck` | `AdviserApp` | No system produces identity checks |

The application's pages are views:

```text
@ontology Finance
@use Crm as CRM

@view ClientPage(contactId: CRM/Contact.Id)     -- One client, their risk tolerance and identity checks
  client: Person
  checks: IdentityCheck = client <- Person {page=10}
  client.Name.Surname
  client.DateOfBirth
  client.Investor.RiskTolerance
  checks.Confirmed
  checks.Method

@view ClientList(contactIds: * CRM/Contact.Id) {page=25, max=100} -- Clients, filtered by their identity checks
  clients: Person
  checks: IdentityCheck = clients <- Person
  clients.Name.Surname
  checks.Confirmed
```

`ClientList` lists clients 25 at a time by default, and never more than 100
at a time. `ClientPage` reads a client's identity checks 10 at a time.

**A page.** A session plans `ClientPage` for `{"contactId": "c-21"}`:
- the CRM read `contact` (`GET /contacts/c-21`) supplies the surname and the
  date of birth;
- a store read of partition `Client/Person_Crm_2FContact_2Fc_2D21` supplies
  the risk tolerance and the first 10 checks, the most recent first, with a
  cursor to the next.

Both run at once, since the client's handle derives from the seed. The session
reconciles their observations, and its report gives each field its holder:

| Field | Value | Holder | Writable |
| --- | --- | --- | --- |
| `client.Name.Surname` | Ngata | `Crm` | No: the CRM has no operations yet |
| `client.Investor.RiskTolerance` | Medium | `AdviserApp` | Yes, at version 12 |
| `checks.Confirmed` | true | `AdviserApp` | Yes, at version 14 |

**A change.** The adviser raises the client's risk tolerance:

```json
{ "claims": [{ "s": "Person_Crm_2FContact_2Fc_2D21", "p": "Investor.RiskTolerance", "v": "High", "version": 12 }] }
```

The session appends it to the client's partition with `expect` version 12. The
same change to `Name.Surname` would be answered `readonly`.

**A list.** The session runs `ClientList` with this query:

```json
{ "filter": { "not": { "eq": ["checks.Confirmed", true] } },
  "sort": [["clients.Name.Surname", "asc"]], "page": { "number": 1, "size": 25 } }
```

1. The store's index `ClientChecks` gives the clients with a confirmed check.
2. The CRM's list read `contacts` lists every contact except those, sorted by
   family name, 25 at a time.
3. One store read of the 25 rows' partitions gives their checks.

The first two steps run on the application's server, since index answers name
clients the user may not see.

**A notice.** The CRM reports that contact `c-21` changed. The session drops
its `contact` response, reruns `ClientPage` and `ClientList`, and answers the
other requests from what it kept.

**A history.** The page shows who last changed the client:
`history("ClientPage", {"contactId": "c-21"}, {"latest": true})` reads the
CRM's history read for contact `c-21` and the newest statements of the
client's partition, and answers the newer change: the risk tolerance, raised
by the adviser.

## Systems and holders

### Systems

A session's systems are named by a store file (spec-08):

- each `@system From -> To` line is a system named `From`, read through its
  read catalogue ([spec-06](spec-06-hexa.md#rooted-retrieval), and
  [list reads](#list-reads)) and its mapping;
- the store is a system named after its `@store` header.

`@system` gains a key, `scope=<token>`: the `@scope` of the system's
observations, which source-qualified handles from that system carry
(spec-05). It defaults to `From`.

### Origins

An instance's origin is the system it comes from. For an instance of type `T`:

1. If no `@system` mapping produces `T`, a type it specialises or a type that
   specialises it, the origin is the store.
2. Otherwise its handle (spec-05) tells:

   | Handle | Origin |
   | --- | --- |
   | Derived from a key under a policy with `from=S` | The system `S` |
   | Source-qualified with a system's scope | That system |
   | Source-qualified with the store's scope | The store |
   | Derived from a key under a policy without `from` | Shared |

   Any other handle of such a type has no origin, and the store rejects
   statements about it (`origin.unknown`).

- **New instances.** An instance created in the store, of a type a system also
  produces, gets a source-qualified handle in the store's scope, with a new
  UUID as its key: `Person_adviser_2Dapp_2FPerson_2F0193a6d0_2D…`. Instances
  of types no system produces may use any handle stable in the scope.
- **Arrivals.** When a store instance later appears in a system (a prospect
  becomes a CRM client), an identity link joins the two handles, and the
  store merges their partitions (spec-08 [merges](spec-08-store.md#merges)).

### Holders

The holder of a slot (spec-02: an attribute path, a facet, existence or a
relation, in a context) of an instance of type `T`:

| Origin | Holder |
| --- | --- |
| The store | The store |
| A system `S` | `S`, when a line of its mapping assigns the slot on `T` or a type compatible with it; otherwise the store |
| Shared | The system whose mapping assigns the slot; otherwise the store |

- **Existence.** A system holds the existence of its instances, so the store
  never states it: a partition's system-origin anchor is implicit there
  (spec-08).
- **Conditions.** A line holds its slot whether or not its conditions hold for
  an instance: when the CRM states nothing about a client's death, the client
  is not known to be deceased; the store does not fill in.
- **Two systems.** A slot that two systems' mappings assign, for shared
  instances, is an error when the bundle is compiled (`holder.shared`).
- **Unhomed.** A store-held slot of an instance that no partition kind can
  home (spec-08 Homes) cannot be stored: plans report it as a gap
  (`Store.Unhomed`), and changes to it are answered `unhomed`.
- **Compiled.** Holders are computed per type, slot and origin when the bundle
  is compiled, and looked up per instance by its origin.

### Writability

- **Store-held slots** are writable, except derived attributes (spec-01 `~`),
  which are computed rather than written.
- **System-held slots** are writable when their mapping line reverses
  (spec-04 Reversal) and one of the system's operations writes the source
  slot: `update` for existing instances, `create` for new ones
  ([spec-10](spec-10-operations.md#writability)). A system that declares no
  operations has read-only slots.

### Reconciliation

- **Delivery.** A session tags each claim with the system whose read delivered
  it.
- **Holders.** For each slot of each instance, a session reconciles only the
  claims its holder delivered, as spec-02 does.
- **Off-authority claims.** It reports the others as off-authority, beside the
  state, rather than as conflicts. They arise from orphaned statements a store
  read includes on request, and from evidence (deferred).
- **Within a system.** Spec-02 applies unchanged: two reads of one system that
  disagree on a slot are a conflict, which the report shows.

## Page views

### Planning

Spec-06 plans a rooted view by choosing, for each proof obligation (a hop or a
projection), the first read that supplies it. A session adds store reads as
suppliers:

- **Store-held slots.** An obligation on a store-held slot is supplied by a
  store read of the partition kind that reaches the slot's owner:
  - a kind's root population supplies its anchors' slots;
  - a member population supplies its members' slots, and the links that reach
    them.

  A view's hop matches a kind's population by its link (owner, member and
  direction), not by its alias.
- **Both systems.** A hop whose link both a system and the store can state
  (CRM notes, and notes the store created) has a supplier in each, and its
  population is the union of their instances.
- **Keyed elements.** A projection of an attribute with keyed elements, such
  as `client.Phones.Number`, has a supplier in each holder when a system fills
  some of its elements (`Phones[Mobile]`) and the store holds the others. Its
  facts are the union of their elements, and the projection is blocked only
  when every supplier is.
- **Selections.** A store read selects, per population of the kind, only the
  slots the view's obligations need, with the selections of spec-08
  [state reads](spec-08-store.md#state).
- **Gaps.** An obligation on a store-held slot of a type no kind reaches is a
  static gap, `Store.Unhomed`.

### Reads and waves

- **Inputs.** A store read takes the handles of its kind's anchors.
- **First wave.** A store read of the root's partition runs in the first wave
  when `rootHandle` gives the root's handle from the seed.
- **Later waves.** Otherwise a store read runs in the wave after the read that
  gives its anchors.
  - After each wave, the session maps what it has read so far, so that the
    next wave's store reads know their anchors' handles. With handles derived
    from a key the seed does not carry, such as a UUID, the root's store read
    waits for its system read.
  - Store reads can also give anchors or keys to later system reads, as system
    reads do.
- **Batching.** Requests are deduplicated as in spec-06, and the store reads of
  one wave are one request (spec-08 `POST /v1/state`).

### Results

- **Observations.** A retrieval returns observations (spec-02), each claim
  with its source.
- **Plans.** A plan (`onto.view-plan/1`) gives each field its `holder` and
  `writable`. Store reads are steps with `kind: "store"`, their partition kind
  and selections.
  - A field with keyed elements gives the holder of the elements no mapping
    names, and `keyedHolders` the elements a system holds, such as
    `{"Phones[Mobile].Number": "AdviceLink"}`.
  - A field with a supplier in each holder lists them, as its `fields` entry.
- **Reports.** A report (`onto.view-report/1`) gives each fact its `holder`
  and `writable`, from its own slot; for store-held facts, also its
  `partition` and its slot `version`. It lists off-authority claims.

## List views

### Declaration

A list view is a rooted view whose parameter is a set of keys:

```text
@view ClientList(contactIds: * CRM/Contact.Id) {page=25, max=100}
```

- **Parameter.** `*` before the key type makes the parameter many keys, as
  `*` marks zero or more in spec-01 cardinalities: every key a query selects,
  rather than one key the caller supplies. The key follows the rules of rooted
  views (spec-01).
- **Rows.** The body is a rooted view's: each key selected is a row, seeding
  the populations and projections.
- **Limits.** The view's [limit hints](#limits-and-pages) bound its pages.

### List reads

A system's list endpoints are declared beside its reads (spec-06). A list read
has:

- **Rows.** `rows`: the source type of the rows, with the bindings that read
  them. The values of the type's key on the instances they bind are the rows'
  keys, in the order the bindings state them.
- **Request.** `request`: a request template, as for reads, with a `{name}`
  placeholder per parameter. A template member whose placeholders are all
  absent is left out of the request.
- **Parameters**, each one of:

  | Kind | Declares |
  | --- | --- |
  | Filter | A source attribute of the row type and an operator: `eq`, `in`, `exists`, or `contains` for text the system matches in part, as it does (DEC0038) |
  | Keys | The row type's key, to `include` or to `exclude`, with a maximum set size |
  | Sort | The source attributes the endpoint sorts by, and their spellings |
  | Direction | The values the endpoint takes for an ascending and a descending sort (DEC0038) |
  | Page | The page size, and the page number with the number of the first page (`0` by default) |

- **Total.** `total`, optional: where the response gives the number of
  matching rows.

```python
lists = {"contacts": ListRead("Crm/Contact", [contactRows],
	request={"method": "POST", "path": "/contacts/search", "body": {"familyName": "{surname}",
		"ids": "{include}", "exceptIds": "{exclude}", "sortBy": "{sort}", "page": "{page}", "pageSize": "{size}"}},
	parameters={"surname": ListFilter("FamilyName", "eq"), "include": ListKeys("include", limit=20000),
		"exclude": ListKeys("exclude", limit=20000), "sort": ListSort({"FamilyName": "familyName"}),
		"page": ListPage("number"), "size": ListPage("size")})}
```

### Key queries

A list view is retrieved with a query instead of a seed, over the view's
fields:

- **`filter`.** The index filters of spec-08 (`eq`, `in`, `exists`, `and`),
  plus `not` around predicates on store-held fields, and `contains` on a
  system-held field whose list read filter takes it.
- **`sort`.** Fields with their directions (`asc` or `desc`). A list read takes
  one sort field.
- **`page`.** A number, from 1, and a size.

```json
{"filter": {"and": [{"field": "Client/Group.Name", "contains": "nemo"}, {"field": "Client/Group.Type", "eq": "Family"}]},
 "sort": [{"field": "Client/Group.Name", "direction": "asc"}], "page": {"number": 1, "size": 25}}
```

A session compiles a query against the view's list read, the one whose rows
are the parameter's source type:

| Part | Compiled to |
| --- | --- |
| A predicate on a system-held field | The list read's filter on the source attribute its mapping line reads, with the value reversed through the line (spec-04 Reversal). A line that does not reverse, or a missing filter, leaves the field unfilterable |
| A predicate on a store-held field | A query of an index of the kind anchored at the root population, whose columns include the field. The matching anchors' keys fill the list read's `include` parameter, or `exclude` under `not`. Anchors of another origin are dropped, since they are no rows of that system |
| `sort` | The list read's sort parameter. Sorting by store-held fields is deferred |
| `page` | The list read's page parameters, within the view's limits ([Limits and pages](#limits-and-pages)) |

- **What pages may offer.** A plan reports which fields a view's queries can
  filter and sort by. The bundle carries the same, compiled by Python: per
  list view, its list read, each filterable field's parameter, operators and
  reversed values, each sortable field's spelling, and the direction and page
  parameters (DEC0038), so that runtimes compile queries alike.
- **Refusals.** A predicate or sort on a field the view's queries cannot use
  fails the query, `Session.Unfilterable` or `Session.Unsortable`.
- **One index.** The store predicates of one query use one index.
- **Size.** An index answer larger than the keys parameter's limit fails the
  query, `Session.KeySetTooLarge`.
- **On the server.** A key query that queries an index runs on the server,
  since index answers name partitions the principal may not see (spec-08). The
  session sends the query to its host (`KeyQuery`), which runs the index query
  and the list read as the principal, and returns only the list read's
  response.

### Rows

- **Seeds.** The list read's rows seed the view. The list read is each row's
  first read, and supplies what its bindings bind.
- **The rest.** The remaining obligations are planned as for page views, for
  all rows of a page at once: one store read of every row's partition, and
  system reads per row, deduplicated. The view's `max` bounds how many rows a
  page has, and so how many reads per row a query makes.
- **Result.** The rows in the list read's order, each with its key and root
  handle; the merged observations, each fact naming its row; `total` when the
  list read gives it; and the next page, while more rows remain.
- **Query as seed.** A list view's seed is its parameter's name with the query
  as its value, as `{"groupIds": {"page": {"number": 2}}}`.

## Limits and pages

### Hints

Views hint how much one query or population may read, as annotations:

| Annotation | On | Means |
| --- | --- | --- |
| `page=N` | A list view | The page size of queries that give none |
| `max=N` | A list view | The largest page a query may ask for. A larger one is refused, `Session.PageTooLarge` |
| `page=N` | A population line | The population is read `N` instances at a time |

- **Checks.** `onto check` requires positive integers, and `page` no larger
  than `max`.
- **Defaults.** A list view without `page` pages by its `max`. One without
  `max` takes the runtime's limit, 100 by default.
- **Bundles.** Hints travel in the bundle, so that pages and agents read them
  from the view rather than repeating them.
- **Cost.** A plan gives the reads a page needs: the reads per row, and the
  store reads per wave. A query's requests are therefore bounded by its page
  size times its reads per row, plus one store read per wave.

### List pages

- **Through the list read.** A key query's page is the list read's page
  parameters, its size within the view's `max`.
- **Without page parameters.** A list read without page parameters is read
  whole, and the session pages its rows itself. Per-row reads are still made
  one page at a time. Plans report such reads (`List.Unpaged`), since every
  page reads the whole list.
- **Next.** An answer gives the next page while more rows remain: from the
  list read's `total`, or a full page when there is no total.

### Population pages

A population with `page=N` is read a page at a time, from each supplier:

- **System suppliers.** A system read may declare page parameters, as list
  reads do. One without them is read whole, and the session keeps one page of
  its instances, in the read's order.
- **Store suppliers.** The store pages its population selections, the most
  recently added first (spec-08 [state reads](spec-08-store.md#state), as
  amended).
- **Several suppliers.** A population that several systems supply is paged
  per supplier: a page holds up to `N` instances from each, in each supplier's
  order. A common order across suppliers is deferred.
- **Below a page.** The hops and projections below a paged population are read
  only for the instances of the pages read.
- **More.** An answer gives a cursor per paged population and supplier.
  `more(population, cursor)` reads the next page and adds its instances to the
  state.
- **Refreshing.** When a notice concerns a paged population, the session
  rereads the pages it holds.

## Sessions

### State

- **Outputs.** A session keeps the latest output of every read it made: system
  reads, list reads and store reads, each by its request.
- **State.** Its state is the reconciliation of the union of those outputs,
  by holder.
- **Sharing.** Each distinct request is made once, and shared by every
  retrieval and list that needs it.
- **Replacing.** A read made again replaces its previous output; nothing is
  retracted from the systems.

### Notices

A notice says what changed, never how:

- **System notices** name source records, as a source type and a key. Hosts
  translate their systems' own notices into them, such as the tables and
  identifiers of a CRM's change feed entry.
- **Store notices** name partitions, from the store's change feed (spec-08),
  relayed by the host.

On a notice, a session drops the outputs of the reads it concerns:

| Read | Dropped when |
| --- | --- |
| A system read | Its input is one of the records, or the instances it bound include one |
| A list read | Its row type is a record's type, since a row may enter or leave the list; or its key query used an index of a noticed partition's kind |
| A store read | It read a noticed partition |

It then reruns the retrievals and lists that used them. Requests it did not
drop are answered from what it kept.

### Changes

A client changes the session's state with a change set: an
`onto.observations/1` log fragment of claims and retractions, in which
`instances` types new handles. Each statement carries what its slot was when
the client saw it:
- on a store-held slot, its `version`, `0` for a new slot or subject;
- on a system-held slot, its value, `was` ([spec-10](spec-10-operations.md#change-sets)).

```json
{ "instances": { "IdentityCheck_adviser_2Dapp_2FIdentityCheck_2F0193a6d4_2D…": { "type": "Finance/IdentityCheck" } },
  "claims": [
    { "s": "IdentityCheck_adviser_2Dapp_2FIdentityCheck_2F0193a6d4_2D…", "exists": true, "version": 0 },
    { "s": "IdentityCheck_adviser_2Dapp_2FIdentityCheck_2F0193a6d4_2D…", "p": "Person", "v": { "ref": "Person_Crm_2FContact_2Fc_2D21" }, "version": 0 },
    { "s": "IdentityCheck_adviser_2Dapp_2FIdentityCheck_2F0193a6d4_2D…", "p": "Confirmed", "v": true, "version": 0 }
  ] }
```

The session routes each statement by its slot's holder:

| Holder | Route | Result when not applied |
| --- | --- | --- |
| The store | Appended to the subject's home partition (spec-08 Homes): one batch per partition, with the store file's `edit` source, `expect` from the versions, and the links that home new subjects; a link a system holds goes in the batch's `links`, as that system's read states it | `conflict`, `rejected` or `uncertain` |
| A system, writable | That system's operations ([spec-10](spec-10-operations.md#changing-system-held-slots)) | `conflict`, `rejected`, `uncertain`, `unconfirmed` or `ambiguous` |
| A system, read-only | None | `readonly` |
| The store, unhomed | None | `unhomed` |

- **Atomic per partition.** A partition's statements apply together or not at
  all. On `409 precondition`, they are all `conflict`, with the slots that
  moved and their current values.
- **Not atomic overall.** A change set spanning several partitions or systems
  is not atomic. The result gives each statement `applied` or the reason it was
  not.
- **Uncertain.** An append without an answer is `uncertain`, and is retried
  with the same request ID (spec-08 [retries](spec-08-store.md#retries)).
- **After applying,** the session rereads the partitions it changed.
- **New handles.** The session mints them, with the store's origin
  ([Origins](#origins)).

## History

> Proposed (DEC0036); not part of the accepted session contract yet.

Pages show who changed what they show, and when: "updated 21 Jul by Mere
Tipoki" on a record, and the record's changes, each with its values before and
after. Each holder supplies the history of the slots it holds:

| Holder | History from |
| --- | --- |
| The store | Its log, newest first, restricted to the view's partitions and slots ([spec-08](spec-08-store.md#log)): each statement with its stamps and the value it replaced |
| A system | Its history read, for the records the view's reads returned |

A history reports how systems recorded facts. Spec-01's `{history}` is
different: it models a domain's own changes as facts.

### History reads

A system declares its history read in the catalogue, as it declares its list
reads (spec-06), with the role `history`:

- **Parameters.** The records, as keys of their source types, and a page: a
  size and a cursor.
- **Entries.** Each change gives its time, its actor, and its record before
  and after the change, as rows of the record's source type. A creation has no
  row before. An event recorded without values has neither, and gives no
  change.
- **Order.** Newest first across the request's records, with a cursor to the
  next page.

The session binds and maps the two rows of each change as it does a read's
rows, and compares the two states slot by slot. Each slot that differs is one
change, so the comparison follows the mapping: a field no slot reads gives
none, and a slot computed from several fields is compared once.

### Reading a history

`history(view, args, query)` reads the history of the facts a page view shows
for `args`, after its retrieval:

- **Scope.** The view's fields, over the instances its retrieval reached. The
  query may restrict them with `fields` and `instances`.
- **Entries.** Each gives:
  - `at`: when the holder recorded the change, a statement's `recorded` or a
    system change's time;
  - `by`: who made it, a statement's `principal` or a system change's actor;
  - the holder, the instance and the field;
  - `was` and `now`, the mapped values before and after: no `was` for a first
    value, no `now` for a retraction;
  - for a statement, its `src` and `ctx`.
- **Order.** Newest first by the instant `at`. Each upstream history stream
  is in time order; a store partition is one stream. Break ties between
  streams by stable stream identity and preserve order within a stream.
  This orders history entries, not populations supplied by several systems
  ([Deferred](#deferred)).
- **Pages.** `page` gives the merged page size. `more` continues each stream
  from its own cursor when its buffered entries have been consumed. Entries
  that did not fit on the merged page stay buffered for the next one.
- **Latest.** `{"latest": true}` gives each instance's newest change among the
  view's fields: what a page shows as "updated … by …".

A page's retrieval makes no history reads; histories are read on request.

### Rules

- **Access.** A history read is authorized as its records' reads are, and a
  log read as its partition's reads (spec-08). Records and partitions the user
  may not read give no entries.
- **Holders.** Entries come only from a slot's holder: off-authority claims
  are not history.
- **Redaction.** A redacted statement's values are absent from its entry.
- **Notices.** A notice that drops a view's reads also drops the history reads
  of the same records and partitions.

## Bundles and runtimes

- **Bundle.** `sessionBundle(operator)` compiles an `onto.view-bundle/3`
  document, the rooted-view `/2` bundle plus:
  - `store`, the store bundle (spec-08), from whose origins and held slots
    holders follow, per type, slot and origin;
  - each view's population page hints (`pages`), and whether each attribute
    is derived, which writability needs;
  - the list reads, and list views resolved like rooted views.
- **JavaScript.** The runtime gains `Session`: store reads, list views,
  notices and changes. It generalises the sessions hosts build over
  `ViewOperator` today.
- **Proposed history extension.** The bundle also carries history reads, the
  `Session` gains `history`, and `StoreRead` can read newest-first logs.
- **Host operations.** `RequestSend` (spec-06), `StoreRead` and `StoreAppend`
  (spec-08 requests), and `KeyQuery`. In a browser, `KeyQuery`, and usually
  `RequestSend`, go to the application's server, which performs them with the
  same runtime.
  - The store's are the host's functions `storeRead(body)` (a batch read) and
    `storeAppend(partition, body)`, such as a store client's `stateMany` and
    `append`. A refusal is a store error; any other failure is an append
    without an answer. Journaling them as hexa effects is deferred.
- **Host adapter.** `rootHandle` may answer `null` when a root's handle is
  known only after reading. A new `noticeRecords(notice)` translates the
  host's notices into source records.
- **Python.** Python is the reference for planning, holders and the
  compilation of key queries. The JavaScript runtime runs plans and sessions,
  and conformance tests check it against Python, as spec-06 describes.
- **Tests** follow `tests/T09-<n>-session-<name>.py`.

## Other specs

Sessions rely on these parts of other specs:

| Spec | Defines |
| --- | --- |
| [spec-01](spec-01-ontology.md#rooted-views) | List views (`*` parameters), and the `page` and `max` hints |
| [spec-06](spec-06-hexa.md#rooted-retrieval) | Holders, store steps, partitions, versions and page costs in plans and reports; list reads and page parameters in the catalogue; `rootHandle` answering `null`; the `/3` bundle |
| [spec-08](spec-08-store.md#held-slots) | `@system` scopes; held slots by origin; `origin.unknown`; pages of population selections; log reads newest first |

## Correctness checks

- **Origins.** Each handle form gives its origin, and a handle of a
  system-produced type in no known form is rejected.
- **Holders.**
  - A slot a system's mapping fills is held by that system for its instances,
    and by the store for store instances.
  - Two systems filling one slot for shared instances fail compilation.
- **Reconciliation.** Off-authority claims are reported and never change the
  state.
- **Planning.**
  - Store-held obligations are supplied by store reads of the right kind and
    populations.
  - A link both systems state is supplied by both.
  - Store reads of the root run in the first wave when the seed gives the
    root's handle.
- **List views.**
  - Filters on system-held fields reach the list read reversed.
  - `not` over store-held fields becomes an exclusion.
  - Index answers never reach the client.
  - Too large a key set fails.
- **Limits and pages.**
  - A query asking for more than its view's `max` is refused.
  - A list read without page parameters is read whole, but per-row reads are
    made for one page only.
  - A paged population reads one page per supplier, and `more` adds the next
    without rereading the first.
  - Plans give each page's reads.
- **Notices.** Exactly the affected reads are made again; the others are
  answered from the session.
- **Changes.**
  - Each statement goes to its holder, and a partition's batch is atomic.
  - A moved slot makes the batch `conflict` with current values.
  - A read-only slot is `readonly`.
  - A retried uncertain append applies once.
- **History (proposed).**
  - Each change is reported once, by its slot's holder, with its values
    before and after.
  - A system's change gives entries only for the slots that differ after
    mapping.
  - Streams merge newest first. If the first page uses only one stream,
    `more` still returns the unconsumed entries from the other streams.
  - `latest` gives each instance's newest change.
  - Records and partitions the user may not read give no entries.
- **Runtimes.** Python and JavaScript plan, compile and reconcile alike.

## Deferred

1. **Sorting by store-held fields**, store predicates across several indexes
   in one query, and a common order for populations several systems supply.
2. **Precedence** between two systems filling one slot.
3. **Evidence:** claims a store keeps on slots a system holds (spec-08
   Deferred), reported as off-authority.
4. **Minted handles** (spec-05 registries) as origins.
5. **Offline sessions:** a session keeps pending changes in memory only.
6. **More history:** histories of list views, and reasons for a change beyond
   its `src` and `ctx`, such as the call that prompted it.

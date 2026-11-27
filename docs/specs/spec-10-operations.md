# Operations

An **operation** changes a record in a system of record through that system's
own API: create a client, update its details, delete a note. Operations are how
a [session](spec-09-sessions.md) writes the slots another system holds:

1. the session reverses the changed facts into the system's terms, through the
   reverse of the mapping it reads them with
   ([spec-04](spec-04-mapping.md#reversal));
2. it chooses the operations that write those source slots;
3. it reads each record afresh, applies the changes, writes the request body
   with a binding used for writing ([spec-06](spec-06-hexa.md#writing)), and
   sends it as the principal;
4. it confirms what the system saved.

Operations are declared beside a system's reads, as data: a request template,
the bindings of the request body, the read that gives the full record, and
what the system answers. This spec also widens reversal, so that the scopes
the AdviceLink mapping uses most (conditions, named, presence-selected and
`into` scopes, source references) reverse instead of being lossy.

## Concepts

| Concept | Meaning |
| --- | --- |
| Operation | A declared request that creates, updates or deletes one record of a system |
| Subject | The source instance an operation writes, of the operation's source type |
| Body binding | A binding describing the request body, used in the writing direction (spec-04 Writing) |
| Preparatory read | The read giving the subject's full record before an update, and confirming it after |
| Argument | A request value that is not state, such as whether to notify someone, with a default |
| Source change | A change to a source slot, obtained by reversing a change to a target slot |
| Seen value | The value of a system-held slot the client saw, carried by its change as `was` |
| Plan | The operations a change set needs, in order, and the requests they render |
| Dry run | A plan whose requests are rendered but not sent |

## Example

The CRM of [spec-09](spec-09-sessions.md#example) versions its contacts and
refuses an update made against an older version:

```text
@ontology Crm rev=2026-11-27

Contact                                         -- A person on the adviser's books
  BirthDate Date
  FamilyName Text
  GivenNames Text
  Id Text {key}
  Version Integer                               -- Incremented by every update
```

Its mapping is spec-09's, with `- Contact.Version {reason=ignore}`. Two
bindings describe the contact as the CRM reads it and as it updates it:

```text
@binding Crm name=contact format=json
Contact <- $ {id=id}
  BirthDate <- birthDate
  FamilyName <- familyName
  GivenNames <- givenNames
  Id <- id
  Version <- version
```

```text
@binding Crm name=contact-update format=json
Contact <- $ {id=id}
  BirthDate <- birthDate
  FamilyName <- familyName
  GivenNames <- givenNames
  Id <- id
  Version <- expectedVersion
```

The host declares the update beside the CRM's reads (spec-06):

```python
operations = {"contactUpdate": Operation("update", "Crm/Contact", [contactUpdate],
	request={"method": "PUT", "path": "/contacts/{Id}", "body": "{body}"},
	read="contact", conflict=409)}
```

`contactUpdate` writes every slot the forward mapping fills, so the client's
surname, given names and date of birth become writable (spec-09
[Writability](spec-09-sessions.md#writability)).

An adviser corrects the date of birth of contact `c-21`:

```json
{ "claims": [{ "s": "Person_Crm_2FContact_2Fc_2D21", "p": "DateOfBirth",
  "v": "1984-03-12", "was": "1984-03-02" }] }
```

1. **Reverse.** `DateOfBirth <- BirthDate` reverses: the source change is
   `Contact_c_2D21.BirthDate` to `1984-03-12`, on the contact the person was
   mapped from.
2. **Plan.** `contactUpdate` writes `Contact.BirthDate`.
3. **Read.** `GET /contacts/c-21` gives the full record, at version 7, with the
   date of birth still `1984-03-02`.
4. **Write.** The body binding writes the record with the new date:

   ```json
   { "id": "c-21", "familyName": "Ngata", "givenNames": "Aroha", "birthDate": "1984-03-12", "expectedVersion": 7 }
   ```

5. **Send.** `PUT /contacts/c-21` as the adviser.
6. **Confirm.** The read, run again, shows the new date: the statement is
   `applied`.

Had a colleague renamed the contact between steps 3 and 5, the CRM would have
answered `409`. The session would have read version 8, found the date still at
its seen value, and sent once more. Had the colleague changed the date of
birth, the statement would have been a `conflict`, with the colleague's value.

## Reversal

Spec-04 reverses a line when its expression can be solved for its input, and
reports the others as lossy. This spec reverses six more forms.

### Source-side conditions

A scope condition testing source paths that no reversible line of the scope
assigns, such as `Client/Client -> Society/Person {when=Deleted:false}`, made
the whole scope lossy. It is a **source-side condition**: the forward scope
produced only instances satisfying it. Therefore:

- **Reverse scope.** The reverse scope applies to every target instance the
  forward scope produced, without a condition.
- **Assertion.** It asserts the tested value on the source instance when the
  condition tests one value of one path: `Deleted` is `false`. A condition with
  alternatives (`Status:Active|Prospect`) or a combination asserts nothing.
- **Updates.** An update checks the condition on the record it reads: a
  record deleted meanwhile is a `conflict`.

### Literal lines

A line assigning a literal (`Type <- "FileNote"`) writes nothing back, as
before. It becomes a condition of the reverse scope: only target instances with
that value reverse through this scope. Where several reverse scopes take one
target type, such conditions help choose the source type of a new instance
([Planning](#planning)). A file note created in a session reverses to a
comment, not to a logged email.

### Named scopes

A named scope's target instance reverses onto the source instance it was
produced from. A named source-qualified handle,
`<scope>/@<name>/<S>/<key>` (spec-04 Instances), names it:
`PartyReference_AdviceLink_2F_40Xplan_2FClient_2F12229` comes from
`Client_12229`. The scope's lines reverse as any others.

### Presence-selected scopes

A scope with `present=expr` reverses as its lines do. Retracting one of its
target instances clears, on the source instance, the paths `expr` reads, when
reversible lines of the scope assign them. Removing a client's Xplan reference
clears the client's `NzhlDetails.XplanId`.

### Update scopes

A scope with `into=Selector` assigns its lines onto the target of another
source instance. A slot it assigns reverses into a **row**: an instance of the
scope's source type.
- The row's selector names the destination's source instance.
- Its other paths come from the scope's reversed lines.
- Retracting the slot retracts the row.

Filing a note under a client creates a key row under the comment
(`Record/ReferenceKeyLookup`).

### Source references

`ref(S, Key)` reverses when the referenced target instance comes from an
instance of `S`: `Key` takes that instance's key.
- **Exclusive lines.** The line whose `S` matches applies, and its `when` test
  value is asserted. A note concerning a client gives `Key` the value
  `ClientId`, and `Value` the client's id.
- **Otherwise lossy.** A reference whose target came from no instance of any
  `S` the lines name stays lossy.

### Source instances

A target instance's source instance is the one the forward mapping produced it
from, in the reads that delivered it: the instance correspondence (spec-04
Instances).
- **New instances.** A target instance created in a session has none. Its
  reversal gives a **new source instance**, with a provisional handle, which a
  create operation makes.
- **Rows.** Rows that update scopes reverse into are new source instances too.

## Operations

### Declaration

Hosts declare operations beside reads (spec-06), each with:

| Member | Declares |
| --- | --- |
| `effect` | `create`, `update` or `delete` |
| `subject` | The source type of the record it writes |
| `body` | The body bindings, used for writing: a scope selecting the subject, and scopes for the rows written with it |
| `request` | A request template, as for reads, with `{Attr}` for the subject's source attributes, `{body}` for the written body, and `{name}` for arguments |
| `read` | For updates and deletes, the read that gives the subject's full record and confirms what was saved |
| `arguments` | Request values that are not state, with their defaults |
| `response` | For creates, the bindings that read the created record's key from the answer |
| `key` | For creates, the subject's source attribute that the system accepts from the client, making a repeated create return the first record |
| `conflict` | The answer status meaning the record changed since it was read |

- **A body binding** is an ordinary binding of the source ontology (spec-04),
  describing the request body, and written as spec-06
  [Writing](spec-06-hexa.md#writing) describes. A version the system checks is
  one of its lines (`Version <- expectedVersion`).
- **Data, not code.** A host may keep its reads and operations as data, such
  as JSON its tooling generates, and load them. The bundle is their compiled,
  language-neutral form, and compiling it checks them.
- **Tooling.** API descriptions that classify request fields, as written
  state, keys or arguments, give the drafts of body bindings and operations.

### Checks

`onto check` checks a host's operations against its source ontology and reads:

- **Full records.** An update's body writes the subject's slots that the
  change sets, plus slots its read supplies. A body slot that neither the
  change nor the read supplies would be written empty, and is an error
  (`operation.unread`).
- **Keys.** The request names the subject's key, in its path or its body.
- **Creates.** A create's body writes the source attributes its subject
  requires (cardinality `1`), or takes them from arguments.
- **Rows.** Rows a body writes belong to scopes whose selector is the subject.

### Writability

A target slot held by a system (spec-09 [Holders](spec-09-sessions.md#holders))
is writable when:
- its mapping line reverses to source slots;
- an operation of that system writes those slots, `update` for existing
  instances and `create` for new ones.

Retracting an instance needs a `delete`, or a presence-selected scope.
Writability is computed when the bundle is compiled, and plans report it per
field.

## Changing system-held slots

### Change sets

The statements of a change set (spec-09
[Changes](spec-09-sessions.md#changes)) on system-held slots carry `was`
instead of `version`: the spec-02 JSON value the client saw. It is `null` for
a confirmed absence, and omitted for a slot the client saw empty. A statement
creating an instance carries no `was`.

A new instance may name the operation that creates it, in the change set's
`instances`:
`"Person_adviser_2Dapp_2FPerson_2F0193a6d9_2D…": { "type": "Finance/Person", "operation": "contactCreate" }`.
A page's "add a client" action knows which one it means.

### Planning

1. **Reverse.** For each changed target instance, the session reverses its
   state before and after the change through the reverse mapping. The
   difference gives the source changes, on its source instance or on a new one.
   - **A new instance's source type.** The operation the change set names for
     it decides. Otherwise the reverse scopes whose conditions hold for it
     (source-side conditions, [literal lines](#literal-lines), value maps) must
     leave exactly one source type.
   - **Ambiguous.** When they leave several, its statements are `ambiguous`:
     the session never guesses. A new interaction typed `FileNote` becomes a
     comment, but a new person needs its operation named, since a CRM's
     clients and users both map to persons.
2. **Group** the source changes by source instance.
3. **Choose** for each source instance the operations of its type, with the
   effect its changes need: `create` for a new instance, `delete` for a
   retracted one, `update` otherwise.
   - It takes the fewest operations whose bodies write every changed slot,
     preferring catalogue order.
   - A slot no operation writes makes its statements `readonly`.
4. **Order.** Creates come first, then updates, then deletes. An operation
   whose body refers to an instance another operation creates runs after it,
   with the created key.

A **dry run** renders the plan's requests without sending them, as Hexa inert
effects. Confirmation screens, approvals and tests use it.

### Running an update

1. **Read.** Run the operation's read as the principal, bypassing the
   session's cached outputs, and bind the subject.
2. **Check.**
   - Each changed slot still holds its seen value.
   - The subject still satisfies its scope's source-side conditions.

   Otherwise the statements are `conflict`, with the current values.
3. **Apply** the source changes to the subject's state.
4. **Write.** The body bindings write the body from that state, with the
   read's response as originals:
   - a field whose canonical value is unchanged keeps the raw value the read
     returned (spec-04 [Writing](spec-04-mapping.md#writing));
   - originals are matched by subject and source slot, since the read's
     response and the request body are different documents.
5. **Send** the request as the principal (spec-06 `RequestSend`).
6. **Answer.**

   | Answer | Then | Result |
   | --- | --- | --- |
   | Success | The read runs again, and the written slots must hold the written values | `applied`, else `unconfirmed` |
   | The `conflict` status | The read runs again. If the changed slots still hold their seen values, steps 3 to 6 run once more | `applied` after the retry, else `conflict` |
   | Another client error | None | `rejected`, with the system's message |
   | No answer, or a server error | The read runs again | `applied` if it shows the written values, else `uncertain` |

   An `uncertain` update is never sent again: it may have been saved.

### Running a create or a delete

- **Create.**
  - There is no read: the body bindings write the new source instance's
    state.
  - When the operation declares a `key`, the session mints it (a UUID) and the
    request carries it. An `uncertain` create is then sent again with the same
    key, which the system answers with the record it may already have made.
    Without a `key`, `uncertain` is final.
  - The `response` bindings read the created record's key. The new source
    instance takes it, and the target instance's correspondence follows.
- **Delete.**
  - The request names the subject's key.
  - An `uncertain` delete is resolved by the read: an absent record is
    `applied`.

### Results

Each statement gets the result of the operations its source changes went to:

| Result | Means |
| --- | --- |
| `applied` | Sent, and the confirming read shows it |
| `conflict` | The record changed under the client; the answer gives the current values |
| `rejected` | The system refused it: validation or permission |
| `uncertain` | No answer, and the read cannot tell |
| `unconfirmed` | Accepted, but the confirming read shows other values |
| `readonly` | No operation writes it |
| `ambiguous` | A new instance that several source types could take, with no operation named |

- **Atomicity.** A change set is not atomic across operations or systems.
  Each statement's result says what happened to it.
- **Refresh.** After its operations, the session drops its outputs for the
  subjects they wrote, as for a notice (spec-09), and reruns what used them.

## Bundles and runtimes

- **Bundle.** The `onto.view-bundle/3` session bundle (spec-09) gains:
  - the reverse of each `@system` mapping, as a mapping program;
  - the operations, with their body and response programs (writing and
    reading), and the inventories and formats of their bodies;
  - writability per type, slot and origin.
- **JavaScript.** The runtime gains writing:
  - reverse mappings run as mappings already do;
  - body bindings are written by the stages of spec-06 Writing, ported to
    JavaScript, including originals and materialisation;
  - sessions plan, run and confirm operations.
- **Conformance.** Python is the reference. Conformance tests record each
  plan, each rendered request and each result in Python, and replay them in
  JavaScript, as spec-06 describes.
- **Tests** follow `tests/T10-<n>-operation-<name>.py`.

## Other specs

Operations rely on these parts of other specs:

| Spec | Defines |
| --- | --- |
| [spec-04](spec-04-mapping.md#reversal) | The reversal of source-side conditions, literal lines, named, presence-selected and update scopes, and source references; originals from another document |
| [spec-06](spec-06-hexa.md#reversing-mappings) | The forms these reversals generate; request bodies with a read's response as originals; operations in the catalogue and the bundle; writing in JavaScript |
| [spec-09](spec-09-sessions.md#changes) | Writability by operations; `was` on system-held statements; their routes and results |

## Correctness checks

- **Reversal.**
  - `{when=Deleted:false}` scopes reverse and assert `false`; conditions with
    alternatives assert nothing.
  - Literal lines choose between reverse scopes.
  - Named, presence-selected and update scopes, and source references,
    reverse as described; a retracted presence instance clears its path.
- **Checks.** An update whose body writes a slot its read does not supply is
  rejected.
- **Planning.**
  - A new instance takes the source type its named operation, or its reverse
    conditions, single out; otherwise it is `ambiguous`.
  - The fewest operations cover the changed slots.
  - Creates run before the operations that refer to what they create.
  - A dry run sends nothing.
- **Updates.**
  - A stale seen value is a `conflict` before anything is sent.
  - The `conflict` status leads to one retry only when the changed slots kept
    their seen values.
  - An `uncertain` update is never resent.
  - Unchanged fields keep the read's raw spellings.
- **Creates and deletes.** A keyed create resent after `uncertain` makes one
  record. An uncertain delete of an absent record is `applied`.
- **Results.** `unconfirmed` when the confirming read differs.
- **Runtimes.** Python and JavaScript render the same requests and reach the
  same results from the same journal.

## Deferred

1. **Files:** uploads and attachments, which are not observations.
2. **Transactions:** compensating an operation when a later one of the same
   change set fails.
3. **Side effects** beyond arguments: operations that send email or start
   workflows, which need a person's approval through a dry run.
4. **Asynchronous operations,** answered later through a job.
5. **Merges** of source records through an operation, which spec-08 merges
   would follow.

# Domain artifacts

A subject's knowledge graph is rebuilt from the textbook on every
`make build-kg`. Whatever a person decides about a concept (a better
definition, an extra alias, a term that is noise, a prerequisite the builder
missed) would be lost on the next rebuild. The domain artifacts are where
those decisions live: four YAML files per subject under
`data/domains/<subject_id>/`, validated in CI and applied on top of the build.

`config/subjects.yaml` stays the runtime registry of subjects. A subject
without a directory under `data/domains/` has no curated domain and behaves
as before.

## Current state

- The schema is version 1 (`schema_version: 1` in every file).
- `us_history` and `economics` have drafts written from the current build.
  Every entry in them is `extracted`: nobody has reviewed one yet.
- With only `extracted` entries, `apply` plans no write and does not connect
  to Neo4j. Seeding and queries are unchanged until an entry is approved,
  rejected or deprecated.
- The request path does not read these files. `backend/app/domain/lexicon.py`
  defines what the query-time lexicon would take from a domain, and nothing
  imports it yet.

## The four files

### `domain.yaml`

| Field | Meaning |
| --- | --- |
| `schema_version` | `1` |
| `subject_id` | The subject; must equal the directory name |
| `status` | `draft`, `approved` or `retired`. Informative: `apply` follows the entries, not this field |
| `steward` | Who looks after the domain, as a role (`project maintainer`), never a name or an address |
| `review_cadence` | How often the domain is reviewed. May be empty in a draft; required once `status` is `approved` |
| `accuracy_bar` | What an entry must meet to be approved. Same rule as `review_cadence` |

### `dictionary.yaml`

One entry per term under `terms`.

| Field | Meaning |
| --- | --- |
| `id` | Lower-case words joined by hyphens (`stamp-act`). Unique in the file. `draft` derives it from the name and keeps it stable: a later name with the same form takes a numeric suffix (`stamp-act-2`), never an id in use |
| `name` | The `Concept.name` in the graph. `apply` matches on it exactly |
| `aliases` | Other spellings a question may use |
| `definition` | The definition, or empty |
| `definition_source` | The `id` of the source in `sources.yaml` the definition comes from |
| `scope`, `context_terms` | For senses, see below. Optional |
| `review_status` | See [Review statuses](#review-statuses) |
| `provenance` | `origin` (`builder` or `reviewer`), the builder's `method` and `module_id`, and for a reviewed entry `reviewed_by` (a role), `reviewed_on` (a date) and an optional `note` |

Two senses of a word are two terms with different names that share an alias.
Each states the words that select it in `context_terms` and may label itself
in `scope`. An alias that two terms share is an error for a `proposed` or
`approved` term without `context_terms`. For `extracted` terms it is only
reported, because the builder produces such pairs: in Economics, "AD" is an
alias of both "Aggregate Demand" and "Aggregate Demand Curve".

### `relationships.yaml`

One entry per edge under `relationships`. An edge is identified by `source`,
`target` and `type`.

| Field | Meaning |
| --- | --- |
| `source`, `target` | Term names. For `PREREQ` the source is the prerequisite and the target depends on it |
| `type` | A `RelationshipType` that links two concepts: `PREREQ` or `RELATED` |
| `rule` | Why the edge holds. `glossary_definition` means the prerequisite is named in the target's glossary definition |
| `evidence_source` | The `id` of the source in `sources.yaml` that holds the evidence |
| `confidence` | 0 to 1 |
| `review_status`, `provenance` | As for terms |

### `sources.yaml`

The source inventory, one entry per source under `sources`.

| Field | Meaning |
| --- | --- |
| `id` | Lower-case words joined by hyphens. For a configured book it is the `id` of its `books` entry in `config/subjects.yaml`, which defaults to the title in that form (`US History` gives `us-history`) |
| `title`, `connector` | The book's title and the ingestion connector (`github_raw`, `openstax_web`) |
| `uri` or `path` | Where the source is fetched from, or where it lies in the repository. At least one |
| `license` | The licence, as the subject's attribution states it |
| `steward` | A role |
| `review_status` | `approved`, `superseded` or `retired` |
| `supersedes` | The `id` of the source this one replaces |

## Review statuses

| Status | Set by | What `apply` does |
| --- | --- | --- |
| `extracted` | `draft`, from the builder's output | Nothing |
| `proposed` | A person, before review | Nothing |
| `approved` | A reviewer | Writes the entry to the graph |
| `rejected` | A reviewer | Removes the concept or the edge from the graph |
| `deprecated` | A reviewer, for an entry that was approved earlier | Removes it, like `rejected` |

`approved`, `rejected` and `deprecated` entries need `provenance.reviewed_by`
and `provenance.reviewed_on`.

## Commands

```bash
poetry run python scripts/domain_tool.py validate                   # every domain directory
poetry run python scripts/domain_tool.py validate --subject economics
make domain-draft SUBJECT=economics                                 # after a graph build
make domain-apply SUBJECT=economics                                 # needs Neo4j
poetry run python scripts/domain_tool.py apply --subject economics --dry-run
poetry run python scripts/domain_tool.py export --subject economics --format csv --table terms
poetry run python scripts/domain_tool.py export --subject economics --format json --out economics.json
```

- `validate` exits 1 when a file is invalid. Each problem names the file, the
  field and the entry, for example
  `data/domains/economics/dictionary.yaml: terms[12].definition_source (term 'gdp'): 'principles' is not a source id in sources.yaml`.
  `backend/tests/test_domains.py` runs the same checks on every committed
  domain in CI.
- The checks run in two passes. The first validates each file against its
  schema. The second compares entries and files (duplicates, source ids,
  relationship endpoints) and needs all four files to parse, so its problems
  only show once the schema problems are fixed.
- A directory under `data/domains/` whose name is not a configured subject
  id is an error. Hidden directories (a name that starts with a dot) are
  ignored.
- When the last build left its JSON copy in `data/processed/build/`,
  `validate` also lists the dictionary names the build lacks, the build's
  concepts the dictionary lacks, and the build's concepts that a rejected or
  deprecated term names in another spelling (`apply` removes by exact name,
  so such a concept stays in the graph). Those lines start with `report:`
  and do not change the exit status.
- `draft` reads the JSON copy of the last graph build. Run `make build-kg`
  first, or
  `poetry run python scripts/build_knowledge_graph.py --subject economics --no-persist`
  without Neo4j.
- `export` prints flat rows: CSV for one table (`terms`, `relationships` or
  `sources`), or JSON with all three.

## What `draft` does

- It writes the build's concepts to `dictionary.yaml` and its `PREREQ` edges
  to `relationships.yaml`, all with `review_status: extracted`. `RELATED`
  edges are association scores without evidence to review, so they are not
  drafted.
- It replaces the `extracted` entries with the current build: a concept the
  builder no longer extracts disappears, a new one appears.
- It keeps the values of every entry with another status, and does not
  draft a second entry for a concept or an edge that a reviewed entry names.
- It rewrites both files as a whole. Entries are sorted (terms by `id`,
  relationships by type, source and target) and keys are sorted, so a second
  run writes the same bytes. Comments, key order and quoting of a
  hand-edited entry are not kept: put a remark in `provenance.note`.
- `domain.yaml` and `sources.yaml` are written once, from
  `config/subjects.yaml`, and never rewritten.
- A definition cites the subject's source when the inventory has exactly one
  approved source. With several books the build does not say which one a
  term came from, so `definition_source` stays empty for the reviewer.
- It writes nothing when the result would be invalid, for example when an
  approved relationship names a term that the build dropped.

## What `apply` does and does not do

`apply` reads the subject's graph, plans the operations that bring it in line
with the domain, prints each one and executes it. A second run plans nothing.
The order is: concepts created and updated, rejected edges removed, approved
edges merged, concepts removed. An edge is removed before its opposite is
merged, so the graph holds no two-edge cycle between two writes.

- **Approved term.** The concept is merged on `name`. A curated definition
  replaces the builder's; a term without a definition leaves the stored one.
  Aliases are added to the stored ones and never removed. The concept gets
  `term_id`, `review_status` and `definition_source`. A term the build did
  not extract is created, and the plan says so.
- **Approved `PREREQ` relationship.** The edge is merged with
  `provenance_source: curated`, `review_status`, `confidence`, `rule` and
  `evidence_source`. `/api/v1/concepts/{name}/prerequisites` returns that
  source for a direct prerequisite.
- **Rejected or deprecated term.** The concept is deleted with all its edges.
  Retrieval no longer expands through it, so the plan lists every removal in
  capitals (`REMOVE concept ...`). Use `--dry-run` to read the plan first.
- **Rejected or deprecated `PREREQ` relationship.** The edge is deleted.

What it does not do:

- It never writes an `extracted` or `proposed` entry.
- It applies `PREREQ` edges only. A curated `RELATED` entry is reported as
  skipped.
- It skips an approved edge whose endpoint is not in the graph, and one that
  would close a cycle with the `PREREQ` edges already there. Reject an edge
  on the path that leads back from the target to the source to apply it. A
  skipped entry is printed and does not change the exit status.
- It does not undo. Changing an approved entry back to `proposed` leaves what
  an earlier run wrote. Rebuild the graph and apply again.
- It does not touch OpenSearch. Chunks are not re-indexed.
- It does not refresh a running API. The API caches a subject's concept
  names and aliases for up to five minutes, so a curated alias or a removal
  reaches questions after that time or after a restart.
- It does not run for a subject without curated entries: no connection to
  Neo4j is opened.
- It does not build. On a graph without concepts it writes nothing and exits
  1: creating the approved terms there would leave a graph that `make seed`
  takes for a built one. Build first (`make build-kg SUBJECT=<id>`, or
  `make seed`).
- It refuses to run when Neo4j is not reachable, and exits 1 when the graph
  still differs from the domain after the writes.

`make seed` runs `apply` after the graph step and stops when it fails. A
rebuild (`make build-kg`) writes the builder's definitions and aliases again,
and with `--clear` drops everything `apply` added. `make doctor` warns when
curated changes are missing from the graph and names the command
(`make domain-apply SUBJECT=<id>`), when the graph has no concepts, and when
a curated entry is skipped, which another `apply` cannot fix. The check reads
Neo4j only, so it also runs while OpenSearch is down.

## Review workflow

1. Build and draft: `make build-kg SUBJECT=<id>`, then
   `make domain-draft SUBJECT=<id>`.
2. Edit `dictionary.yaml` and `relationships.yaml`. To accept an entry, set
   `review_status: approved` and add `reviewed_by` and `reviewed_on` to its
   `provenance`. Correct the definition or the aliases if needed. To refuse
   a noise concept, set `rejected`. To suggest a term or an edge the builder
   did not find, add it as `proposed` with `origin: reviewer`.
3. Run `poetry run python scripts/domain_tool.py validate --subject <id>`.
4. Open a pull request. CI validates every committed domain.
5. After the merge, run `make domain-apply SUBJECT=<id>` (or `make seed`)
   and check `make doctor`.

When the builder changes, run `make domain-draft` again: the extracted
entries follow the build and the reviewed ones stay. `validate` then reports
reviewed names the build no longer has.

## Modules

| Module | Role |
| --- | --- |
| `backend/app/domain/models.py` | Pydantic models of the four files and the status enums |
| `backend/app/domain/loader.py` | `load_domain(subject_id)`: schema and cross-file validation |
| `backend/app/domain/lexicon.py` | What the query-time lexicon would take from a domain (not wired in) |
| `backend/app/domain/overlay.py` | `plan_overlay` (pure) and `apply_overlay` (through the Neo4j adapter) |
| `scripts/domain_tool.py` | `validate`, `draft`, `apply`, `export` |

# Adding a Subject

This guide describes the repository's subject configuration and local content pipeline. Run the commands from the repository root unless noted otherwise.

## 1. Add the configuration

Add a new entry under `subjects` in `config/subjects.yaml`. Use a lowercase `subject_id` with underscores; keep `default_subject` unchanged unless the new subject should become the application's default.

A GitHub-hosted book source uses `source_type: github_raw` (the default):

```yaml
subjects:
  my_subject:
    name: "My Subject"
    description: "A short description shown in the subject picker."
    database:
      neo4j_database: "neo4j"
      label_prefix: "my_subject"
      opensearch_index: "textbook_chunks_my_subject"
    books:
      - title: "Book title"
        source_type: "github_raw"
        repo_url_raw: "https://raw.githubusercontent.com/OWNER/REPOSITORY/BRANCH"
        summary_path: "SUMMARY.md"
        content_path: "contents"
        branch: "main"
    prompts:
      system_prompt: "Answer from the supplied textbook context and cite it."
      context_label: "Context from My Subject"
    theme:
      primary_color: "#2563eb"
      secondary_color: "#bfdbfe"
      accent_color: "#1d4ed8"
      chapter_colors: {}
    attribution: "Book title, author, edition, source URL, and required license credit."
```

For an OpenStax web source, set `source_type: openstax_web` and provide its `openstax_slug` instead of the GitHub repository paths. Copy the matching shape from an existing entry in `config/subjects.yaml`.

GitHub content downloads use a 30-second request timeout and an identifying
User-Agent. Transient HTTP 429/5xx responses, timeouts and connection failures
are retried up to three attempts with 1-second then 2-second backoff; other
HTTP failures are not retried. A failed content fetch is logged and returns
no text, preserving the existing skip behavior.

Each subject needs a unique `label_prefix` and `opensearch_index`. The subject ID is also used for subject-specific processed data. Check the spelling and YAML indentation, then confirm that the configuration loads:

```bash
poetry run python scripts/ingest_books.py --list-subjects
```

## 2. Ingest the books

Follow the README's development setup first. Make sure the local Neo4j and OpenSearch services are running before the graph-build and indexing steps: `make up` starts both and waits until they are healthy. Fetch and process the configured book sources:

```bash
make ingest-books SUBJECT=my_subject
```

The command writes one record per module to `data/processed/books_my_subject.jsonl`:

| Field | Content |
| --- | --- |
| `module_id` | The module's file name (`m49990`) or OpenStax page slug |
| `section` | The module's title: the `title` in its front matter (GitHub sources) or its page title (OpenStax web) |
| `chapter` | The enclosing chapter: the `{: .chapter}` entry in `SUMMARY.md`, or the page's parent in the OpenStax table of contents; `null` for the preface, parts and appendices |
| `module_title` | `"<chapter> - <section>"`, or the section alone without a chapter |
| `book_title`, `subject_id`, `text`, `key_terms` | The book, the subject and the cleaned module text |

The chapter is part of `module_title` because section titles repeat: most chapters open with an "Introduction". Retrieval boosts `module_title`, and the chat cites each source by chapter and section, so check a few records for sensible titles. For a GitHub source, `SUMMARY.md` must list chapters as numbered `{: .chapter} [Title](contents/m….md)` items with their sections indented below them, as the OpenStax mirrors on `raw.githubusercontent.com/philschatz` do. Check the command's output for failed source or chapter downloads before continuing.

## 3. Build the knowledge graph and index retrieval content

Run the graph build and retrieval indexing as separate steps:

```bash
make build-kg SUBJECT=my_subject
make index-rag SUBJECT=my_subject
```

The graph build uses the processed records for that subject. The indexing step uses its configured OpenSearch index. Resolve missing input or service errors before checking the UI.

## 4. Verify the subject in the UI

Start the API and frontend using the README's development commands, then open the local frontend at `http://localhost:3000`. Use the subject picker to select `My Subject`; confirm the configured name, description, and theme appear. Ask a question from the ingested material and check that the answer uses the expected subject context and includes its attribution. Restart the API if a configuration change is not visible, because subject configuration is cached while the process runs.

## Source rights and attribution

Before adding a source, confirm that its terms allow the planned downloading, processing, indexing, and display. Do not use private, employer, customer, or learner data without explicit permission. Record the book title, author, edition, source URL, license, and any required credit in the subject's `attribution` value, and retain required attribution in answers and other outputs.

OpenStax content is licensed under CC BY 4.0. Keep the required attribution and license link, do not imply OpenStax or Rice University endorses this project, and follow the repository policy not to train models on OpenStax content. For other sources, follow their own license and attribution terms.

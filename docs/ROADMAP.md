# Roadmap

## Milestone 1 — Source discovery and ingestion
- Run crawler against the approved domain.
- Review sitemap, inventory, crawl errors, PDF extraction.
- Confirm the institution boundary and exclude other campuses unless explicitly approved.

## Milestone 2 — Structured knowledge
- Add topic classification and record schemas for admissions, departments, courses, fees, regulations, contacts, placements, facilities, and notices.
- Add freshness and academic-year metadata.
- Add conflict detection and human review.

## Milestone 3 — Better retrieval
- Add keyword + vector retrieval and reranking.
- Add metadata filters for topic, source type, academic year, and freshness.
- Include document section/page references where available.

## Milestone 4 — Quality evaluation
- Curate approved student questions and expected source records.
- Measure retrieval relevance, answer faithfulness, source correctness, and refusal/uncertainty behavior.
- Run regression tests after each data refresh.

## Milestone 5 — Production readiness
- Add authentication for admin/ingestion routes.
- Run ingestion as a background job queue.
- Add rate limiting, monitoring, backups, secrets management, and access controls.
- Add a review/publish workflow before public release.
- Add scheduled change detection and incremental re-indexing.

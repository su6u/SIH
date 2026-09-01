# SIH26123 research dossier

**Working name:** SwarmRoute  
**Snapshot date:** 2 September 2026  
**Decision:** build a hybrid, logically distributed fleet coordinator in which deterministic protocols own safety and a small edge model predicts congestion/ETA.

This folder is the audit trail behind the proposed hackathon solution. The pasted explainer was treated only as context. Claims below were checked against research papers, official project documentation, source repositories, standards, and a small amount of clearly labelled community evidence.

## Start here

1. [Problem framing](00-problem-framing.md)
2. [Research method and corpus](01-research-method.md)
3. [Literature and algorithm review](02-literature-review.md)
4. [Open-source landscape](03-open-source-landscape.md)
5. [Recommended architecture](04-solution-architecture.md)
6. [Failure and threat model](05-failure-threat-model.md)
7. [Evaluation plan](06-evaluation-plan.md)
8. [Six-person hackathon plan](07-hackathon-plan.md)
9. [Pitch and demo script](08-pitch-and-demo.md)
10. [Curated bibliography](09-bibliography.md)

## Evidence layers

- **Discovery corpus:** 2,879 unique OpenAlex records from eight deliberately broad queries. It is a searchable index, not a claim that every record was read end to end.
- **Screening shortlist:** 250 recent/high-signal records selected mechanically for manual review.
- **Curated evidence:** the strongest research papers, official repositories, standards and documentation used to make architecture decisions.
- **Community evidence:** Reddit, ROS Discourse and Hacker News are used only to identify integration pain and operational edge cases. No substantive 4chan material was found; none was padded into the evidence base.

## The one-sentence solution

Each robot independently auctions tasks, plans a short space-time route, exchanges signed/ordered intent with relevant peers, leases shared conflict zones, inherits priority to break local jams, and passes every motion through a hard collision shield; an on-device model only adjusts bids and route costs.

## What we explicitly rejected

- End-to-end MARL as the motion/safety controller.
- Independent shortest-path A* as the proposed system.
- A central SQL database, dashboard, MQTT broker, or Open-RMF schedule as coordination truth.
- Blockchain, federated learning, LLM control, or a giant ROS/Gazebo integration before the coordination algorithm works.
- Claims of industrial certification or universal “zero collisions.” The defensible statement is zero modeled conflicts across declared seeded trials and assumptions.

## Files in `corpus/`

- `openalex_sources.jsonl` — deduplicated machine-readable corpus.
- `openalex_sources.csv` — spreadsheet-friendly copy.
- `screening_shortlist.csv` — 250-record manual-screening queue.
- `raw/` — page-level API responses retained for reproducibility.

Regenerate with `bash scripts/harvest_openalex.sh` (network access required).

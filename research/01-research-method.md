# 01 — Research method and corpus

## Questions used to drive the search

1. What formulation best represents continuous warehouse work?
2. Which planners remain fast with many agents and short deadlines?
3. Which mechanisms are genuinely decentralized?
4. What breaks when messages, clocks and motion are imperfect?
5. Where can learning improve throughput without owning safety?
6. Which open-source components are permissively licensed and feasible in 36 hours?
7. What evidence would make the SIH performance claim defensible?

## Discovery protocol

OpenAlex was queried with eight broad searches:

1. `"multi-agent path finding"`
2. `"lifelong multi-agent path finding"`
3. `"multi-robot task allocation"`
4. `"autonomous mobile robot" warehouse`
5. `"warehouse robot" fleet management`
6. `decentralized multi-robot coordination`
7. `distributed robot collision avoidance`
8. `edge computing mobile robots`

Filters: publication date from 2015-01-01; two cursor pages of 200 results per query. Records were deduplicated by OpenAlex work ID.

## Corpus snapshot

| Measure | Count |
|---|---:|
| Unique records | 2,879 |
| Published in 2026 | 184 |
| Published in 2025 | 328 |
| Published in 2024 | 337 |
| Published since 2023 | 1,212 |
| Records with DOI | 2,771 |
| Marked open-access (gold/green/hybrid/bronze) | 1,793 |

This exceeds the requested 1,500-source discovery target. It intentionally favors recall over precision. The corpus includes adjacent robotics, edge and task-allocation material; “2,879 indexed” must not be represented as “2,879 papers deeply read.”

## Screening

The 250-record shortlist favors:

- 2024–2026 publications;
- titles explicitly referencing MAPF, MAPD, MRTA, warehouses, fleet coordination or collision avoidance;
- citations only as a secondary signal, because new papers have had less time to accumulate them;
- primary paper/project pages over summaries;
- released code, standard benchmarks and stated assumptions.

Manual synthesis then emphasized papers that change an implementation decision. Literature without accessible methodology, implausible claims, unclear provenance, or only tangential relevance was excluded from the curated set.

## Source hierarchy

1. Peer-reviewed paper or current arXiv preprint from identifiable authors.
2. Official repository, project documentation or standard body.
3. Competition benchmark and reproducible artifact.
4. Vendor/industry material for context only.
5. Community posts for integration anecdotes only.

## Bias and limitations

- OpenAlex search relevance is not a systematic-review database protocol.
- Publication metadata can be incomplete or duplicated across versions.
- 2026 work contains preprints that have not yet passed peer review.
- Citation count undervalues new work and can overvalue famous but less applicable work.
- Many MAPF results assume synchronized discrete motion and perfect communication.
- Repository activity does not equal correctness or production fitness.
- Community discussions overrepresent problems and self-selected users.

## Reproducibility

- Harvester: `scripts/harvest_openalex.sh`
- Full records: `research/corpus/openalex_sources.jsonl`
- CSV: `research/corpus/openalex_sources.csv`
- Screening queue: `research/corpus/screening_shortlist.csv`
- Curated references: `research/09-bibliography.md`

The raw API pages are retained so later team members can audit record transformation without re-querying the service.

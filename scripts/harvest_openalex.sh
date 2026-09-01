#!/usr/bin/env bash
set -euo pipefail

root_dir="$(cd "$(dirname "$0")/.." && pwd)"
raw_dir="$root_dir/research/corpus/raw"
out_jsonl="$root_dir/research/corpus/openalex_sources.jsonl"
out_csv="$root_dir/research/corpus/openalex_sources.csv"

mkdir -p "$raw_dir"

queries=(
  '"multi-agent path finding"'
  '"lifelong multi-agent path finding"'
  '"multi-robot task allocation"'
  '"autonomous mobile robot" warehouse'
  '"warehouse robot" fleet management'
  'decentralized multi-robot coordination'
  'distributed robot collision avoidance'
  'edge computing mobile robots'
)

query_index=0
for query in "${queries[@]}"; do
  query_index=$((query_index + 1))
  cursor='*'
  for page in 1 2; do
    destination="$raw_dir/query-${query_index}-page-${page}.json"
    curl -L --fail --silent --show-error --get \
      'https://api.openalex.org/works' \
      --data-urlencode "search=$query" \
      --data-urlencode 'filter=from_publication_date:2015-01-01' \
      --data-urlencode 'per-page=200' \
      --data-urlencode "cursor=$cursor" \
      --data-urlencode 'mailto=research@example.com' \
      --output "$destination"
    cursor="$(jq -r '.meta.next_cursor' "$destination")"
  done
done

jq -s -c '
  [.[].results[] |
    {
      openalex_id: .id,
      title: .display_name,
      year: .publication_year,
      publication_date: .publication_date,
      doi: .doi,
      type: .type,
      cited_by_count: .cited_by_count,
      source: (.primary_location.source.display_name // null),
      landing_page: (.primary_location.landing_page_url // .id),
      open_access: .open_access.oa_status,
      authors: ([.authorships[].author.display_name] | join("; ")),
      concepts: ([.topics[0:3][].display_name] | join("; "))
    }
  ]
  | unique_by(.openalex_id)
  | sort_by([-(.year // 0), -(.cited_by_count // 0)])
  | .[]
' "$raw_dir"/*.json > "$out_jsonl"

jq -r -s '
  (["openalex_id", "title", "year", "publication_date", "doi", "type", "cited_by_count", "source", "landing_page", "open_access", "authors", "concepts"] | @csv),
  (.[] | [.openalex_id, .title, .year, .publication_date, .doi, .type, .cited_by_count, .source, .landing_page, .open_access, .authors, .concepts] | @csv)
' "$out_jsonl" > "$out_csv"

printf 'Deduplicated OpenAlex records: '
wc -l < "$out_jsonl"

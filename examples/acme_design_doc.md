# Acme data platform — Q3 ingestion changes

This is an ordinary design doc. The prose is for humans; the tables
below are picked up by `triplite import` because their headers have
s/p/o columns. Everything else (including this paragraph and the
non-triple table at the bottom) is ignored.

## New event stream

We are adding a product-analytics vendor. The contract starts in Q3
and lands in the warehouse as follows:

| s               | p          | o                 | schedule  |
|-----------------|------------|-------------------|-----------|
| clickpath-pa    | PROVIDES   | clickpath-webhook |           |
| clickpath-webhook | INGESTS_TO | RAW_PRODUCT_EVENTS | streaming |

## Known change events

| subject            | predicate   | object                                              |
|--------------------|-------------|-----------------------------------------------------|
| RAW_PRODUCT_EVENTS | AFFECTED_BY | 2025-09-01 clickpath drops the legacy session_id field |

## Rollout owners (not a triple table — ignored on import)

| step     | owner |
|----------|-------|
| contract | alice |
| webhook  | bob   |

# Incident log — ingest

2026-03-04. The ingest job failed overnight. The warehouse connection
pool was exhausted; the job cannot run without the warehouse, and the
warehouse was mid-upgrade. Platform restarted it at 07:10 and it caught
up by 09:00.

2026-09-04. The ingest job failed overnight again, same cause. Platform
restarted it. We should size the pool properly, but nobody has.

The ingest job is owned by Platform. Ownership moved there in 2024 from
the old data team, which no longer exists.

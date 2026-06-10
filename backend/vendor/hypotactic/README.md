# Hypotactic scansion data

Syllable-level scansion of the entire Iliad by David Chamberlain,
downloaded from https://hypotactic.com/use-the-source/
(archive: https://hypotactic.com/wp-content/uploads/2017/05/IliadAllCSV.zip)
and licensed CC BY 4.0.

Committed rather than fetched on demand so meter imports work offline and
keep working if the upstream URL moves. One CSV per book; each row is a
syllable with its length (long/short), word number, foot number, and
half-line position. Consumed by `scripts/import_meter.py`.

Per the author's notes, caesura (`Half-line`) values are subjective and
should not be treated as authoritative; we store but do not display them.

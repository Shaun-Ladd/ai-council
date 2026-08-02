# Final Plan — session 20260802-143159-fb85bc

Approved by Judge: proposal v002 (sha256 `c1a0ed34891a67c97984feab31cd9c36c9347399fb5025df07b93775f4192547`).

---

# Widget Importer — Proposal

## Design

A `widgets import` CLI subcommand parses the CSV with a strict schema,
validates every row, and upserts widgets keyed by SKU.

## Requirement Coverage

- REQ-001: rows are validated by a pydantic row model before any write.
- REQ-002: upsert keyed on widget SKU makes re-runs idempotent.

## Test Plan

Unit tests for validation; integration test importing the same file twice
(AC-001).

## Failure Handling

Row failures are collected and reported; the import runs in a transaction so
partial imports never persist.

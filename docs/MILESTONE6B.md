# Milestone 6B — Frozen Forward Research Orchestration

## Purpose

Milestone 6B provides the durable journal that the 90+ day paper/shadow research period needs.

Milestone 6 can evaluate evidence, but evaluation is only trustworthy when the evidence comes from a study whose strategy version, experiment, parameters and GREEN policy were fixed **before** the forward period. This milestone creates that boundary.

## Frozen study definition

A forward study can start only when:

- the strategy exists;
- the strategy version exists and is immutable;
- the experiment exists and belongs to that exact strategy version;
- the experiment is registered/running;
- initial simulated capital is positive.

At creation, the study permanently snapshots:

- strategy-version ID;
- experiment ID;
- family / venue / instrument;
- starting capital;
- study configuration;
- the complete Milestone-6 evaluation policy;
- forward start timestamp.

Later `.env` changes therefore do **not** rewrite the standard by which an already-running study is judged.

## Forward journal

The journal stores normalized:

- NAV observations;
- closed paper/shadow trade outcomes;
- paper-vs-shadow execution comparisons;
- resolved probability forecasts;
- study incidents.

Worker-facing records use deterministic external keys. Exact retries are intended to be idempotent; conflicting data for an existing observation/key is treated as a research-integrity error rather than creating a second hidden history.

Trade P&L is validated before persistence:

`net P&L = gross P&L - fees - slippage`

Planned loss must be positive and cannot exceed allocated capital.

## Database-backed evaluation

`ForwardResearchService.evaluate_study()` reconstructs a Milestone-6 `EvaluationInput` directly from the frozen study journal and evaluates it with the **policy snapshot stored at study creation**, not current environment settings.

The resulting `StrategyEvaluationRun` is linked to the same immutable strategy version. Evaluation still returns only:

- `RED`;
- `AMBER`;
- `GREEN-1_CANDIDATE`.

It cannot promote `Strategy.status` or authorize live capital.

## Incident semantics

- any recorded data-integrity incident invalidates the study period for GREEN, even if the operational incident was later resolved;
- unresolved `critical` incidents also force RED;
- ordinary resolved operational warnings remain in the audit journal without automatically destroying the study.

This prevents a repaired feed bug from disappearing from the history used to justify live money.

## Protected internal API

Forward journal writes are intentionally disabled unless `FORWARD_INGEST_SECRET` is configured.

Write/read/evaluate study endpoints require the `X-Edge-Research-Secret` header. The comparison uses a constant-time secret check.

`GET /forward/status` is safe to expose and reports only the research mode/safety state.

Primary routes:

- `POST /forward/studies`
- `GET /forward/studies/{study_id}`
- `POST /forward/studies/{study_id}/nav`
- `POST /forward/studies/{study_id}/trades`
- `POST /forward/studies/{study_id}/executions`
- `POST /forward/studies/{study_id}/forecasts`
- `POST /forward/studies/{study_id}/incidents`
- `POST /forward/studies/{study_id}/evaluate`
- `POST /forward/studies/{study_id}/complete`

## Completed studies

A completed study is read-only. New NAV/trades/executions/forecasts/incidents cannot be appended after completion.

Completion does not make the strategy GREEN; it merely freezes the evidence period.

## Safety boundary

Milestone 6B adds no:

- wallet/private key;
- signer;
- exchange order submission;
- Solana transaction submission;
- Hyperliquid exchange action;
- Polymarket authenticated order action;
- bridge/CCTP transfer;
- vault access;
- live-capital authorization;
- automatic strategy promotion.

## Next step

With the durable journal available, venue-specific forward runners can write real paper/shadow observations into it. The first runner should be Hyperliquid funding/carry because it is the first-priority research strategy and already has public market/funding/L2-book collectors.

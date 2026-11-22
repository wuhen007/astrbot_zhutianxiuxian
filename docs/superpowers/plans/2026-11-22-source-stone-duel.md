# Source Stone Duel Implementation Plan

> **For agentic workers:** This plan is executed inline in this session. Tests are added with implementation but, per user instruction, are run together only before an explicitly requested push.

**Goal:** Port the three original NPC source-stone duels with persistent five-minute sessions, three-stone choices, wager modes, cooldowns, and atomic source-stone accounting.

**Architecture:** Put stone-form generation, outcome rules, NPC selection, resonance, and settlement arithmetic in a pure `core/source_duel.py` module. Store session, cooldown, and duel stats in the existing `ext["yuanshi"]` document and make command handlers settle through the existing per-player lock and SQLite transaction.

**Tech Stack:** Python 3.12, existing `PlayerDoc`, `core.yuanshi`, AstrBot command handlers, SQLite `DataBase.transaction()`.

**Spec:** `docs/superpowers/specs/2026-11-22-source-stone-duel-design.md`

## Global Constraints

- Keep source-stone currency in `ext["yuanshi"]["amount"]`.
- Preserve the original NPC fees, wagers, skill rates, stone forms, outcome thresholds, resonance bonuses, settlement branches, five-minute session lifetime, and six-hour completed-duel cooldown.
- Persist the random session seed so settlement retries reproduce the same NPC cut.
- Do not add cross-group state or a database table.
- Do not run tests or QA during implementation; run the unified checks only immediately before the next explicitly authorized push.
- Do not push without explicit user confirmation; bump plugin metadata and registration version on every push.

---

### Task 1: Pure Source Duel Rules

**Files:**
- Create: `core/source_duel.py`
- Create: `tests/test_source_duel.py`

**Interfaces:**
- `NPCS`: immutable three-NPC catalog containing id, name, title, wager, stone fee, skill, and opening line.
- `create_session(npc_id, player, now, seed) -> dict`: creates both five-stone batches and stores the seed and expiry.
- `resolve_session(session, choices, stake_mode) -> dict`: validates three distinct ids, uses the stored seed to select the NPC stones, and returns both cuts and settlement.
- `cooldown_left(yuanshi_state, now) -> int`: returns the active six-hour cooldown seconds.

- [x] Add the weighted 19-form stone table and unique weighted sampler from `sourceStoneForms.js`.
- [x] Add original outcome thresholds, appearance bias, 55% clue accuracy, occupation insight accuracy, and resonance pairs from `sourceDuelRules.js`.
- [x] Add the original NPC score selection algorithm and settlement arithmetic for win, loss, draw, and all stake multipliers.
- [x] Store seed and `expires_at` in seconds in each newly created session; implement expiry detection without touching player state.
- [x] Add deterministic unit cases for tiers, resonance, NPC choice, malformed picks, and payout formulas without running them yet.

**Task 1 implementation:** `core/source_duel.py`; rule test file `tests/test_source_duel.py`. Tests were authored but not run per user instruction.

### Task 2: Player Duel State And Atomic Economy Updates

**Files:**
- Modify: `core/yuanshi.py`
- Modify: `core/source_duel.py`
- Test: `tests/test_source_duel.py`

**Interfaces:**
- `duel_state(yuanshi_state) -> dict`: normalizes `session`, `cooldown_until`, and stats under `yuanshi_state["duel"]`.
- `record_duel_ledger(yuanshi_state, now, *, price, source, name, extra) -> None`: appends one bounded source-ledger row without incrementing stone-cut counts.

- [x] Normalize duel state while preserving existing amount, market, cooldown, and ledger keys.
- [x] Track wins, losses, draws, net source, total player cut source, and peak player cut source.
- [x] Ensure fee and settlement ledger rows use the current ledger format and stay within `yuanshi.LEDGER_KEEP`.
- [x] Keep timeout fee loss recorded while leaving result counts and cooldown unchanged.
- [x] Add tests for legacy yuanshi documents without duel fields and ledger/stat updates without running them yet.

### Task 3: Commands And Transactional Settlement

**Files:**
- Modify: `main.py`
- Modify: `data/help/help.json`
- Modify: `core/yuanshi.py`
- Create/extend: `tests/test_source_duel_handlers.py`

**Interfaces:**
- `#源石坊对决`: displays source balance, three opponents, total risk, cooldown, and pending-session status.
- `#源石坊对决1|2|3`: checks fee plus base-wager funds, charges only the NPC stone fee, creates the persistent session, and displays the player's batch while keeping the NPC batch hidden until resolution.
- `#对决选石 A B C [平注|加注|豪赌]`: validates the active session and extra wager, settles exactly once, records statistics/cooldown/ledger, and reports cuts and net source.

- [x] Serialize start and choice handlers with `_serialized_player_command`.
- [x] Reject starting while a valid session exists or cooldown remains; lazily clear expired sessions without refunding the fee.
- [x] Save the fee deduction and new session atomically before returning the five-minute choice prompt.
- [x] On invalid choices or insufficient selected wager, keep the session and do not mutate currency or statistics.
- [x] Settle source balance, duel statistics, six-hour cooldown, session removal, and ledger changes in one database transaction.
- [x] Preserve deterministic resolution by using the session seed; a failed transaction must leave the same session available for retry.
- [x] Update `#源石账本` output to include duel record totals and add both commands to runtime and JSON help.
- [x] Add handler/database regression cases for insufficient funds, expiry, cooldown, rollback, duplicate settlement, and ledger updates without running them yet.

### Task 4: Unified Push-Time Validation

**Files:**
- No code changes unless validation reveals a defect.

- [x] At the explicit push request, run focused source-duel tests (20 passed) and full `python -m unittest discover -s tests` (204 passed).
- [x] Run `python tests/selfcheck.py` (`ALL M12 CHECKS PASSED`), `python -m compileall -q main.py core infra tests`, parse 170 data JSON files and runtime help JSON, and pass `git diff --check`.
- [x] Fix the selfcheck fixture and missing `math` import found during validation; bump `metadata.yaml` and `main.py` to version `0.1.3` before pushing.

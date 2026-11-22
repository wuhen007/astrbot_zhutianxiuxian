# Source Stone Duel Design

## Goal

Port the original five-stone source appraisal duel against three NPC opponents into the Python plugin, preserving its costs, NPC selection, stone generation, three-stone choice, wager modes, cooldown, and source-stone accounting.

## Scope

- Add `#源石坊对决` for the player menu and `#源石坊对决1|2|3` to start one of the three original NPC duels.
- Add `#对决选石 1 3 5 [平注|加注|豪赌]` to resolve an active session.
- Preserve a five-minute session lifetime and six-hour cooldown after a completed duel. The source-stone fee is charged at start and is not refunded on timeout, matching the original.
- Require enough source stones at start for the NPC's fee plus base wager. Charge only the fee at start; validate and charge the selected multiplier wager at settlement.
- Keep duel state in the player's existing `ext["yuanshi"]` data so it survives process restart and does not need a new database table.
- Apply fee, wager, payout, duel statistics, cooldown, and ledger entries atomically through the existing SQLite transaction and per-player command lock.
- Update the existing source-stone ledger and help entry with duel totals, wins/losses/draws, source net, and peak cut value.

## Original Rules To Preserve

- NPCs: 吴子明 (wager/fee 200,000, skill 0.12), 拓跋昌 (1,000,000, skill 0.58), and 南宫奇 (5,000,000, skill 0.92).
- A duel generates five unique stone forms for each side. Stone outcome tiers, appearance bias, clues, occupation insight accuracy, NPC selection skill, and stone-pair resonance follow `work/original/apps/Game/sourceDuelRules.js`.
- The player selects three distinct stones. Stakes are 平注 ×1, 加注 ×2, or 豪赌 ×3, and the NPC's wager is multiplied by the same mode.
- Win: return the player's wager and credit both sides' cut-source values plus the NPC wager. Draw: return the player's wager and the player's cut-source value. Loss: no credit; the player's wager and cut-source value are lost. The already charged stone fee is never refunded.
- Completed duels record win/loss/draw, source net, total cut source, and peak cut source. Invalid selections and insufficient settlement funds leave the session available until expiry.

## State And Settlement

- Add pure source-duel rules in a focused `core` module: NPC catalog, source-stone form data, weighted source outcomes, resonance, session creation, NPC selection, result calculation, and settlement arithmetic.
- Store `session`, `cooldown_until`, and duel statistics inside `ext["yuanshi"]`. Store `expires_at` in seconds and clear expired sessions lazily when opening the menu or beginning a duel.
- Generate and persist both five-stone batches when starting. The player's batch includes occupation-specific insight. The NPC batch and session are not regenerated when the player submits a choice.
- Use the player's existing lock and one database transaction for each start or settlement, so fee/session state and final currency/stat/ledger changes cannot partially persist.
- Use a seeded per-session RNG or persisted random seed so retrying settlement after an interrupted database transaction produces the same NPC choice and outcome.

## User Output

- Menu displays current source balance, each NPC's title, fee, base wager, maximum exposure, current cooldown, and pending-session status.
- Start displays the player's five stones, surface clues, occupation insight where applicable, available resonances, fee, wager, valid command form, and remaining selection time. Keep the NPC stone batch hidden until settlement, matching the original command output.
- Settlement reveals both selected three-stone cuts and their values/resonances.
- Settlement displays selected stones and NPC stones, cut values, resonance, result, stake, net result, and updated source balance.

## Validation At Push

- Add deterministic tests for stone-form uniqueness, occupation insight, outcome boundaries, resonance, NPC skill selection, choice validation, all three result branches, and stake multipliers.
- Add handler/database tests for start fee, timeout without refund, cooldown, insufficient initial funds, insufficient selected wager, transaction rollback, idempotent settlement, and ledger/stat updates.
- Per the user's workflow preference, run the full test suite, selfcheck, compilation, help JSON validation, and diff checks together immediately before the next explicitly authorized push.

## Exclusions

- No player-versus-player source duel.
- No cross-group or group-scoped duel state; each player's NPC duel is private and independent.
- No new database tables or Redis-compatible service.

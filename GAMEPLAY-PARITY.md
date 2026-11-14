# Original Gameplay Parity Port

This change replaces the remaining lightweight approximations found in the fixed-source comparison with stateful behavior based on the JS model. Source-derived gameplay data is stored as JSON so the plugin does not invoke Node at runtime.

## Implemented

- **Endless realm:** 150 layers per tier, elite/boss placement and checkpoints follow layer cadence. The combat engine now resolves independent dodge, damage reduction, reflect, execute, summon, extra action, combo, damage-taken growth, fire scaling, team shield, victory healing, and victory attack growth effects instead of folding them into static attributes.
- **Zhutian projection:** imports all 30 source events across the three supported worlds. The persisted exploration state tracks relationships, flags, completed/recent events, pending follow-ups, material/stat effects and idempotent resolutions. Follow-up choices remain available for 15 minutes; an expired command session is cleared without dropping the pending story event.
- **Endless reincarnation:** ports the source's seven-scene branching run, eight professions, 20 NPCs, 14 monsters, nine endings, encounter checks/effects, team state, dynamic task statuses and outcome scoring. The 12 original meta-exchange products and four permanent attribute training groups are connected to the existing cumulative-points wallet. Existing wallet saves remain readable.
- **Xiangu NPC ecology:** active private maps initialize a 15-second delay, then advance one rotating NPC action every 30 seconds with one BFS movement step. The plugin tick persists map state and serializes it against map-mutating player commands.
- **Star Pavilion auctions:** official and inner lots open during the source windows (Shanghai time: 20:00–21:00 and 21:00–23:00) and settle after two minutes without a bid. Human bids can trigger an eligible hated Tianjiao counterbid; the inner scheduled lot also performs its source-style per-minute NPC bid. The existing player-to-player market remains command-driven rather than being opened by this scheduler.

## Validation

- `python -m unittest discover -s tests`: 48 tests passed.
- Changed Python modules compile with `py_compile`.
- `data/help/help.json` parses as JSON; `git diff --check` passes.

## Known Boundaries

- Endless combat still runs a single player unit; source multi-member synergies and cross-server flows are not included in this port.
- Auction timers and broadcast are exercised through the Python state engine and static main-module compilation, not a live AstrBot/QQ host. The implementation uses the plugin's single-process locks and SQLite transactions instead of the source Redis Lua/CAS deployment model.
- Full production database, platform-message delivery, and long-running scheduler behavior have not been exercised in a live host.

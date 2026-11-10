# Phase6 G08: explicit endogenous grid-feedback stage

Product path: normal project → independent grid-feedback preset/JSON → save/validate/publish → frozen cost envelope/AC off → execute/history → formal ZIP. See `docs/OPT_GRID_FEEDBACK_MODEL_CONTRACT.zh.md` and `docs/BROWSER_REPLAY_PHASE6.zh.md`.

- `app/opt_grid_feedback.py`: Pyomo DC cost clearing, current-dispatch four signals with FD/binding-basis diagnostics, work-conserving scheduler/lexicographic cleanup, actual re-clearing and truthful iteration/failure statuses.
- `build_inputs.py`: copies already-downloaded PUBLIC RTS CSVs; no network, no optimal decision injection. `raw_manifest.json` pins content/Gitblob but NOT exact author commit. Whole8784 load retained; only four original leap-day hours run in this stage. Static renewable and linear heat coefficients are explicit VARIANTS, not paper TableI/II reproduction.
- `independent_reference.py INPUT.zip OUTPUT.json`: standalone SciPy generator/PTDF LP, cost-optimal-face emission range, CSV work/migration/FD/cost/LCA audit. Does not import product code. This new reference is not the missing old oracle.
- `acceptance_api.py EVIDENCE_DIR`: creates a NEW explicitly named public-input acceptance project; requires healthy idle local Mock app. Writes new records only; do not rerun blindly if already created (consult api_acceptance_index.json). Four success scenes, two genuine failed scenes, one frozen rerun.
- `independent_gates.py EVIDENCE_DIR`: 12 separately counted independent gates from frozen ZIPs/raw CSVs. LP groups are subchecks, not test-count inflation. Synthetic controls are NOT paper precision.
- `tests/test_opt_grid_feedback_phase6.py`: product regressions counted in pytest, separate from independent gates.

Unimplemented: full8784 feedback, author exact commit/VRE profiles/node mapping/cost/ton-unit alignment, OPF-FLEX global benchmark, routed migration fees/latency/bandwidth, AC/UC/ramping/storage intertemporal/GPU/integer coupling, grid-endogenous annual CFE. Existing default daily and opt_cfe models remain separate. No global-optimality claim from a feedback fixed point. Browser is still blocked and unverified; Shell/API is not UI acceptance.

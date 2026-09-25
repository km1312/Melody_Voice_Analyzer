# Phase 1 build status — 2026-09-21

Everything in PRD section 9 (milestones A and M0–M11) is implemented on
branch `interpret-phase1`, with 182 offline tests green and the extended
`--selftest` passing on this machine. Phase 2 items were not started beyond
what the PRD marks as groundwork (the provider checklist template and the
harness's refusal logic for remote entries).

Findings from the first dogfood pass, with causes and fixes, are in
`docs/FIX_LIST.md`. **All ten items were fixed on 2026-09-21** (commit
"First dogfood fixes"): playback no longer fights clicks (and the player's
end-of-range bug is gone), context names save automatically and update an
open Results window live, the timeline has a legend, its own family
colours and hover tooltips, other-speaker interjections show inline as
`[Name: yeah]`, the same-person outcome trigger is wired, the coaching
table always shows its direction column with units, long transcript turns
render fully, questions are counted mid-turn, and baseline rows carry the
recording's date. Item 4's deeper half (splitting short interjections into
their own turns) is recorded in `docs/DECISIONS.md` as a Phase 1.5
candidate with the measurement it needs first. The dogfood bundle in
`dist\Melody Tone Analyzer\` was rebuilt with these fixes.

## Release checklist (PRD section 5), as it stands

| Item | State |
| --- | --- |
| Milestone acceptance tests | **Done** — `pytest -q`: 182 passed, all offline under the socket guard |
| Offline test with the adapter disabled | **Code-level done** (socket guard + netguard + firewall script); the literal adapter-off full run is a 5-minute owner errand |
| Ten dogfood calls, feedback recorded | **Owner** — the store, feedback buttons and outcome asks are waiting |
| Both ablations run and written up | **Harness ready** (`bench/`, variants tested); needs real calls and a model |
| One benchmark report, two local models | **Harness ready**; needs a local server running |
| `--selftest` extended | **Done** — net guard, pack build, verifier, store; transcript text removed from the log |
| Owner decisions recorded | **Done** — `docs/DECISIONS.md`, all ten, flagged for review |

## What the owner should do first

1. Read `docs/DECISIONS.md` (ten decisions adopted from the PRD's own
   recommendations, plus eight recorded deviations) and object to anything.
2. Run one real call through the app: the row grows Context / Results /
   Interpret buttons; mark yourself in Context; send the pack to any model
   by hand and paste the reply into Results.
3. `docs/CHECKLIST_RESULTS.md` is the manual UI walk for one release.
4. For unattended runs: start a server with `tools\start_local_llm.ps1`,
   set Settings > Interpretation to `openai_compat`, and press Interpret.
5. `tools\verify_offline.ps1` (elevated) for the firewall half of PR-3.

## Numbers

- 12 commits on the branch, one per milestone.
- New code: `revolv/interpret/` (view, context, pack, schema, verify,
  manual_import, runner, providers), `netguard`, `safelog`, `player`,
  `store`, `coaching`, `retention`, `selfcheck`, three GUI modules, the
  timeline widget, `bench/` (run, variants, metrics, judge, report, gold),
  prompts p1.0.0 (P0–P6 plus eight lenses), 19 test files and a synthetic
  three-speaker fixture that exercises six note features, both overlap
  kinds and a converging hesitation turn.
- The verifier's golden test drops exactly the seven bad readings of the
  PRD's M4.7 list for exactly the listed reasons, and keeps the four sound
  ones.

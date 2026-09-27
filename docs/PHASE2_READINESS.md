# Before Phase 2 — readiness checklist

2026-09-22. What has to be true before an agent is sent to build Phase 2 (PRD section 11). The PRD's own gate is strict: "Phase 2 starts only after the Phase 1 release checklist is complete." The practical reading below splits that into what blocks a Phase 2 agent from doing good work (A–D) and what can run alongside it (E).

Why the order matters: Phase 2 plugs into `interpret/runner.py`, the `Provider` protocol, the Settings popover and the Results window. Fix-list items 1–3 change the same files, and a second agent editing them at the same time means merge conflicts and duplicated work. Close Phase 1 first, merge, then branch Phase 2 from `main`.

## A. Close out the Phase 1 code (an agent can do all of this)

- [ ] Work `docs/FIX_LIST.md`, items 1–10, on the `interpret-phase1` branch. Items 1–3 (playback seek, names not applied, timeline legend) are the ones that touch Phase 2 surfaces.
- [ ] `pytest -q` green; `main.py --selftest` exits 0; rebuild to `dist\staging` and run the bundle's selftest.
- [ ] Merge `interpret-phase1` into `main`. Delete the untracked root `MELODY_PRD.md` (the `docs/` copy is canonical). Rename `dist\Melody Tone Analyzer` to `.old` and move the staging build up so shortcuts point at the current app.

## B. Prove the loop once, end to end (you, about an hour)

- [ ] Run one call through the local runner: Settings → Interpretation → `openai_compat`, base URL `http://127.0.0.1:1234/v1` (LM Studio) or `http://127.0.0.1:11434/v1` (Ollama), model name, 32k context, then the row's Interpret button. This is the exact code path every Phase 2 adapter reuses; if it has never been seen working locally, a remote failure later cannot be attributed.
- [ ] Finish the items marked *not judged* in `docs/CHECKLIST_RUN_2026-09-21.md`: Notes, Under the surface, pins, Import errors, dark mode, the "Building your baseline" line.
- [ ] Click Useful / Not useful on a few cards, then export the feedback CSV once and confirm it holds no words from the call.

## C. Decisions only you can make (record in `docs/DECISIONS.md` before the agent starts)

- [ ] **Which provider(s) first.** The PRD suggests Bedrock or Groq because zero retention is self-serve. Pick one, at most two, to actually build and test; the rest stay as table rows.
- [ ] **Accounts and keys.** Create the account, accept the API or commercial terms (not a consumer chat plan), generate a key. The agent never sees the key; you paste it into the app once the Credential Manager field exists. Fill in `docs/providers/<name>.md` from the template for each provider you pick.
- [ ] **De-identification policy.** Default on and not switchable, or default on with a per-run toggle shown in the confirm dialog? Recommendation: the second. Confirm that the names line is dropped as well (PRD P2-3).
- [ ] **Firewall.** `tools/verify_offline.ps1` (PR-3) adds an outbound *block* for the app, which Phase 2 has to get past. Choose: the script gains an `-AllowRemote <host>` mode that adds allow rules for the chosen provider hosts only (recommended), or the rules are removed while `allow_remote` is on.
- [ ] **Dependencies.** `keyring` is already approved. Choose SDKs or plain HTTPS: Anthropic, Groq and OpenAI-compatible endpoints work over `urllib` with no SDK; Bedrock needs request signing, which in practice means `boto3` (large in a PyInstaller bundle). Recommendation: plain HTTPS unless Bedrock is chosen.
- [ ] **Product name (D3).** If a rename is coming, decide it now; Phase 2 adds user-facing strings (confirm dialog, ledger, settings) that would otherwise be written twice.
- [ ] **A `cloud_ok` test recording.** At least one call you are allowed to send to a cloud model: a public earnings call or published interview is simplest; your own calls need every participant's agreement. Without one, every adapter and harness test runs against a fake.
- [ ] **Scope.** Confirm P2-8 (an audio model as second opinion) stays out, and the harness cost column (P2-7) is in.

## D. Write the Phase 2 build plan

Section 11 of the PRD is a table of what, not a plan of how. Before the agent starts it needs milestones with "done when" tests, in the style of section 9. Suggested order, because nothing may send before the ledger can record it:

1. `allow_remote` setting (default off), the per-run confirm dialog, and the `egress_log` table with the "0 bytes sent" indicator. Done when a test proves no remote call can be made without a click in the dialog, and a ledger row exists before any request goes out.
2. `keyring` storage for provider keys and the HuggingFace token. Done when a test greps `settings.json` and `melody.log` and finds neither.
3. De-identification: names and Dictionary terms to `PERSON_n` / `ORG_n` in the view, restored locally in the reply. Done when the round-trip test passes and the residual-risk note is in the docs.
4. One adapter (the provider chosen in C), through `runner`, refused unless `cloud_ok` and `allow_remote` are both true. Done when the socket guard still passes in tests (adapter mocked) and one real run on the `cloud_ok` recording writes an insights file and a ledger row.
5. Harness: cost column from a price table; remote cells refused for calls without `cloud_ok`. Done when the guard test passes and one report has a cost figure.
6. Packaging and docs: bundle the keyring backend, update `verify_offline.ps1` per the firewall decision, README section, `docs/providers/<name>.md` signed off.

Rules for the agent, to write into the plan: never write a key to disk or a log; every remote request goes through `runner` and writes its ledger row first; `cloud_ok` is checked in both the app and the harness; tests keep the non-loopback socket guard and mock every adapter; stop and ask on anything in C that is still blank.

## E. Not blocking — run alongside Phase 2

- [ ] Ten dogfood calls with feedback recorded (release checklist).
- [ ] Both ablations and a two-model local benchmark (needs a local server). Worth doing before paying for cloud runs, since it picks the default prompt version.
- [ ] Rotate the HuggingFace token if any build folder has been shared.
- [ ] A lawyer's read of Phase 2 before anyone but you uses it: sending conversations to a vendor is the exposure category the PRD flags in section 4.

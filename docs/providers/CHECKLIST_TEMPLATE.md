# Provider checklist — <provider name> (P2-6)

Copy this file to `docs/providers/<provider>.md` and complete every line
before the adapter is enabled. One file per provider; owner sign-off at the
bottom. The PRD's provider notes (section 11) were gathered 2026-09-19 and
must be re-verified on the day this is filled in.

- [ ] API or commercial terms apply, not a consumer chat plan
- [ ] No training on inputs by default, in the contract and not only as a toggle
- [ ] Retention in days, and what extends it (abuse flags, legal holds): ____
- [ ] Who can review content, and when: ____
- [ ] Subprocessors and processing region: ____
- [ ] The zero-retention route, whether it needs approval, and which
      features break it (files, batch, caching, web tools): ____
- [ ] A current SOC 2 Type II or ISO 27001 report on file (where): ____
- [ ] No router or aggregator in the path; no third-party prompt-logging tool

Adapter gates (all of P2-2 to P2-5 must exist first):

- [ ] `allow_remote` setting and the per-run confirm dialog
- [ ] De-identification round-trip test passing
- [ ] Egress ledger writing a row before the request leaves
- [ ] Keys in Windows Credential Manager, never settings.json

Owner sign-off: ____________________  date: __________

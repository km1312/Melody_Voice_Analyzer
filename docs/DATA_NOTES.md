# Data notes — pipeline shapes re-verified 2026-09-21

PRD section 7.0, checked line by line against `revolv/pipeline.py`,
`revolv/analysis.py` and `revolv/writers.py` on the day M0 was built. Nothing
had moved since the PRD's 2026-09-21 snapshot; the notes below add detail the
interpretation layer depends on. If the pipeline changes, re-verify here
first: `interpret/view.py` asserts its rebuilt turns match the report and
fails loudly, which is the tripwire.

## Segments (`<name>.json`)

A bare list. Each entry: `start`, `end`, `speaker`, `text`, `words`,
`pacing{word_count, duration_seconds, wpm}`, and on segments of scored turns
`emotion{valence, arousal, dominance, measured_over[, raw, clipped, passes]}`
and (when the head loaded) `stance{certainty, probabilities, measured_over}`.
Words: `word`, `start`, `end`, optional `speaker` (from the exclusive
diarization), optional `kind` in {`filler`, `vocalisation`, `event`,
`cutoff`, `repetition`}; ordinary words carry no `kind`. Timestamps are
original-media seconds, rounded to 2 dp, even under `trim`.

## Report (`meta["analysis"]`, serialised as `<name>.analysis.json`)

- `summary`: `media_seconds`, `turns`, `speakers`, `speech_seconds`,
  `speaker_changes`, `seconds_between_changes`, `longest_turn`,
  `scored_turns`, `emotion_gate_seconds`, `emotion_scope`.
- `speakers[label]`: `turns`, `scored_turns`, `speech_seconds`, `talk_share`,
  `median_turn_seconds`, `median_reply_latency`, `articulation_wpm`,
  `baseline_turns` (0 below `MIN_TURNS_FOR_BASELINE` = 12); with a baseline,
  one `{median, scale, mad, n}` (or null) per feature: `arousal`, `valence`,
  `articulation`, `f0_range`, `loudness_sd`, `terminal_rise`,
  `intensity_onset`, `intensity_mid`, `certainty`, `medial_fillers`,
  `lexical`.
- `moments[]`: `turn` (0-based turn index), `start`, `speaker`,
  `observations` (voice notes + pause wording), `voice_observations`,
  `evidence[{feature, note, z, n}]` (`mismatch` items add `arousal_z`),
  `baseline` ("call" | "trailing"), `mismatch`, `preview` (80 chars — the
  only transcript text in the report; never used by the view).
- `turns[]`: `index`, `speaker`, `start`, `end`, `text`, `speech_seconds`,
  `word_count`, `reply_latency` (null unless the speaker changed),
  `pauses[{at, seconds, within_segment, after_word, before_word}]` (all
  >= `PAUSE_MIN_SECONDS` = 1.0), `pace{word_count, speech_seconds, wpm,
  articulation_wpm}`, `emotion|null`, `stance|null`, `lexical`,
  `disfluency|null` (null on a Whisper-only transcript; else
  `filled_pauses, initial, medial, final, repetitions, cutoffs,
  vocalisations, per_100_words, medial_per_100_words[, events]`),
  `prosody|null` (`f0_median_hz, f0_range_semitones, f0_terminal_rise,
  loudness_db_sd, voiced_fraction[, intensity_onset_db, intensity_mid_db,
  intensity_words]`). `segments` are stripped by `_public`, so word kinds and
  word timings come from the segments file, matched by index.
- `settings`: the thresholds, `baseline_estimator`, `trailing_baseline_turns`
  (null below 900 s of media), `lexical_source`, `pitch_tracker` (null when
  analysed without a track).
- `audio_coverage` only when a track was supplied; `audio_starts_at` only
  when trimmed.
- `overlap` + `overlap_events` only when `meta` carried `diarization` or
  `overlaps`. Events: `start, end, seconds, speakers[a,b], by, over, kind`
  ("backchannel" | "floor_taking").

## Meta (in memory; the writers serialise only `analysis`)

`source`, `media_seconds`, `language`, `segments` (count), `speakers`
(count), `backend`, `verbatim` (bool), `model`, `device`, `device_name`,
`compute_type`; when present: `verbatim_model`, `verbatim_merge`,
`verbatim_tokens`, `stance_head`, `stance_scored_turns`, `emotion_scope`,
`emotion_scored_turns`, `trimmed_from`, `trimmed_to`, `diarization` (rows of
`start`, `end`, `speaker`), `overlaps`, `overlap_seconds`, `pitch_tracker`,
`analysis`.

## Details that matter downstream

- `analysis.build_turns(analysis.split_segments_by_speaker(segments))` is
  deterministic and reproduces the report's turns with segments attached.
  Turn indexes are 0-based; `T001` is index 0. Moment ids are the 1-based
  position in `report["moments"]`.
- `reply_latency` is set only when the previous turn's speaker differs;
  the first turn's is null. It can be tiny or negative-adjacent only in
  theory — segments cannot overlap, so it is >= 0 in practice.
- `_spread` falls back to the IQR when the MAD is zero; when both are zero
  the feature has no scale and no note can fire, which is why the fixture's
  medial-filler pattern needs nonzero spread to exercise that note.
- `write_all` writes `.analysis.json` only when both `md` and `json` are
  requested; `meta["numbers_file"]` steers the legend wording.
- `unique_path` treats `call.insights.json` as stem `call.insights`, so a
  second run writes `call.insights (2).json`.
- The frozen bundle sets `HF_HUB_DISABLE_TELEMETRY=1` in `runtime_hook.py`;
  source runs now get it (plus the offline flags, once the cache exists)
  from `main.py` via `revolv/netguard.py`.
- `core.autocrlf=true` in this clone; git stores LF. Do not compare raw
  newline bytes across a checkout.

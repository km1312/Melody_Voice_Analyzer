# Local model notes (M9.6)

The app talks to any OpenAI-compatible endpoint on loopback
(`Settings > Interpretation`, default `http://127.0.0.1:8080/v1`).
`tools/start_local_llm.ps1` starts a llama.cpp-style server with the right
flags. The benchmark harness (`bench/`) picks the default model; this file
only lists what to try first on the 16 GB card.

## Candidates for a 16 GB card

| Model | Size at 4-bit | Notes |
| --- | --- | --- |
| gpt-oss-20b | ~12 GB (MXFP4) | Reasoning effort medium; strongest small option to try first |
| Qwen 14B-class instruct | ~9 GB | Solid JSON discipline; leaves headroom for the 32k context |
| Gemma 4 26B-A4B | ~10 GB + CPU experts | Experts offloaded to CPU; slower first token |

## Ground rules

- **The server and the pipeline cannot share the card.** The pipeline peaks
  at 11.3 GB during the verbatim pass. Start the server after the batch
  finishes (the app's own runner also waits for the pipeline worker to exit
  before connecting), or run it on a second GPU.
- **Context 32,768 or more.** A 30-minute call's single-pass prompt is
  ~14k tokens in, and the reply needs room.
- **Loopback only.** The provider refuses any endpoint that does not
  resolve to this machine, and `tools/verify_offline.ps1` adds firewall
  rules that make the same promise at the OS level.
- **JSON.** The runner asks for `response_format` with a JSON Schema and
  falls back to plain JSON with validation plus one retry, so servers
  without structured-output support still work — they just fail a little
  more often, which the run records will show.

## Choosing between them

Run the harness on the same calls and read `bench/` reports: schema-valid
rate on the first try, quote-mismatch rate, kept-per-call, test-retest
overlap and the judged scores are the decision, not vibes. With fewer than
ten calls, treat differences as directional.

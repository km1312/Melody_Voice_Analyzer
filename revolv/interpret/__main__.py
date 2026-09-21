"""The interpretation CLI: pack, import and (with a provider) run.

    python -m revolv.interpret pack <name>.json
    python -m revolv.interpret import <name>.json <response.json>
    python -m revolv.interpret run <name>.json

`pack` reads the pipeline's `<name>.json` and, when present, the
`<name>.analysis.json` and `<name>.context.json` beside it. A missing
analysis file is re-derived from the segments without a prosody track, and
the pack says so (`"prosody": false` in pack.json). Everything is written
beside the input, never to a temp folder (PR-14).
"""

import argparse
import json
import sys
from pathlib import Path


def _load_segments(json_path):
    with open(json_path, encoding="utf-8") as f:
        segments = json.load(f)
    if not isinstance(segments, list):
        raise SystemExit(
            "{0} is not a segments file (expected a JSON list)".format(json_path))
    return segments


def _assemble(json_path):
    """(segments, meta-with-analysis, source_paths) for a `<name>.json`."""
    from .. import analysis

    json_path = Path(json_path)
    segments = _load_segments(json_path)
    sources = [json_path]
    analysis_path = json_path.with_name(json_path.stem + ".analysis.json")
    media_seconds = max((float(s.get("end", 0.0)) for s in segments),
                       default=0.0)
    meta = {
        "source": str(json_path.with_suffix("")),
        "media_seconds": round(media_seconds, 2),
        "segments": len(segments),
        "speakers": len({s.get("speaker", "UNKNOWN") for s in segments}),
    }
    if analysis_path.exists():
        with open(analysis_path, encoding="utf-8") as f:
            meta["analysis"] = json.load(f)
        meta["numbers_file"] = True
        sources.append(analysis_path)
    else:
        print("No {0} beside the input; re-analysing without a prosody "
              "track, so the pack will carry no pitch or energy notes."
              .format(analysis_path.name))
        meta["analysis"] = analysis.analyse(segments, meta)
        meta["numbers_file"] = False
    return segments, meta, sources


def _context_for(json_path):
    from .context import context_path, load

    return load(context_path(json_path))


def cmd_pack(args):
    from ..coaching import slots_for
    from .pack import build_pack

    json_path = Path(args.json)
    segments, meta, sources = _assemble(json_path)
    context = _context_for(json_path)
    pack_dir = build_pack(segments, meta, json_path.parent, json_path.stem,
                          context=context, source_paths=sources,
                          coaching_slots=slots_for(meta.get("analysis"),
                                                   context, json_path))
    print("Prompt pack written to {0}".format(pack_dir))
    return 0


def cmd_import(args):
    from .manual_import import import_response

    json_path = Path(args.json)
    segments, meta, _ = _assemble(json_path)
    result = import_response(
        segments, meta, json_path.parent, json_path.stem,
        Path(args.response).read_text(encoding="utf-8"),
        context=_context_for(json_path))
    if result.problems:
        print("The response could not be used:")
        for problem in result.problems:
            print("  - {0}".format(problem))
        return 1
    print("Wrote {0}".format(result.insights_path))
    print("Wrote {0}".format(result.notes_path))
    print("Kept {0} readings, dropped {1}; the file records each reason."
          .format(result.kept, result.dropped))
    return 0


def cmd_run(args):
    from .runner import run_from_cli

    return run_from_cli(Path(args.json), mode=args.mode)


def main(argv=None):
    parser = argparse.ArgumentParser(prog="python -m revolv.interpret")
    commands = parser.add_subparsers(dest="command", required=True)

    pack_cmd = commands.add_parser(
        "pack", help="Build <name>.prompt/ from a pipeline .json")
    pack_cmd.add_argument("json", help="The pipeline's <name>.json")
    pack_cmd.set_defaults(func=cmd_pack)

    import_cmd = commands.add_parser(
        "import", help="Verify a model response and write insights + notes")
    import_cmd.add_argument("json", help="The pipeline's <name>.json")
    import_cmd.add_argument("response", help="The model's JSON reply")
    import_cmd.set_defaults(func=cmd_import)

    run_cmd = commands.add_parser(
        "run", help="Run interpretation over the configured provider")
    run_cmd.add_argument("json", help="The pipeline's <name>.json")
    run_cmd.add_argument("--mode", choices=["single_pass", "multi_pass"],
                         default=None)
    run_cmd.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())

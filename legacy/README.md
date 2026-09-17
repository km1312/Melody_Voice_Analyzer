# Revolv Transcriber

A Windows desktop app that turns recordings into speaker-labelled transcripts with
word-level timing, speaking pace, and valence / arousal / dominance scores. Everything
runs locally. No audio leaves the machine.

It is the pipeline from `VoiceModel.py`, wrapped in a drag-and-drop window and packaged
as a standalone `.exe`.

## Using it

1. Launch **Revolv Transcriber.exe**.
2. Drop audio or video files onto the window, or click the drop area to browse.
   Dropping files onto the `.exe` icon works too, and dropping a folder queues every
   media file inside it.
3. Choose where output goes: next to each original, or a folder you pick.
4. Tick the formats you want, then press **Start transcribing**.

Double-click any finished row to open its output in Explorer.

### What it writes

| Format | Contents |
| --- | --- |
| `.json` | Every segment with words, timings, speaker, pacing and emotion. Same shape `VoiceModel.py` produced, so existing downstream code still reads it. |
| `.txt` | A readable transcript grouped by speaker. |
| `.srt` | Subtitles with the speaker name in each cue. |
| `.csv` | One row per segment, for a spreadsheet. Opens directly in Excel. |

Existing files are never overwritten. A second run writes `name (2).json`.

## Hardware detection

On launch the app probes the machine and picks settings to match. The detected
configuration is shown under the title.

With a CUDA GPU it selects by available VRAM:

| VRAM | Whisper model | Precision | Batch |
| --- | --- | --- | --- |
| 15 GB and up | large-v3 | float16 | 16 |
| 11 GB | large-v3 | float16 | 12 |
| 8 GB | large-v3 | float16 | 8 |
| 6 GB | large-v3 | int8_float16 | 4 |
| 4.5 GB | medium | int8_float16 | 4 |
| 3 GB | small | int8_float16 | 4 |
| 2 GB | base | int8_float16 | 2 |

Below 6 GB the emotion model is moved to the CPU so it does not compete with
transcription for VRAM. Below 2 GB, or with no CUDA GPU at all, everything falls back
to the CPU and the model is chosen from RAM and core count instead. GPUs older than
compute capability 7.0 drop to int8, since float16 buys them nothing.

If the GPU runs out of memory mid-run, the emotion model relocates to the CPU and the
run continues rather than failing.

Override any of this under **Settings** by pinning a model size or forcing CPU.

## Appearance

The window is light by default. Dark is available under **Settings > Appearance**
and switches live, so you can see it before saving.

The design brief was calm, so the palette is muted rather than saturated, the
neutrals are warm rather than clinical grey, and the layout leans on space instead
of dividers and boxes. Containers are rounded 16 to 20 pixels and controls 10 to 12,
in the range current guidance puts soft, approachable interfaces. The accent is a
desaturated denim that sits back instead of competing with the content.

Every foreground and background pairing clears the WCAG AA contrast floor of 4.5:1
on the surface it sits on. The subtle grey is reserved for disabled controls and is
never used for text a reader needs.

### Why Qt and not Tkinter

The first version of this window was Tkinter. It could not be made to look calm.
Tk draws no rounded corners, no shadows and no real hover states, its widget
indicators are fixed-size bitmaps that break on a high-DPI display, and its file
drop hands over a quoted string rather than paths. Qt does all of it natively,
handles DPI scaling on its own, and styles through a stylesheet, so the palette
lives in one place and both themes stay in step.

Two Qt details worth knowing if you edit the interface:

- The stylesheet cannot draw a chevron or a tick. The zero-size-box border trick
  that works in CSS renders as a dash here. Both are painted once with QPainter,
  cached as PNGs in the temp folder, and referenced from the stylesheet.
- No drop shadow is applied to the file list. A `QGraphicsDropShadowEffect` on a
  scroll area stops its viewport clipping, and the rows spill over the controls
  underneath.

## Settings

Stored in `%LOCALAPPDATA%\RevolvTranscriber\settings.json`.

- **HuggingFace token** gates speaker diarization. Without one, transcription still
  runs but every segment is labelled `UNKNOWN`. Accept the terms for
  `pyannote/speaker-diarization-3.1` and `pyannote/segmentation-3.0` on huggingface.co
  before first use.
- **Language** defaults to English. Set it to `auto` to detect per file; the matching
  alignment model is then loaded on demand and cached.
- **Whisper model** and **Processor** override hardware detection.
- Speaker labelling and emotion scoring can each be turned off to save time.
- **Appearance** picks light or dark.

## First run

Models are downloaded from HuggingFace into `%USERPROFILE%\.cache\huggingface`, about
3 GB. That happens once and only needs a network connection the first time. Every run
after that is offline.

Model loading takes a couple of minutes. It happens once per batch, not once per file,
so queueing several recordings together is much faster than running them one at a time.

## Speed

On an RTX 5060 Ti with large-v3 at float16, a 90 second clip took 15 seconds end to
end, roughly 6x real time. A one hour meeting lands near ten minutes. CPU-only is
slower by more than an order of magnitude.

## Troubleshooting

Activity is logged to the window and to `%LOCALAPPDATA%\RevolvTranscriber\revolv.log`.
**Settings > Open log file** opens it. The log is the place to look if the app closes
unexpectedly, since the windowed build has no console.

If a file fails, its row shows why and the rest of the queue continues.

## Building from source

```powershell
.\build.ps1
```

The result is `dist\Revolv Transcriber\`, 4.8 GB across roughly 13,800 files: a
106 MB `.exe` and an `_internal` folder holding the rest, most of it the CUDA
libraries inside PyTorch. Keep the two together and move the folder as a unit.
A clean build takes about 25 minutes.

To confirm a build is sound, run the self-test. It walks the whole pipeline and
writes the outcome to the log:

```powershell
& ".\dist\Revolv Transcriber\Revolv Transcriber.exe" --selftest "some-clip.wav"
```

Exit code 0 means the bundle is good. Without a file argument it checks imports
and hardware detection only. This matters because a windowed build has no
console, so a missing dependency would otherwise show up as a window that never
appears.

### Layout

| Path | Role |
| --- | --- |
| `main.py` | Entry point. Redirects stdout and stderr to the log, since a windowed build has neither. |
| `revolv/hardware.py` | Hardware probe and the tier tables above. |
| `revolv/audio.py` | Decodes any container PyAV can open to mono 16 kHz. |
| `revolv/pipeline.py` | WhisperX transcription, alignment, diarization and emotion scoring. |
| `revolv/writers.py` | The four output formats. |
| `revolv/gui.py` | The window, built on PySide6. |
| `revolv/theme.py` | The light and dark palettes and the Qt stylesheet built from them. |
| `revolv/config.py` | Settings persistence. |
| `RevolvTranscriber.spec` | PyInstaller bundle definition. |

### Notes on the packaging

The bundle is onedir rather than onefile. A onefile build unpacks about 4 GB of CUDA
libraries to a temp folder on every launch, which makes startup take minutes.

UPX compression is off. It corrupts some CUDA DLLs.

`torchcodec` is excluded. It is broken in this environment and pyannote only reaches it
through a `try`/`except`, so its absence changes nothing.

## Security note

The HuggingFace token is stored in plain text in the settings file, and a copy is
compiled into the bundle as the first-run default. Anyone with the app folder can read
it. Rotate the token at huggingface.co/settings/tokens before sharing this build with
anyone, and clear `DEFAULT_HF_TOKEN` in `revolv/config.py` first so the next build
carries no secret.

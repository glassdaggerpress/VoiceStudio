# Automation Central Audio Studio profile

This fork can serve the VoiceStudio tab of Audio Studio as a separate native
Apple Silicon service. Existing audiobook production remains in AC's Audiobooks
tab, using its original service, manuscript plan, output folders and resumable
chapter cache. This profile does not migrate or replace them.

Build the web UI with `VITE_AC_AUDIO_STUDIO=1 bun run build:web`. Run the backend
with `AC_AUDIO_STUDIO=1`, a dedicated `OMNIVOICE_DATA_DIR`, and
`AC_AUDIO_RENDER_LOCK` pointing to the lock also inherited by AC audiobook
render subprocesses. Native macOS execution preserves MLX acceleration; a Linux
Docker container on a Mac cannot provide that acceleration.

The embedded navigation exposes dubbing, cloning, voice design, saved voices,
studio projects and settings. The standalone app's audiobook, dictation,
workflow, batch and marketplace features are excluded. Prepared installations
enter the workspace directly. Analytics, diagnostic reporting, cloud sync and
native dictation runtimes are not mounted by this web profile. Its shared status
controls do not poll the excluded batch and dictation endpoints.

## Models and commercial use

Only these voice weights are accepted by the profile:

| Model | Purpose | Installation |
| --- | --- | --- |
| mlx-community/Qwen3-TTS-12Hz-0.6B-Base-8bit | Compact cloning and dubbed speech | Initial |
| mlx-community/Qwen3-TTS-12Hz-1.7B-VoiceDesign-4bit | Text-described voices | Initial |
| mlx-community/Qwen3-TTS-12Hz-1.7B-Base-bf16 | Larger cloning alternative | Optional |

Their converted and original Qwen model cards declare Apache 2.0, including the
Qwen speech tokenizer. Whisper Small's Systran conversion declares MIT; the
original OpenAI model card declares Apache 2.0 and its implementation is MIT.
The pinned revisions, source document URLs and hashes are recorded in
`backend/config/ac_commercial_models.json`. Downloads and MLX model selection
reject unlisted repositories; changing a runtime revision requires a matching
review record. Arbitrary local model folders and sidecar installs are disabled.

This records published model licence grants, including commercial model use.
It is not clearance of uploaded recordings, a person's voice, or every possible
output. Preserve applicable licence, copyright and NOTICE files when
redistributing weights. The VoiceStudio app remains AGPL-3.0; the app's licence
and the model licences are separate.

Local Argos translation packages are MIT/CC0, as the publisher explicitly
confirmed for the model binaries in
<https://github.com/argosopentech/argos-translate/issues/533>. The initial AC
installation prepares English↔German. Additional language packs are on demand.

Unreviewed automatic source-separation, speaker-diarization, neural watermark
and language-specific alignment weights are disabled. Dubbing replaces the
speech track without separating/preserving original background music, and uses
native Whisper timestamps. It does not alter an actor's mouth movements.

## Resource admission

There is one shared OS render lease. Active legacy audiobook narration is
detected before a new studio job starts. Full backend tasks and streaming
generation hold the lease; a disconnected client cannot release it while native
GPU work is still running. Finished TTS models are unloaded before release.

The AC service sets one GPU worker, one resident TTS engine, no model preloads,
a 30-second idle timeout, a 6 GiB MLX allocation ceiling and a 256 MiB MLX cache.
New work requires 6 GiB of available host memory. These bounds reduce contention;
other applications can still change system memory availability during a job.
The shared Audio Studio RAM display refreshes every five seconds. `/ac/status`
reports exact available bytes, the required minimum and `memory_ready` using the
same threshold as admission, so a rounded display cannot falsely admit a job.

## Validation

`python -m unittest discover -s tests -p test_ac_audio_studio.py -v` checks model
allowlisting, normal-app compatibility, active-audiobook admission, cross-process
locking and low-memory refusal without downloading or generating audio.
Run the existing Electron type checks and web build after UI changes. Validate
real cloning, design and dubbed-video output separately on the intended host.

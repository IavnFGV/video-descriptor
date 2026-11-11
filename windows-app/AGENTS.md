# Windows application and runtime

Scope: native launcher/backend, workers, component management and packaging in
this directory. Root constraints and [host safety](../docs/development/safety.md)
apply. For UI also read [ui/AGENTS.md](ui/AGENTS.md).

`Start-App.ps1`/`desktop.py`/`DesktopHost.cs` launch the WinForms/WebView2 host;
`app.py` configures the local server and shared `video_descriptor` API.
`compute.py` plans speech devices; `component_manager.py`, `setup_service.py` and
`diarization_setup.py` manage setup. `storage_service.py` owns recording storage.
Do not create a second settings, job, editor or installation lifecycle.

- Keep source-development launch separate from embedded-Python installed releases.
  Use [development guide](../docs/development/README.md), not dated prototype claims
  in the older README as a current acceptance matrix.
- Check model/backend health before readiness; retain explicit-device errors,
  per-model capabilities, cached diarization proof and job/preparation locks.
- Keep the benchmark venv and live external workers intact. A new worker must not
  take over an occupied port or silently point existing jobs to another model.
- Keep instance/installation/workspace checks and safe refusal to stop active work.
  Models, runtime state and local configuration are not source assets.
- Packaging uses pinned release inputs/wheels, public gates and installer lifecycle
  checks. Domestic/cached packages are private. Never edit BUILD/version files or
  run release preparation unless the task authorizes a release.

See [release guide](../docs/development/releases.md) and
[device policy](../docs/device-policy-and-release.md). Use focused Windows tests;
clean-machine installer acceptance and real NPU/GPU checks establish different facts.

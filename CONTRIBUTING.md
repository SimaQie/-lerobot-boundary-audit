# Contributing

Install `.[repair,dev]`, run `python -m pytest -q` and `python -m ruff check src tests examples`.
Keep the default installation free of Torch and network services. Optional official
checks use a separate environment and never modify installed upstream code.

Useful contributions are small reproducible loader failures with independently known
expected frames. Include tool, LeRobot, decoder, Torch, FFmpeg and OS versions; a command;
expected versus actual frame IDs; and whether the defect was naturally observed or
deliberately injected. Attach a minimal synthetic reproducer when possible. Do not upload
restricted robot datasets. Preserve source files and generate every repair into a new copy.

Unsupported layouts and missing runtimes must remain explicit incomplete results.
An ordinal timestamp match is not proof of semantic frame identity or physical synchronization.

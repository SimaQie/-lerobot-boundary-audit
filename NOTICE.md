# Attribution and scope

This implementation was rebuilt in a separate directory from the diagnostic
ideas in the user's saved robot data engineering materials. The original saved
directory is not part of this distribution and was not edited.

The MIT license covers this project's new code and documentation. External
libraries and datasets retain their own licenses. In particular, the AgiBotWorld2026
public sample used for local validation declares **CC BY-NC-SA 4.0**; it is not
covered by this project's MIT license and is not included in the source package.

- Public re-export: https://huggingface.co/datasets/Voxel51/AgiBotWorld2026-sample-10ep
- Upstream data: https://huggingface.co/datasets/agibot-world/AgiBotWorld2026
- Official reader: https://github.com/huggingface/lerobot
- Second real sample: https://huggingface.co/datasets/lerobot/aloha_static_screw_driver
- Original ALOHA research: https://tonyzhaozh.github.io/aloha/
- FFmpeg duration model reference: https://ffmpeg.org/doxygen/8.1/movenc_8c_source.html

The optional consumer checks call the separately installed official LeRobot
decoder functions or complete dataset loader. The fixture generator calls its
recording and merging APIs. Upstream source is not copied or patched. The bundled
tiny marker videos and scalar actions are original synthetic test data under MIT;
they contain no downloaded robot footage. No models, Torch, FFmpeg binaries,
downloaded videos/actions, or derivatives of external robot datasets are bundled.
The ALOHA sample's dataset card declares MIT; its actual videos and actions are
also excluded. Reports distinguish the original RSS 2023 research from the pinned
LeRobot v3 re-export and retain its source revision and download fingerprints.

# Independent pixel identity experiment

The 0.3.0 suite supplies camera (8 bits), original episode (12 bits), and frame
(12 bits) inside each image, plus a synchronization byte and CRC-16. Cell averages
decode these IDs after lossy H.264 compression. The oracle is specified before
encoding; MP4 PTS and the consumer's selected frame do not define expected IDs.

The installed LeRobot 0.6.1 producer records two datasets with episode lengths
[7, 9, 5] and [8, 6]. Its official merge concatenates the videos and tables into
five episodes (35 rows). Original marker episode IDs [0, 1, 2, 100, 101] persist
while table episode IDs become [0, 1, 2, 3, 4]. This independently checks renumbering.

Two deliberate negative controls are produced from the merged data: shift only
the left camera's episode 1 metadata by 1/30 s, and exchange left/right video
payloads while leaving timestamps valid. The existing guarded repair corrects
the offset copy, and exact restoration is checked against every source file hash.
The camera-swap input passes storage timing checks but fails pixel identity checks.

Each case is checked with PyAV and TorchCodec in separate processes, against all
rows (or odd original episode IDs for subset mode). Temporal phases use −1/0/+1
frame requests, independently clamp within episode ranges, and verify camera and
action padding masks. Batch size is four; worker mode spawns two processes and
does not first open a decoder in the main process.

Reproduction commands are in README.md. Published evidence is under results/v030;
summary.json links to the full per-check reports. A suite PASS means deliberate
faults were detected and clean cases passed, not that every input is valid. Runtime
failures without wrong pixel IDs cannot satisfy a negative control.

The tested configuration is Windows, Python 3.12.14, LeRobot 0.6.1, PyAV 15.1.0,
TorchCodec 0.10.0, Torch 2.10.0 CPU and FFmpeg 8.1 shared. This is one version and
one synthetic H.264 configuration, not a broad version/codec benchmark. No naturally
occurring recording/merge defect was observed here. Markers cannot certify arbitrary
robot footage or physical camera/action synchronization. Larger real failure corpora
and version matrices should precede population-level or novelty claims.

# Typical-random receipts

Median CPU time of 1,000 fresh uniform draws from the paper's encodings,
one evaluation per draw, seed 20260719, measured 2026-07-19 on the
reference machine (Ryzen 5 8600G) pinned to CPU 1 UNDER THE CAMPAIGN'S
FOUR-CORE LOAD REGIME (sha256sum fillers on CPUs 2-4, replicating
keep_four_core_load.py; cpu-frequency.csv logs ~4.82 GHz mean on the
measurement core). Because the multi-hour campaign ran hotter (~4.6 GHz
observed during the campaign), paper ratios are rounded DOWN to survive a ~5-10% clock
penalty: SAT 1151x -> "roughly 1,000x"; NPFS 8x4 269x -> "over 250x";
NPFS 10x5 1849x -> "over 1,700x".

- sat-typical-kcnf.json    median 0.0104 s (champion 11.976 s)
- npfs-typical-8x4.json    median 0.0269 s (champion 7.235 s)
- npfs-typical-10x5.json   median 0.129 s  (champion 238.637 s;
                           also confirms the Stage-0 calibration window)

Reproduce: run_under_load.sh (drives typical_random.py sat|npfs8|npfs10).

# rebench sweep — SAT (k=10, reps=5)

946 instances re-solved across 95 cells, 19 optimizers.

## Optimizer ranking (by CLEAN local top-K median; best cell per opt)

| # | optimizer | local top-k med | local max | chimera max | spike× | cell |
|---|---|---|---|---|---|---|
| 1 | MultiScaleCMA | 12.596s | 12.793s | 16.441s | 1.3 | log_gt1s2L_sat_kcnf_neg/it1 |
| 2 | TripleCMA | 11.406s | 11.995s | 15.278s | 1.3 | log_gt1s2L_sat_mpfx_log/it2 |
| 3 | MultiCMA | 5.128s | 5.510s | 7.260s | 1.3 | log_gt1s2L_sat_mpfx_log/it4 |
| 4 | PSO | 3.230s | 3.239s | 4.283s | 1.3 | log_gt1s2L_sat_mpfx_log/it4 |
| 5 | MetaModelPSO | 3.214s | 3.219s | 5.394s | 1.7 | log_gt1s2L_sat_mpfx_pow2/it0 |
| 6 | SQORealSpacePSO | 3.056s | 3.062s | 5.421s | 1.8 | log_gt1s2L_sat_mpfx_log/it1 |
| 7 | ChainPSOwithMetaRecentering | 2.283s | 2.286s | 3.075s | 1.3 | log_gt1s2L_sat_mpfx_log/it2 |
| 8 | LQOTPDE | 1.345s | 1.351s | 1.707s | 1.3 | log_gt1s2L_sat_mpfx_log/it4 |
| 9 | RecMixES | 1.016s | 1.843s | 2.996s | 1.6 | log_gt1s2L_sat_mpfx_log/it3 |
| 10 | NgIohTuned | 920.1ms | 924.5ms | 1.442s | 1.6 | log_gt1s2L_sat_mpfx_log/it4 |
| 11 | QOTPDE | 883.5ms | 888.5ms | 1.426s | 1.6 | log_gt1s2L_sat_mpfx_log/it1 |
| 12 | MixES | 872.1ms | 1.001s | 1.346s | 1.3 | log_gt1s2L_sat_mpfx_pow2/it4 |
| 13 | BFGSCMA | 671.7ms | 742.8ms | 1.158s | 1.6 | log_gt1s2L_sat_mpfx_log/it1 |
| 14 | NonNSGAIIES | 638.7ms | 792.7ms | 1.068s | 1.3 | log_gt1s2L_sat_mpfx_log/it2 |
| 15 | AnisotropicAdaptiveDiscreteOnePlusOne | 576.8ms | 580.9ms | 0.000s | 0.0 | log_gt1s2L_sat_mpfx_pow2/it1 |
| 16 | ASCMADEthird | 512.2ms | 755.1ms | 0.947s | 1.3 | log_gt1s2L_sat_mpfx_pow2/it2 |
| 17 | LHSSearch | 449.1ms | 648.7ms | 0.797s | 1.2 | log_gt1s2L_sat_mpfx_log/it3 |
| 18 | HullCenterHullAvgScrHammersleySearchPlusMiddlePoint | 349.0ms | 456.2ms | 0.558s | 1.2 | log_gt1s2L_sat_mpfx_log/it2 |
| 19 | NaiveTBPSA | 69.7ms | 71.9ms | 0.000s | 0.0 | log_gt1s2L_sat_kcnf_neg/it0 |

_Cells flagged as contention spikes (chimera/local > 3.0×): 6 of 95._
_Trust `local top-k med`; a high chimera value with a big spike× is fake._
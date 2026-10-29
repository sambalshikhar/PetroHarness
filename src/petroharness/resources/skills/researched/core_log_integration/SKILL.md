---
name: core_log_integration
when: Questions that compare log-derived and core properties, ask what a core-calibrated curve means or how well it agrees with core, involve depth matching, scale or core-condition differences, or must be answered with no core at all.
areas: [core_log_integration]
---

# core_log_integration

## Consider
- Which core data exist (PHIC, GDEN, KH_CORE, KV_CORE, SWC, SOC), over which depths and zones, and how many points in each zone?
- Are core and log depths matched? What shift was applied, and was it checked for each cored section (core gamma vs GR, PHIC vs log porosity)?
- Which log porosity matches how the core was cleaned and dried: total (PHIT) or effective (PHIE)?
- Were core values measured at low (ambient) stress or reservoir stress? Is permeability gas permeability or corrected for gas slippage (Klinkenberg)?
- Are PHIE_CC and PERM_CC transforms fitted to core and applied to logs? Over what porosity range and which rock types was the fit made?
- Do log and core see the same rock: a plug from a thin streak, vugs, fractures, BAD_HOLE depths?

## Compare
- core_vs_log   (core plug statistics against the logs at the core depths, in each zone with core)
- lag_correlation PHIC, PHIT   (core against log porosity: the Pearson correlation at zero lag and at its peak, with the depth shift)
- compare PHIT PHIC   (log total against core porosity where both have values: the two averages, the difference and its spread)
- compare PHIE PHIC   (log effective against core porosity where both have values: the two averages, the difference and its spread)
- compare PERM KH_CORE   (log against core horizontal permeability where both have values: the averages and the rank correlation)
- compare PHIE PHIE_CC   (effective porosity against the core-calibrated curve: the two averages, the difference and its spread)
- compare PHIT PHIE_CC   (total porosity against the core-calibrated curve: the two averages, the difference and its spread)
- compare PERM PERM_CC   (log permeability against the core-calibrated curve: the averages, the difference and the rank correlation)
- step core_correction   (how the core-calibrated curves were fitted)
- step porosity   (the porosity method with its matrix and fluid parameters)

## Decide
- Depth-match first: shift core to log by correlating core gamma or PHIC against GR or log porosity (lag correlation). Shifts can differ between cored sections, and a weak correlation means an uncertain shift.
- Match scales: compare logs with core averaged over a window near tool resolution (roughly 0.3-1 m), or compare zone statistics. Plug-to-sample comparisons mix scale noise with real disagreement. Closest here: core_vs_log, zone by zone.
- Pair like with like: core porosity on oven-dried plugs is close to log total porosity (PHIT); humidity drying keeps part of the clay-bound water, moving it toward PHIE. Compare GDEN with the matrix density used for PHID (sensitivity: see porosity).
- Measure agreement on matched pairs: bias (mean of log minus core), scatter (SD of differences) and n. For permeability use log10 differences and give scatter as a factor (10 to the SD).
- A bias matters most where it moves samples across a cutoff; one that is small against the scatter and against the margin to cutoffs matters less.
- To calibrate porosity, prefer fixing model inputs (matrix density from GDEN, shale and fluid parameters) over a bare regression. For permeability, fit log10 k on porosity per rock type when data allow; check residuals by zone.
- Apply a calibration only within the porosity range and rock types of the core. Flag extrapolation beyond the core range or into uncored zones of other lithology.
- Before fitting, remove plugs that are fractured, broken, or at BAD_HOLE depths; consider stress and Klinkenberg corrections.
- Answer shape: relate (direction, strength, where it holds and where it breaks). The bias and scatter of log against core at the core depths, per zone, with n, and the depths where they disagree beyond the scatter.

## Know
- Core plugs are 2.5-3.8 cm across and usually taken about 0.3 m apart. Logs average roughly 0.3-0.6 m of rock vertically (more for sonic and deep resistivity), so plugs vary more than logs over the same interval.
- Core depth comes from the drill pipe and log depth from the logging cable; they can differ by a metre or more, and the size varies. Core loss makes the position of recovered core uncertain.
- At reservoir stress, porosity of consolidated rock usually falls only slightly, while permeability can fall much more, up to about an order of magnitude in low-permeability sandstones.
- Gas (air) permeability exceeds liquid permeability because of gas slippage (Klinkenberg effect); the gap grows as permeability falls.
- Core water saturation is altered by mud-filtrate invasion, flushing and gas expansion during recovery. Oil-based-mud cores best preserve irreducible water; SOC is usually below the in-situ oil saturation.
- A fit of log10 k on porosity predicts the median k at each porosity. Its predictions vary less than core does (smoothing), and back-transformed means are biased low.
- Vertical plugs (KV_CORE) often avoid shale laminae and fractures, so plug kv/kh may not represent the interval; whole core samples larger features.
- Porosity-permeability transforms differ by rock type. One transform across mixed rock types gives wide scatter and biased predictions in each type.

## Easily misread
- PHIE_CC and PERM_CC are log curves passed through a core-fitted relation. They are not core data and carry the log errors plus the fit scatter.
- A high correlation between log and core can coexist with a large bias. Assess agreement by bias and scatter, not by r alone.
- Good overall agreement can hide opposite biases in different zones. Check each zone.
- Comparing core and log without a depth shift turns a good match into apparent scatter, most of all in thin-bedded rock.
- Comparing core total porosity with log effective porosity, or the reverse, creates a false bias in shaly rock.
- Few core points in a zone give an uncertain fit, and separate transforms per zone may then overfit.

## Do not state
- That a log-derived or core-calibrated value is a measured core value; only the core curves (PHIC, GDEN, KH_CORE, KV_CORE, SWC, SOC) are measurements.
- That a calibration holds in uncored zones of other lithology or beyond the core range; core or test data there would establish it.
- In-situ saturation from SWC or SOC alone; invasion and recovery effects must be assessed, ideally with oil-based-mud core or log saturations.
- Without core, that log porosity or permeability is calibrated or accurate; sidewall cores, formation-tester mobility, NMR or tests would establish it.

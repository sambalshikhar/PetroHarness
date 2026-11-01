---
name: permeability_rock_quality
when: Questions about permeability values, ranking or comparing rock quality between or within zones, flow units, pore-throat or rock-fabric classes, controls on permeability, baffles and barriers, or vertical versus horizontal permeability.
areas: [permeability_rock_quality]
---

# permeability_rock_quality

## Consider
- How was PERM computed (read the recorded method) and from which inputs (PHIE, SW, VCL)? Is PERM_CC, KH_CORE or KV_CORE present to check it?
- If PERM comes from porosity alone, do RQI, FZI or class labels add any information beyond porosity?
- Is SW at irreducible saturation here (no water leg or transition zone)? Timur, Coates and Wyllie-Rose need it; with transition-zone or water-leg SW they give falsely low k.
- Does permeability span orders of magnitude? Then summarize it in log space (median, geometric mean, percentiles), not with the plain mean alone.
- Do zones differ more than samples vary inside each zone? Where along depth does FZI or RQI change, and is each change thicker than tool resolution?
- Which controls are visible: VCL, mineral volumes (VQUAR, VCALC, VDOLO, VANHY), PHI_SEC, cemented streaks (low PHIE, high RHOB, high resistivity)?

## Compare
- profile PERM   (permeability zone by zone from the top, the zones ranked by each statistic, and the direction with depth)
- stats FZI, RQI, PHIE, PERM, KH   (FZI, RQI, porosity, permeability and permeability-thickness: n of N and the statistics in each zone)
- lithology_stats PERM, PHIE, FZI   (permeability, porosity and FZI per rock type of the zones)
- crossplot PERM PHIE log_y   (a least-squares line of log10 permeability on porosity in each zone: slope, intercept, R2 and n)
- crossplot RQI PHI_Z log_y log_x   (a least-squares line of log RQI on log normalized porosity in each zone: slope, intercept, R2, n)
- runs SEALFLAG   (the depth runs where the workflow's seal flag is set, top to base: thickness and share of each zone)
- zone_contrast PERM   (the zones split in halves by average permeability: thickness-weighted shale volume, porosity, lithology mix)
- overlap A B   (where two classes or conditions hold together and apart: thickness by zone and the runs)
- section permeability.permeability_distribution_analysis   (the workflow's permeability classes)
- section permeability.flow_unit_classification_system   (the workflow's FZI classes)
- section permeability.permeability_variation_controls   (the workflow's shale-content classes for permeability)
- section permeability.overall_permeability_interpretation   (the workflow's reservoir classes mapped from its permeability classes)

## Decide
- Choose or assess a transform. Usual order: a core-fitted porosity-permeability transform per rock type; else Timur, Coates or Wyllie-Rose (porosity plus irreducible water), tuned to local core if any.
- Rank zones by median or geometric mean, by arithmetic mean, and by permeability-thickness (kh = sum of k x thickness). They can disagree.
- Flow units (Ebanks 1987: intervals with consistent flow properties, predictably different from those above and below; Amaefule et al. 1993: hydraulic units by FZI): on logs a flow unit is a depth interval. Start from the workflow's own FZI classes zone by zone, then check them with the FZI distribution: histogram modes, straight segments on a normal-probability plot, or parallel unit-slope trends on log RQI vs log PHI_Z. Closest here: crossplot RQI PHI_Z log_y log_x, and stats FZI with percentiles for its distribution.
- Alternatives give different units: data-driven clusters, fixed FZI bands (global hydraulic elements, each bound double the last), Winland R35 classes, or Lucia classes in carbonates. Report an alternative beside the workflow's classes and say where they differ.
- Use the fewest units that explain the spread. A unit thinner than the tool resolution cannot be separated on logs, and a unit resting on a few samples is weak.
- Report the flow units as depth intervals, each with its class and its PHIE, PERM and FZI. Intervals sharing a class are units of that class, or one unit spanning them. Where their FZI or PERM ranges overlap strongly, the boundary between them is weak: that lowers the grade of the split, not the intervals or their classes. Two FZI modes in one interval suggest two units.
- Baffles and barriers show on logs as thin layers with low PHIE, high VCL, SEALFLAG, or cement or anhydrite signs. Their depth and thickness can be read; their lateral extent cannot, from one well.
- kv/kh (vertical over horizontal permeability) comes from paired KV_CORE and KH_CORE plugs, per zone; without them any ratio is an assumption. Shale layers lower effective kv.
- Answer shape: classify (units with their classes), or relate (direction, strength, where it holds and where it breaks). Each zone with its class or value on each curve the record holds, the core-calibrated one named; for a relation, the zones that follow it and those that break it.

## Know
- Timur (1968), sandstones: k = 0.136 phi^4.4 / Swi^2, with k in mD and phi, Swi (irreducible water saturation) in percent. In fractions this is about k = 8581 phi^4.4 / Swi^2.
- Wyllie-Rose form k^0.5 = C phi^3 / Swi, with Morris-Biggs C about 250 (medium-gravity oil) or 79 (dry gas); Coates-Denoo k^0.5 = C phi^2 (1 - Swi) / Swi, original C 70 or 100. Fractions, k in mD; local C fits better.
- Sensitivity: with k proportional to phi^4.4 / Swi^2, a 10% relative error in porosity changes k by about 50%, and a 10% error in Swi by about 20%. Uncalibrated estimates are often off by a factor of several or more.
- RQI (reservoir quality index, micrometres) = 0.0314 x sqrt(k / phi_e), k in mD, phi_e fraction. PHI_Z = phi_e / (1 - phi_e). FZI (flow zone indicator) = RQI / PHI_Z. Samples with one FZI share pore geometry (Amaefule et al. 1993).
- Winland equation (published by Kolodzie 1980): log R35 = 0.732 + 0.588 log k - 0.864 log phi (k in mD, phi in percent, R35 in micrometres). R35 is the pore-throat radius at 35% mercury saturation.
- Port-size classes by R35 (Martin et al. 1997 and later papers): megaport above 10, macroport 2-10, mesoport 0.5-2, microport below 0.5 micrometres; some papers add nanoport below 0.1. Bounds vary slightly between papers.
- Lucia carbonate classes by particle or crystal size: class 1 above 100 micrometres (grainstones), class 2 from 20 to 100, class 3 below 20 (mud-dominated). At equal interparticle porosity, permeability falls by orders of magnitude from class 1 to class 3.
- Controls: k rises roughly with grain size squared and with better sorting; it falls with clay, cement and compaction. Pore-lining or pore-bridging clay can cut k by orders of magnitude with little porosity loss. Pore-throat size, not pore volume, controls k.
- Within one rock type, log k against porosity is often near-linear; across rock types, k can differ by orders of magnitude at the same porosity. Permeability is roughly log-normal (see statistics_data_analysis).
- Averages for flow: along layers (parallel), the thickness-weighted arithmetic mean gives effective kh; across layers (series), the harmonic mean gives kv; random heterogeneity tends toward the geometric mean.

## Easily misread
- A log PERM is a model output, not a measurement. Where it is computed from porosity alone, its ranking of zones repeats the porosity ranking; read the recorded method.
- If PERM comes from one porosity transform, log-derived FZI, RQI and R35 are functions of porosity only. Their units then restate porosity differences: say so as a limit of the units, and still give them.
- The arithmetic mean of permeability is dominated by a few high values; one thin high-k streak can set it. Check the median and how kh is spread over depth.
- Separate vugs raise PHIT without raising k, so a transform on PHIT in vuggy carbonates overestimates k; separate vuggy porosity first (PHI_SEC is an index). Touching vugs or fractures can make k far higher than any transform predicts.
- Class labels from analyzers (for example flow_unit_classification_system) use fixed thresholds. A class change at a threshold is a convention, not a geological boundary; read the thresholds and name the convention with the classes.
- Thin beds, bad hole and shoulder effects distort PHIE and so PERM. A one-sample spike in PERM may be an artifact.

## Do not state
- Permeability as fact, or flow rate and productivity, from logs alone; core, formation-tester mobility, calibrated NMR, a well test (kh from pressure transients) or production data would establish them.
- That a layer is a lateral or field-wide barrier or baffle; pressure profiles across it, interference tests or production history would establish that.
- A measured kv/kh without KV_CORE or a vertical interference test; logs do not measure vertical permeability.
- A pore-throat radius, R35 class or Lucia class as measured; mercury capillary pressure or thin sections measure them, logs only estimate them.

---
name: porosity
when: Questions on how porous a zone or interval is, which porosity curve to trust, why porosity logs disagree, shale or gas effects, secondary porosity, bad hole, or how log porosity compares with core.
areas: [porosity]
---

# porosity

## Consider
- Which porosity does the question mean: total (PHIT), effective (PHIE), one log (PHID, PHIN, PHIS), core-calibrated (PHIE_CC) or core plugs (PHIC)? Each measures something different.
- How was each curve made (matrix density, fluid density, sonic transform, shale point)? Does the matrix fit each zone's minerals (VQUAR, VCALC, VDOLO, VANHY, PEF, GDEN)?
- Is the hole good where you read? Check BAD_HOLE, CALI minus bit size, and DRHO, and decide whether to drop flagged samples before you average.
- In each zone, do PHID and PHIN overlay, does neutron read above density (shale or dolomite-like), or density above neutron (gas, or a matrix mismatch)? How much VCL is there, and how far apart are PHIT and PHIE?
- Is core present (PHIC, GDEN)? How many plugs, over which depths, and are they depth-matched to the logs?
- Between zones, compare the same curve, statistic and filtered samples. Within a zone, look at the spread and depth trend before calling a difference real.

## Compare
- stats PHIT, PHIE, PHIE_CC, BAD_HOLE   (total, effective and core-calibrated porosity and the bad-hole share: n of N and the statistics in each zone)
- stats PHID, PHIN, PHIS, PHIT, PEF   (each tool's porosity beside total porosity and PEF: n of N and the statistics in each zone)
- stats CURVES where CONDITION   (a porosity's statistics over only the samples where a condition holds: a class, a flag, BAD_HOLE < 0.5)
- compare PHID PHIN   (density against neutron porosity in each zone: the two averages, the difference, its spread and the shares)
- crossplot RHOB NPHI   (a least-squares line of density on neutron in each zone: slope, intercept, R2 and n)
- stats DS_SEPARATION, PHI_SEC   (density-sonic separation and the secondary porosity index: n of N and the statistics in each zone)
- core_vs_log   (core plug porosity against the log porosities at the core depths, in each zone with core)
- step porosity   (the porosity method with its matrix and fluid parameters)
- section porosity.total_porosity_quality_distribution   (the workflow's porosity classes)
- section porosity.pore_system_architecture_classification   (the workflow's pore-system classes from density-sonic separation)
- section porosity.porosity_quality_assessment_characteristics   (the workflow's flow-unit classes from porosity and permeability cutoffs)
- section porosity.integrated_porosity_reservoir_assessment   (the workflow's reservoir classes from its porosity and flow-unit classes)

## Decide
- Log effective porosity is total porosity minus clay-bound water. Core porosity on oven-dried plugs is close to log total porosity (PHIT); humidity drying keeps part of the clay-bound water. Compare like with like (see core_log_integration).
- In clean, liquid-filled rock on the right matrix, PHID and PHIN agree within a few porosity units (p.u., percent of rock volume). Lasting separation points to wrong matrix, shale, gas or bad hole; test each.
- Density-neutron combinations: arithmetic mean for liquid-filled rock, root-mean-square sqrt((PHID² + PHIN²)/2) in gas, or a chart or crossplot solution. They differ most in gas and shale.
- Shale corrections: subtract VCL times the shale's apparent porosity from each log, or PHIE = PHIT − VCL × (total porosity of shale). Results depend on the VCL method and the shale point.
- Sonic transforms: Wyllie time-average (needs a compaction correction in uncompacted rock) or Raymer-Hunt-Gardner. They can differ by several p.u. Check which one made PHIS.
- Read PHI_SEC (PHIT − PHIS) as a sign of vugs or fractures only where matrix, hole, shale and gas are under control and the gap exceeds the sonic method's error. Look for support from other data.
- Answer shape: quantify (values on each standard reading). Each zone's porosity on each porosity curve the record holds, saying which is core-calibrated; where the curves disagree, each with what separates them, graded.

## Know
- Density porosity: PHID = (ρma − RHOB)/(ρma − ρf). Matrix (grain) density ρma: quartz 2.65, calcite 2.71, dolomite 2.87 g/cc (more in lithology_mineralogy). Fluid density ρf about 1.0 (fresh filtrate) to 1.1 (salty).
- A 0.05 g/cc error in matrix density moves PHID by about 2-3 p.u. (from the equation). Core grain density (GDEN) or mineral volumes check the matrix.
- The neutron log responds to hydrogen. It is often scaled in limestone units: clean sandstone then reads low and dolomite high. PHIN is corrected to a matrix; check which. Clay-bound water raises neutron porosity.
- Gas lowers RHOB (PHID reads high) and the hydrogen index (PHIN reads low, plus an 'excavation effect'), so PHID reads above PHIN (crossover). True porosity usually lies between the two.
- Wyllie: PHIS = (DTC − DTma)/(DTf − DTma). Matrix DTma (µs/ft): sandstone 51-55.5, limestone 43.5-47.6, dolomite 38.5-43.5; fluid DTf about 185-189. In uncompacted rock divide by Bcp ≈ shale DTC/100 when shale DTC > 100.
- Raymer-Hunt-Gardner: 1/DTC = (1 − φ)²/DTma + φ/DTf. A common field form is φ ≈ C × (DTC − DTma)/DTC, with C usually 0.625 (5/8); some charts use up to about 0.7.
- Hydrocarbons raise sonic porosity. Hilchie's empirical corrections multiply Wyllie porosity by about 0.7 in gas and 0.9 in oil.
- Sonic responds mainly to intergranular porosity; vugs, fractures and rounded (moldic) pores affect it less. Density and neutron respond to all pore space, connected or not.
- Density and neutron logs resolve roughly 0.3-0.6 m vertically; a core plug is a few centimetres across. In laminated rock, plug values scatter widely around the log curve.

## Easily misread
- Density above neutron is not proof of gas: sandstone computed on a limestone matrix, halite, coal and washouts also produce it. Check matrix, caliper, DRHO and PEF first.
- Neutron above density is not proof of shale: dolomite on a limestone scale and hydrous minerals such as gypsum also produce it. Check VCL, GR, PEF and mineral volumes.
- PHI_SEC above zero can come from PHIS errors (wrong DTma or transform, uncompacted rock, gas, shale, cycle skipping) rather than vugs or fractures.
- Washouts make RHOB read low and PHID high, so zone means that include BAD_HOLE samples can overstate density porosity. Recompute without them to check; bad-hole limits are in data_quality.
- GDEN is grain density, not porosity. A gap between GDEN and the matrix density assumed for PHID biases PHID in that zone.
- PHIE_CC is a log curve fitted to core: its agreement with PHIC is partly by construction, not independent validation, and it holds only within the plugs' rock types and porosity range.

## Do not state
- Logs alone cannot establish pore type (vugs, molds, fractures) with confidence; core description, thin sections, image logs or nuclear magnetic resonance (NMR) logs would.
- Porosity logs alone do not show that pores are connected or will flow; core permeability, pressure tests or production would.
- A porosity as exact where it rests on an unconfirmed matrix or fluid density; core grain density (GDEN) or mineral data would confirm the matrix.
- Do not blame a core-log difference on the tool before checking depth match, stress correction, drying method and sampling; the core report and depth-shift record would settle it.

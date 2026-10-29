---
name: lithology_mineralogy
when: Working out what rock or minerals a zone holds from log responses, crossplots or mineral-solver output, checking a lithology label against the logs, and telling clastics, carbonates, evaporites, coal and heavy minerals apart.
areas: [lithology_mineralogy]
---

# lithology_mineralogy

## Consider
- What label does each zone carry, where does it come from (cuttings, core, a log model), and do the zone's RHOB, PHIN or NPHI, PEF, DTC and GR medians fit it?
- Is PEF usable here (no barite mud, good hole)? Is the neutron in limestone units (NPHI) or corrected to the zone's matrix (PHIN)?
- On neutron-density, PEF-density, M-N or apparent-matrix plots, does the zone sit near one mineral point, between two, or off all lines?
- How much shale (VCL) and gas indication does the zone hold? Both displace points on every porosity crossplot.
- Which minerals did the solver include (VQUAR, VCALC, VDOLO, VANHY, clay)? A mineral left out of the model is forced into the others.
- Between zones, do medians of RHOB, PHIN, PEF, DTC and GR differ by more than tool noise and within-zone spread? Within a zone, do responses cluster, split into groups, or spread along a mixing line?

## Compare
- stats GR, RHOB, NPHI, PEF, DTC   (the main lithology logs: n of N and the statistics in each zone)
- lithology_stats GR, RHOB, NPHI, PEF   (the same logs per rock type of the zones, with each rock type's thickness and share)
- crossplot RHOB NPHI   (a least-squares line of density on neutron in each zone: slope, intercept, R2, n; a fit, not positions)
- crossplot PEF RHOB   (a least-squares line of PEF on density in each zone: slope, intercept, R2, n; a fit, not mineral-point positions)
- compare PHID PHIN   (density against neutron porosity on the step's matrix in each zone: the two averages, the difference, its spread)
- stats VQUAR, VCALC, VDOLO, VANHY   (the mineral volumes in each zone, with n of N: the samples the solver left unsolved count)
- step lithology   (the lithology step's method, inputs and the mineral volumes it solved)
- section lithology.lithology_distribution_classification   (the rock types of the lithology log by thickness and share)
- section lithology.lithology_log_consistency   (the workflow's check of each label against GR and PEF)
- section lithology.carbonate_analysis   (the workflow's PEF and RHOB carbonate check against the labels)
- section lithology.overall_interpretation   (the workflow's reservoir or rock-type label per interval, from its lithology classes)
- section lithology.formation_level_summary   (the workflow's reservoir and seal fractions in each zone)

## Decide
- Neutron-density crossplot with matched units (both limestone-scaled, or PHID and PHIN on one matrix): points on the sandstone, limestone or dolomite line give lithology and porosity; points between lines are mixtures or ambiguous; shale, gas and evaporites plot off the lines.
- Break neutron-density ambiguity with a third measurement: PEF (photoelectric factor), or U = PEF × RHOB, separates quartz, dolomite and calcite well; sonic separates them less well and does not see vuggy porosity.
- Apparent matrix values, with porosity φ from neutron-density: RHOmaa = (RHOB - φ·ρfluid)/(1 - φ); Umaa = (PEF·RHOB - φ·Ufluid)/(1 - φ). Compare RHOmaa with mineral grain densities and with GDEN where present. Closest here: calc on a zone's mean RHOB, porosity and PEF.
- M-N plot: M = 0.01·(Δtfluid - DTC)/(RHOB - ρfluid), N = (φN,fluid - NPHI)/(RHOB - ρfluid), with DTC in us/ft. Porosity largely cancels; mixtures fall between mineral points; vugs raise M because sonic under-reads them. Closest here: calc on a zone's mean DTC, RHOB and NPHI.
- Mineral solver output: treat VQUAR, VCALC, VDOLO, VANHY as one model's estimate. Check the reconstruction error (modelled against measured logs), the number of minerals against the number of independent logs, and how much volumes move when endpoints change. Closest here: step lithology, for what the record states of the solve.
- Checking a label against logs: weigh what supports it (responses near that mineral's values) against what argues against it (responses near another mineral that gas, shale or hole cannot explain). Weigh hole quality and depth resolution before calling a conflict.
- Carbonate against clastic: PEF, apparent matrix density and the neutron-density position discriminate best (values in Know 1-2). GR discriminates poorly, since clean sand and clean carbonate both read low.
- Evaporites, coal and heavy minerals stand out as responses far from the porous-rock lines (very high or very low RHOB, extreme NPHI or PEF) in good hole; confirm with cuttings or core where possible.
- Answer shape: classify (units with their classes). Each zone with its rock type, its thickness and share, and the log responses that support it; where the logs and a label disagree, both, each graded.

## Know
- Grain density (g/cc): quartz 2.65, calcite 2.71, dolomite 2.87, anhydrite 2.98, gypsum 2.35, halite 2.16 (log reads about 2.03), siderite 3.89, pyrite about 5.0, barite 4.48 (log reads about 4.1).
- PEF (barns/electron): quartz 1.81, dolomite 3.14, calcite 5.08, anhydrite 5.05, halite 4.65, gypsum 3.99, siderite 14.7, pyrite 17.0, barite 267, coal about 0.2, water about 0.4. Porosity and fluid change PEF only slightly.
- U (volumetric photoelectric absorption, barns/cc, about PEF × RHOB): quartz 4.8, dolomite 9.0, calcite 13.8, anhydrite 14.9. U mixes linearly by volume; PEF does not, so use U for mixtures.
- Neutron at zero porosity in limestone units (approximate, tool-dependent): quartz about -0.02, calcite 0, dolomite near 0 to slightly positive, anhydrite near 0, halite about -0.03, gypsum very high (0.5 or more); shale and coal read high.
- Shale: GR high relative to clean rock; RHOB about 2.2-2.75 g/cc (rising with compaction); NPHI high from bound water (often about 0.25-0.6); PEF about 2-4; DTC slow, often 70-150 us/ft. Ranges vary widely; calibrate to the well's own shale.
- Evaporites: anhydrite NPHI near 0, PEF about 5, DTC about 50 us/ft; halite NPHI slightly negative, DTC about 67, very high resistivity, often washed out in fresh mud; gypsum high NPHI from crystal water. All read low GR.
- Coal: RHOB about 1.2-1.8 g/cc, high NPHI, PEF about 0.2, slow DTC (often above 100 us/ft), often high resistivity, usually low GR (higher if ashy or uranium-rich).
- Gas moves neutron-density points toward lower NPHI and higher PHID; shale moves them toward higher NPHI; vugs make sonic porosity (PHIS) lower than neutron-density porosity, which PHI_SEC records.
- Mixtures mimic single minerals: quartz plus dolomite can plot on the limestone line of a neutron-density plot, but PEF then reads about 2-3, not 5. Calcite or anhydrite cement in sand raises RHOB and PEF.
- A solver with n independent log equations plus closure (volumes sum to 1) resolves at most n + 1 components; beyond that the result is set by constraints and endpoint choices, not by the data.

## Easily misread
- On a limestone-scaled display a water-bearing quartz sandstone shows PHID above NPHI (apparent crossover); that is matrix, not gas. Use matched-matrix PHID and PHIN or the crossplot lines.
- Dolomite and shale both read NPHI above PHID on a limestone-scaled display and both have PEF near 3; GR, DTC and RHOB level usually separate them.
- Anhydrite and calcite have almost the same PEF (about 5); RHOB (2.98 against 2.71) and NPHI tell them apart.
- Coal reads as very high PHID; check NPHI, PEF and DTC together before treating it as porous rock.
- A lithology log from cuttings is lagged, mixed with cavings and coarse in depth; a mismatch near zone edges may be depth, not rock.
- A PEF jump with no matching change in RHOB, NPHI or GR suggests mud or hole (barite, rugosity), not rock.

## Do not state
- Exact mineral species and amounts (clay species, feldspar, cement type) as measured; logs give bulk and elemental responses, and X-ray diffraction (XRD), thin sections or core analysis establish mineralogy.
- Solver volumes as measured composition; they are estimates tied to the model's mineral set and endpoints, and XRD or thin sections would measure composition.
- Origin (for example replacement dolomite or a diagenetic cement) from logs alone; petrography settles it.
- A unique lithology where two mixtures fit the same logs; a further measurement (PEF, sonic, U) or core would separate them.

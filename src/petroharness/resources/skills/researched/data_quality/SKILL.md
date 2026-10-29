---
name: data_quality
when: Judging whether log readings can be trusted at a depth or in a zone (hole condition, environmental effects, spikes, gaps, sonic quality, depth mismatch, repeat runs) and stating how data problems change an interpretation.
areas: [data_quality]
---

# data_quality

## Consider
- Which curves exist in each zone, and what fraction of each zone's samples is valid (not null, not flagged)? Is the missing or flagged part spread evenly or concentrated in one rock type?
- Where does CALI depart from bit size (BS; or DCAL, if the record defines it as caliper minus bit size), and do those depths match BAD_HOLE, large |DRHO|, or jumps in RHOB, NPHI, PEF and DTC?
- Which curves come from pad or shallow-reading tools (RHOB, PEF, RXO, RMIC) and which from centred or deep-reading ones (NPHI, GR, RDEP)? Pad tools fail first in rough or enlarged hole.
- What mud was used, if known (water-based, oil-based, salty, KCl, barite-weighted)? It decides which logs are usable and how they are biased.
- Do curves from different runs line up at sharp beds? Is there a repeat section, and does it agree with the main pass?
- Which derived curves (PHID, PHIT, PHIE, VCL, SW, PERM, the NET and CROSSOVER flags) inherit a problem from a measured curve?

## Compare
- stats CALI, BS, DRHO   (caliper, bit size and DRHO: n of N and the statistics in each zone and pooled)
- runs BAD_HOLE   (the depth runs where the workflow flags bad hole, top to base: thickness and share of each zone)
- data_record   (each log's share of samples with a value, and its gaps, in each zone)
- spike_flags GR, RHOB, NPHI, DTC   (samples beyond 2 and 3 std of each zone's own average, with depths and z-scores; adjacent-sample jumps)
- adjacent_jumps CURVE threshold=VALUE   (changes between adjacent samples above your threshold, in the curve's units: count, largest, depths)
- stats CURVES where CONDITION   (a curve's statistics over only the samples where a condition holds, such as BAD_HOLE < 0.5)
- lag_correlation GR, RHOB, NPHI, DTC   (each pair's Pearson correlation at zero lag and at its peak, with the apparent depth shift)
- section numerical.log_quality_control_assessment   (the workflow's log-quality classes from bad hole and DRHO)
- section numerical.statistical_data_coverage_analysis   (the workflow's per-sample completeness of the logs)
- section numerical.statistical_deviation_detection   (the workflow's per-sample outlier counts from z-scores)
- section numerical.integrated_numerical_assessment   (the workflow's combined classes from pay, deviations, log quality and consistency)

## Decide
- Screen hole condition with CALI minus bit size and |DRHO|. A service-company glossary treats |DRHO| above about 0.15 g/cc as possibly inaccurate; many workflows flag lower (for example 0.05-0.1). Common washout limits: about 1-2 in, or a fraction of bit size.
- Assess zone statistics by their coverage: compute the valid-sample fraction per curve per zone, then recompute the key statistic without flagged samples to see whether it changes materially.
- Tell artefacts from thin beds: an artefact usually hits one curve, lasts one or two samples and may exceed physical bounds; a real thin bed (coal, cemented streak, pyrite, anhydrite) shows on several independent curves at the same depth.
- Flag outliers per zone with robust measures (median, interquartile range IQR, median absolute deviation MAD), not interval-wide mean and standard deviation; each rock type has its own normal range. Fence conventions are in statistics_data_analysis.
- Screen sonic: DTC slower than the pore fluid (about 189 us/ft, fresh water) or faster than dolomite matrix (about 38.5-43.5 us/ft) is not plausible rock. Sudden high-DTC spikes, often in gas, fractures, weak rock or enlarged hole, suggest cycle skips.
- Depth-match against one reference curve recorded on every run (usually GR): cross-correlate windows of the other run's GR and confirm the shift at sharp tie beds. A shift that changes with depth suggests cable stretch or sticking; apply it piecewise.
- Compare curves at a common resolution: smooth the sharper curve, or compare only beds thicker than the coarser tool resolves. Single-sample features below a tool's resolution are not reliable. Closest here: runs with min_thickness.
- Trace a data problem through: which curves and depths it affects, the direction of bias (for example RHOB too low so PHID too high), which derived curves inherit it, and whether the conclusion survives without those samples.
- Answer shape: locate (depth runs, each graded). The runs each screen flags, per curve and zone, with the screen's rule and threshold; 'not established' is its own graded claim, never in place of the list.

## Know
- CALI above bit size means enlargement (washout or caving), common in shale, weak sand, fractured rock and salt in fresh mud. CALI below bit size often means mudcake on permeable rock, or swelling clay; mudcake thickness ≈ (bit size - CALI)/2.
- The density tool is a pad device reading a few inches into the rock. Where the pad loses contact it reads mud: RHOB too low, PHID too high, |DRHO| large. DRHO (the compensation applied) also tracks rugosity.
- The sign of DRHO depends on mudcake density compared with the rock; heavy barite mudcake can give negative corrections. Barite (PEF about 267 barns/electron) in mud or mudcake inflates PEF and makes it unreliable for lithology.
- NPHI is corrected for hole size, standoff (tool-to-wall gap), mud salinity, temperature and pressure; uncorrected enlargement adds hole fluid and raises NPHI. Thermal neutron readings also respond to neutron absorbers such as chlorine and boron.
- GR is lowered by large holes and heavy mud (more attenuation) and raised by potassium-chloride (KCl) mud, which also raises POTA; service-company charts correct for hole size and mud weight.
- Borehole-compensated sonic reduces but does not remove hole effects. Cycle skips (a missed first arrival) give sharp high-DTC spikes; noise can give low-DTC spikes. Sonic reads close to the wall, which may be altered or invaded.
- Mud limits tools: SP, laterologs and micro-resistivity (RXO, RMIC) need conductive water-based mud; induction degrades in very salty mud and at very high resistivity; PEF degrades in barite mud.
- Vertical resolution, roughly (one tool table; others differ): density and PEF 0.4 m, neutron 0.3-0.6 m, GR 0.45 m, sonic 0.6-1.1 m, deep induction 2 m. Depth of investigation: density about 0.2 m, neutron 0.2-0.5 m, deep induction 1.2-1.5 m.
- LAS files commonly mark nulls as -999.25. Constant values while depth advances (stuck tool), long interpolated stretches, logs above the casing shoe and the bottom metres below the upper sensors are not valid formation data.
- Nuclear tools (GR, RHOB, NPHI, PEF) carry random counting noise that grows at low count rates and fast logging; filtering reduces noise but blurs thin beds.

## Easily misread
- Washout can mimic gas: low RHOB pushes PHID above PHIN and gives false neutron-density crossover. Treat crossover in BAD_HOLE samples as unconfirmed.
- A small |DRHO| does not prove good density: compensation can fail in very rough hole, and a large DRHO in gauge hole may only reflect heavy mudcake.
- A zone average can look normal while its worst part is missing: if washouts sit in the shaliest beds, the valid samples over-represent clean rock.
- Depth mismatch between curves makes false thin anomalies at bed edges (spurious crossover, VCL or SW spikes) where one curve has changed and the other has not.
- Units and scales: NPHI in percent or fraction, neutron in limestone or sandstone units, DT in us/ft or us/m (us/m = 3.281 × us/ft), RHOB in g/cc or kg/m3.
- Curves with similar names (DTC, DT, DTC_ALT) may be different runs or processing; check that they agree before choosing one.

## Do not state
- That a curve is correct because no flag marks it; flags test only what they check. Log headers, run notes, calibrations and repeat sections establish quality.
- A depth more precise than the depth-matching uncertainty; core-to-log shifts and checkshots settle depth.
- The size of an environmental correction the record does not show; it needs hole size, mud weight, salinity and tool-specific charts.
- A spike's cause (cycle skip, stuck tool, thin bed) as fact; waveforms, repeat passes or core decide it.

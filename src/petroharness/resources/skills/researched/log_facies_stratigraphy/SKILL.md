---
name: log_facies_stratigraphy
when: 'Describing log character and vertical organisation: electrofacies, log shapes (cylinder, funnel, bell, serrated), upward trends, bed and zone boundaries, stacking of units, correlation of units within one well, and the limits of reading depositional environment from logs.'
areas: [log_facies_stratigraphy]
---

# log_facies_stratigraphy

## Consider
- For each zone: thickness, base and top contacts (sharp or gradational), internal trend and internal character (smooth or serrated) on GR and on a second curve (RHOB, NPHI, DTC or resistivity).
- Is a trend larger than tool noise and longer than several resolution lengths, or only a few samples?
- Does GR here track clay (check spectral GR, PEF, neutron-density) so that its shape can stand for grain size or depositional energy?
- How do successive units stack: cleaner, dirtier or similar upward?
- Do zone boundaries sit on log breaks, or are they offset (depth mismatch or a coarse lithology log)?

## Compare
- profile GR   (GR zone by zone from the top: the statistics, the zones ranked and the direction with depth in words)
- profile VCL   (shale volume zone by zone from the top, with the direction with depth in words)
- crossplot GR DEPTH   (a least-squares line of GR on depth in each zone: slope per depth unit, R2, n and the direction in words)
- vertical_sequence   (GR zone by zone from base to top: each zone's change from the one below, and the packages of one direction)
- adjacent_jumps CURVE threshold=VALUE   (changes between adjacent samples above your threshold, in the curve's units: count, largest, depths)
- stats GR_GRAD, RHOB_GRAD, RDEP_GRAD, NPHI_GRAD, DTC_GRAD   (the workflow's depth gradients of the key logs: n of N and the statistics in each zone)
- lithology_stats PHIE, PERM, VCL   (porosity, permeability and shale volume per rock type of the zones)
- section lithology.lithology_petrophysics_relationships   (the workflow's reservoir classes within each lithology)
- section numerical.log_gradient_trend_analysis   (the workflow's trend-intensity classes from the key-log gradients)
- section numerical.advanced_parameter_characterization   (the workflow's acoustic, elastic and electrofacies curves)

## Decide
- Describe each unit by base contact, top contact, internal trend and internal character before naming a shape: cylinder (blocky, no trend), funnel (cleaning up), bell (dirtying up), bow (symmetrical), irregular; each smooth or serrated.
- Test a trend: fit GR (or VCL) against depth within the unit and compare the total change with the unit's scatter and tool noise. Call it a trend only where the change clearly exceeds both.
- Contacts: sharp where the change happens within about one tool resolution length, gradational where it spreads over several. Place the boundary at the midpoint (inflection) of the change.
- Electrofacies: group samples with similar responses on several curves (crossplot fields, or clustering such as k-means). Choose and scale curves and drop bad-hole samples first; the number of classes is a choice. Check against core or the lithology log. Closest here: the record's ELECTROFACIES curve, with stats or runs.
- Stacking: units that each clean upward and get cleaner unit after unit point to progradation; units getting dirtier unit after unit point to retrogradation; similar units point to aggradation. These are hypotheses, not unique readings.
- Treat environment as hypotheses: weigh what supports each (shape, contacts, thickness, neighbouring lithologies, coal, glauconite, spectral GR) against what argues against it.
- Correlate within the well by recurring motifs and marker beds (a GR maximum, a coal, an anhydrite). Breaks seen on GR, RHOB and DTC together support a real boundary; a break on one curve may be fluid or hole.
- Answer shape: relate (direction, strength, where it holds and where it breaks). The trend from base to top in words (higher upward or downward), each step's size against the spread within units, and the units where it holds and where it breaks.

## Know
- Electrofacies: the set of log responses that characterizes a bed and distinguishes it from others (after Serra and Abbott 1982). It is a log class, not a lithofacies or an environment.
- GR shapes describe clay-content trends: funnel = GR decreasing upward (cleaning up); bell = GR increasing upward (dirtying up); cylinder or boxcar = low, flat GR with sharp top and base; bow = decrease then increase; irregular = no clear trend.
- Common associations, not rules: cylinders with fluvial-channel, turbidite or aeolian sands and also evaporites; funnels with prograding shorefaces, delta fronts or fan lobes; bells with channel fills or deepening. One shape occurs in several settings.
- GR tracks grain size only where clay content falls as grain size rises. It fails with feldspar, mica, glauconite or heavy minerals, in carbonates, and between clean sands of different grain size.
- Serration reflects thin interbeds or variable composition near tool resolution (GR about 0.45 m, density about 0.4 m). Thinner beds are averaged and undercounted.
- Flooding surfaces often coincide with GR maxima, some from uranium-rich condensed beds; sequence boundaries can appear as abrupt shifts to cleaner rock. Neither is unique on logs.
- Parasequences are small upward-shallowing units bounded by flooding surfaces; in shallow-marine clastics they often show as funnels. Parasequence sets stack as progradational, aggradational or retrogradational.
- In carbonates, log shape often reflects diagenesis (cementation, dolomitisation, dissolution) and clay or uranium content more than depositional energy.
- In a deviated well or dipping beds, logged thickness exceeds true thickness, and trends per metre change accordingly.
- Curves sense different properties: GR radioactivity, RHOB and NPHI porosity and lithology, resistivity also fluids. A motif on GR and porosity logs together is more robust; resistivity shapes may reflect fluid.

## Easily misread
- Depth increases downward: GR falling with increasing depth means GR rising upward (bell, dirtying up). Check the sign before naming a shape.
- A shape spanning a few samples, or one driven by a single spike, is not a trend.
- Fluid contacts and hole effects change resistivity, RHOB and NPHI and can mimic facies boundaries; GR is least affected by fluid.
- Zone boundaries from a lithology log may be offset from log breaks by depth lag or coarse sampling; do not read a facies change where only the label changes.
- Electrofacies count and boundaries change with the curves, scaling and cluster number chosen; they are not unique.
- A cylinder does not mean uniform grain size; clean fine sand over clean coarse sand gives the same flat GR.

## Do not state
- Depositional environment from logs alone; core (grain size, structures, fossils, trace fossils), image logs and regional context establish it.
- Grain size, sorting or sedimentary structures from GR shape alone; core or image logs measure them.
- Unconformities, sequence boundaries or ages from one well's logs; biostratigraphy, regional correlation and seismic establish them.
- Lateral extent or geometry (sheet or channel) from one well; more wells, seismic, or dip and image data are needed.

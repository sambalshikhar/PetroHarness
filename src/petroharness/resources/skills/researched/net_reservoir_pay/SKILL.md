---
name: net_reservoir_pay
when: Questions about gross, net rock, net reservoir, net pay, net-to-gross, cutoffs and their effect, pay thickness and thin beds, how confident pay is, or whether rock is likely to produce.
areas: [net_reservoir_pay]
---

# net_reservoir_pay

## Consider
- Which cutoffs define NET_ROCK, NET_RES and NET_PAY here, and which porosity (PHIE or PHIT) and saturation curves do they test? Were they set for this rock and fluid, or are they generic defaults?
- How many samples sit close to a cutoff? If many do, small cutoff changes move net thickness a lot.
- What is gross here (whole interval, one zone, or the reservoir unit), and is thickness measured depth or true vertical?
- Is SW trustworthy where pay is flagged (RW, shale correction, thin beds, BAD_HOLE)? Is there a fluid contact inside the interval?
- Is pay thick and continuous, or many thin runs near tool resolution?
- What independent evidence exists: core saturations (SWC, SOC), MHI and invasion (see invasion_movability), gas signs (CROSSOVER_FLAG), tests?

## Compare
- pay_summary   (net rock, reservoir and pay thickness and net-to-gross, the cutoffs in order, and the workflow's averages over net pay)
- runs NET_RES   (the depth runs where the net-reservoir flag is set, top to base: thickness and share of each zone)
- runs NET_PAY   (the depth runs where the net-pay flag is set, top to base: thickness and share of each zone)
- runs CONDITION   (the depth runs where a condition holds, such as the cutoffs with one moved by a step, top to base)
- stats PHIE, PERM, VCL, SW, RDEP where NET_PAY   (the reservoir curves over only the net-pay samples: n of N and the statistics)
- stats PERM where NET_RES   (permeability over only the net-reservoir samples: n of N and the statistics)
- crossplot PERM PHIE log_y   (a least-squares line of log10 permeability on porosity in each zone: slope, intercept, R2 and n)
- step net_pay   (the cutoffs and the curve each flag tests)
- overlap A B   (where a flag and another condition hold together and apart, such as NET_RES and NET_PAY: thickness by zone, runs)
- section hydrocarbon.reservoir_quality_for_hydrocarbons   (the workflow's reservoir classes from porosity and permeability thresholds)
- section hydrocarbon.integrated_hydrocarbon_potential   (the workflow's combined pay and target classes)
- section numerical.net_pay_flag_analysis   (the workflow's pay and non-pay classes from the net-pay flag)

## Decide
- Usual sequence: a VCL cutoff gives net rock; adding a porosity cutoff gives net reservoir; adding an SW cutoff gives net pay. A sample counts only if it passes every cutoff.
- Cutoffs are set field by field. Common methods: porosity read off a porosity-permeability crossplot at a permeability cutoff; VCL from a VCL-porosity crossplot; SW from capillary or relative-permeability limits; tested pay/non-pay boundaries.
- Another method sets cutoffs where the cumulative loss of storage (porosity x thickness) or flow capacity (k x thickness) below the cutoff reaches a small share of the total; about 5% is used in some studies. Closest here: stats of KH or PHIE where a cutoff condition holds, set against all samples with calc.
- Permeability, or mobility (permeability over viscosity), is the physical basis; porosity and VCL cutoffs are surrogates for it. Keep cutoffs consistent with each other and with the expected drive (depletion or waterflood).
- Test sensitivity: move each cutoff by a plausible step (for example 0.02 v/v porosity, 0.05 v/v VCL or SW) and see how net changes. A large change means a low-confidence net figure.
- Thin beds: below tool resolution, a fixed cutoff tends to overcount net in sand-rich laminated rock and undercount it in shale-rich laminated rock.
- Pay confidence rests on how many independent signs agree: margin from each cutoff, thickness against resolution, SW quality, invasion or MHI, gas signs, core saturations, pressures or samples, tests.
- Compare zones by net thickness, net-to-gross, mean PHIE and SW over net pay, porosity-thickness and hydrocarbon pore thickness. Rankings can change with the measure.
- Answer shape: quantify (values on each standard reading). Net thickness and net-to-gross for each cutoff set, with the cutoffs named and the runs that pass; for a zone that fails, which cutoffs it fails and by how much.

## Know
- Definitions: gross is the whole unit thickness; net sand or rock passes a shale cutoff; net reservoir also passes a porosity or permeability cutoff; net pay is net reservoir that also passes a saturation cutoff.
- There is no universal definition or cutoff set. Net pay belongs to a stated set of cutoffs and a stated purpose (volumes, flow modelling, completion).
- Cutoffs are set per field from core, tests and sensitivity; published values vary by rock and fluid.
- Critical SW is commonly 0.5-0.7 for light oil and gas reservoirs, and can be as low as 0.25-0.30 for heavy oil; values vary.
- Averages over net pay: porosity thickness-weighted; SW pore-volume-weighted, sum(SW x phi x h) / sum(phi x h). Hydrocarbon pore thickness = sum of phi x (1 - SW) x h.
- Vertical resolution, roughly: GR, density and neutron 0.3-0.6 m; deep induction about 2 m; micro-resistivity a few cm. Beds thinner than this read blended values.
- Laminated sand-shale reads low resistivity and high VCL. SW from blended logs is then too high, so thin-bedded pay is easily missed (low-resistivity, low-contrast pay).
- Producible pay needs mobile hydrocarbon, enough permeability for the fluid, pressure support and a connected volume. Logs address saturation and indirectly permeability; the rest needs other data.
- Thickness from measured depth exceeds true vertical thickness in deviated wells. Net-to-gross within one well changes little where deviation is steady.

## Easily misread
- NET_PAY = 1 marks samples that pass cutoffs. It is not proof of hydrocarbon, and not proof the rock will produce.
- Net-to-gross depends on what gross is. Zone ratios combine as total net thickness over total gross thickness, not as a plain mean of zone ratios.
- A sample count is a thickness only after multiplying by the sample step. Runs shorter than tool resolution are not resolved beds.
- Net reservoir is not net pay: rock below a fluid contact can pass VCL and porosity cutoffs and fail SW. Rock that fails cutoffs is not necessarily water-bearing; it may hold hydrocarbon assessed as non-productive.
- Applying a porosity cutoff to PHIT instead of PHIE, or the reverse, changes net in shaly rock. Check which curve the flag tests.
- In fractured or vuggy carbonates a matrix porosity cutoff can exclude rock that flows through fractures or touching vugs.

## Do not state
- That pay will produce, or at what rate or fluid cut; formation tests, drill-stem tests, production logs or production would establish that.
- A fluid type or contact from cutoff flags alone; pressure gradients, fluid samples or tests would establish it.
- That the cutoffs are right for the field; calibration against core (permeability, capillary pressure) and tested intervals would establish that.
- Net pay away from the well or connected pay volume; correlation between wells, seismic, pressure and production data would establish it.

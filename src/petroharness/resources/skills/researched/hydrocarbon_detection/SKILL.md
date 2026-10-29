---
name: hydrocarbon_detection
when: Questions on whether a zone or interval holds hydrocarbons, which indicators support or argue against it, whether the fluid is gas, oil or water, and how confident a call can be.
areas: [hydrocarbon_detection]
---

# hydrocarbon_detection

## Consider
- Is there a water-bearing reference in the same rock type and porosity range? If not, which assumed RW does every resistivity indicator rest on?
- Within each lithology zone, does deep resistivity (RDEP) rise at similar porosity? Could the rise come instead from lower porosity, less shale, tight streaks, anhydrite, salt or coal?
- Where CROSSOVER_FLAG is set, is the rock clean, porous, in good hole and on the right matrix? Are the flagged samples contiguous or scattered?
- Do shallow and deep resistivities separate the way filtrate displacing hydrocarbon would for this mud type (see invasion_movability)?
- How strong is each signal against the within-zone scatter and against uncertainty in RW, m and n?
- What fraction of the zone shows the indicator, and does it sit at the top of a porous body, as buoyant fluid would?

## Compare
- runs CROSSOVER_FLAG   (the depth runs where the workflow's density-neutron crossover flag is set, top to base, by zone)
- runs NPHI < PHID   (the depth runs where neutron porosity reads below density porosity, top to base, by zone)
- runs NET_PAY   (the depth runs where the workflow's net-pay flag is set, top to base, by zone)
- stats PHID, PHIN, DRHO, SW, VCL where CROSSOVER_FLAG   (the porosity logs, DRHO, SW and VCL over only the flagged samples: n of N and the statistics)
- crossplot RDEP PHIE log_y log_x   (a least-squares line of log deep resistivity on log porosity in each zone: slope, intercept, R2, n)
- crossplot BVW PHIE   (a least-squares line of bulk volume water on porosity in each zone: slope, R2, n; slope near 0: BVW constant)
- overlap A B   (where two indicators hold together and apart, such as crossover and low SW: thickness by zone, runs)
- section hydrocarbon.petrophysical_hydrocarbon_indicators   (the workflow's indicators from SW, MHI and the pay flag)
- section hydrocarbon.geophysical_hydrocarbon_indicators   (the workflow's crossover and Vp/Vs screens)
- section saturation.gas_indicator_analysis_methods   (the workflow's gas-effect classes)
- section hydrocarbon.integrated_hydrocarbon_potential   (the workflow's combined hydrocarbon classes)

## Decide
- Resistivity test: compare RDEP with Ro = F × RW (F = formation factor, a/φ^m), the resistivity of the same rock filled with water. The ratio I = Rt/Ro rises with hydrocarbon saturation. It is only as good as RW and m. Closest here: calc on a zone's RDEP, porosity and RW, with the saturation step's a and m.
- Compare like with like. Within a zone, compare high- and low-resistivity samples of similar porosity. Between zones, compare only where rock type is similar; otherwise lithology alone changes Rt.
- Apparent water resistivity Rwa = φ^m × Rt / a equals RW in clean water-bearing rock and rises with hydrocarbon. One rule of thumb (a service-company glossary; values vary): Rwa above 3 × RW suggests producible hydrocarbon. Treat it as a screen, not a cutoff. Closest here: calc on a zone's RDEP and porosity, with the saturation step's a and m.
- Read density-neutron crossover as gas only after matrix, shale and hole checks. Its size grows with gas saturation near the borehole and with porosity; shale, low porosity and deep invasion shrink it.
- Other gas indicators: compressional/shear velocity ratio (VP_VS_RATIO) below the water-bearing trend of the same rock type; sonic slowdown or cycle skipping. Shale raises Vp/Vs, so compare within one clean zone (see elastic_properties).
- Buckles test within a zone: BVW constant as porosity changes suggests rock at irreducible water above a transition; BVW rising or scattered suggests transition or water-bearing rock (see water_saturation).
- Weigh indicators by independence, not by count: all resistivity-derived indicators are one line of evidence. Agreement across different physics (resistivity, density-neutron, sonic, pressure) is stronger.
- Screening flags (NET_PAY, PRIME_GAS_TARGET, PRIME_OIL_TARGET) rest on cutoffs that vary between studies. Check how far zone values sit from each cutoff, and whether the call survives plausible changes in RW, m and the cutoffs.
- Answer shape: locate (depth runs, each graded). The runs where an indicator's criterion holds, each with the indicators that agree there and its grade; 'not established' is its own graded claim, never in place of the list.

## Know
- Hydrocarbons do not conduct electricity; formation water does. At equal porosity, rock type and water salinity, higher Rt means higher hydrocarbon saturation.
- Rwa = φ^m × Rt / a is Archie with SW = 1. RW/Rwa = SW^n, so Rwa = 4 × RW means SW = 0.5 when n = 2.
- Gas lowers RHOB (PHID reads high) and the hydrogen index (PHIN reads low), so PHID reads above PHIN (crossover). The record's CROSSOVER_FLAG marks PHID − PHIN above a threshold in clean, porous, good-hole rock.
- Density and neutron read close to the borehole (roughly 0.2-0.5 m), so they see the gas left after invasion, not the uninvaded saturation. Logs run soon after drilling can show a stronger gas effect.
- Shale raises PHIN and can cancel crossover; a shaly gas sand may show only reduced neutron-density separation.
- Fluid typing: logs separate gas from liquid (density-neutron, sonic, Vp/Vs) more readily than oil from water (resistivity only). Resistivity cannot tell oil from gas. Pressure gradients and fluid samples type fluids.
- Low-resistivity pay: thin laminated sands, conductive clays, pyrite, microporosity or fresh formation water can give hydrocarbon zones with little resistivity contrast.
- High resistivity without moveable hydrocarbon: tight rock, anhydrite, salt, coal, fresh formation water, and residual (immobile) hydrocarbon left behind after migration or below a moved contact.
- Light oil and condensate can give a weak gas-like density-neutron effect; heavier oil reads much like water on porosity logs.

## Easily misread
- Crossover can come from matrix mismatch (sandstone on a limestone matrix), halite, coal or washouts. Lack of crossover does not rule out gas (shale, deep invasion, low porosity).
- SW, Rwa, BVW, NET_PAY and PRIME flags share RW, porosity and Rt. Their agreement is one piece of evidence, not several.
- A wrong RW moves every resistivity indicator together; where RW is assumed, the pay call for a whole interval can shift.
- A few scattered flagged samples inside a zone are weaker evidence than a contiguous interval.
- Beds thinner than tool resolution read averaged values: thin hydrocarbon beds may look wet, and thin tight streaks may look like pay.
- Hydrocarbon moved near the borehole supports mobility, not producibility (see invasion_movability).

## Do not state
- Logs alone do not establish that a zone will produce or at what rate; drill-stem or production tests, or formation-tester sampling, would.
- Do not type oil versus gas from resistivity, nor oil versus water from resistivity when RW and m are uncertain; pressure gradients and fluid samples establish fluid type.
- Hydrocarbon presence from resistivity-derived indicators alone; independent physics (density-neutron, sonic, pressure data, fluid samples) would support it.
- Logs alone do not separate residual from moveable hydrocarbon; flushed-zone data, tests or core flooding would.

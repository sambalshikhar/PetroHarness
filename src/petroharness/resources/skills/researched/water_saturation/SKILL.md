---
name: water_saturation
when: Questions on how much of the pore space holds water or hydrocarbon, which saturation model and parameters apply, where RW comes from, how sensitive SW is, irreducible water, or bulk volume water.
areas: [water_saturation]
---

# water_saturation

## Consider
- Which model made SW (Archie or a shaly-sand model), with which a, m, n, RW and shale terms? Does it suit each zone's VCL and the water salinity?
- Where did RW come from: a water sample, a clean water-bearing zone, the spontaneous potential (SP) log, a Pickett plot, or a catalogue? Was it corrected to formation temperature (TEMP)?
- Does the interval hold clean, porous, water-bearing rock where deep resistivity (Rt) should equal Ro = F × RW (F = formation factor)? Use it to check RW and m.
- Which porosity feeds SW: total (PHIT) for dual-water style models, effective (PHIE) for effective models? Model and porosity must match.
- Within a zone, how do SW and BVW vary with depth and porosity: constant BVW, a trend, or scatter?
- Is there core water saturation (SWC), capillary-pressure data, or a test to compare with?

## Compare
- stats SW, RDEP, PHIE, VCL   (saturation and its main inputs: n of N and the statistics in each zone)
- stats BVW, PHIE, SW   (bulk volume water beside porosity and saturation: n of N and the statistics in each zone)
- crossplot BVW PHIE   (a least-squares line of bulk volume water on porosity in each zone: slope, R2, n; slope near 0: BVW constant)
- crossplot RDEP PHIE log_y log_x   (a least-squares line of log deep resistivity on log porosity in each zone: the Pickett line, R2, n)
- crossplot PHIT VCL   (a least-squares line of total porosity on shale volume in each zone: slope, intercept, R2 and n)
- compare SW SWC   (log against core water saturation where both have values: the two averages, the difference, the rank correlation)
- step saturation   (the saturation model, its inputs and a, m, n)
- step rw   (the source of RW, its method and the formation temperatures)
- section saturation.water_saturation_estimation_analysis   (the workflow's saturation classes)
- section saturation.bulk_volume_water_porosity_integration   (the workflow's classes from BVW)
- section saturation.integrated_saturation_interpretation   (the workflow's combined fluid classes from saturation, BVW and the gas screens)

## Decide
- Archie suits clean rock, or very saline water, with regular intergranular pores. Where VCL is significant, water is fresh or Rt is low, Archie overstates SW; shaly-sand models correct for the clay conduction.
- Shaly-sand choices: shale-volume models (Simandoux and variants; Poupon-Leveaux 'Indonesia', built for fresh water and high shale) or clay counter-ion models (Waxman-Smits, needs core clay charge Qv; dual water, uses total porosity). They can differ widely in shaly rock.
- Laminated shale (thin shale beds in sand) suits a laminated model or thin-bed analysis; dispersed clay suits shale-volume or counter-ion models. The distribution is inferred from density-neutron patterns (Thomas-Stieber) or core, and is uncertain.
- RW sources, from most to least direct: a representative water sample, corrected for contamination; RW = φ^m × Rt / a in clean water-bearing rock of the same formation; a Pickett-plot water line; SP; catalogues.
- m choices: 2 for consolidated intergranular rock; Humble (a = 0.62, m = 2.15) or Tixier (a = 0.81, m = 2) for sands; core-measured m; a Pickett fit in water-bearing rock. Vugs raise m; fractures lower it.
- n: 2 is the usual default for water-wet rock; oil-wet rock raises n (values up to about 8 reported). Prefer core resistivity-index data where they exist.
- Correct RW and RMF to formation temperature with Arps: R2 = R1 × (T1 + 6.77)/(T2 + 6.77) in °F, or (T + 21.5) in °C. Uncorrected bottom-hole temperatures usually read low.
- Irreducible water estimates: zones where BVW stays constant as porosity changes (Buckles); the plateau of core capillary-pressure curves; SWC from cores cut with oil-based mud; nuclear magnetic resonance (NMR) bound fluid. Each has its own bias.
- Answer shape: quantify (values on each standard reading). Each zone's saturation with the model and the parameters it rests on; an uncertain parameter lowers the grade and keeps the value.

## Know
- Archie: SW^n = a × RW / (φ^m × Rt). Formation factor F = a/φ^m; water-filled resistivity Ro = F × RW; resistivity index I = Rt/Ro = SW^(−n).
- Archie parameters: a is often taken as 1; m is 1.8-2.0 in consolidated sandstone and near 1.3 in loose sand, and varies widely in carbonates (lower with fractures, up to 4 or more with separate vugs); n about 2 in water-wet rock.
- Sensitivity: SW ∝ RW^(1/n) × φ^(−m/n). With m = n = 2, RW 20% too high raises SW about 10%; a 1 porosity-unit (p.u.) error at 10% porosity moves SW about 10% (relative).
- Sensitivity to m: SW scales by φ^(−Δm/n). At φ = 0.10 and n = 2, raising m by 0.2 raises SW about 26%; the effect grows as porosity falls. Raising n raises SW wherever SW < 1.
- Shaly-sand models add a clay conduction term to Archie: shale-volume models use VCL and shale resistivity (Rsh); Waxman-Smits uses Qv, the cation exchange capacity per pore volume from core; dual water uses total porosity and the clay-bound water fraction.
- Clay conduction matters most when RW is high (fresh water) and Rt is low; in very saline water the clay term is small next to free-water conduction.
- Pickett plot: log Rt against log φ. Water-bearing points fall on a line of slope −m that meets φ = 1 at a·RW. Constant-SW lines run parallel to it (constant n); constant-BVW lines are also straight.
- Static SP: SSP = −K·log10(Rmfe/Rwe), K ≈ 61 + 0.133·T(°F) mV; for fresh filtrate Rmfe ≈ 0.85·RMF. SP-based RW fails with oil-based mud, thin or shaly beds, hydrocarbons, or RMF close to RW.
- BVW = φ × SW. In one rock type at irreducible water, BVW stays nearly constant as porosity varies (Buckles). Rule-of-thumb values: about 0.02 (coarse sand) to 0.09 (silt); carbonates about 0.005 (vuggy) to 0.05 (chalky); they vary by source.
- Irreducible water saturation is not a rock constant: it falls with height above free water and with larger pore throats. Lab values depend on drive pressure or centrifuge speed; 'connate' water is the in-situ value.

## Easily misread
- Low SW may come from porosity read too high (bad hole, gas, wrong matrix) or RW set too low; check inputs before reading low SW as hydrocarbon.
- High SW in shaly or laminated rock, or with conductive minerals such as pyrite, or microporosity, may be a model limit (low-resistivity pay), not water.
- SW holds only with the deep, invasion-corrected resistivity; SW from a shallow or medium curve describes the invaded zone.
- Taking the lowest apparent RW (Rwa) as RW where no water-bearing rock exists makes RW too high and SW too high.
- Equal SW does not mean equal water production: fine-grained rock at irreducible water and coarse rock in a transition zone can share an SW. BVW and rock type separate them.
- One m or n for all zones hides pore-type and wettability changes; an SW difference between zones may come from the parameter, not the fluid.

## Do not state
- RW, m and n as known where no water sample, water-bearing zone or core electrical data exist; water analysis or core resistivity tests would settle them.
- SW alone does not show whether a zone will produce water-free hydrocarbon; capillary-pressure, relative-permeability data and well tests would.
- Logs do not measure irreducible water; a low, steady log SW is an apparent irreducible value. Core capillary pressure, oil-based-mud core SWC or NMR would measure it.
- That one saturation model gives the true SW in shaly rock; core electrical measurements (Qv, m, n) or tests would decide between models.

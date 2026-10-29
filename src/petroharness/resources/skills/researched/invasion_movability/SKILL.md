---
name: invasion_movability
when: Questions on invasion profiles, how shallow, medium and deep resistivities compare, flushed-zone saturation and the moveable hydrocarbon index, and what curve separation does and does not show about permeability and movability.
areas: [invasion_movability]
---

# invasion_movability

## Consider
- Which mud was used: water-based (compare mud-filtrate resistivity RMF with RW, both at formation temperature) or oil-based? The expected profile depends on it.
- Which curves read which depth? By name, RXO or RMIC read the flushed zone (Rxo), RSHA shallow, RMED medium, RDEP deep (nearest to Rt); check the record's curve descriptions. Are they from one tool family with similar resolution?
- In each zone, what is the order of RSHA, RMED and RDEP? Does it match water-bearing rock for this RMF/RW, or does the medium curve read below both (a possible annulus)?
- How was SXO (flushed-zone water saturation) made: from a measured RXO with RMF, or from SW by a formula? If from SW, MHI (SW/SXO) only repeats SW.
- Is the separation steady through the zone, or confined to washouts, thin beds or zone boundaries (BAD_HOLE, caliper, shoulder beds)?
- Is there independent sign of permeability: mudcake (caliper below bit size), micro-resistivity separation, core permeability?

## Compare
- stats RDEP, RMED, RSHA, RXO, INVASION_RATIO   (the resistivities by depth of investigation and the invasion ratio: n of N and the statistics in each zone)
- curve_order RSHA, RMED, RDEP   (the share of samples, and of zones by their averages, where shallow, medium and deep keep that order)
- runs RSHA > RMED and RMED > RDEP   (the depth runs where resistivity falls from shallow to deep, top to base, by zone)
- runs RDEP > RMED   (the depth runs where deep resistivity reads above medium, top to base, by zone)
- compare RMF RW   (mud-filtrate against formation-water resistivity in each zone: the two averages, the difference and its spread)
- compare CALI BS   (caliper against bit size in each zone: the two averages, the difference and the shares on each side)
- step invasion   (how the invasion ratio was computed, and from which resistivity curves)
- step mhi   (how MHI was computed from SW and SXO, and the route of SXO)
- overlap A B   (where an invasion sign and another condition hold together and apart: thickness by zone, runs)
- section saturation.hydrocarbon_movability_invasion_characteristics   (the workflow's movability classes from MHI or the invasion ratio)
- section permeability.invasion_profile_permeability_indicators   (the workflow's invasion classes from the shallow-to-deep resistivity ratio)
- section permeability.mhi_confirmation   (the workflow's count of high-MHI samples in each zone)

## Decide
- Water-zone reference: with SW = Sxo = 1 and the same a and m, Rxo/Rt = RMF/RW. Fresh mud (RMF > RW): shallow reads above deep. Salty mud (RMF < RW): shallow reads below deep.
- In hydrocarbon-bearing rock, Rxo/Rt = (RMF/RW) × (SW/Sxo)^n. Filtrate displacing hydrocarbon lowers the ratio: fresh-mud separation shrinks or reverses, salty-mud separation grows. Compare each zone with the water-zone ratio.
- Flushed-zone saturation from Archie: Sxo^n = a × RMF / (φ^m × RXO). MHI = SW/Sxo. At 1 or above, invasion moved no hydrocarbon; below about 0.7 in sandstones or 0.6 in carbonates, moveable hydrocarbon is indicated (Asquith 1982; values vary).
- If SXO came from SW (for example Sxo = SW^(1/5), the ratio-method assumption), MHI is fixed by SW (here SW^0.8) and adds no evidence of movability.
- Separation within one tool family, mudcake on the caliper, or micro-resistivity separation each show that filtrate entered the rock, so some permeability exists. None shows how much.
- No separation is ambiguous: RMF close to RW, very shallow or very deep invasion, oil-based mud, or impermeable rock can each cause it. Test each before concluding.
- Annulus: on induction logs, a medium reading below both shallow and deep may mark a ring of displaced formation water, which forms where hydrocarbon is mobile. It fades with time; laterologs barely see it.
- Oil-based mud: the filtrate does not conduct, so RMF-based Sxo does not apply and shallow curves rise from filtrate, not hydrocarbon. Movability then needs other data.
- Answer shape: locate (depth runs, each graded). The runs where the indicator holds, with the status of its inputs (measured, or computed from SW), each graded; where an input has no value, the indicator is not computed there.

## Know
- Invasion zones: the flushed zone next to the borehole wall (moveable fluids displaced by filtrate; Rxo, Sxo), a transition zone (partial displacement), and the uninvaded zone (Rt, SW). Mudcake builds on permeable rock.
- Approximate depths of investigation: micro-resistivity a few cm; shallow about 0.3-0.5 m; medium about 0.6-0.8 m; deep about 1.2-1.5 m or more. Values depend on tool and resistivity contrast.
- Typical water-zone profiles: fresh mud gives Rxo > Ri > Rt; salty mud with RMF near RW gives Rxo ≈ Ri ≈ Rt (Ri = resistivity of the transition zone).
- Ratio method: assumes Sxo = SW^(1/5) (moderate invasion), giving SW = [(Rxo/Rt)/(RMF/RW)]^(5/8). It needs no porosity but builds Sxo from SW.
- Moved hydrocarbon = Sxo − SW as a fraction of pore volume, or φ × (Sxo − SW) as bulk volume. Residual hydrocarbon in the flushed zone = 1 − Sxo.
- 'Moved' hydrocarbons (displaced by invasion) are not the same as 'moveable' hydrocarbons (producible on production).
- Flushing is rarely complete: residual hydrocarbon (1 − Sxo) stays in the flushed zone, so Sxo is often below 1 even in good, permeable pay.
- Sxo ∝ (RMF/RXO)^(1/n); an RMF error (wrong temperature, or mud instead of filtrate sample) shifts Sxo and MHI directly.
- Gravity can make invasion differ between the top and base of a thick, permeable bed when filtrate and formation fluid densities differ.
- Logs run while drilling see less invasion than later wireline logs; separation growing between runs indicates permeable rock.

## Easily misread
- Shoulder beds, thin beds, washouts, and mixing tool types (laterolog vs induction, different resolutions) separate curves without invasion; use one tool family on good-hole samples.
- MHI from an SXO that came from SW, or from a shallow curve not corrected for mudcake and borehole, is not independent evidence.
- MHI near 1 fits both water-bearing rock and unflushed or tight hydrocarbon rock; it means moved hydrocarbon only where SW < 1 and the rock is permeable.
- Large separation is not high permeability: invasion depth depends mostly on mudcake, overbalance and time, little on the formation, and low-porosity rock invades deeper for the same filtrate volume.
- Hydrocarbon moved by filtrate under overbalance does not prove the rock will flow under drawdown.
- An out-of-order medium curve can come from tool or environmental effects, not only an annulus; check hole condition and bed thickness first.

## Do not state
- Logs cannot establish producibility, flow rate or relative permeability; well tests, formation-tester mobility and core relative-permeability data would.
- A measured Sxo or movability without a measured RXO (or RMIC) and RMF; an Sxo built from SW is an assumption, not a measurement.
- Do not give permeability values from curve separation; core, formation-tester mobility or nuclear magnetic resonance (NMR) logs would.
- Under oil-based mud, do not apply water-filtrate Rxo/Rt equations.

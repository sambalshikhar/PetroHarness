---
name: fluid_contacts
when: Questions on whether and where a gas-oil, gas-water or oil-water contact or a transition zone occurs, how sure a contact pick is, and what else could explain a change in fluid with depth.
areas: [fluid_contacts]
---

# fluid_contacts

## Consider
- Within one zone of steady porosity, how do SW and RDEP change with depth: sharply, or gradually over metres (a transition zone)? Is there a level below which SW stays near 1 and Rt near Ro (water-filled resistivity)?
- Does the change line up with a change in rock (zone boundary, VCL, porosity, SEALFLAG, NET_ROCK) or hole condition (BAD_HOLE)? Then it may be a rock change, not a contact.
- Is there a gas-liquid change: does gas evidence (CROSSOVER_FLAG, low VP_VS_RATIO) end at a depth inside clean rock while resistivity stays high?
- Does the well reach water-bearing reservoir rock below the hydrocarbon? If not, only the lowest known hydrocarbon is seen.
- Are there several porous bodies separated by seals? Each may hold its own contact.
- Are depths measured depth (MD) or true vertical depth (TVD)? Contacts are near-horizontal surfaces, so compare them in TVD.

## Compare
- profile SW   (SW zone by zone from the top: the statistics, the zones ranked and the direction with depth in words)
- profile RDEP   (deep resistivity zone by zone from the top, with the direction with depth in words)
- profile PHIE   (effective porosity zone by zone from the top, with the direction with depth in words)
- profile VCL   (shale volume zone by zone from the top, with the direction with depth in words)
- crossplot SW DEPTH   (a least-squares line of SW on depth in each zone: slope per depth unit, R2, n and the direction in words)
- runs CROSSOVER_FLAG   (the depth runs where the workflow's density-neutron crossover flag is set, top to base, by zone)
- runs SEALFLAG   (the depth runs where the workflow's seal flag is set, top to base: thickness and share of each zone)
- runs CONDITION   (the depth runs where a condition holds, such as a class or SW above a value, top to base, by zone)
- overlap A B   (where two conditions hold together and apart, such as a contact class and a rock change: by zone, with runs)
- section saturation.fluid_contact_detection_indicators   (the workflow's contact and transition classes from depth changes in SW and porosity)

## Decide
- Log contact: look for where SW (or Rt/Ro) changes from the hydrocarbon trend to water within one rock type at similar porosity. Pick choices: SW reaching 1, SW crossing a chosen cutoff, or a break in the Rt trend.
- A log contact lies between the last clearly hydrocarbon-bearing and the first clearly water-bearing sample; that gap is the uncertainty of the pick.
- Separate contact from transition: SW falling upward over a height is a capillary transition zone. Its base (SW reaches 1) is the log contact; the free water level lies at or below it.
- Pressure data: fit a gradient to good tester points in each fluid. Where gradients intersect is a free-fluid level (free water level or free oil level), not the log contact.
- Gas-oil contact: look for the base of gas indicators in one clean rock type at steady porosity while resistivity stays high; resistivity alone cannot place it. A gradient change in pressure data would confirm it.
- Compare between zones: rocks with different pore sizes show log contacts at different depths over one free water level. A consistent free water level supports connected rock; a mismatch suggests separate compartments or a misread.
- Where no water-bearing reservoir is penetrated, only the lowest known hydrocarbon ('hydrocarbon down to') is known; where no hydrocarbon is seen, only the highest known water ('water up to').
- The pick's precision is limited by tool vertical resolution (about 0.3-0.6 m for GR, density and neutron; about 2 m for deep induction), sample spacing and the transition height.
- Answer shape: locate (depth runs, each graded). The depth or depth window of a contact or transition, with the runs above and below that bound it, graded; candidate depths that meet part of the criterion are listed with their grade and what they lack.

## Know
- Free water level (FWL): the highest level where capillary pressure is zero, so water and hydrocarbon pressures are equal. The log contact lies above it by a height set by the rock's entry (displacement) pressure.
- Height above FWL: h = Pc / (Δρ × g), with Pc the capillary pressure. In field units, h (ft) = Pc (psi) / (0.433 × Δρ), with Δρ the water-hydrocarbon density difference in g/cc.
- Transition zones are thicker where pore throats are small (low permeability) and where density contrast is small (oil-water more than gas-water). Coarse, permeable rock gives sharp contacts.
- Fluid pressure gradient = density × 0.433 psi/ft per g/cc (9.81 kPa/m per g/cc). Example values often quoted are about 0.45 (water), 0.35 (oil) and 0.08 (gas) psi/ft; real values vary with salinity, oil type and pressure.
- Above the transition, SW nears irreducible and BVW is roughly constant in one rock type (see water_saturation). Below the contact, Rt ≈ Ro and apparent water resistivity (Rwa) falls to RW.
- Contacts are usually close to horizontal but may tilt (moving aquifer water) or step between compartments; production also moves them.
- Residual hydrocarbon below a present contact (left by a former, deeper contact) can raise Rt and lower SW without any moveable hydrocarbon.
- Formation-tester pressures can read high in low-permeability rock (supercharging by filtrate); tight or leaking tests give false gradients. Gradients need stable, repeatable points.

## Easily misread
- A downward drop in Rt can come from more shale, higher porosity in water-bearing rock, or saltier water, not only from a contact.
- A downward rise in SW can come from finer-grained rock with more irreducible water; compare SW within one zone, not across zone boundaries.
- A shale or tight streak (SEALFLAG, NET_ROCK = 0) can mimic the top of water; pick contacts in reservoir rock above and below it.
- Deep invasion with salty mud, or a conductive annulus, lowers deep resistivity and can mimic water; check the shallow-medium-deep order (see invasion_movability).
- The base of crossover can be a rock change (more shale, lower porosity, deeper invasion) rather than a gas-oil contact.
- In a deviated well, a contact in measured depth is not its vertical depth; compare contacts in TVD.

## Do not state
- Logs in one well cannot place the free water level precisely; pressure gradients from good tests or core capillary-pressure data would.
- A contact where the well does not reach water-bearing reservoir; deeper penetration or pressure gradients in both fluids would establish it.
- Do not state the lateral extent or tilt of a contact from one well; other wells, pressure data and seismic would.
- Do not type the fluids on either side of a contact (oil vs gas) from resistivity alone; fluid samples and pressure gradients would.

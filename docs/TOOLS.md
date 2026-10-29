# Petrophys tools

PetroHarness answers with the well's interpretation record. It can also ask Petrophys for more. A user can ask
"compute SW with Simandoux and give me the statistics", "what Rw does this well suggest?", "how does net pay change
at a 0.5 SW cutoff?" or "fit a saturation-height function above 870 m", and the model calls Petrophys to compute
the answer.

Petrophys does every calculation. Inputs not named in the call come from the record. Every result says where each
input came from, and every call is kept in the trace.

## The tools by request

The model sees its tools grouped by the kind of request. The record's lookups are members of their verb. The verbs
over Petrophys add what the record cannot give.

| verb | what users ask | the record's lookups | over Petrophys |
|---|---|---|---|
| **describe** | "what is the porosity in Z2?", "where is SW below 0.5?" | stats, profile, runs, section, step, formation_summary | |
| **compare and group** | "is porosity higher where shale is lower?", "by rock type?" | compare, crossplot, overlap, lithology_stats, zone_contrast, curve_order, vertical_sequence | |
| **check** | "where are the washouts?", "held readings?", "is core depth-matched?" | spike_flags, adjacent_jumps, threshold_exceedance, data_record, lag_correlation | `check` |
| **calculate** | "SW with Simandoux", "VCL with Larionov", "porosity with a dolomite matrix" | | `calculate`, `what_if` |
| **estimate** | "what Rw does the well suggest?", "what is m?" | | `estimate` |
| **classify** | "what minerals?", "is there gas?", "what flow units?" | zone_classes, unit_roles | `classify` |
| **summarize** | "net pay and HCPT per zone at a 0.5 SW cutoff?" | pay_summary | `summarize` |
| **calibrate** | "does log porosity match core?", "predicted shear?" | core_vs_log | `calibrate` |

Each verb over Petrophys has two parts:
- **shortcuts:** named objects for common requests, below;
- **search and run:** they reach every public Petrophys function, about 300 of them.

## Shortcuts

### calculate

`{"calculate": {"property": ..., "method": ..., "parameters": {...}, "label": ...}}`

- **What it recomputes:** a property with Petrophys's own workflow step: clay volume, porosity, water resistivity,
  mud-filtrate resistivity, saturation, permeability, rock quality, BVW, MHI, net pay or temperature.
- **Where the methods come from:** the step catalog Petrophys ships. Examples:
  - saturation: archie, simandoux, indonesia, north_sea, nigeria_schlumberger, dual_water, waxman_smits, auto;
  - permeability: timur, coates, wyllie_rose, lith_vcl;
  - clay volume from GR with linear, Larionov, Steiber or Clavier transforms.
- **Downstream:** the steps that read the property's outputs run after it, so a new SW carries into BVW and pay.
- **What it shows:** the change against a baseline run with the record's parameters, zones pooled and each zone.
- **New curves:** each is written as `<CURVE>_<LABEL>`, for example `SW_SIMANDOUX`, and every lookup and condition
  reads it.
- **An input another property computes** (Rw, VCL, PHIE) is changed by calculating that property:
  `{"property": "water_resistivity", "parameters": {"rw": 0.03, "rw_temp_f": 105}}`.
- **With the property alone,** it lists the step's parameters with the record's values and the choices.

### what_if

`{"what_if": {"property": ..., "parameter": ..., "values": [...], "target": ..., "parameters": {...}}}`

An input's effect on a target. Petrophys recomputes for each value, with every other input taken from the record.
Examples:
- the SW cutoff against net pay;
- m against SW;
- the saturation models side by side.

### estimate

`{"estimate": {"parameter": ..., "method": ..., "zones": [...]}}`

| parameter | methods |
|---|---|
| rw | rwa (apparent water resistivity over clean, porous samples), pickett, sp (needs Rmf) |
| archie_m | pickett (a, m and n) |
| clay_point | neutron_density (the shale's NPHI and RHOB) |
| gr_endpoints | percentiles (as the clay-volume step picks them) |
| matrix | apparent (RHOMAA, and UMAA with PEF) |
| temperature | gradient (a BHT refines it) |

Each estimate is shown against the record's value of the same parameter.

### check

`{"check": {"what": ...}}`

- **held_readings:** stuck or padded readings per measured log, by depth run and zone.
- **bad_hole:** the parts of bad hole (washout, large hole, caliper rugosity, low density, PEF out of range), each as
  a flag curve with its depth runs.
- **depth_shift:** the shift that ties core plugs in the LAS to a log, with the correlation before and after.

### classify

`{"classify": {"what": ..., "method": ..., "k": ...}}`

- **gas:** neutron-density gas effect, as GAS_FLAG with its depth runs.
- **minerals:** mineral volumes from the multi-mineral solver, with its poor-fit flag, or calcite and dolomite.
- **flow_units:** hydraulic flow units per sample from FZI.
- **electrofacies:** electrofacies classes from k-means.
- **moveable_hydrocarbons:** moveable and residual oil saturation, where SXO comes from a flushed-zone log.

### summarize

`{"summarize": {"what": "pay", "sw_cutoff": 0.5}}`

Net rock, reservoir and pay thickness, net-to-gross, pay averages and hydrocarbon pore thickness, per zone and
pooled. It takes any cutoffs given; pay_summary gives the record's own flags.

### calibrate

`{"calibrate": {"what": ...}}`

- **porosity, permeability, saturation:** the fit of a log to core (R2, bias, RMSE and the line). core_vs_log gives
  the statistics side by side.
- **poro_perm:** a porosity-permeability transform.
- **shear:** shear slowness predicted from DTC (Greenberg-Castagna).
- **elastic:** dynamic elastic properties.

## Search and run: every Petrophys function

Each verb also takes `search` and `run`. For example:

```json
{"calibrate": {"search": "saturation height"}}
{"calibrate": {"run": "fit_saturation_height_from_well", "args": {"fwl": 870, "sw_curve": "SW", "vertical": true}}}
```

**The registry** is generated from the installed Petrophys. It holds every public function of its interpretation,
evaluation and preprocessing packages, filed under the verb its package serves:

| verb | functions | groups (from the Petrophys modules) |
|---|---|---|
| calculate | 80 | clay volume methods, Thomas-Stieber, porosity and its corrections, saturation models, permeability, invasion, Eaton |
| estimate | 58 | Rw, Rwa, Pickett, Rmf, temperature, apparent matrix |
| calibrate | 46 | core calibration, grain size, NMR calibration, saturation height, capillary pressure, formation pressure, rock physics |
| classify | 39 | flow units, rock quality, MHI, zonation, heterogeneity, geochemistry, lithology crossplots, mineral solvers |
| summarize | 37 | net pay, averages, net-to-gross, ranking, zone summaries, hydrocarbon pore volume (OOIP, OGIP) |
| check | 32 | washout detection, held readings, value ranges, normalization, imputation, depth matching |
| what_if | 5 | sensitivity, uncertainty |

A function Petrophys adds appears with no change to the harness. A search finds matches under every verb, its own
verb's first.

**The binder** calls any function on the question's interval:
- **an array parameter** takes the curve the call names, else a condition such as `VCL > 0.6` (as a 0/1 mask), else
  the curve its name stands for (`rt` is RT or RDEP, `phi_d` is PHID, ...);
- **a number** takes the call's value, else the record's parameter of that name (Rw, a, m, n, Rcl, cutoffs), else
  Petrophys's default;
- **a function that reads a whole well** gets the prepared well, with the interval's top and bottom.

Each input is listed with its source.

**Outputs:**
- an array over the interval becomes a curve of the question (`<FUNCTION>_<PART>`);
- a number becomes a value;
- a dataclass, dict or tuple becomes its parts;
- class codes become class shares.

A call Petrophys refuses comes back with Petrophys's own message, for example "model='dual_water' needs rwb", so
the answer can say what the user would have to provide.

## An example

"can u compute saturation with Simandoux and give me the statistics", for one formation of a sample well. The
model called:

```json
{"calculate": {"property": "saturation", "method": "simandoux"}}
```

Petrophys re-ran the saturation step and the steps after it. Part of the result:

```
saturation recomputed by Petrophys with model simandoux; inputs: model simandoux (asked), a 0.81 (record), m 2 (record), n 2 (record), rcl 3.3933 (record); then bvw, mhi, net_pay (they read its outputs)
  Petrophys did not run: mhi: Needs RMF (mud-filtrate resistivity), which is not on this well; add steps.mud_filtrate(rmf=..., rmf_temp_f=...) before 'mhi'
  SW: mean 0.9017 -> 0.8679 (-0.03375) zones pooled; 41 samples changed
    each zone (mean, baseline -> changed): Z1 0.9105 -> 0.9571; Z2 0.8968 -> 0.8191
    the baseline reproduces the record's SW (100.0% of samples within 1%)
  ...
```

The model then compared `SW_SIMANDOUX` with the record's SW by zone, and wrote the statistics. Every number in the
answer cites one of these results.

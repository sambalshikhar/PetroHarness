# Examples

Six questions a petrophysicist would ask, each on a well that ships with Petrophys, answered by the default model
(K2-Horizon-7B). The questions need more than a lookup: two formations compared inside a group, a sensitivity study, the
logs set against core, a well missing its neutron and PEF logs, a carbonate against a clastic reading and a fluid contact.
Each answer below is quoted from the run, cut where marked […]; the figures are the
answers' own, drawn by Petrophys.

| # | Question | Well | What it shows |
|---|---|---|---|
| 1 | [Ness against Etive](#1-two-formations-inside-a-group) | GeoLink 30/6-5, Brent Group | the tops file's formations inside the interval, compared zone group by zone group |
| 2 | [Net pay's sensitivity](#2-how-sensitive-is-net-pay) | GeoLink 30/6-5, Brent Group | what-if runs of the saturation model and of m, zone by zone |
| 3 | [Logs against core](#3-logs-against-core) | GeoLink 25/5-1, 2990–3290 m | core fits refused below their gate, a depth offset found, where permeability fails |
| 4 | [No neutron, no PEF](#4-a-well-missing-its-neutron-and-pef-logs) | GeoLink 16/7-1, 2000–2560 m | what can still be said, and what the missing logs leave unconfirmed |
| 5 | [A carbonate](#5-a-carbonate-against-a-clastic-reading) | COSTA HW-3, KHARAIB-2 | field notes that set the interpretation, and a sandstone what-if |
| 6 | [A fluid contact](#6-a-fluid-contact) | Taranaki tuhua-7, McKee Formation | a negative answer, with the evidence weighed |

The commands use the bundled wells by name:

```bash
export PETROHARNESS_MODEL_URL=http://localhost:8000/v1        # any OpenAI-compatible endpoint (MODELS.md)
w() { python -c "import petrophys, sys; print(petrophys.sample(sys.argv[1]))" "$1"; }
```

Every answer also comes with its trace: each step, the results the model opened and how every number in the answer
was computed ([Evidence and audit](EVIDENCE.md)).

## 1. Two formations inside a group

```bash
petroharness --las $(w 30/6-5) --tops $(w formations_30_6-5.csv) --formation "BRENT GP." \
  --question "Compare the Ness and Etive formations within the Brent Group: which has the better reservoir quality, and is the difference driven by clay content, porosity or permeability?"
```

The tops file lists Ness (2841–2865 m) and Etive (2865–2958 m) inside the Brent Group, so the question carries them.
The model read the lithology zones by formation, Z1–Z3 for Ness and Z4–Z20 for Etive, and set clay, porosity and
permeability against each other with zone statistics, crossplots and a zone contrast (8 steps, 13 results opened).

> **Etive (Z4–Z20, 2865–2957.9 m) holds the better reservoir-quality rock; Ness (Z1–Z3, 2841.3–2861.7 m) is
> predominantly a clay- and water-bearing unit.** The contrast is clay-driven, not sandiness-driven alone. […]
>
> Mean VCL over Ness Z1–Z3 is **0.5279** (median 0.643, n = 68); over Etive Z4–Z20 it is **0.2930** (median 0.193,
> n = 499). […] PHIE_CC falls with VCL: pooled fit PHIE_CC = 0.1964 − 0.2213·VCL (R² = 0.6105, n = 567) […]
> Where PERM_CC is defined, it separates by clay: lower-VCL zones mean 360.1 mD versus higher-VCL zones 25.3 mD. […]
> In Ness, PERM_CC exists only in Z1 (n = 20 of 30, mean 135.98 mD); Z2 and Z3 have **no PERM_CC**.

![Core-calibrated porosity against clay volume in the Brent Group](images/example-ness-etive.png "The answer's crossplot: core-calibrated effective porosity (PHIE_CC) against clay volume (VCL) over the Brent Group's 20 zones, 567 samples coloured by depth, with the least-squares line. Drawn by Petrophys. Data: GeoLink, CC BY-SA 4.0.")

## 2. How sensitive is net pay

```bash
petroharness --las $(w 30/6-5) --tops $(w formations_30_6-5.csv) --formation "BRENT GP." \
  --question "How sensitive is net pay in the Brent Group to the saturation model and the Archie exponents? Compare Archie, Simandoux and Indonesia, and vary m between 1.8 and 2.2."
```

Two what-if runs: the saturation step rerun with each model, and with m at 1.8 and 2.2, every other input the record's
(8 steps). The tool said the rerun's baseline differs from the record at 10 of 768 samples, and the answer reads the
changes against the baseline accordingly.

> Fixed **Simandoux** gives a pooled NET_PAY share of **31.5697%**, and fixed **Indonesia** gives **32.2751%**. The
> changes are confined to **Z1, Z8 and Z9**; Z4–Z7 are unchanged across all three models. […] Sweeping m to **2.2**
> gives a pooled share of **26.455%**, with **Z1 at 20%** […] **Z8 at 0%** and **Z9 at 0%**. […]
>
> **Z7 is invariant at 100%** across all model and m runs […] The sensitivity is concentrated in the **marginal
> clay/shallow zones Z1, Z8 and Z9**, where SW sits near or above the 0.7 cutoff and where model routing and m exponent
> flip samples across the boundary.

![Saturation and net pay in the Brent sands](images/example-pay-sensitivity.png "The answer's log display: water saturation (Sw, Sxo), the net-pay flag and the reservoir flag beside the sand zones that carry pay. Drawn by Petrophys. Data: GeoLink, CC BY-SA 4.0.")

## 3. Logs against core

```bash
petroharness --las $(w 25/5-1) --top 2990 --base 3290 \
  --question "How well do the log porosity and permeability match the core in this interval, zone by zone, and where should the log permeability not be trusted?"
```

The interval is given by depths. The model fitted the log to the core plugs with Petrophys, zone by zone, scanned the
core against the log for a depth offset, and read permeability where it is computed (8 steps, 10 results opened).

> Core covers 203 of 1638 zoned samples (12.4%) […] There is **no core in Z8–Z15** […] Because no calibrated core
> curve was written (r² 0.08 < 0.5 threshold), there is no core-anchored porosity transform […]
>
> Log PERM (Coates–Denoo, clipped at 10000 mD) carries values in only 445 of 1638 zoned samples. It agrees with core
> KH_CORE in order of magnitude only in the clean crossbedded sands Z4, Z5 and Z19; Z19 is close (log 316.3 mD mean vs
> KH_CORE 311.9 mD mean). It should **not** be trusted in Z9 and Z11 (PERM not computed, no SWIRR_APP) […] and in Z20
> (mean 960.0 mD vs KH_CORE mean 0.37 mD). […]
>
> The only lag scan ran on PHIC–PHIT and found r 0.2879 at zero lag, rising […] to r 0.5948 at dz = −2.7423 m (PHIC
> reads 2.74 m shallower than PHIT).

![Porosity and permeability in GeoLink 25/5-1](images/example-core-check.png "The answer's log display, 2990–3290 m: caliper and bit size, the density correction, total and effective porosity, and log permeability beside the zones. Log permeability is absent through most of the silt, and bad hole is shaded. Drawn by Petrophys. Data: GeoLink, CC BY-SA 4.0.")

## 4. A well missing its neutron and PEF logs

```bash
petroharness --las $(w 16/7-1) --top 2000 --base 2560 \
  --question "This well has no neutron or PEF log. What can still be said about porosity and lithology in this interval, and where are the logs unreliable?"
```

The model read the bad-hole flags, the lithology-log consistency check and the log-quality assessments, and said
which products the missing logs disable (8 steps, 8 results opened).

> With no NPHI and no PEF log in 16_7-1, **porosity is density-only**: PHIT equals PHID because no neutron integrated
> porosity (PHIN) curve exists in the well's data […] **SILT, ANHYDRITE and HALITE are classed NO_LOG_LITHOLOGY_MATCH
> across 100% of their samples**, so those zonal lithologies are unconfirmed by the logs present. Bad-hole flags are
> severe: 77.6% of Z1 samples, 100% of Z2, 100% of Z3 and 30.3% of Z4 samples […]
>
> Density-derived porosity means, by zone: **Z1 Limestone 0.1924 v/v, Z2 Silt 0.4506 v/v, Z3 Anhydrite 0.4635 v/v,
> Z4 Halite 0.0008625 v/v** […] Neutron–density clay volume is not computed; RHOB is present throughout, so the
> absence of the neutron input is what disables this product.

![Bad hole, density and clay volume in GeoLink 16/7-1](images/example-missing-logs.png "The answer's log display, 2000–2560 m: clay volume, bulk density and the bad-hole flag beside the limestone, anhydrite and halite zones; bad hole is shaded. Drawn by Petrophys. Data: GeoLink, CC BY-SA 4.0.")

## 5. A carbonate against a clastic reading

A field notes file states what the team knows of the reservoir, and sets the interpretation from the start:

```yaml
name: KHARAIB-2 carbonate study
settings:
  lithology_domain: carbonate
  matrix_type: limestone
notes:
  - KHARAIB-2 is a limestone reservoir.
```

```bash
petroharness --las $(w HW-3) --tops $(w formations_costa.csv) --formation KHARAIB-2 --field-notes kharaib.yaml \
  --question "Interpreted as a carbonate, what are the porosity, water saturation and net pay of KHARAIB-2, and how do they change against a clastic reading with a sandstone matrix?"
```

Petrophys interpreted the interval as a carbonate (a calcite–dolomite solve on a 2.71 g/cm³ matrix). The model read
the record and had Petrophys recompute density porosity on a sandstone matrix (8 steps). The tops table holds several
COSTA wells; the rows of HW-3 are used, in feet.

> - **Porosity:** uncalibrated PHIE mean **0.1981 v/v** (median 0.2164, range 0.0324–0.3099); core-calibrated
>   PHIE_CC mean **0.2443** (median 0.29) over the 351 samples where it exists. […]
> - **Net pay:** **194 ft of NET_PAY (90% of the zoned thickness)**, flagged where NET_ROCK (VCL < 0.3) and NET_RES
>   (PHIE > 0.045) hold and SW < 0.7. […]
> - **Carbonate support:** VCALC mean **0.7422** (median 0.7719) and VDOLO mean **0.0559** (median 0) with quartz and
>   anhydrite fixed at 0 […]
>
> A 2.65 g/cm³ sandstone matrix lowers density porosity from ~0.196 to ~0.169 (mean, pooled) […] What would follow for
> Archie SW and pay was not run and cannot be stated from this record.

The last line is the answer keeping to what was computed: the sandstone what-if covered porosity, so the answer does
not guess its effect on saturation and pay.

![Density against neutron in COSTA HW-3](images/example-carbonate.png "The answer's density-neutron crossplot of KHARAIB-2, 431 samples coloured by gamma ray, with the sandstone, limestone and dolomite lines. Drawn by Petrophys. Data: Costa Gomes, Geiger and Arnold (2022), COSTA model, Heriot-Watt University, CC BY.")

## 6. A fluid contact

```bash
petroharness --las $(w tuhua-7) --tops $(w formations_tuhua-7.csv) --formation McKee \
  --question "Is there a hydrocarbon-water contact in the McKee Formation? If so, at what depth, and how strong is the evidence?"
```

The well has no lithology log, so the zones are bands of shale volume. The model read saturation by depth, the
fluid-contact and hydrocarbon analyzers, invasion and crossover, and overlapped the low-saturation samples with bad
hole (8 steps, 16 results opened).

> **Answer:** No reliable hydrocarbon–water contact is identified in the McKee Formation of well tuhua-7. Water
> saturation is high throughout, no pay flag is set anywhere, and the few low-SW samples sit inside clay-rich, largely
> bad-hole intervals where the hydrocarbon-indicator criteria cannot operate cleanly. […] The strongest signal for any
> hydrocarbon potential is a marginal LOW_SW sample at 1991.7156 m in Z4; it is too thin, too clay-dominated, and too
> data-limited to define a contact depth.

![Saturation and porosity in the McKee Formation](images/example-contact.png "The answer's log display of the McKee Formation in tuhua-7: deep resistivity, effective porosity and bulk volume water, water saturation, the net-pay flag and the crossover flag; no pay is flagged, and bad hole is shaded. Drawn by Petrophys. Data: Taranaki Basin Curated Well Logs Dataset (New Zealand Petroleum & Minerals), CDLA-Sharing-1.0.")

The wells ship with Petrophys. Data: GeoLink, CC BY-SA 4.0; Taranaki Basin Curated Well Logs Dataset (New Zealand
Petroleum & Minerals), CDLA-Sharing-1.0; Costa Gomes, Geiger and Arnold (2022), COSTA model, Heriot-Watt University,
CC BY.

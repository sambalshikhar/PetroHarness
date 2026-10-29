---
name: shale_clay
when: Estimating or comparing shale and clay content, explaining why shale-volume methods disagree, judging clay distribution (laminated, dispersed, structural), and stating how clay affects neutron, density, sonic, resistivity and porosity.
areas: [shale_clay]
---

# shale_clay

## Consider
- Which method produced VCL in the record, with which clean and shale baselines, and were the baselines set per zone or for the whole interval?
- Could GR be raised by something other than clay? Compare GR with CGR (commonly gamma ray minus uranium; check the record's description) and with THOR, POTA and URAN.
- Do independent indicators (GR, SP, neutron-density separation, spectral GR) agree in each zone? Where they disagree, which method's assumption fails there?
- How does porosity (PHIT, PHIE) change with VCL within a zone? Does the trend look like layers of shale, or clay filling pores?
- Is gas present? It shrinks neutron-density separation and lowers neutron-density shale estimates.
- Is the 'shale' a clay-rich mudstone, a siltstone, or sand-shale laminations thinner than the logs resolve?

## Compare
- stats VCL, GR, NPHI   (shale volume and two of its indicators: n of N and the statistics in each zone)
- stats GR, SGR, CGR, THOR, POTA, URAN   (total and spectral gamma ray: n of N and the statistics in each zone)
- compare PHIN PHID   (neutron against density porosity in each zone: the two averages, the separation and its spread)
- stats PHIT, PHIE, VCL   (total and effective porosity beside shale volume: n of N and the statistics in each zone)
- crossplot PHIT VCL   (a least-squares line of total porosity on shale volume in each zone: slope, intercept, R2 and n)
- zone_contrast PHIE   (the zones split in halves by average effective porosity: thickness-weighted shale volume and lithology mix)
- step vclay   (the shale-volume method with its baselines and inputs)
- section lithology.clay_content_indicators   (the workflow's composite clay indication from GR, NPHI and PEF)
- section porosity.clay_content_impact_on_porosity_variation   (the workflow's clay-impact classes from shale volume)

## Decide
- Gamma ray index IGR = (GR-GRclean)/(GRshale-GRclean). Pick baselines from the well (histogram modes, percentiles such as 5th and 95th, or chosen clean and shale beds), per zone or per interval. Baselines often move Vsh more than the equation.
- Linear Vsh = IGR tends to overstate shale; non-linear forms (Larionov for young or older rocks, Stieber, Clavier) give lower values at mid-range IGR. None is right everywhere; calibrate to core or X-ray diffraction (XRD) clay if present.
- Neutron-density: Vsh ≈ (PHIN - PHID)/(PHINshale - PHIDshale), with both porosities on the same matrix. It works best in liquid-filled rock of known matrix; gas lowers it and a wrong matrix biases it.
- SP: Vsh ≈ 1 - PSP/SSP (SP in the shaly bed over the static SP of a thick clean water bed). It needs water-based mud and a clear mud-filtrate to formation-water resistivity contrast; hydrocarbons and thin beds lower SP and overstate Vsh.
- Where uranium is high, use CGR or THOR and POTA instead of total GR; uranium follows organic matter, phosphate or fluid flow more than clay.
- Combine indicators: each is raised by a different non-clay effect, so a common practice takes the minimum of the reliable estimates at each depth; others average them, or choose one per zone after calibration.
- Clay distribution: plot PHIT (or PHID) against VCL per zone (Thomas-Stieber). Laminated shale lowers porosity linearly toward shale porosity; dispersed clay fills pores and lowers it faster; structural shale (clay grains replacing sand grains) changes it little.
- Answer shape: quantify (values on each standard reading). Each zone's shale volume on each method the record holds, the method named; where the indicators disagree, the range they span, graded.

## Know
- Larionov: Vsh = 0.083·(2^(3.7·IGR) - 1) for Tertiary (young) rocks and 0.33·(2^(2·IGR) - 1) for older rocks. Stieber: Vsh = IGR/(3 - 2·IGR). Clavier: Vsh = 1.7 - √(3.38 - (IGR + 0.7)²).
- Shale is a fine-grained rock of clay- and silt-size particles. Clay is both a size (under 4 µm, Wentworth; 2 µm in clay mineralogy) and a sheet-silicate mineral group; silt is 4-63 µm. So shale volume exceeds clay-mineral volume.
- Clay-bound water and hydroxyls make NPHI read high in shale (often about 0.25-0.6; it varies with clay type and compaction), giving the usual NPHI-above-PHID separation on a matched-matrix display.
- Shale density ranges widely (about 2.2-2.75 g/cc) with compaction and mineralogy, so PHID in shale may read above or below its true porosity.
- Shale slows the sonic (higher DTC), so sonic porosity overstates porosity in shaly rock; young, poorly compacted shales are slower still.
- Clay conducts through exchangeable cations (cation exchange capacity, CEC), roughly smectite > illite and chlorite > kaolinite. This lowers resistivity, so Archie SW reads too high in shaly hydrocarbon-bearing rock.
- Thomas-Stieber, with clean-sand porosity φmax and shale porosity φsh: laminated φ = φmax·(1 - Vsh) + Vsh·φsh; dispersed φ = φmax - Vsh·(1 - φsh), valid while Vsh ≤ φmax; structural φ = φmax + Vsh·φsh.
- Dispersed clay lines, fills or bridges pores. Pore-filling and pore-bridging clays (for example fibrous illite) cut permeability far more than porosity.
- Spectral GR: thorium sits mainly in clays and heavy minerals; potassium in illite, mica, feldspar and glauconite; uranium in organic matter and phosphate. Th/K ratios rank minerals roughly from feldspar and glauconite (low) through illite to kaolinite (high), with wide overlaps.
- Laminae thinner than tool resolution (about 0.3-0.6 m for GR, density and neutron) are averaged with the sand; parallel conduction through the shale then lowers resistivity and can hide pay.

## Easily misread
- High GR is not proof of shale: potassium feldspar, mica, glauconite, uranium-rich organic or phosphatic rock and thorium-bearing heavy-mineral sands raise GR in rock with little clay.
- Low GR is not proof of clean rock: low-potassium clays, carbonate-rich mudstones and some silty shales can read below the chosen shale baseline; check neutron-density and spectral GR.
- Neutron-density separation also comes from matrix: dolomite and other dense minerals look shaly on a limestone-scaled display, and gas shrinks separation and hides shale.
- VCL methods disagree for physical reasons; the spread across reliable methods measures the uncertainty in VCL.
- Vshale is not Vclay; swapping them changes porosity and saturation corrections. Check which one the record's VCL represents.
- A moderate mean VCL may be clean sand interbedded with shale (laminated) or uniformly muddy sand (dispersed); the two differ strongly in quality. Look at the within-zone distribution, not only the mean.

## Do not state
- Clay species (smectite, illite, kaolinite, chlorite) or their amounts; XRD, electron microscopy or core analysis measures them, and spectral GR and PEF give only hints.
- Clay distribution as fact; a log-based distribution is a model fit that thin sections, core photographs or image logs confirm.
- CEC or clay-bound water volume from GR alone; core measurements (or NMR for bound water) establish them.
- That a shaly zone seals; SEALFLAG marks VCL above a cutoff, while seal capacity needs capillary entry pressure, lateral continuity and fracture evidence.

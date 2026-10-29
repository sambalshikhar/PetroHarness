---
name: elastic_properties
when: 'Questions on acoustic and elastic behaviour: compressional and shear velocity, Vp/Vs and Poisson''s ratio, acoustic impedance, dynamic and static moduli, lithology and fluid effects on velocity, and how far log-based geomechanics can go.'
areas: [elastic_properties]
---

# elastic_properties

## Consider
- Which sonic curves exist (DTC, DT, DTC_ALT, DTS), in what units, and how good are they (cycle skips, washouts, BAD_HOLE)? Is shear measured or estimated?
- Is VP_VS_RATIO physically possible at every sample, and where does it change: between zones (lithology) or within a zone (fluid, porosity, shale)?
- What lithology, porosity, shale content and fluid does each zone have? Velocity responds to all four at once.
- Does the sonic see the invaded zone? Its shallow reading may sense mud filtrate rather than the original fluid.
- Is RHOB reliable where impedance or moduli are computed?
- Are core tests, leak-off or minifrac tests, or image logs available to calibrate mechanical estimates?

## Compare
- stats DTC, DTS, VP_VS_RATIO, RHOB   (compressional and shear slowness, Vp/Vs and density: n of N and the statistics in each zone)
- spike_flags DTC, DTS   (sonic samples beyond 2 and 3 std of each zone's own average, with depths and z-scores; adjacent-sample jumps)
- crossplot DTC DTS   (a least-squares line of compressional on shear slowness in each zone: slope, intercept, R2 and n)
- profile ACOUSTIC_IMPEDANCE   (acoustic impedance zone by zone from the top, the zones ranked and the direction with depth in words)
- stats ACOUSTIC_IMPEDANCE, POISSON_RATIO, YOUNG_MOD, BRITTLENESS_INDEX, S_V, PP_HYDROSTATIC   (the workflow's elastic and stress curves: n of N and the statistics in each zone)
- section numerical.advanced_parameter_characterization   (how the workflow computed Vp, Vs, impedance, moduli and brittleness)
- section numerical.geomechanical_stress_analysis   (how the workflow computed overburden, hydrostatic pressure and minimum stress)

## Decide
- Use measured DTS where it exists and is good. Shear estimated from Vp (Castagna mudrock line, Greenberg-Castagna mixing) makes every shear-based result an estimate; errors grow in gas, carbonates and unusual lithologies.
- Separate lithology from fluid: compare VP_VS_RATIO with lithology indicators (PEF, RHOB, VCL) zone by zone. A Vp/Vs drop without a lithology change, with low RHOB and neutron-density crossover, supports gas; without them, consider lithology or data error.
- Crossplot Vp against Vs per zone against the mudrock line (Vp = 1.16·Vs + 1.36 km/s, brine-saturated clastics, Castagna et al. 1985; local fits differ): brine-bearing clastics lie near it, gas sands at lower Vp; carbonates follow their own trends. Closest here: crossplot DTC DTS, on slowness.
- Compare acoustic impedance (AI = RHOB × Vp) between zones. The normal-incidence reflection coefficient is (AI2 - AI1)/(AI2 + AI1), so the contrast across a boundary, not the absolute value, sets reflection strength.
- Static moduli and rock strength from logs rest on empirical correlations that differ widely between rock types (for example Eissa and Kazi 1988 for static modulus; Chang et al. 2006 compile strength fits). Core tests on similar rock calibrate them.
- Stress estimates need overburden (density integrated from surface), pore pressure and a stress model (for example uniaxial strain using Poisson's ratio). Each assumption is uncertain; calibrate with leak-off or minifrac tests.
- Brittleness indices (elastic, from Young's modulus and Poisson's ratio; or mineral-based) are relative rankings with different definitions and normalisations; rankings from different indices can disagree.
- Answer shape: quantify (values on each standard reading). Each zone's value with the logs it comes from, measured shear or estimated; where a needed log has no value, the property is not computed here, with what would provide it.

## Know
- Vp = 304,800/DTC and Vs = 304,800/DTS in m/s (slowness in us/ft); Vp/Vs = DTS/DTC. Shear waves do not travel through fluids.
- Poisson's ratio ν = (R² - 2)/(2·(R² - 1)), with R = Vp/Vs: R 1.5 gives ν 0.10, R 1.73 gives 0.25, R 2.0 gives 0.33. R below 1.41 (√2) means ν below zero, rare in rock; suspect the shear pick.
- Dynamic moduli in GPa (RHOB in g/cc, velocities in km/s): shear G = RHOB·Vs²; bulk K = RHOB·(Vp² - 4/3·Vs²); Young's E = 2G·(1 + ν); Lamé λ = RHOB·(Vp² - 2·Vs²).
- Lab Vp/Vs: limestone about 1.9, dolomite about 1.8, clean sandstone 1.6-1.7 (Pickett 1963). Typical Poisson's ratio: sandstone about 0.2, carbonate about 0.3, shale above 0.3, coal about 0.4. Ranges overlap widely.
- Gardner: density ≈ 0.31·Vp^0.25 (Vp in m/s, density in g/cc), an average for brine-saturated sediments; it fails for evaporites, coal and gas-bearing rock.
- Fluids (Gassmann): pore fluid changes the bulk modulus but not the shear modulus. A little gas lowers Vp sharply while Vs rises slightly as density falls, so Vp/Vs and Poisson's ratio drop.
- Velocity rises with less porosity, more compaction and cement, and falls with shale and fractures. Sonic porosity transforms are in porosity.
- Dynamic moduli usually exceed static ones, more so in weak, porous or microcracked rock; sonic and lab tests differ in strain amplitude, frequency, drainage and stress path.
- A monopole sonic cannot record shear where formation shear is slower than the mud ('slow formations'); dipole tools are needed there.
- Shales and laminated rocks are anisotropic (often transversely isotropic: properties differ along and across layering); a vertical well measures vertical velocities, and horizontal moduli can differ strongly.

## Easily misread
- Low Vp/Vs means gas only after lithology is ruled out: clean quartz-rich rock has low Vp/Vs even when brine-filled.
- A large Vp drop does not mean high gas saturation; a few percent gas causes most of the drop.
- Shear estimated from a Vp transform carries no independent fluid or lithology information; Vp/Vs from estimated DTS mostly returns the transform.
- Cycle skips and washouts make spurious high DTC, which inflate Vp/Vs swings and lower moduli at single samples; exclude BAD_HOLE samples and spikes before statistics.
- Dynamic moduli are not the moduli used in drilling or fracture design; using them directly overstates stiffness.
- Sonic (kHz), seismic (Hz) and checkshot velocities differ by dispersion, scale and anisotropy; a difference is not by itself an error.

## Do not state
- In situ stresses, pore pressure or fracture gradient as fact from logs alone; leak-off, minifrac and pressure tests and image-log breakouts establish them.
- Rock strength or failure behaviour as measured; only core tests measure it.
- Gas saturation from Vp/Vs or Poisson's ratio; saturation needs resistivity, pressure or test data.
- Fracture presence or orientation from velocities alone; image logs, cross-dipole shear anisotropy and core establish it.

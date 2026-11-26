# Data and acknowledgements

PetroHarness's code is released under CC BY 4.0 ([LICENSE](LICENSE)). The data below are not covered by that licence:
each keeps its source's licence and attribution, and so does material in this repository derived from it (the public
mini set's recordings in `tests/gate/mini/`, and the screenshots, figures and worked examples in `docs/`). PetroHarness
bundles no well log of its own: the wells it reads ship with [Petrophys](https://github.com/sambalshikhar/petrophys),
and the scores it reports come from [WellLogBench](https://welllogbench.com).

## WellLogBench: the results

The results in the README and on [welllogbench.com/petroharness](https://welllogbench.com/petroharness/) are scores on
WellLogBench, which is built on public data. We thank the organizations and authors who released it.

- **GeoLink.** We thank GEOLINK (<https://www.geolink-s2.com/>) for providing the North Sea well logs and lithology
  interpretations, released through the MalenoV repository (Rutherford Ildstad and Bormann, 2017,
  <https://github.com/bolgebrygg/MalenoV>); we obtained them through the well-log imputation benchmark of Gama et al.
  ("Imputation in Well Log Data: A Benchmark for Machine Learning Methods", *Computers & Geosciences*, 2025,
  [doi:10.1016/j.cageo.2024.105789](https://doi.org/10.1016/j.cageo.2024.105789); processed datasets,
  [doi:10.5281/zenodo.10987946](https://doi.org/10.5281/zenodo.10987946)). The formation tops of these wells are the
  stratigraphic picks of the Norwegian Offshore Directorate, formerly the Norwegian Petroleum Directorate
  (<https://factpages.sodir.no/>). Contains data under the Norwegian licence for Open Government data (NLOD) 2.0
  (<https://data.norge.no/nlod/en/2.0>) distributed by GEOLINK and the Norwegian Offshore Directorate.
- **COSTA.** We thank Jorge Costa Gomes, Sebastian Geiger and Daniel Arnold (Heriot-Watt University) for the COSTA
  model ("The Design of an Open-Source Carbonate Reservoir Model", *Petroleum Geoscience*, 2022,
  [doi:10.1144/petgeo2021-067](https://doi.org/10.1144/petgeo2021-067); dataset
  [doi:10.17861/6e36e28d-50d9-4e31-9790-18db4bce6e5d](https://doi.org/10.17861/6e36e28d-50d9-4e31-9790-18db4bce6e5d)),
  used under the Creative Commons Attribution 4.0 International licence (CC BY 4.0).
- **Danish data.** We thank the Geological Survey of Denmark and Greenland (GEUS) for the released well data of the
  [Subsurface Data Denmark](https://eng.geus.dk/products-services-facilities/data-and-maps/subsurface-data-denmark/)
  portal and for the standardized formation tops of Danish exploration wells, version 1.4
  ([doi:10.22008/FK2/RJ35BW](https://doi.org/10.22008/FK2/RJ35BW)), used under CC BY 4.0.

WellLogBench converted and resampled these logs, derived petrophysical curves from them with Petrophys, and built its
questions and reference answers on top of them. We thank the domain experts from ThinkOnward for their contributions
to defining the problem scope and validating the benchmark requirements.

## Petrophys's sample wells: the quick start, documentation, examples and tests

The quick start, the documentation and its screenshots, the worked examples and the recorded tests use wells that
ship with Petrophys. Their full notices are in Petrophys's
[THIRD_PARTY_DATA.md](https://github.com/sambalshikhar/petrophys/blob/main/THIRD_PARTY_DATA.md); in short:

- **GeoLink** (30/6-5, 25/5-1, 16/7-1). Data attribution: GEOLINK-S2. The public
  [GeoLink distribution](https://github.com/LukasMosser/geolink_dataset) identifies its data and analysis as
  [CC BY-SA 4.0](https://creativecommons.org/licenses/by-sa/4.0/). Contains data under the Norwegian Licence for Open
  Government Data (NLOD) distributed by the Norwegian Offshore Directorate
  ([FactPages](https://factpages.sodir.no/en), [NLOD terms](https://data.norge.no/nlod/en/2.0)).
- **COSTA** (HW-3 and other wells, Kharaib-2 interval). Jorge Costa Gomes, Sebastian Geiger and Daniel Arnold (2022),
  Heriot-Watt University, *COSTA MODEL: Hierarchical carbonate reservoir benchmarking case study*,
  [doi:10.17861/6e36e28d-50d9-4e31-9790-18db4bce6e5d](https://doi.org/10.17861/6e36e28d-50d9-4e31-9790-18db4bce6e5d),
  CC BY.
- **Taranaki** (Tuhua-7, Cheal-1). Taranaki Basin Curated Well Logs Dataset, IBM Developer Data Asset eXchange,
  curated from the New Zealand Petroleum & Minerals Online Exploration Database and Petlab (GNS Science); W.S.R. de
  Carvalho et al. (2020), version 1.0, [doi:10.5281/zenodo.3832955](https://doi.org/10.5281/zenodo.3832955).
  Licence: Community Data License Agreement - Sharing 1.0.
- **Kansas Geological Survey** (Morgan No. 1-17, KGS identifier 1046123714). The source of this material is the Kansas
  Geological Survey website at http://www.kgs.ku.edu/. All Rights Reserved. Supplied without warranty.
- **Teapot Dome** (NPR-3; Fenix WX #17-21). Teapot Dome data set released by the Rocky Mountain Oilfield Testing Center
  (RMOTC), U.S. Department of Energy, as non-proprietary data; logs acquired by Schlumberger for Fenix & Scisson.
  Supplied without warranty.

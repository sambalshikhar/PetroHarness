---
name: statistics_data_analysis
when: Questions that need summary statistics, averages, distributions, spread, correlation or regression between curves, trends with depth, comparisons between zones, outlier screening, or data coverage and missing data in log data.
areas: [statistics_data_analysis]
---

# statistics_data_analysis

## Consider
- Over what set is each number computed: one zone, all zones, a flagged subset (for example NET_PAY), or the whole interval?
- How many valid samples and how much thickness stand behind each number? How much is null or in BAD_HOLE?
- What is the shape of the data: near-symmetric, skewed, multimodal (mixed rock types), or log-normal (PERM, resistivity)?
- Are the samples independent? Depth samples closer than tool resolution repeat the same information.
- Is a relation over the whole interval driven by differences between zones rather than by variation within zones?
- Are extreme values errors (bad hole, tool spikes, depth mismatch) or real thin layers (cemented streaks, coals, anhydrite)?

## Compare
- formation_summary   (each statistic of effective porosity with the zones ranked high to low, the zones pooled and the whole interval)
- stats CURVES statistics NAMES where CONDITION   (named statistics such as std, p25, p75 or any percentile, over the samples where a condition holds)
- lithology_stats CURVES   (curves' statistics per rock type of the lithology log, the zones pooled and the whole interval)
- crossplot A B   (a least-squares line of A on B: the zone averages first, then each zone, pooled: slope, intercept, R2, n; B may be DEPTH)
- compare A B   (two curves where both have values: the zone averages first, then the averages, the difference, the rank correlation)
- spike_flags CURVES   (samples beyond 2 and 3 std of each zone's own average, with depths and z-scores: the workflow's rule)
- stats GR_GRAD, RHOB_GRAD, RDEP_GRAD, NPHI_GRAD, DTC_GRAD   (the workflow's depth gradients of the key logs: n of N and the statistics in each zone)
- section numerical.statistical_deviation_detection   (the workflow's per-sample outlier counts from z-scores)
- section numerical.log_correlation_consistency_evaluation   (the workflow's check of log pairs against their expected sign)
- section numerical.log_gradient_trend_analysis   (the workflow's trend-intensity classes from the key-log gradients)

## Decide
- Centre: mean for near-symmetric data; median for skewed data or data with outliers; geometric mean (mean of logs, transformed back) for log-normal data such as PERM.
- Spread: standard deviation (SD) and coefficient of variation (Cv = SD / mean) for near-normal data; interquartile range (IQR), P10-P90 and median absolute deviation (MAD) for skewed data; SD of log10 values for log-normal data.
- Correlation: Pearson r for linear relations; Spearman rank correlation for monotonic relations, outliers or log-normal data. Check whether the relation also holds within zones.
- Regression: regress the variable you predict on the one you know, in the space fitted (for example log10 k); assess it by residual scatter, not R-squared alone. Do not invert a fitted line to predict the other variable; fit the reverse regression.
- Significance: replace n by an effective n for autocorrelated depth samples, about n (1 - r1) / (1 + r1) with r1 the lag-one autocorrelation, or roughly thickness over tool resolution. Small effective n means wide uncertainty. Closest here: n and thickness from stats, with calc.
- Comparing zones: compare between-zone spread with within-zone spread (ANOVA F = their variance ratio; eta-squared = between-zone sum of squares over total, the share of variance zones explain). Use Kruskal-Wallis, a rank-based test, for skewed data. Overlapping IQRs mean weak separation. Closest here: each zone's and the pooled n, mean, std and quartiles from stats, with calc.
- Depth trends: fit value against depth per zone and over the interval, with slope in units per metre or foot and its scatter. Check whether an apparent trend is really a step between zones.
- Outliers: screen with quality flags first (BAD_HOLE, DRHO, CALI). Common rules: |z| > 3 SD for near-normal data; modified z = 0.6745 (x - median) / MAD > 3.5; or more than 1.5 IQR outside the quartiles (3 IQR: far out).
- Answer shape: quantify (values on each standard reading), or relate (direction, strength, where it holds and where it breaks). A statistic with its basis, its n of N and its unit; a relation with its direction in words, the coefficient with its n and range, and the zones where it holds and where it breaks.

## Know
- For positive data, arithmetic mean >= geometric mean >= harmonic mean (equal only if all values are equal). For log-normal data the median ≈ geometric mean, and arithmetic mean = geometric mean x exp(s^2 / 2), s = SD of natural logs.
- Permeability is usually close to log-normal. Porosity within one rock type is often near-normal. A mixture of rock types gives skewed or multimodal distributions.
- Weighted averages: thickness-weighted mean = sum(x h) / sum(h), which equals the plain sample mean for equal depth steps; pore-volume-weighted SW = sum(SW phi h) / sum(phi h); permeability-thickness kh = sum(k h).
- A rule of thumb for permeability heterogeneity by Cv: below about 0.5 fairly homogeneous, 0.5 to 1 heterogeneous, above 1 very heterogeneous. Bands vary by source.
- Samples needed to estimate a mean within plus or minus P percent at about 95% confidence: n = (200 Cv / P)^2, so for plus or minus 20% n = (10 Cv)^2 (the 'N-zero' rule). Use effective n.
- Standard error (SE) of a mean = SD / sqrt(effective n); an approximate 95% interval is mean ± 2 SE. At the 5% level, |r| must exceed about 2 / sqrt(effective n) to differ from zero (0.36 for n = 30).
- MAD x 1.4826 estimates SD for normal data. The 3.5 modified-z and 1.5 / 3 IQR fences are conventions, not laws.
- Logs are commonly sampled every 0.1524 m (0.5 ft), while GR, density and neutron resolve about 0.3-0.6 m, so neighbouring samples are strongly autocorrelated.
- R-squared grows with the range of x and with groups whose means differ: two separated clusters give a high R-squared even with no relation inside either cluster.
- Back-transforming a fit of log10 y gives the median, not the mean; the mean is about the back-transformed value x exp(2.65 s^2), s = residual SD in log10 units.

## Easily misread
- Simpson's paradox: a correlation over the whole interval can come only from differences between zones and can vanish or reverse within zones.
- A mean of zone means is not the interval mean unless zones are equally thick; a mean of ratios is not a ratio of sums.
- Curves built from the same inputs correlate by construction (for example PERM with the porosity it was computed from, BVW with SW, FZI with RQI). Such a correlation is not evidence of a geological link.
- With thousands of autocorrelated depth samples almost any difference looks 'significant'; assess effect size and effective n, not p-values alone. Thin zones rest on few effective samples, so their statistics are unstable.
- P10 and P90 conventions differ: in reserves practice P90 is the low case (exceeded with 90% probability), which is the 10th percentile in statistics.
- Null codes (for example -999.25) or zero-filled gaps read as data distort every statistic.

## Do not state
- That a statistical difference or correlation has a geological cause; core, lithology, mineral volumes or other logs would supply the mechanism.
- That a statistic describes the reservoir away from the well; one well samples one vertical line, and other wells or seismic would test it.
- A precise confidence level when samples are autocorrelated; effective n is only estimated, so any interval is approximate.

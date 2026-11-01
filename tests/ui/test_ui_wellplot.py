"""The well plot's scales and thinning (petroharness.ui.wellplot): a log on its conventional scale when nine in ten of
its values fall on it, else on its own P1-P99 in the conventional direction; a thinned flag keeps a set sample of each
window. The plot on a real well is checked end to end in test_ui_runs.py."""
import numpy as np

from petroharness.ui import wellplot as W


def test_a_log_on_its_conventional_scale_or_its_own_range():
    assert W._scale(np.array([0.05, 0.2, 0.31, np.nan]), (0.5, 0), False) == (0.5, 0)
    got = W._scale(np.linspace(5.0, 40.0, 200), (0.45, -0.15), False)    # neutron in percent: its own range, reversed
    assert got[0] > got[1] and 39 < got[0] <= 40 and 5 <= got[1] < 6
    assert W._scale(np.array([1.0, 10.0, 100.0]), (0.2, 2000), True) == (0.2, 2000)
    assert W._scale(np.array([np.nan, np.nan]), (0, 1), False) == (0, 1)
    lo, hi = W._scale(np.array([-1.0, 0.0, 0.001, 0.01, 0.1]), None, True)   # a log scale reads positive values only
    assert 0 < lo < hi


def test_thinning_keeps_a_thin_flagged_run():
    flag = np.zeros(1000)
    flag[503] = 1.0
    assert W._thin(flag, 10, flag=True)[50] == 1.0 and sum(W._thin(flag, 10, flag=True)) == 1.0
    assert W._thin(flag, 10) == [0.0] * 100                              # a curve: every k-th sample
    assert W._thin(np.array([1.234567, np.nan]), 1) == [1.2346, None]

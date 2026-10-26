from footballiq import spatial as SP


def test_unknown_never_becomes_observed():
    assert SP.pff_flags(None) == SP.Flags(None, None)
    assert SP.pff_flags("weird") == SP.Flags(None, None)
    assert SP.pff_flags("VISIBLE") == SP.Flags(True, False)
    assert SP.pff_flags("ESTIMATED") == SP.Flags(False, True)
    assert SP.skillcorner_flags(None) == SP.Flags(None, None)
    assert SP.skillcorner_flags(False) == SP.Flags(False, True)
    assert SP.optical_flags(None, 3.0) == SP.Flags(None, None)


def test_coverage_is_null_when_any_state_unknown():
    assert SP.coverage([True, False, True, True]) == 0.75
    assert SP.coverage([True, None]) is None
    assert SP.coverage([]) is None
    assert set(SP.PROVIDERS) == {"pff_fc", "dfl_idsse", "skillcorner", "statsbomb_360"}

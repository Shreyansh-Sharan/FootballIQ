import math

from footballiq.ml import strength as S

R = [
    S.Result("2022-01-01", "Alpha", "Beta", 3, 0, True, "Friendly"),
    S.Result("2022-02-01", "Beta", "Alpha", 1, 1, False, "FIFA World Cup qualification"),
    S.Result("2022-03-01", "Alpha", "Gamma", 2, 1, True, "FIFA World Cup"),
]


def test_ratings_use_only_earlier_results():
    r = S.Ratings("nations").fit(R)
    assert r.before("Alpha", "2022-01-01")["elo"] is None            # nothing before the first match
    a1 = r.before("Alpha", "2022-01-02")["elo"]
    assert a1 > S.START and r.before("Beta", "2022-01-02")["elo"] == 2 * S.START - a1
    assert r.before("Alpha", "2022-03-01")["games"] == 2              # same-day result excluded
    assert r.before("Alpha", "2022-12-31")["games"] == 3
    # 3-0 friendly: K 20 x goal multiplier (11+3)/8, expected 0.5 on a neutral venue
    assert a1 - S.START == 20 * (14 / 8) * 0.5


def test_form_and_missing_teams_are_nan():
    r = S.Ratings("nations").fit(R)
    f = S.prior_features(r, "Alpha", "Nowhere", "2022-12-31")
    assert f["form_ppg_for"] == (3 + 1 + 3) / 3 and f["form_gd_for"] == (3 + 0 + 1) / 3
    assert math.isnan(f["elo_against"]) and math.isnan(f["elo_diff"]) and f["rated_games_min"] == 0


def test_duplicate_feeds_count_once_and_names_resolve():
    primary = [S.Result("2016-01-10", "FC Bayern München", "Bayer 04 Leverkusen", 3, 0)]
    extra = [S.Result("2016-01-10", "Bayern Munich", "Bayer Leverkusen", 3, 0)]   # StatsBomb spelling
    r = S.Ratings("clubs").fit(primary, extra)
    assert r.resolve("Bayern Munich") == r.resolve("FC Bayern München")
    assert r.before("Bayern Munich", "2016-02-01")["games"] == 1
    assert S.club_key("Stade Rennais FC 1901") == S.club_key("Rennes")

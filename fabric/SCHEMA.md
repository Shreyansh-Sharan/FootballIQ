# Lakehouse schema: `lh_football_intelligence`

Generated from the live tables in workspace **Football Analytics Shreyansh** (folder `FootballIQ`) at 2026-10-10T02:39:35Z by `python fabric/scripts/fabric_bootstrap.py catalog`. Do not edit by hand.

Bronze is raw files under `Files/bronze/` (event-feed JSON; tracking JSON and JSONL.bz2), not tables.

| Table | Layer | Rows | Columns | Partitioned by |
|---|---|---:|---:|---|
| [`gold_match_history`](#gold_match_history) | gold | 128 | 14 | - |
| [`gold_match_summary`](#gold_match_summary) | gold | 128 | 24 | - |
| [`gold_player_match_metrics`](#gold_player_match_metrics) | gold | 1,996 | 20 | - |
| [`gold_player_metrics_1s`](#gold_player_metrics_1s) | gold | 8,701,584 | 21 | pff_game_id |
| [`gold_player_physical_match`](#gold_player_physical_match) | gold | 1,986 | 20 | - |
| [`gold_team_metrics_5s`](#gold_team_metrics_5s) | gold | 72,812 | 19 | - |
| [`gold_team_shape_5s`](#gold_team_shape_5s) | gold | 158,360 | 13 | - |
| [`gold_tracking_coverage_1m`](#gold_tracking_coverage_1m) | gold | 6,694 | 10 | - |
| [`silver_freeze_frame`](#silver_freeze_frame) | silver | 203,882 | 7 | - |
| [`silver_match`](#silver_match) | silver | 64 | 19 | - |
| [`silver_match_event`](#silver_match_event) | silver | 234,637 | 36 | - |
| [`silver_pff_event`](#silver_pff_event) | silver | 144,541 | 218 | pff_game_id |
| [`silver_pff_match`](#silver_pff_match) | silver | 64 | 25 | - |
| [`silver_pff_player`](#silver_pff_player) | silver | 2,321 | 7 | - |
| [`silver_pff_roster`](#silver_pff_roster) | silver | 3,230 | 11 | - |
| [`silver_player`](#silver_player) | silver | 3,244 | 8 | - |
| [`silver_player_position`](#silver_player_position) | silver | 260,712,096 | 16 | pff_game_id |
| [`silver_tracking_event`](#silver_tracking_event) | silver | 88,925 | 12 | - |
| [`silver_tracking_frame`](#silver_tracking_frame) | silver | 11,849,815 | 24 | pff_game_id |
| [`silver_tracking_period`](#silver_tracking_period) | silver | 134 | 14 | - |

## Silver - conformed, canonical frame

### silver_freeze_frame

203,882 rows, 64 files, 57.6 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `event_id` | `string` | yes |
| 1 | `match_elapsed_ms` | `bigint` | yes |
| 2 | `match_id` | `string` | yes |
| 3 | `players` | `string` | yes |
| 4 | `source` | `string` | yes |
| 5 | `visible_area` | `string` | yes |
| 6 | `ingested_at_utc` | `timestamp` | yes |

### silver_match

64 rows, 64 files, 0.9 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `attribution` | `string` | yes |
| 1 | `away` | `string` | yes |
| 2 | `canonical_match_id` | `string` | yes |
| 3 | `competition` | `string` | yes |
| 4 | `direction_convention` | `string` | yes |
| 5 | `duration_ms` | `bigint` | yes |
| 6 | `home` | `string` | yes |
| 7 | `kickoff_source` | `string` | yes |
| 8 | `kickoff_utc` | `string` | yes |
| 9 | `periods` | `string` | yes |
| 10 | `players` | `string` | yes |
| 11 | `referee` | `string` | yes |
| 12 | `result` | `string` | yes |
| 13 | `season` | `string` | yes |
| 14 | `source_ids` | `string` | yes |
| 15 | `stadium` | `string` | yes |
| 16 | `stage` | `string` | yes |
| 17 | `statsbomb_match_id` | `bigint` | yes |
| 18 | `ingested_at_utc` | `timestamp` | yes |

### silver_match_event

234,637 rows, 64 files, 27.5 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `card` | `string` | yes |
| 1 | `clock_label` | `string` | yes |
| 2 | `duration_ms` | `bigint` | yes |
| 3 | `end_x_m` | `double` | yes |
| 4 | `end_y_m` | `double` | yes |
| 5 | `event_id` | `string` | yes |
| 6 | `has_freeze_frame` | `boolean` | yes |
| 7 | `is_goal` | `boolean` | yes |
| 8 | `is_own_goal` | `boolean` | yes |
| 9 | `is_shootout` | `boolean` | yes |
| 10 | `match_elapsed_ms` | `bigint` | yes |
| 11 | `match_id` | `string` | yes |
| 12 | `observed` | `boolean` | yes |
| 13 | `outcome` | `string` | yes |
| 14 | `period` | `bigint` | yes |
| 15 | `period_elapsed_ms` | `bigint` | yes |
| 16 | `play_pattern` | `string` | yes |
| 17 | `player_id` | `string` | yes |
| 18 | `player_name` | `string` | yes |
| 19 | `possession` | `bigint` | yes |
| 20 | `possession_team_id` | `string` | yes |
| 21 | `provider` | `string` | yes |
| 22 | `provider_xg` | `double` | yes |
| 23 | `recipient_id` | `string` | yes |
| 24 | `recipient_name` | `string` | yes |
| 25 | `related_events` | `string` | yes |
| 26 | `source_location` | `string` | yes |
| 27 | `source_sequence` | `bigint` | yes |
| 28 | `subtype` | `string` | yes |
| 29 | `team_id` | `string` | yes |
| 30 | `team_name` | `string` | yes |
| 31 | `type` | `string` | yes |
| 32 | `under_pressure` | `boolean` | yes |
| 33 | `x_m` | `double` | yes |
| 34 | `y_m` | `double` | yes |
| 35 | `ingested_at_utc` | `timestamp` | yes |

### silver_pff_event

144,541 rows, 64 files, 99.9 MB, partitioned by `pff_game_id`

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `pff_game_id` | `bigint` | yes |
| 1 | `game_event_id` | `bigint` | yes |
| 2 | `match_id` | `string` | yes |
| 3 | `possession_event_id` | `bigint` | yes |
| 4 | `sequence` | `double` | yes |
| 5 | `start_time_s` | `double` | yes |
| 6 | `end_time_s` | `double` | yes |
| 7 | `event_time_s` | `double` | yes |
| 8 | `duration_s` | `double` | yes |
| 9 | `team_attacking_direction` | `string` | yes |
| 10 | `ball_x_raw` | `double` | yes |
| 11 | `ball_y_raw` | `double` | yes |
| 12 | `ball_z_raw` | `double` | yes |
| 13 | `home_players_json` | `string` | yes |
| 14 | `away_players_json` | `string` | yes |
| 15 | `grades_json` | `string` | yes |
| 16 | `ge_earlyDistribution` | `boolean` | yes |
| 17 | `ge_endType` | `string` | yes |
| 18 | `ge_gameEventType` | `string` | yes |
| 19 | `ge_homeTeam` | `boolean` | yes |
| 20 | `ge_initialNonEvent` | `boolean` | yes |
| 21 | `ge_outType` | `string` | yes |
| 22 | `ge_period` | `bigint` | yes |
| 23 | `ge_playerId` | `bigint` | yes |
| 24 | `ge_playerName` | `string` | yes |
| 25 | `ge_playerOffId` | `bigint` | yes |
| 26 | `ge_playerOffName` | `string` | yes |
| 27 | `ge_playerOffType` | `string` | yes |
| 28 | `ge_playerOnId` | `bigint` | yes |
| 29 | `ge_playerOnName` | `string` | yes |
| 30 | `ge_setpieceType` | `string` | yes |
| 31 | `ge_startFormattedGameClock` | `string` | yes |
| 32 | `ge_startGameClock` | `bigint` | yes |
| 33 | `ge_subType` | `string` | yes |
| 34 | `ge_teamId` | `bigint` | yes |
| 35 | `ge_teamName` | `string` | yes |
| 36 | `ge_touches` | `bigint` | yes |
| 37 | `ge_touchesInBox` | `bigint` | yes |
| 38 | `ge_videoMissing` | `boolean` | yes |
| 39 | `ge_videoUrl` | `string` | yes |
| 40 | `pe_accuracyType` | `string` | yes |
| 41 | `pe_additionalDueler2PlayerId` | `bigint` | yes |
| 42 | `pe_additionalDueler2PlayerName` | `string` | yes |
| 43 | `pe_additionalDuelerPlayerId` | `bigint` | yes |
| 44 | `pe_additionalDuelerPlayerName` | `string` | yes |
| 45 | `pe_awayDuelPlayerId` | `bigint` | yes |
| 46 | `pe_awayDuelPlayerName` | `string` | yes |
| 47 | `pe_badParry` | `boolean` | yes |
| 48 | `pe_ballCarrierPlayerId` | `bigint` | yes |
| 49 | `pe_ballCarrierPlayerName` | `string` | yes |
| 50 | `pe_ballCarryOutcome` | `string` | yes |
| 51 | `pe_ballHeightType` | `string` | yes |
| 52 | `pe_ballMoving` | `boolean` | yes |
| 53 | `pe_betterOptionPlayerId` | `bigint` | yes |
| 54 | `pe_betterOptionPlayerName` | `string` | yes |
| 55 | `pe_betterOptionTime` | `string` | yes |
| 56 | `pe_betterOptionType` | `string` | yes |
| 57 | `pe_blockerPlayerId` | `bigint` | yes |
| 58 | `pe_blockerPlayerName` | `string` | yes |
| 59 | `pe_bodyMovementType` | `string` | yes |
| 60 | `pe_bodyType` | `string` | yes |
| 61 | `pe_carrierPlayerId` | `bigint` | yes |
| 62 | `pe_carrierPlayerName` | `string` | yes |
| 63 | `pe_carryDefenderPlayerId` | `bigint` | yes |
| 64 | `pe_carryDefenderPlayerName` | `string` | yes |
| 65 | `pe_carryIntent` | `string` | yes |
| 66 | `pe_carrySuccessful` | `string` | yes |
| 67 | `pe_carryType` | `string` | yes |
| 68 | `pe_challengeKeeperPlayerId` | `bigint` | yes |
| 69 | `pe_challengeKeeperPlayerName` | `string` | yes |
| 70 | `pe_challengeOutcomeType` | `string` | yes |
| 71 | `pe_challengeType` | `string` | yes |
| 72 | `pe_challengeWinnerPlayerId` | `bigint` | yes |
| 73 | `pe_challengeWinnerPlayerName` | `string` | yes |
| 74 | `pe_challenger2PlayerId` | `bigint` | yes |
| 75 | `pe_challenger2PlayerName` | `string` | yes |
| 76 | `pe_challengerPlayerId` | `bigint` | yes |
| 77 | `pe_challengerPlayerName` | `string` | yes |
| 78 | `pe_clearanceOutcomeType` | `string` | yes |
| 79 | `pe_clearerPlayerId` | `bigint` | yes |
| 80 | `pe_clearerPlayerName` | `string` | yes |
| 81 | `pe_closingDown2PlayerId` | `bigint` | yes |
| 82 | `pe_closingDown2PlayerName` | `string` | yes |
| 83 | `pe_closingDownPlayerId` | `bigint` | yes |
| 84 | `pe_closingDownPlayerName` | `string` | yes |
| 85 | `pe_createsSpace` | `boolean` | yes |
| 86 | `pe_crossOutcomeType` | `string` | yes |
| 87 | `pe_crossType` | `string` | yes |
| 88 | `pe_crossZoneType` | `string` | yes |
| 89 | `pe_crosserPlayerId` | `bigint` | yes |
| 90 | `pe_crosserPlayerName` | `string` | yes |
| 91 | `pe_csGrade` | `double` | yes |
| 92 | `pe_csPlayerId` | `bigint` | yes |
| 93 | `pe_csPlayerName` | `string` | yes |
| 94 | `pe_dab2PlayerId` | `bigint` | yes |
| 95 | `pe_dab2PlayerName` | `string` | yes |
| 96 | `pe_dabPlayerId` | `bigint` | yes |
| 97 | `pe_dabPlayerName` | `string` | yes |
| 98 | `pe_defenderPlayerId` | `bigint` | yes |
| 99 | `pe_defenderPlayerName` | `string` | yes |
| 100 | `pe_deflectorPlayerId` | `bigint` | yes |
| 101 | `pe_deflectorPlayerName` | `string` | yes |
| 102 | `pe_discipline2PlayerId` | `bigint` | yes |
| 103 | `pe_discipline2PlayerName` | `string` | yes |
| 104 | `pe_discipline3PlayerId` | `bigint` | yes |
| 105 | `pe_discipline3PlayerName` | `string` | yes |
| 106 | `pe_disciplinePlayerId` | `bigint` | yes |
| 107 | `pe_disciplinePlayerName` | `string` | yes |
| 108 | `pe_dribbleType` | `string` | yes |
| 109 | `pe_dribblerPlayerId` | `bigint` | yes |
| 110 | `pe_dribblerPlayerName` | `string` | yes |
| 111 | `pe_eventVideoUrl` | `string` | yes |
| 112 | `pe_failedBlocker2PlayerId` | `bigint` | yes |
| 113 | `pe_failedBlocker2PlayerName` | `string` | yes |
| 114 | `pe_failedBlocker3PlayerId` | `bigint` | yes |
| 115 | `pe_failedBlocker3PlayerName` | `string` | yes |
| 116 | `pe_failedBlockerPlayerId` | `bigint` | yes |
| 117 | `pe_failedBlockerPlayerName` | `string` | yes |
| 118 | `pe_failedClearerPlayerId` | `bigint` | yes |
| 119 | `pe_failedClearerPlayerName` | `string` | yes |
| 120 | `pe_failedCrosserPlayerId` | `bigint` | yes |
| 121 | `pe_failedCrosserPlayerName` | `string` | yes |
| 122 | `pe_failedPasserPlayerId` | `bigint` | yes |
| 123 | `pe_failedPasserPlayerName` | `string` | yes |
| 124 | `pe_failedShooterPlayerId` | `bigint` | yes |
| 125 | `pe_failedShooterPlayerName` | `string` | yes |
| 126 | `pe_formattedGameClock` | `string` | yes |
| 127 | `pe_gameClock` | `bigint` | yes |
| 128 | `pe_glClearerPlayerId` | `bigint` | yes |
| 129 | `pe_glClearerPlayerName` | `string` | yes |
| 130 | `pe_highPointType` | `string` | yes |
| 131 | `pe_homeDuelPlayerId` | `bigint` | yes |
| 132 | `pe_homeDuelPlayerName` | `string` | yes |
| 133 | `pe_incompletionReasonType` | `string` | yes |
| 134 | `pe_keeperPlayerId` | `bigint` | yes |
| 135 | `pe_keeperPlayerName` | `string` | yes |
| 136 | `pe_keeperTouchType` | `string` | yes |
| 137 | `pe_linesBrokenType` | `string` | yes |
| 138 | `pe_missedTouchPlayerId` | `bigint` | yes |
| 139 | `pe_missedTouchPlayerName` | `string` | yes |
| 140 | `pe_missedTouchType` | `string` | yes |
| 141 | `pe_movement2PlayerId` | `bigint` | yes |
| 142 | `pe_movement2PlayerName` | `string` | yes |
| 143 | `pe_movement3PlayerId` | `bigint` | yes |
| 144 | `pe_movement3PlayerName` | `string` | yes |
| 145 | `pe_movementPlayerId` | `bigint` | yes |
| 146 | `pe_movementPlayerName` | `string` | yes |
| 147 | `pe_nonEvent` | `boolean` | yes |
| 148 | `pe_opportunityType` | `string` | yes |
| 149 | `pe_originateType` | `string` | yes |
| 150 | `pe_passOutcomeType` | `string` | yes |
| 151 | `pe_passType` | `string` | yes |
| 152 | `pe_passerPlayerId` | `bigint` | yes |
| 153 | `pe_passerPlayerName` | `string` | yes |
| 154 | `pe_position2PlayerId` | `bigint` | yes |
| 155 | `pe_position2PlayerName` | `string` | yes |
| 156 | `pe_position3PlayerId` | `bigint` | yes |
| 157 | `pe_position3PlayerName` | `string` | yes |
| 158 | `pe_position4PlayerId` | `bigint` | yes |
| 159 | `pe_position4PlayerName` | `string` | yes |
| 160 | `pe_position5PlayerId` | `bigint` | yes |
| 161 | `pe_position5PlayerName` | `string` | yes |
| 162 | `pe_positionPlayerId` | `bigint` | yes |
| 163 | `pe_positionPlayerName` | `string` | yes |
| 164 | `pe_possessionEventType` | `string` | yes |
| 165 | `pe_pressurePlayerId` | `bigint` | yes |
| 166 | `pe_pressurePlayerName` | `string` | yes |
| 167 | `pe_pressureType` | `string` | yes |
| 168 | `pe_reboundOutcomeType` | `string` | yes |
| 169 | `pe_rebounderPlayerId` | `bigint` | yes |
| 170 | `pe_rebounderPlayerName` | `string` | yes |
| 171 | `pe_receiverFacingType` | `string` | yes |
| 172 | `pe_receiverPlayerId` | `bigint` | yes |
| 173 | `pe_receiverPlayerName` | `string` | yes |
| 174 | `pe_saveHeightType` | `string` | yes |
| 175 | `pe_saveReboundType` | `string` | yes |
| 176 | `pe_saveable` | `boolean` | yes |
| 177 | `pe_secondIncompletionReasonType` | `string` | yes |
| 178 | `pe_shooterPlayerId` | `bigint` | yes |
| 179 | `pe_shooterPlayerName` | `string` | yes |
| 180 | `pe_shotInitialHeightType` | `string` | yes |
| 181 | `pe_shotNatureType` | `string` | yes |
| 182 | `pe_shotOutcomeType` | `string` | yes |
| 183 | `pe_shotType` | `string` | yes |
| 184 | `pe_tackleAttemptType` | `string` | yes |
| 185 | `pe_targetFacingType` | `string` | yes |
| 186 | `pe_targetPlayerId` | `bigint` | yes |
| 187 | `pe_targetPlayerName` | `string` | yes |
| 188 | `pe_touchOutcomeType` | `string` | yes |
| 189 | `pe_touchPlayerId` | `bigint` | yes |
| 190 | `pe_touchPlayerName` | `string` | yes |
| 191 | `pe_touchType` | `string` | yes |
| 192 | `pe_trickType` | `string` | yes |
| 193 | `foul_correctDecision` | `boolean` | yes |
| 194 | `foul_finalCulpritPlayerId` | `bigint` | yes |
| 195 | `foul_finalCulpritPlayerName` | `string` | yes |
| 196 | `foul_finalFoulOutcomeType` | `string` | yes |
| 197 | `foul_finalOffenseType` | `string` | yes |
| 198 | `foul_foulType` | `string` | yes |
| 199 | `foul_onFieldCulpritPlayerId` | `bigint` | yes |
| 200 | `foul_onFieldCulpritPlayerName` | `string` | yes |
| 201 | `foul_onFieldFoulOutcomeType` | `string` | yes |
| 202 | `foul_onFieldOffenseType` | `string` | yes |
| 203 | `foul_var` | `boolean` | yes |
| 204 | `foul_varReasonType` | `string` | yes |
| 205 | `foul_victimPlayerId` | `bigint` | yes |
| 206 | `foul_victimPlayerName` | `string` | yes |
| 207 | `touch_facingType` | `string` | yes |
| 208 | `touch_initialBodyType` | `string` | yes |
| 209 | `touch_initialHeightType` | `string` | yes |
| 210 | `touch_initialPressurePlayerId` | `bigint` | yes |
| 211 | `touch_initialPressurePlayerName` | `string` | yes |
| 212 | `touch_initialPressureType` | `string` | yes |
| 213 | `touch_initialTouchType` | `string` | yes |
| 214 | `team_id` | `string` | yes |
| 215 | `ingested_at_utc` | `timestamp` | yes |
| 216 | `frame_num` | `bigint` | yes |
| 217 | `match_elapsed_ms` | `bigint` | yes |

### silver_pff_match

64 rows, 16 files, 0.2 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `pff_game_id` | `bigint` | yes |
| 1 | `kickoff_utc` | `timestamp` | yes |
| 2 | `match_date` | `date` | yes |
| 3 | `competition` | `string` | yes |
| 4 | `season` | `string` | yes |
| 5 | `week` | `int` | yes |
| 6 | `home_team_name` | `string` | yes |
| 7 | `home_team_short` | `string` | yes |
| 8 | `home_pff_team_id` | `string` | yes |
| 9 | `away_team_name` | `string` | yes |
| 10 | `away_team_short` | `string` | yes |
| 11 | `away_pff_team_id` | `string` | yes |
| 12 | `home_kit_color` | `string` | yes |
| 13 | `away_kit_color` | `string` | yes |
| 14 | `stadium` | `string` | yes |
| 15 | `pitch_length_m` | `double` | yes |
| 16 | `pitch_width_m` | `double` | yes |
| 17 | `fps` | `double` | yes |
| 18 | `meta_home_start_left` | `boolean` | yes |
| 19 | `meta_home_start_left_et` | `boolean` | yes |
| 20 | `video_url` | `string` | yes |
| 21 | `home_team_id` | `string` | yes |
| 22 | `away_team_id` | `string` | yes |
| 23 | `match_id` | `string` | yes |
| 24 | `ingested_at_utc` | `timestamp` | yes |

### silver_pff_player

2,321 rows, 1 files, 0.1 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `pff_player_id` | `string` | yes |
| 1 | `player_name` | `string` | yes |
| 2 | `first_name` | `string` | yes |
| 3 | `last_name` | `string` | yes |
| 4 | `dob` | `date` | yes |
| 5 | `height_cm` | `double` | yes |
| 6 | `position_group` | `string` | yes |

### silver_pff_roster

3,230 rows, 16 files, 0.2 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `pff_game_id` | `bigint` | yes |
| 2 | `pff_player_id` | `string` | yes |
| 3 | `player_name` | `string` | yes |
| 4 | `jersey_num` | `string` | yes |
| 5 | `position_group` | `string` | yes |
| 6 | `started` | `boolean` | yes |
| 7 | `pff_team_id` | `string` | yes |
| 8 | `team_name` | `string` | yes |
| 9 | `team_id` | `string` | yes |
| 10 | `player_id` | `string` | yes |

### silver_player

3,244 rows, 64 files, 0.4 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `jersey_number` | `bigint` | yes |
| 1 | `match_id` | `string` | yes |
| 2 | `name` | `string` | yes |
| 3 | `nickname` | `string` | yes |
| 4 | `player_id` | `string` | yes |
| 5 | `starter` | `boolean` | yes |
| 6 | `statsbomb_id` | `bigint` | yes |
| 7 | `team_id` | `string` | yes |

### silver_player_position

260,712,096 rows, 77 files, 5,012.0 MB, partitioned by `pff_game_id`

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `pff_game_id` | `bigint` | yes |
| 2 | `period` | `int` | yes |
| 3 | `frame_num` | `bigint` | yes |
| 4 | `match_elapsed_ms` | `bigint` | yes |
| 5 | `team_id` | `string` | yes |
| 6 | `side` | `string` | yes |
| 7 | `jersey_num` | `string` | yes |
| 8 | `x_m` | `double` | yes |
| 9 | `y_m` | `double` | yes |
| 10 | `x_smooth_m` | `double` | yes |
| 11 | `y_smooth_m` | `double` | yes |
| 12 | `speed_mps` | `double` | yes |
| 13 | `visibility` | `string` | yes |
| 14 | `confidence` | `string` | yes |
| 15 | `observed` | `boolean` | yes |

### silver_tracking_event

88,925 rows, 8 files, 2.0 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `pff_game_id` | `bigint` | yes |
| 2 | `game_event_type` | `string` | yes |
| 3 | `formatted_game_clock` | `string` | yes |
| 4 | `pff_player_id` | `string` | yes |
| 5 | `player_name` | `string` | yes |
| 6 | `jersey_num` | `string` | yes |
| 7 | `team_name` | `string` | yes |
| 8 | `team_id` | `string` | yes |
| 9 | `home_ball` | `boolean` | yes |
| 10 | `start_frame` | `bigint` | yes |
| 11 | `end_frame` | `bigint` | yes |

### silver_tracking_frame

11,849,815 rows, 64 files, 395.6 MB, partitioned by `pff_game_id`

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `pff_game_id` | `bigint` | yes |
| 2 | `period` | `int` | yes |
| 3 | `frame_num` | `bigint` | yes |
| 4 | `video_time_ms` | `bigint` | yes |
| 5 | `period_elapsed_ms` | `bigint` | yes |
| 6 | `match_elapsed_ms` | `bigint` | yes |
| 7 | `ball_x_m` | `double` | yes |
| 8 | `ball_y_m` | `double` | yes |
| 9 | `ball_z_m` | `double` | yes |
| 10 | `ball_visibility` | `string` | yes |
| 11 | `ball_observed` | `boolean` | yes |
| 12 | `ball_present` | `boolean` | yes |
| 13 | `ball_x_smooth_m` | `double` | yes |
| 14 | `ball_y_smooth_m` | `double` | yes |
| 15 | `game_event_id` | `bigint` | yes |
| 16 | `possession_event_id` | `bigint` | yes |
| 17 | `game_event_ids` | `array<bigint>` | yes |
| 18 | `possession_event_ids` | `array<bigint>` | yes |
| 19 | `source_rows` | `bigint` | yes |
| 20 | `game_event_type` | `string` | yes |
| 21 | `possession_event_type` | `string` | yes |
| 22 | `home_players_n` | `int` | yes |
| 23 | `away_players_n` | `int` | yes |

### silver_tracking_period

134 rows, 1 files, 0.0 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `pff_game_id` | `bigint` | yes |
| 2 | `period` | `int` | yes |
| 3 | `start_frame` | `bigint` | yes |
| 4 | `end_frame` | `bigint` | yes |
| 5 | `frames` | `bigint` | yes |
| 6 | `pff_duration_ms` | `bigint` | yes |
| 7 | `start_match_ms` | `bigint` | yes |
| 8 | `clock_source` | `string` | yes |
| 9 | `home_gk_jersey` | `string` | yes |
| 10 | `home_gk_mean_x` | `double` | yes |
| 11 | `home_attacks_positive_x` | `boolean` | yes |
| 12 | `meta_home_attacks_positive_x` | `boolean` | yes |
| 13 | `direction_agrees_with_metadata` | `boolean` | yes |

## Gold - analytics-ready

### gold_match_history

128 rows, 1 files, 0.0 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `team_id` | `string` | yes |
| 1 | `opponent_id` | `string` | yes |
| 2 | `match_id` | `string` | yes |
| 3 | `competition` | `string` | yes |
| 4 | `season` | `string` | yes |
| 5 | `match_date` | `date` | yes |
| 6 | `goals` | `bigint` | yes |
| 7 | `goals_against` | `bigint` | yes |
| 8 | `result` | `string` | yes |
| 9 | `shots` | `bigint` | yes |
| 10 | `provider_xg` | `double` | yes |
| 11 | `pass_accuracy_pct` | `double` | yes |
| 12 | `as_of_time` | `timestamp` | yes |
| 13 | `provider` | `string` | yes |

### gold_match_summary

128 rows, 1 files, 0.0 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `team_id` | `string` | yes |
| 2 | `goals` | `bigint` | yes |
| 3 | `shots` | `bigint` | yes |
| 4 | `shots_on_target` | `bigint` | yes |
| 5 | `provider_xg` | `double` | yes |
| 6 | `passes_attempted` | `bigint` | yes |
| 7 | `passes_completed` | `bigint` | yes |
| 8 | `corners` | `bigint` | yes |
| 9 | `fouls` | `bigint` | yes |
| 10 | `yellow_cards` | `bigint` | yes |
| 11 | `red_cards` | `bigint` | yes |
| 12 | `tackles` | `bigint` | yes |
| 13 | `tackles_won` | `bigint` | yes |
| 14 | `pressures` | `bigint` | yes |
| 15 | `pass_accuracy_pct` | `double` | yes |
| 16 | `opponent_id` | `string` | yes |
| 17 | `goals_against` | `bigint` | yes |
| 18 | `competition` | `string` | yes |
| 19 | `season` | `string` | yes |
| 20 | `kickoff_source` | `string` | yes |
| 21 | `match_date` | `date` | yes |
| 22 | `result` | `string` | yes |
| 23 | `built_at_utc` | `timestamp` | yes |

### gold_player_match_metrics

1,996 rows, 1 files, 0.1 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `team_id` | `string` | yes |
| 2 | `player_id` | `string` | yes |
| 3 | `player_name` | `string` | yes |
| 4 | `goals` | `bigint` | yes |
| 5 | `shots` | `bigint` | yes |
| 6 | `shots_on_target` | `bigint` | yes |
| 7 | `provider_xg` | `double` | yes |
| 8 | `passes_attempted` | `bigint` | yes |
| 9 | `passes_completed` | `bigint` | yes |
| 10 | `corners` | `bigint` | yes |
| 11 | `fouls` | `bigint` | yes |
| 12 | `yellow_cards` | `bigint` | yes |
| 13 | `red_cards` | `bigint` | yes |
| 14 | `tackles` | `bigint` | yes |
| 15 | `tackles_won` | `bigint` | yes |
| 16 | `pressures` | `bigint` | yes |
| 17 | `actions` | `bigint` | yes |
| 18 | `pass_accuracy_pct` | `double` | yes |
| 19 | `built_at_utc` | `timestamp` | yes |

### gold_player_metrics_1s

8,701,584 rows, 64 files, 78.9 MB, partitioned by `pff_game_id`

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `team_id` | `string` | yes |
| 2 | `jersey_num` | `string` | yes |
| 3 | `pff_game_id` | `bigint` | yes |
| 4 | `period` | `int` | yes |
| 5 | `side` | `string` | yes |
| 6 | `second` | `bigint` | yes |
| 7 | `x_m` | `double` | yes |
| 8 | `y_m` | `double` | yes |
| 9 | `avg_speed_mps` | `double` | yes |
| 10 | `max_speed_mps` | `double` | yes |
| 11 | `distance_m` | `double` | yes |
| 12 | `frames` | `bigint` | yes |
| 13 | `observed_frames` | `bigint` | yes |
| 14 | `observed_pct` | `double` | yes |
| 15 | `player_id` | `string` | yes |
| 16 | `pff_player_id` | `string` | yes |
| 17 | `player_name` | `string` | yes |
| 18 | `position_group` | `string` | yes |
| 19 | `started` | `boolean` | yes |
| 20 | `built_at_utc` | `timestamp` | yes |

### gold_player_physical_match

1,986 rows, 160 files, 1.7 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `team_id` | `string` | yes |
| 2 | `jersey_num` | `string` | yes |
| 3 | `pff_game_id` | `bigint` | yes |
| 4 | `side` | `string` | yes |
| 5 | `distance_m` | `double` | yes |
| 6 | `hsr_distance_m` | `double` | yes |
| 7 | `sprint_distance_m` | `double` | yes |
| 8 | `top_speed_mps` | `double` | yes |
| 9 | `tracked_span_min` | `double` | yes |
| 10 | `frames` | `bigint` | yes |
| 11 | `observed_frames` | `bigint` | yes |
| 12 | `observed_pct` | `double` | yes |
| 13 | `thresholds` | `string` | yes |
| 14 | `player_id` | `string` | yes |
| 15 | `pff_player_id` | `string` | yes |
| 16 | `player_name` | `string` | yes |
| 17 | `position_group` | `string` | yes |
| 18 | `started` | `boolean` | yes |
| 19 | `built_at_utc` | `timestamp` | yes |

### gold_team_metrics_5s

72,812 rows, 2 files, 0.4 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `team_id` | `string` | yes |
| 2 | `period` | `bigint` | yes |
| 3 | `bin_start_ms` | `bigint` | yes |
| 4 | `goals` | `bigint` | yes |
| 5 | `shots` | `bigint` | yes |
| 6 | `shots_on_target` | `bigint` | yes |
| 7 | `provider_xg` | `double` | yes |
| 8 | `passes_attempted` | `bigint` | yes |
| 9 | `passes_completed` | `bigint` | yes |
| 10 | `corners` | `bigint` | yes |
| 11 | `fouls` | `bigint` | yes |
| 12 | `yellow_cards` | `bigint` | yes |
| 13 | `red_cards` | `bigint` | yes |
| 14 | `tackles` | `bigint` | yes |
| 15 | `tackles_won` | `bigint` | yes |
| 16 | `pressures` | `bigint` | yes |
| 17 | `source` | `string` | yes |
| 18 | `built_at_utc` | `timestamp` | yes |

### gold_team_shape_5s

158,360 rows, 24 files, 4.0 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `match_id` | `string` | yes |
| 1 | `pff_game_id` | `bigint` | yes |
| 2 | `period` | `int` | yes |
| 3 | `team_id` | `string` | yes |
| 4 | `bin_start_ms` | `bigint` | yes |
| 5 | `centroid_x_m` | `double` | yes |
| 6 | `centroid_y_m` | `double` | yes |
| 7 | `width_m` | `double` | yes |
| 8 | `depth_m` | `double` | yes |
| 9 | `block_area_m2` | `double` | yes |
| 10 | `avg_outfield_players` | `double` | yes |
| 11 | `observed_pct` | `double` | yes |
| 12 | `built_at_utc` | `timestamp` | yes |

### gold_tracking_coverage_1m

6,694 rows, 1 files, 0.1 MB

| # | Column | Type | Nullable |
|---:|---|---|---|
| 0 | `pff_game_id` | `bigint` | yes |
| 1 | `period` | `int` | yes |
| 2 | `minute` | `int` | yes |
| 3 | `match_id` | `string` | yes |
| 4 | `frames` | `bigint` | yes |
| 5 | `ball_present_pct` | `double` | yes |
| 6 | `ball_observed_pct` | `double` | yes |
| 7 | `avg_players_per_frame` | `double` | yes |
| 8 | `player_observed_pct` | `double` | yes |
| 9 | `built_at_utc` | `timestamp` | yes |

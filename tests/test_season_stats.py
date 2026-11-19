import pandas as pd
import pytest
from fastapi.testclient import TestClient
from src.services.season_stats import build_season_stats


def sample():
    rows=[]
    for player in range(1,9):
        for game in range(6):
            rows.append({'player_id':player,'game_id':str(game),'season':'2026-27','min':30,
                'pts':30 if player==1 else (1000 if player==8 else 10+player),
                'reb':1 if player==1 else 10,'ast':3,'stl':1,'blk':1,
                'tov':1 if player==1 else 5,'plus_minus':-10 if player==1 else 5,
                'fgm':8 if player==1 else 4,'fga':12,'fg3m':3 if player==1 else 1,'fg3a':6})
    positions=pd.DataFrame([{'player_id':pid,'position_raw':'PG' if pid==8 else 'C'} for pid in range(1,9)])
    return pd.DataFrame(rows),positions


def test_tiers_and_ranks_compare_entire_league_and_reverse_turnovers():
    logs,positions=sample()
    result=build_season_stats(1,logs,positions,'2026-27')
    stats={stat['key']:stat for stat in result['stats']}
    assert len(result['stats'][:10])==10
    assert result['games_played']==6
    assert result['position_label']=='Centers'
    assert result['comparison']['scope']=='league'
    assert stats['pts']['peer_count']==8
    assert stats['pts']['league_average']==pytest.approx(139.62)
    assert stats['pts']['tier']=='below'
    assert stats['reb']['tier']=='below'
    assert stats['ast']['tier']=='average'
    assert stats['tov']['tier']=='above'
    assert stats['pts']['rank']==2
    assert stats['tov']['rank']==1
    assert stats['reb']['rank']==8
    assert stats['ast']['rank']==1  # Equal values share rank.
    assert stats['pts']['rank_out_of']==8
    assert stats['plus_minus']['tier']=='below'
    assert stats['fg3_pct']['value']==50


def test_percentages_use_total_makes_over_total_attempts_and_no_shots_stay_missing():
    logs,positions=sample()
    own=logs.player_id.eq(1)
    logs.loc[own,'fgm']=[1,9,0,0,0,0]
    logs.loc[own,'fga']=[1,19,0,0,0,0]
    logs.loc[own,'fg3a']=0
    stats={s['key']:s for s in build_season_stats(1,logs,positions,'2026-27')['stats']}
    assert stats['fg_pct']['value']==50
    assert stats['fg_pct']['tier']=='unrated'  # Only 20 attempts.
    assert stats['fg_pct']['rank'] is None
    assert stats['fg3_pct']['value'] is None
    assert stats['fg3_pct']['tier']=='unrated'


def test_season_filter_deduplication_and_unknown_position_still_ranked():
    logs,positions=sample()
    older=logs.assign(season='2025-26',pts=9999)
    logs=pd.concat([logs,logs.iloc[[0]],older],ignore_index=True)
    result=build_season_stats(1,logs,positions,'2026-27')
    assert result['games_played']==6
    assert result['stats'][0]['value']==30
    positions.loc[positions.player_id.eq(1),'position_raw']='Unknown'
    result=build_season_stats(1,logs,positions,'2026-27')
    assert result['stats'][0]['rank']==2
    assert result['stats'][0]['peer_count']==8


def test_all_positions_share_benchmark_and_small_samples_are_unrated():
    logs,positions=sample()
    positions.loc[positions.player_id.between(2,7),'position_raw']='PF'
    result=build_season_stats(1,logs,positions,'2026-27')
    assert all(stat['peer_count']==8 for stat in result['stats'][:10])
    assert result['stats'][0]['rank']==2
    logs,positions=sample()
    logs=logs[~((logs.player_id==1)&(logs.game_id.isin(['3','4','5'])))]
    result=build_season_stats(1,logs,positions,'2026-27')
    assert all(stat['tier']=='unrated' for stat in result['stats'][:10])


def test_endpoint_returns_season_stats_and_rejects_unknown_player(monkeypatch):
    import src.api.main as api
    logs,positions=sample()
    monkeypatch.setattr(api,'PLAYER_LOGS_DF',logs)
    monkeypatch.setattr(api,'PLAYER_POSITIONS_DF',positions)
    monkeypatch.setattr(api,'PLAYERS_DF',pd.DataFrame([{'player_id':1,'full_name':'Test Center'}]))
    client=TestClient(api.app)
    response=client.get('/api/players/1/season-stats')
    assert response.status_code==200,response.text
    assert len(response.json()['stats'])>=10
    assert response.json()['stats'][0]['value']==30
    assert client.get('/api/players/99999999/season-stats').status_code==404


def test_extended_stats_from_box_scores_have_no_rank_and_use_season_totals():
    logs,positions=sample()
    own=logs.player_id.eq(1)
    logs.loc[own,'dreb']=7
    logs.loc[own,'oreb']=3
    logs.loc[own,'ftm']=4
    logs.loc[own,'fta']=5
    logs.loc[own,'pf']=2
    logs.loc[own,'pts']=24
    logs.loc[own,'reb']=10
    logs.loc[own,'ast']=[10,8,8,8,8,8]
    result=build_season_stats(1,logs,positions,'2026-27')
    extended={s['key']:s for s in result['stats'] if s.get('ranked') is False}
    assert len(extended)==13
    for stat in extended.values():
        assert stat['rank'] is None
        assert stat['rank_out_of'] is None
    assert extended['dreb']['value']==7
    assert extended['oreb']['value']==3
    assert extended['fg2m']['value']==5
    assert extended['fg3m']['value']==3
    assert extended['ftm']['value']==4
    assert extended['ft_pct']['value']==80
    assert extended['fg2_pct']['value']==pytest.approx(83.33)
    assert extended['ast_to']['value']==pytest.approx(8.33)
    assert extended['ts_pct']['value']==pytest.approx(round(100*24/(2*(12+.44*5)),2))
    assert extended['efg_pct']['value']==pytest.approx(round(100*(8+.5*3)/12,2))
    assert extended['double_doubles']['value']==6
    assert extended['triple_doubles']['value']==1
    assert result['unavailable_stats']==['USG%','ORtg','DRtg','PER']


def test_zero_denominators_and_missing_inputs_are_omitted_not_fabricated():
    logs,positions=sample()
    own=logs.player_id.eq(1)
    logs.loc[own,'tov']=0
    result=build_season_stats(1,logs,positions,'2026-27')
    assert 'AST/TO' in result['unavailable_stats']
    assert 'FT' in result['unavailable_stats']
    assert not any(s['key']=='ast_to' for s in result['stats'])

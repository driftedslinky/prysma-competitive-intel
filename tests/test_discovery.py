"""Tests for the Discovery Agent. All network calls are stubbed."""
from unittest.mock import MagicMock, patch

import pytest

from prysma.agents.discovery import (
    MAX_CANDIDATES,
    SOURCE_APP_STORE,
    SOURCE_LISTICLE,
    SOURCE_PLAY,
    DiscoveryAgent,
    apply_relevance,
    merge_candidates,
    normalise_name,
    parse_input,
    parse_relevance,
    rank_candidates,
)
from prysma.config import config


def _cand(name, platform="android", package=None, ios_id=None, rating_count=None,
          source=SOURCE_PLAY, position=0):
    return {
        "name": name,
        "platform": platform,
        "package": package,
        "ios_id": ios_id,
        "store_url": None,
        "developer": None,
        "rating": None,
        "rating_count": rating_count,
        "price": None,
        "sources": [source],
        "_position": position,
    }


class TestParseInput:
    def test_play_store_link(self):
        r = parse_input("https://play.google.com/store/apps/details?id=wtf.riedel.onesec&hl=en")
        assert r["type"] == "store_link"
        assert r["package"] == "wtf.riedel.onesec"
        assert r["ios_id"] is None

    def test_app_store_link(self):
        r = parse_input("https://apps.apple.com/gb/app/one-sec-screen-time-focus/id1532875441")
        assert r["type"] == "store_link"
        assert r["ios_id"] == 1532875441
        assert r["package"] is None

    def test_short_name(self):
        assert parse_input("app blocker")["type"] == "app_name"
        assert parse_input("one two three four five")["type"] == "app_name"

    def test_long_idea(self):
        r = parse_input("an app that stops me doomscrolling at night by locking social media")
        assert r["type"] == "idea"


class TestMergeAndRank:
    def test_normalise_name_strips_tagline(self):
        assert normalise_name("AppBlock - Block Apps & Sites") == "appblock"
        assert normalise_name("ScreenZen・Screen Time Control") == "screenzen"
        assert normalise_name("Freedom: App & Website Blocker") == "freedom"

    def test_dedupes_across_stores(self):
        play = [_cand("Freedom: App Blocker", package="to.freedom.android2")]
        ios = [_cand("Freedom - Block Apps", platform="ios", ios_id=123, rating_count=500,
                     source=SOURCE_APP_STORE)]
        merged = merge_candidates([play, ios])
        assert len(merged) == 1
        assert merged[0]["package"] == "to.freedom.android2"
        assert merged[0]["ios_id"] == 123
        assert merged[0]["rating_count"] == 500
        assert set(merged[0]["sources"]) == {SOURCE_PLAY, SOURCE_APP_STORE}

    def test_dedupes_same_package(self):
        merged = merge_candidates([[_cand("Block", package="a.b")], [_cand("Block Pro", package="a.b")]])
        assert len(merged) == 1

    def test_cap_at_twelve(self):
        many = [_cand(f"App{i}", package=f"pkg.app{i}", position=i) for i in range(30)]
        ranked = rank_candidates(merge_candidates([many]))
        assert len(ranked) == MAX_CANDIDATES == 12

    def test_multi_source_ranks_first(self):
        play = [_cand(f"Solo{i}", package=f"solo.p{i}", position=i) for i in range(5)]
        play.append(_cand("Shared", package="shared.app", position=5))
        ios = [
            _cand("Popular", platform="ios", ios_id=1, rating_count=1_000_000, source=SOURCE_APP_STORE),
            _cand("Shared", platform="ios", ios_id=2, rating_count=10, source=SOURCE_APP_STORE, position=1),
        ]
        ranked = rank_candidates(merge_candidates([play, ios]))
        assert ranked[0]["name"] == "Shared"
        # Then rating count, then store position
        assert ranked[1]["name"] == "Popular"
        assert [c["name"] for c in ranked[2:4]] == ["Solo0", "Solo1"]


@pytest.fixture
def agent():
    with patch("prysma.agents.discovery.AnalystAgent"), \
            patch("prysma.agents.discovery.CompetitiveIntelAgent"):
        a = DiscoveryAgent()
    a.client = MagicMock()
    yield a


class TestSources:
    def test_play_search_parses_anchors(self, agent):
        html = """
        <a href="/store/apps/details?id=cz.mobilesoft.appblock"><span>AppBlock - Block Apps</span>
          <span>MobileSoft s.r.o.</span><span>4.7</span><span>star</span></a>
        <a href="/store/apps/details?id=cz.mobilesoft.appblock"><img></a>
        <a href="/store/apps/details?id=com.screenzen"><span>ScreenZen</span>
          <span>screenzen</span><span>4.8</span><span>star</span></a>
        <a href="/store/apps/collection/x">Not an app</a>
        """
        agent.client.get.return_value = MagicMock(text=html)
        results = agent.search_play_store("app blocker")
        assert [r["package"] for r in results] == ["cz.mobilesoft.appblock", "com.screenzen"]
        assert results[0]["name"] == "AppBlock - Block Apps"
        assert results[0]["developer"] == "MobileSoft s.r.o."
        assert results[0]["rating"] == 4.7
        assert results[1]["_position"] == 1

    def test_app_store_search_parses_json(self, agent):
        agent.client.get.return_value = MagicMock(json=lambda: {"results": [{
            "trackName": "one sec", "trackId": 1532875441, "bundleId": "wtf.riedel.onesec",
            "sellerName": "Riedel", "averageUserRating": 4.83, "userRatingCount": 9000,
            "formattedPrice": "Free", "trackViewUrl": "https://apps.apple.com/gb/app/id1532875441",
        }]})
        results = agent.search_app_store("one sec")
        assert results[0]["ios_id"] == 1532875441
        assert results[0]["rating"] == 4.8
        assert results[0]["rating_count"] == 9000


class TestDiscover:
    @pytest.fixture(autouse=True)
    def _no_profiling(self, agent):
        """Skip profiling and relevance; these tests cover search, merge, and rank."""
        agent.profile_candidates = lambda cands: cands
        agent.score_relevance = MagicMock(return_value=None)

    def test_discover_merges_sources(self, agent):
        agent.search_play_store = MagicMock(return_value=[
            _cand("Opal - Screen Time", package="com.opal", position=0),
            _cand("Blocky", package="com.blocky", position=1),
        ])
        agent.search_app_store = MagicMock(return_value=[
            _cand("Opal: Screen Time Control", platform="ios", ios_id=9, rating_count=50,
                  source=SOURCE_APP_STORE),
        ])
        agent.search_listicles = MagicMock(return_value="The best apps: Opal and Freedom")

        results = agent.discover("app blocker")
        assert results[0]["name"] == "Opal - Screen Time"
        assert set(results[0]["sources"]) == {SOURCE_PLAY, SOURCE_APP_STORE}
        assert "_position" not in results[0]
        agent.search_play_store.assert_called_once_with("app blocker")

    def test_listicle_mention_adds_source(self, agent):
        agent.search_play_store = MagicMock(return_value=[_cand("Freedom: Blocker", package="to.freedom")])
        agent.search_app_store = MagicMock(return_value=[])
        agent.search_listicles = MagicMock(return_value="Top pick: Freedom blocks distractions")
        results = agent.discover("app blocker")
        assert SOURCE_LISTICLE in results[0]["sources"]

    def test_failed_source_does_not_break_discovery(self, agent):
        agent.search_play_store = MagicMock(side_effect=RuntimeError("blocked"))
        agent.search_app_store = MagicMock(return_value=[_cand("One", platform="ios", ios_id=1,
                                                               source=SOURCE_APP_STORE)])
        agent.search_listicles = MagicMock(return_value="")
        assert [c["name"] for c in agent.discover("focus")] == ["One"]

    def test_store_link_excludes_own_app(self, agent):
        agent.intel._scrape_google_play.return_value = {"app_name": "Blocky - Focus Timer"}
        agent.search_play_store = MagicMock(return_value=[
            _cand("Blocky - Focus Timer", package="com.blocky"),
            _cand("Other", package="com.other", position=1),
        ])
        agent.search_app_store = MagicMock(return_value=[])
        agent.search_listicles = MagicMock(return_value="")
        results = agent.discover("https://play.google.com/store/apps/details?id=com.blocky")
        assert [c["package"] for c in results] == ["com.other"]
        agent.search_play_store.assert_called_once_with("Focus Timer")


class TestProfile:
    def test_parse_profile(self):
        summary, features = DiscoveryAgent._parse_profile(
            "thinking...\nSummary: Blocks distracting apps.\nFeatures: schedules, breathing pause, stats"
        )
        assert summary == "Blocks distracting apps."
        assert features == ["schedules", "breathing pause", "stats"]

    def test_profile_candidates_keeps_order(self, agent):
        agent.profile_candidate = lambda c: {**c, "summary": c["name"].upper(), "features": []}
        out = agent.profile_candidates([_cand("a"), _cand("b"), _cand("c")])
        assert [c["summary"] for c in out] == ["A", "B", "C"]


def _named(*names):
    return [{"name": n, "summary": f"{n} app", "sources": [SOURCE_PLAY]} for n in names]


class TestRelevance:
    def test_parse_takes_last_bucket_per_index(self):
        answer = ("1: direct? no, it is a planner.\n2: Adjacent\n1: unrelated\n"
                  "**3**: direct\n4: maybe\n5: unknown")
        assert parse_relevance(answer) == {1: "unrelated", 2: "adjacent", 3: "direct"}

    def test_drops_unrelated_and_puts_direct_first(self):
        cands = _named("a", "b", "c", "d", "e")
        out = apply_relevance(cands, {1: "adjacent", 2: "direct", 3: "unrelated", 4: "direct",
                                      5: "adjacent"})
        assert [(c["name"], c["relevance"]) for c in out] == [
            ("b", "direct"), ("d", "direct"), ("a", "adjacent"), ("e", "adjacent")]

    def test_too_few_kept_keeps_top_five(self):
        cands = _named("a", "b", "c", "d", "e", "f", "g")
        buckets = {i: "unrelated" for i in range(1, 8)}
        buckets.update({2: "direct", 5: "adjacent"})
        out = apply_relevance(cands, buckets)
        assert [c["name"] for c in out] == ["b", "e", "a", "c", "d"]

    def test_missing_index_counts_as_unrelated(self):
        out = apply_relevance(_named("a", "b", "c", "d"), {1: "direct", 2: "direct", 3: "adjacent"})
        assert [c["name"] for c in out] == ["a", "b", "c"]

    def test_model_failure_keeps_all(self, agent):
        agent.analyst._chat.side_effect = RuntimeError("down")
        cands = _named("a", "b", "c")
        with patch.object(config, "nebius_api_key", "key"):
            buckets = agent.score_relevance("idea", cands)
        assert buckets is None
        out = apply_relevance(cands, buckets)
        assert [(c["name"], c["relevance"]) for c in out] == [
            ("a", "unknown"), ("b", "unknown"), ("c", "unknown")]
        assert agent.analyst._chat.call_count == 2

    def test_empty_reply_retries_once(self, agent):
        agent.analyst._chat.side_effect = ["thinking about it...", "1: direct\n2: unrelated"]
        with patch.object(config, "nebius_api_key", "key"):
            buckets = agent.score_relevance("idea", _named("a", "b"))
        assert buckets == {1: "direct", 2: "unrelated"}
        assert agent.analyst._chat.call_count == 2

    def test_two_empty_replies_give_none(self, agent):
        agent.analyst._chat.side_effect = ["hmm", "still thinking", "1: direct"]
        with patch.object(config, "nebius_api_key", "key"):
            assert agent.score_relevance("idea", _named("a")) is None
        assert agent.analyst._chat.call_count == 2

    def test_discover_adds_relevance(self, agent):
        agent.search_play_store = MagicMock(return_value=[
            _cand("Buffer", package="com.buffer", position=0),
            _cand("Forest", package="cc.forest", position=1),
            _cand("one sec", package="wtf.onesec", position=2),
            _cand("ScreenZen", package="com.screenzen", position=3),
        ])
        agent.search_app_store = MagicMock(return_value=[])
        agent.search_listicles = MagicMock(return_value="")
        agent.profile_candidates = lambda cands: [{**c, "summary": "x"} for c in cands]
        agent.analyst._chat.return_value = "1: unrelated\n2: adjacent\n3: direct\n4: direct"

        with patch.object(config, "nebius_api_key", "key"):
            results = agent.discover("app blocker")
        assert [(c["name"], c["relevance"]) for c in results] == [
            ("one sec", "direct"), ("ScreenZen", "direct"), ("Forest", "adjacent")]
        assert agent.analyst._chat.call_args.args[0] == config.nebius_model_nano
        assert agent.analyst._chat.call_args.kwargs["max_tokens"] == 2000
        assert "Reply with exactly 4 lines, one per app." in agent.analyst._chat.call_args.args[1]

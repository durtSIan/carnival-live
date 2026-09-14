import threading
import time

import pytest

from data_sources.playcricket_public import PlayCricketPublicSource
from data_sources.response_cache import SharedResponseCache


def test_cache_returns_independent_copies_until_ttl_expires():
    now = [100.0]
    cache = SharedResponseCache(clock=lambda: now[0], report_every=0)
    calls = []

    def load():
        calls.append(True)
        return {"matches": [{"status": "LIVE"}]}

    first = cache.get_or_load("grade", load, ttl_seconds=30, stale_seconds=120)
    first["matches"][0]["status"] = "CHANGED"
    second = cache.get_or_load("grade", load, ttl_seconds=30, stale_seconds=120)

    assert second["matches"][0]["status"] == "LIVE"
    assert len(calls) == 1
    assert cache.snapshot()["hits"] == 1

    now[0] += 31
    cache.get_or_load("grade", load, ttl_seconds=30, stale_seconds=120)
    assert len(calls) == 2


def test_cache_combines_concurrent_loads_for_the_same_key():
    cache = SharedResponseCache(report_every=0)
    loader_started = threading.Event()
    release_loader = threading.Event()
    calls = []
    results = []

    def load():
        calls.append(True)
        loader_started.set()
        assert release_loader.wait(timeout=2)
        return {"score": 42}

    def request():
        results.append(
            cache.get_or_load("match", load, ttl_seconds=25, stale_seconds=120)
        )

    first = threading.Thread(target=request)
    second = threading.Thread(target=request)
    first.start()
    assert loader_started.wait(timeout=1)
    second.start()
    deadline = time.monotonic() + 1
    while cache.snapshot().get("waits", 0) == 0 and time.monotonic() < deadline:
        time.sleep(0.01)
    release_loader.set()
    first.join(timeout=2)
    second.join(timeout=2)

    assert results == [{"score": 42}, {"score": 42}]
    assert len(calls) == 1
    assert cache.snapshot()["waits"] == 1


def test_cache_serves_last_success_briefly_when_refresh_fails():
    now = [100.0]
    cache = SharedResponseCache(clock=lambda: now[0], report_every=0)
    cache.get_or_load(
        "scorecard", lambda: {"score": "3-120"}, ttl_seconds=25, stale_seconds=120
    )
    now[0] += 26

    def fail():
        raise RuntimeError("temporary upstream failure")

    assert cache.get_or_load(
        "scorecard", fail, ttl_seconds=25, stale_seconds=120
    ) == {"score": "3-120"}
    assert cache.snapshot()["stale_served"] == 1

    now[0] += 95
    with pytest.raises(RuntimeError):
        cache.get_or_load(
            "scorecard", fail, ttl_seconds=25, stale_seconds=120
        )


def test_play_cricket_only_caches_dynamic_match_endpoints():
    class Response:
        def __init__(self, url):
            self.url = url

        def raise_for_status(self):
            return None

        def json(self):
            return {"url": self.url}

    class Session:
        def __init__(self):
            self.urls = []

        def get(self, url, **kwargs):
            self.urls.append(url)
            return Response(url)

    session = Session()
    source = PlayCricketPublicSource(session=session)
    grade_path = "/scores/grades/grade-id/matches"
    scorecard_path = "/scores/matches/match-id"
    grade_detail_path = "/fixturesladders/grades/grade-id"

    source._get(grade_path)
    source._get(grade_path)
    source._get(scorecard_path, responseModifier="includeScorecard")
    source._get(scorecard_path, responseModifier="includeScorecard")
    source._get(grade_detail_path)
    source._get(grade_detail_path)

    assert session.urls.count(source.base_url + grade_path) == 1
    assert session.urls.count(source.base_url + scorecard_path) == 1
    assert session.urls.count(source.base_url + grade_detail_path) == 2
    assert source.cache_stats()["hits"] == 2

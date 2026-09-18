import fakeredis.aioredis as fake_aioredis
import pytest

from app import cache


@pytest.fixture(autouse=True)
def fake_redis():
    """Back the disposable cache with fakeredis so tests need no real Redis."""
    cache._redis = fake_aioredis.FakeRedis(decode_responses=True)
    yield
    cache._redis = None

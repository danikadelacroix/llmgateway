import pytest
from cache.cacheability import classify, QueryClass, DEFAULT_POLICY

def test_ephemeral_classification():
    assert classify([{"role": "user", "content": "What day is it today?"}]) == QueryClass.EPHEMERAL
    assert classify([{"role": "user", "content": "What is the weather like?"}]) == QueryClass.EPHEMERAL
    assert classify([{"role": "user", "content": "Tell me the news right now"}]) == QueryClass.EPHEMERAL

def test_personalized_classification():
    assert classify([{"role": "user", "content": "Where is my order?"}]) == QueryClass.PERSONALIZED
    assert classify([{"role": "user", "content": "What is my account number?"}]) == QueryClass.PERSONALIZED

def test_non_deterministic_classification():
    assert classify([{"role": "user", "content": "Give me a random number"}]) == QueryClass.NON_DETERMINISTIC
    assert classify([{"role": "user", "content": "Roll a dice for me"}]) == QueryClass.NON_DETERMINISTIC

def test_stable_permanent_classification():
    assert classify([{"role": "user", "content": "Write a binary search algorithm"}]) == QueryClass.STABLE_PERMANENT
    assert classify([{"role": "user", "content": "What is 2+2?"}]) == QueryClass.STABLE_PERMANENT

def test_stable_short_classification():
    assert classify([{"role": "user", "content": "What is the capital of France?"}]) == QueryClass.STABLE_SHORT
    assert classify([{"role": "user", "content": "What is the population of Tokyo?"}]) == QueryClass.STABLE_SHORT

def test_default_fallback():
    assert classify([{"role": "user", "content": "Explain how a combustion engine works."}]) == QueryClass.STABLE_LONG
    assert classify([{"role": "user", "content": "Who wrote Hamlet?"}]) == QueryClass.STABLE_LONG

def test_is_cacheable():
    assert not QueryClass.EPHEMERAL.is_cacheable
    assert not QueryClass.PERSONALIZED.is_cacheable
    assert not QueryClass.NON_DETERMINISTIC.is_cacheable
    
    assert QueryClass.STABLE_SHORT.is_cacheable
    assert QueryClass.STABLE_LONG.is_cacheable
    assert QueryClass.STABLE_PERMANENT.is_cacheable

def test_ttl_values():
    assert DEFAULT_POLICY.ttl_for(QueryClass.EPHEMERAL) == 0
    assert DEFAULT_POLICY.ttl_for(QueryClass.STABLE_SHORT) == 6 * 3600
    assert DEFAULT_POLICY.ttl_for(QueryClass.STABLE_LONG) == 24 * 3600
    assert DEFAULT_POLICY.ttl_for(QueryClass.STABLE_PERMANENT) == 7 * 86400

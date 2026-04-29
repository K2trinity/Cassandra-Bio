from __future__ import annotations


def test_fetch_market_news_returns_disabled_status_without_api_key(monkeypatch):
    from src.tools.alpha_vantage_news_client import fetch_market_news_events

    monkeypatch.delenv("ALPHA_VANTAGE_API_KEY", raising=False)

    events, status = fetch_market_news_events("MRNA")

    assert events == []
    assert status["source"] == "alphavantage"
    assert status["status"] == "disabled"
    assert status["item_count"] == 0
    assert "ALPHA_VANTAGE_API_KEY" in status["message"]


def test_fetch_market_news_queries_ticker_topics_and_time_range(monkeypatch):
    from src.tools import alpha_vantage_news_client

    captured = {}

    class FakeResponse:
        def raise_for_status(self):
            return None

        def json(self):
            return {"feed": []}

    def fake_get(url, params, timeout):
        captured["url"] = url
        captured["params"] = params
        captured["timeout"] = timeout
        return FakeResponse()

    monkeypatch.setattr(alpha_vantage_news_client.requests, "get", fake_get)

    events, status = alpha_vantage_news_client.fetch_market_news_events(
        "mrna",
        start="2026-04-01",
        end="2026-04-20",
        limit=10,
        api_key="test-key",
    )

    assert events == []
    assert status["status"] == "empty"
    assert captured["url"] == alpha_vantage_news_client.ALPHA_VANTAGE_NEWS_URL
    assert captured["params"]["function"] == "NEWS_SENTIMENT"
    assert captured["params"]["tickers"] == "MRNA"
    assert "life_sciences" in captured["params"]["topics"]
    assert captured["params"]["time_from"] == "20260401T0000"
    assert captured["params"]["time_to"] == "20260420T2359"
    assert captured["params"]["limit"] == 10
    assert captured["params"]["apikey"] == "test-key"


def test_normalize_news_sentiment_feed_classifies_life_sciences_news():
    from src.tools.alpha_vantage_news_client import normalize_news_sentiment_feed

    payload = {
        "feed": [
            {
                "title": "Moderna announces Phase 3 vaccine data and partnership",
                "url": "https://example.com/mrna-news",
                "time_published": "20260420T130000",
                "summary": "The company announced positive Phase 3 data.",
                "source": "Example Wire",
                "overall_sentiment_score": "0.42",
                "overall_sentiment_label": "Bullish",
                "ticker_sentiment": [
                    {
                        "ticker": "MRNA",
                        "relevance_score": "0.91",
                        "ticker_sentiment_score": "0.36",
                        "ticker_sentiment_label": "Bullish",
                    }
                ],
                "topics": [{"topic": "Life Sciences", "relevance_score": "0.95"}],
            }
        ]
    }

    events = normalize_news_sentiment_feed(payload, requested_ticker="MRNA")

    assert len(events) == 1
    event = events[0]
    assert event["ticker"] == "MRNA"
    assert event["source"] == "alphavantage"
    assert event["type"] == "partnership_mna"
    assert event["category"] == "news"
    assert event["date"] == "2026-04-20"
    assert event["sentiment"] == "positive"
    assert event["source_url"] == "https://example.com/mrna-news"
    assert event["metadata"]["category"] == "news"
    assert event["metadata"]["source_kind"] == "news"
    assert event["metadata"]["source_tier"] == "market_news"
    assert event["metadata"]["confidence_score"] >= 0.6

import random
from typing import Any

TOOLS = [    
   {
        "name": "search_news",
        "description": "Search recent news articles about a company or topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "query":       {"type": "string",  "description": "Search query — company name or topic"},
                "max_results": {"type": "integer", "description": "Max articles to return (default 5)"},
            },
            "required": ["query"],
        },
    },
    {
        "name": "filter_by_date",
        "description": "Filter a list of articles to only those published within the last N days.",
        "input_schema": {
            "type": "object",
            "properties": {
                "articles":  {"type": "array",   "description": "List of article objects from search_news"},
                "days_back": {"type": "integer", "description": "How many days back to include"},
            },
            "required": ["articles", "days_back"],
        },
    },
    {
        "name": "analyze_sentiment",
        "description": "Score the market sentiment expressed in a list of text snippets.",
        "input_schema": {
            "type": "object",
            "properties": {
                "texts":  {"type": "array",  "items": {"type": "string"}, "description": "Texts to analyze"},
                "entity": {"type": "string", "description": "Company or topic being analyzed"},
            },
            "required": ["texts", "entity"],
        },
    },
    {
        "name": "get_social_metrics",
        "description": "Get social media engagement metrics (mentions, sentiment ratio) for a topic.",
        "input_schema": {
            "type": "object",
            "properties": {
                "topic":    {"type": "string", "description": "Topic or company to look up"},
                "platform": {
                    "type": "string",
                    "enum": ["twitter", "reddit", "all"],
                    "description": "Which platform to query (default: all)",
                },
            },
            "required": ["topic"],
        },
    },
    {
        "name": "get_financial_signals",
        "description": "Retrieve key financial signals: stock price trend, analyst consensus, and earnings data.",
        "input_schema": {
            "type": "object",
            "properties": {
                "company": {"type": "string", "description": "Company name or stock ticker"},
                "period":  {"type": "string", "description": "Look-back period e.g. '90d' or '30d' (default 90d)"},
            },
            "required": ["company"],
        },
    },
]



# ── Mock implementations ──────────────────────────────────────────
# Return realistic-looking data without any real API calls.

def _search_news(query: str, max_results: int = 5) -> list[dict]:
    articles = [
        {"title": f"{query}: Q4 earnings beat expectations by 12%",              "source": "Bloomberg",   "date": "2024-11-15", "url": "https://bloomberg.com/1"},
        {"title": f"{query} announces major product launch at investor day",      "source": "Reuters",     "date": "2024-11-10", "url": "https://reuters.com/2"},
        {"title": f"Analysts raise {query} price targets after strong guidance",  "source": "CNBC",        "date": "2024-11-08", "url": "https://cnbc.com/3"},
        {"title": f"{query} faces supply-chain pressure in Asia markets",         "source": "FT",          "date": "2024-11-05", "url": "https://ft.com/4"},
        {"title": f"Regulatory scrutiny increases on {query}'s market practices", "source": "WSJ",         "date": "2024-10-30", "url": "https://wsj.com/5"},
        {"title": f"{query} partners with enterprises on AI integration",         "source": "TechCrunch",  "date": "2024-10-25", "url": "https://techcrunch.com/6"},
    ]
    return articles[:max_results]


def _filter_by_date(articles: list, days_back: int) -> list:
    # Mock: all dates are static, so return the first (days_back // 10 + 2) articles
    cutoff = max(1, days_back // 10 + 2)
    return articles[:cutoff]


def _analyze_sentiment(texts: list, entity: str) -> dict:
    seed = sum(ord(c) for c in entity)
    random.seed(seed)
    score = round(random.uniform(0.30, 0.85), 3)
    label = "bullish" if score > 0.60 else "neutral" if score > 0.42 else "bearish"
    return {
        "entity":        entity,
        "overall_score": score,
        "label":         label,
        "article_count": len(texts),
        "breakdown": {
            "positive": int(len(texts) * score),
            "neutral":  1,
            "negative": max(0, len(texts) - int(len(texts) * score) - 1),
        },
    }


def _get_social_metrics(topic: str, platform: str = "all") -> dict:
    seed = sum(ord(c) for c in topic) + 1
    random.seed(seed)
    return {
        "topic":              topic,
        "platform":           platform,
        "mention_count_24h":  random.randint(1_200, 45_000),
        "sentiment_ratio":    round(random.uniform(0.45, 0.80), 3),
        "trending":           random.choice([True, False]),
        "top_hashtags":       [f"#{topic.split()[0]}", "#investing", "#markets"],
    }


def _get_financial_signals(company: str, period: str = "90d") -> dict:
    seed = sum(ord(c) for c in company) + 2
    random.seed(seed)
    return {
        "company":                  company,
        "period":                   period,
        "price_change_pct":         round(random.uniform(-15, 35), 2),
        "analyst_consensus":        random.choice(["Strong Buy", "Buy", "Hold", "Underperform"]),
        "target_upside_pct":        round(random.uniform(-5, 40), 2),
        "earnings_surprise_pct":    round(random.uniform(-8, 18), 2),
        "pe_ratio":                 round(random.uniform(12, 65), 1),
        "institutional_ownership":  round(random.uniform(55, 92), 1),
    }

# ── Dispatcher ────────────────────────────────────────────────────

_DISPATCH = {
    "search_news":          _search_news,
    "filter_by_date":       _filter_by_date,
    "analyze_sentiment":    _analyze_sentiment,
    "get_social_metrics":   _get_social_metrics,
    "get_financial_signals": _get_financial_signals,
}

def execute_tool(tool_name: str, tool_input: dict) -> Any:
    """Route a tool_use block to its implementation."""
    fn = _DISPATCH.get(tool_name)
    if fn is None:
        raise ValueError(f"Unknown tool: {tool_name!r}")
    return fn(**tool_input)
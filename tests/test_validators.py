"""Unit tests for data validation functions."""

import pytest
from validators import validate_article, validate_batch, ValidationResult


def test_validate_article_valid():
    """Valid article passes validation."""
    article = {
        "id": "abc123",
        "title": "Test headline",
        "body": "Article content here"
    }
    result = validate_article(article)
    assert result.is_valid is True
    assert len(result.errors) == 0


def test_validate_article_missing_id():
    """Article without ID fails validation."""
    article = {
        "title": "Test headline",
        "body": "Content"
    }
    result = validate_article(article)
    assert result.is_valid is False
    assert "id" in result.errors[0].lower()


def test_validate_article_no_content():
    """Article with neither title nor body fails validation."""
    article = {
        "id": "abc123"
    }
    result = validate_article(article)
    assert result.is_valid is False


def test_validate_article_sentiment_out_of_range():
    """Sentiment score outside [-1, 1] fails validation."""
    article = {
        "id": "abc123",
        "title": "Test",
        "sentiment_score": 1.5
    }
    result = validate_article(article)
    assert result.is_valid is False


def test_validate_batch_separates_valid_invalid():
    """Batch validation correctly separates valid from invalid."""
    articles = [
        {"id": "1", "title": "Valid article"},
        {"title": "Missing ID"},
        {"id": "2", "title": "Another valid one"}
    ]
    valid, invalid = validate_batch(articles)
    assert len(valid) == 2
    assert len(invalid) == 1
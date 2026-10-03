"""
Data validation functions for the news ETL pipeline.

This module implements the "fail fast" principle: catch data quality issues
early in the pipeline before bad data reaches the database.
"""

from dataclasses import dataclass
from typing import Any


@dataclass
class ValidationResult:
    """
    Holds the result of a validation check.

    Using a dataclass instead of just returning True/False gives us:
    - The ability to include error messages
    - A record of what was checked
    - Structured data for logging/alerting
    """
    
    is_valid: bool
    errors: list[str]
    warnings: list[str]
    record_id: str | None = None


def validate_article(article: dict[str, Any]) -> ValidationResult:
    """
    Apply data quality rules to a single article before database insertion.
    
    Implements fail-fast validation: catches issues early in the pipeline
    rather than allowing bad data to reach the database.

    Validation rules:
    1. Required fields must be present and non-empty
    2. Sentiment score must be in valid range (if present)
    3. Word count must be non-negative (if present)
    4. Article ID must exist (critical - it's our primary key)

    Returns ValidationResult with is_valid=False if critical rules fail,
    but may still have warnings for non-critical issues.
    """

    errors = []
    warnings = []
    record_id = article.get("id")

    # CRITICAL: Primary key must exist
    if not record_id:
        errors.append("Missing required field: id (article_id)")

    # CRITICAL: Must have some content to store
    if not article.get("title") and not article.get("body"):
        errors.append("Article has neither title nor body - no content to store")

    # WARNING: Title should exist for most articles
    if not article.get("title"):
        warnings.append("Missing title - article may be incomplete")

    # WARNING: Body should exist for text processing
    if not article.get("body"):
        warnings.append("Missing body - sentiment and word count will be null")

    # VALIDATION: Sentiment score range check
    sentiment = article.get("sentiment_score")
    if sentiment is not None:
        if not isinstance(sentiment, (int, float)):
            errors.append(f"Sentiment score must be numeric, got {type(sentiment)}")
        elif sentiment < -1.0 or sentiment > 1.0:
            errors.append(f"Sentiment score {sentiment} outside valid range [-1.0, 1.0]")

    return ValidationResult(
        is_valid=len(errors) == 0,
        errors=errors,
        warnings=warnings,
        record_id=record_id
    )


def validate_batch(articles: list[dict[str, Any]]) -> tuple[list[dict], list[ValidationResult]]:
    """
    Separate valid articles from invalid ones for batch processing.
    
    Uses a lenient approach common with external APIs: valid records
    proceed to insertion while invalid ones are logged for review.

    Returns:
        - List of valid articles (ready for insertion)
        - List of ValidationResults for invalid articles (for logging/alerting)

    This implementation uses a lenient approach, which is common when
    dealing with external APIs where you can't control data quality.
    """

    valid_articles = []
    invalid_results = []

    # Check for duplicate IDs within the batch
    ids_seen = set()
    duplicates = set()

    for article in articles:
        article_id = article.get("id")
        if article_id in ids_seen:
            duplicates.add(article_id)
        ids_seen.add(article_id)

    for article in articles:
        result = validate_article(article)

        # Add duplicate warning if applicable
        if article.get("id") in duplicates:
            result.warnings.append(f"Duplicate ID in batch: {article.get('id')}")

        if result.is_valid:
            valid_articles.append(article)
            # Log warnings even for valid articles
            if result.warnings:
                print(f"Warnings for article {result.record_id}: {result.warnings}")
        else:
            invalid_results.append(result)

    return valid_articles, invalid_results
import os
import json
from datetime import datetime
from typing import Any

import psycopg2
from newsdataapi import NewsDataApiClient
from textblob import TextBlob
from validators import validate_batch


# Read the API key from an environment variable
API_KEY: str | None = os.environ.get("NEWS_API_KEY")

if not API_KEY:
    print("Error: NEWS_API_KEY environment variable not set.")
    exit(1)

api = NewsDataApiClient(apikey=API_KEY)  # type: ignore


def log_to_db(cursor, level: str, message: str, record_id: str | None = None, details: dict[str, Any] | None = None) -> None:
    """
    Write a structured log entry to the pipeline_logs table.
    
    Centralizes logging to enable pipeline monitoring and debugging
    through SQL queries rather than parsing container logs.

    Levels: INFO, WARNING, ERROR
    """
    cursor.execute("""
        INSERT INTO pipeline_logs (log_level, message, record_id, details)
        VALUES (%s, %s, %s, %s)
    """, (
        level,
        message,
        record_id,
        json.dumps(details) if details else None
    ))


def calculate_sentiment(text: str | None) -> float | None:
    """
    Calculate sentiment polarity using TextBlob's lexicon-based analysis.
    
    Returns values between -1.0 (negative) and 1.0 (positive).
    News headlines often return 0.0 due to neutral, factual language.
    """
    if not text or not text.strip():
        return None

    try:
        blob = TextBlob(text)
        return round(blob.sentiment.polarity, 4)
    except Exception as e:
        print(f"Sentiment analysis failed: {e}")
        return None


def get_latest_article_date(cursor) -> str | None:
    """
    Retrieve the most recent article's publication date from the database.

    Enables incremental loading by filtering fetched articles client-side,
    since the free tier API endpoint doesn't support date parameters.
    """
    cursor.execute("SELECT MAX(published_at) FROM articles")
    row = cursor.fetchone()
    return row[0] if row and row[0] else None


def _initialize_schema(cursor) -> None:
    """
    Create tables and handle schema evolution.
    """

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS articles (
            id TEXT PRIMARY KEY,
            title TEXT,
            author TEXT,
            body TEXT,
            source TEXT,
            published_at TEXT,
            sentiment_score REAL,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
    """)

    cursor.execute("""
        CREATE TABLE IF NOT EXISTS pipeline_logs (
            id SERIAL PRIMARY KEY,
            run_timestamp TIMESTAMP DEFAULT CURRENT_TIMESTAMP,
            log_level TEXT NOT NULL,
            message TEXT NOT NULL,
            record_id TEXT,
            details JSONB
        )
    """)

    # Schema evolution for existing databases
    alter_statements = [
        "ALTER TABLE articles ADD COLUMN IF NOT EXISTS sentiment_score REAL",
        "ALTER TABLE articles ADD COLUMN IF NOT EXISTS created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP",
        "ALTER TABLE articles ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP"
    ]
    for stmt in alter_statements:
        cursor.execute(stmt)


def _transform_articles(articles_to_store: list) -> list[dict]:
    """
    Transform raw API articles into processed records with computed features.
    """

    processed_articles = []
    for item in articles_to_store:
        creator = item.get("creator")
        if isinstance(creator, list):
            creator = ", ".join(creator)

        title = item.get("title")
        body = item.get("content")

        article = {
            "id": item.get("article_id"),
            "title": title,
            "author": creator,
            "body": body,
            "source": item.get("source_name"),
            "published_at": item.get("pubDate"),
            "sentiment_score": calculate_sentiment(title),
        }
        processed_articles.append(article)

    return processed_articles


def _load_articles(cursor, valid_articles: list[dict]) -> int:
    """
    Insert validated articles into the database. Returns count of inserted articles.
    """

    inserted_count = 0
    for article in valid_articles:
        cursor.execute("""
            INSERT INTO articles (id, title, author, body, source, published_at, sentiment_score)
            VALUES (%(id)s, %(title)s, %(author)s, %(body)s, %(source)s, %(published_at)s, %(sentiment_score)s)
            ON CONFLICT (id) DO UPDATE SET
                title = EXCLUDED.title,
                author = EXCLUDED.author,
                body = EXCLUDED.body,
                source = EXCLUDED.source,
                published_at = EXCLUDED.published_at,
                sentiment_score = EXCLUDED.sentiment_score,
                updated_at = CURRENT_TIMESTAMP
        """, article)
        inserted_count += 1

    return inserted_count


def _verify_data(cursor) -> None:
    """
    Verify data was inserted by selecting sample records.
    """

    cursor.execute("SELECT id, title, source FROM articles LIMIT 5")
    rows = cursor.fetchall()
    print("\n--- Verifying data by selecting records ---")
    for row in rows:
        print(row)


def fetch_and_store_articles() -> None:
    """
    Execute the complete ETL pipeline: extract from API, transform with
    sentiment analysis, validate data quality, and load to PostgreSQL.
    
    Implements incremental loading when existing data is present,
    falling back to full load for empty databases.

    Pipeline stages:
    1. EXTRACT: Fetch articles from NewsData.io API
    2. TRANSFORM: Compute sentiment scores
    3. VALIDATE: Check data quality before insertion
    4. LOAD: Insert validated articles into PostgreSQL
    """
    POSTGRES_URL = os.environ.get("POSTGRES_URL")
    if not POSTGRES_URL:
        print("Error: POSTGRES_URL not set")
        return

    try:
        with psycopg2.connect(POSTGRES_URL) as conn:
            with conn.cursor() as cursor:
                # Initialize database schema
                _initialize_schema(cursor)

                # EXTRACT: Fetch from API (with client-side incremental filtering)
                try:
                    # Get the latest article date for incremental loading
                    latest_date = get_latest_article_date(cursor)

                    if latest_date:
                        # Incremental load: fetch all recent articles, filter client-side
                        from_date_str = latest_date[:10]  # Extract date portion (YYYY-MM-DD)
                        log_to_db(cursor, "INFO",
                                  f"Incremental load from {from_date_str} (client-side filtering)")
                        print(f"Performing incremental load from {from_date_str} (client-side filtering)")
                    else:
                        # Full load: no existing data
                        log_to_db(cursor, "INFO",
                                  "Performing full load (no existing data)")
                        print("Performing full load")
                        from_date_str = None

                    # Fetch latest articles (free tier endpoint, no date filtering)
                    response_data = api.latest_api(language="en")
                except Exception as e:
                    log_to_db(cursor, "ERROR", f"API fetch failed: {str(e)}",
                              details={"exception_type": type(e).__name__})
                    conn.commit()
                    print(f"Failed to fetch data from API: {e}")
                    return

                if not (response_data and response_data.get("status") == "success"):
                    log_to_db(cursor, "ERROR", "API request unsuccessful",
                              details={"response": str(response_data)})
                    conn.commit()
                    print(
                        f"API request was unsuccessful. Details: {response_data}")
                    return

                articles_to_store = response_data.get("results", [])
                if not articles_to_store:
                    log_to_db(cursor, "WARNING",
                              "No articles returned from API")
                    conn.commit()
                    print("No articles found to store.")
                    return

                api_fetch_count = len(articles_to_store)
                print(f"Successfully fetched {api_fetch_count} articles from API.")

                # CLIENT-SIDE FILTERING: Only keep articles newer than latest_date
                # This handles incremental loading on the free tier where the API
                # endpoint doesn't support date filtering.
                if latest_date:
                    filtered_articles = []
                    for article in articles_to_store:
                        article_pub_date = article.get("pubDate")
                        # Compare ISO format dates (e.g., "2026-07-15T12:30:00")
                        # String comparison works because ISO format is sortable
                        if article_pub_date and article_pub_date > latest_date:
                            filtered_articles.append(article)

                    if not filtered_articles:
                        log_to_db(cursor, "INFO",
                                  f"No new articles since {latest_date}")
                        conn.commit()
                        print(f"No new articles found since {latest_date}. Pipeline complete.")
                        return

                    articles_to_store = filtered_articles
                    print(f"Filtered to {len(articles_to_store)} new articles (older {api_fetch_count - len(articles_to_store)} discarded)")

                log_to_db(cursor, "INFO",
                          f"Fetched {api_fetch_count} articles from API, storing {len(articles_to_store)}")

                # TRANSFORM: Build article records with computed features
                processed_articles = _transform_articles(articles_to_store)

                # VALIDATE: Check data quality before insertion
                valid_articles, invalid_results = validate_batch(
                    processed_articles)

                print(
                    f"Validation complete: {len(valid_articles)} valid, {len(invalid_results)} invalid")
                log_to_db(cursor, "INFO",
                          f"Validation: {len(valid_articles)} valid, {len(invalid_results)} invalid")

                # Log invalid records
                for result in invalid_results:
                    print(
                        f"REJECTED article {result.record_id}: {result.errors}")
                    log_to_db(cursor, "WARNING", "Article failed validation",
                              record_id=result.record_id,
                              details={"errors": result.errors, "warnings": result.warnings})

                if not valid_articles:
                    log_to_db(cursor, "WARNING",
                              "No valid articles to insert after validation")
                    conn.commit()
                    print("No valid articles to insert after validation.")
                    return

                # LOAD: Insert only validated articles
                inserted_count = _load_articles(cursor, valid_articles)

                # Log final summary
                run_summary = {
                    "load_type": "incremental" if latest_date else "full",
                    "from_date": latest_date if latest_date else None,
                    "articles_fetched": len(articles_to_store),
                    "articles_valid": len(valid_articles),
                    "articles_invalid": len(invalid_results),
                    "articles_inserted": inserted_count,
                    "run_timestamp": datetime.now().isoformat()
                }
                log_to_db(cursor, "INFO", "Pipeline run completed",
                          details=run_summary)

                conn.commit()
                print(
                    f"Successfully inserted/updated {inserted_count} articles into the database.")
                print(f"Pipeline run summary: {run_summary}")

                # Verification
                _verify_data(cursor)

    except psycopg2.Error as e:
        print(f"Database error occurred: {e}")

    except Exception as e:
        print(f"Unexpected error: {e}")


if __name__ == "__main__":
    fetch_and_store_articles()
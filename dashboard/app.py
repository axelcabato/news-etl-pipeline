import os
from datetime import datetime, timedelta

import pandas as pd
import plotly.express as px
import plotly.graph_objects as go
import psycopg2
import streamlit as st


# Page configuration
st.set_page_config(
    page_title="News ETL Dashboard",
    page_icon="📰",
    layout="wide",
    initial_sidebar_state="expanded"
)


def get_connection():
    """Create database connection using environment variable."""

    postgres_url = os.environ.get("POSTGRES_URL")
    if not postgres_url:
        st.error("POSTGRES_URL environment variable not set")
        st.stop()
    return psycopg2.connect(postgres_url)


@st.cache_data(ttl=300)  # Cache for 5 minutes
def load_articles():
    """Load articles from database with caching."""

    query = """
        SELECT
            id,
            title,
            source,
            sentiment_score,
            published_at,
            created_at
        FROM articles
        ORDER BY published_at DESC
    """
    with get_connection() as conn:
        df = pd.read_sql(query, conn)

    # Convert published_at to datetime
    df['published_at'] = pd.to_datetime(df['published_at'], errors='coerce')
    df['created_at'] = pd.to_datetime(df['created_at'], errors='coerce')

    return df


@st.cache_data(ttl=300)
def load_pipeline_logs():
    """Load recent pipeline logs for monitoring.

    Scoped to the last 7 days so resolved historical failures do not surface
    as current issues. The pgdata volume is external and survives rebuilds,
    so the logs table retains entries indefinitely.
    """

    query = """
        SELECT
            run_timestamp,
            log_level,
            message,
            details
        FROM pipeline_logs
        WHERE run_timestamp > NOW() - INTERVAL '7 days'
        ORDER BY run_timestamp DESC
        LIMIT 50
    """
    with get_connection() as conn:
        df = pd.read_sql(query, conn)
    return df


def render_header():
    """Render dashboard header with key metrics."""

    st.title("📰 News ETL Pipeline Dashboard")
    st.markdown("Real-time insights from your automated news ingestion pipeline")
    st.divider()


def render_metrics(df: pd.DataFrame):
    """Render key performance indicators."""

    col1, col2, col3 = st.columns(3)

    with col1:
        st.metric(
            label="Total Articles",
            value=f"{len(df):,}"
        )

    with col2:
        avg_sentiment = df['sentiment_score'].mean()
        if avg_sentiment < -0.3:
            sentiment_label = "Negative"
            sentiment_color = "red"
        elif avg_sentiment > 0.3:
            sentiment_label = "Positive"
            sentiment_color = "green"
        else:
            sentiment_label = "Neutral"
            sentiment_color = "gray"
        st.metric(
            label="Average Sentiment",
            value=f"{avg_sentiment:.3f}",
            delta=sentiment_label,
            delta_color="off"
        )

    with col3:
        unique_sources = df['source'].nunique()
        st.metric(
            label="Unique Sources",
            value=f"{unique_sources:,}"
        )


def render_articles_over_time(df: pd.DataFrame):
    """Visualization 1: Articles ingested over time."""

    st.subheader("📈 Articles Over Time")

    df_valid = df.dropna(subset=['published_at']).copy()

    if df_valid.empty:
        st.warning("No articles with valid publication dates")
        return

    df_valid['date'] = df_valid['published_at'].dt.date
    daily_counts = df_valid.groupby('date').size().reset_index(name='article_count')
    daily_counts['date'] = pd.to_datetime(daily_counts['date'])

    if len(daily_counts) == 1:
        single_date = daily_counts['date'].iloc[0]
        article_count = daily_counts['article_count'].iloc[0]
        
        fig = go.Figure(data=[
            go.Bar(
                x=[single_date],
                y=[article_count],
                marker_color='#1f77b4',
                width=[1000 * 60 * 60 * 24 * 0.2]  # Narrower: 20% of a day
            )
        ])
        
        fig.update_layout(
            title='Daily Article Ingestion',
            xaxis=dict(
                range=[single_date - pd.Timedelta(days=1), single_date + pd.Timedelta(days=1)],
                tickformat='%Y-%m-%d',
                title='Date'
            ),
            yaxis=dict(
                range=[0, article_count * 1.2],
                title='Number of Articles'
            ),
            hovermode='x unified'
        )
    else:
        fig = px.area(
            daily_counts, x='date', y='article_count',
            title='Daily Article Ingestion',
            labels={'date': 'Date', 'article_count': 'Articles'},
            color_discrete_sequence=['#1f77b4'], markers=True
        )
        fig.update_xaxes(tickformat='%Y-%m-%d')
        fig.update_yaxes(rangemode='tozero')

    fig.update_layout(
        xaxis_title="Date",
        yaxis_title="Number of Articles",
        hovermode='x unified'
    )

    st.plotly_chart(fig, use_container_width=True)

    col1, col2, col3 = st.columns(3)
    with col1:
        st.caption(
            f"**Date Range:** {daily_counts['date'].min().strftime('%Y-%m-%d')} to {daily_counts['date'].max().strftime('%Y-%m-%d')}")
    with col2:
        st.caption(
            f"**Peak Day:** {daily_counts.loc[daily_counts['article_count'].idxmax(), 'date'].strftime('%Y-%m-%d')} ({daily_counts['article_count'].max()} articles)")
    with col3:
        st.caption(
            f"**Daily Average:** {daily_counts['article_count'].mean():.1f} articles")


def render_sentiment_trends(df: pd.DataFrame):
    """Visualization 2: Sentiment distribution and trends."""

    st.subheader("😊 Sentiment Analysis")

    col1, col2 = st.columns(2)

    with col1:
        # Sentiment distribution
        df_sentiment = df.dropna(subset=['sentiment_score'])

        if df_sentiment.empty:
            st.warning("No articles with sentiment scores")
            return

        # Categorize sentiment
        def categorize_sentiment(score):
            if score < -0.3:
                return 'Negative'
            elif score > 0.3:
                return 'Positive'
            else:
                return 'Neutral'

        df_sentiment['category'] = df_sentiment['sentiment_score'].apply(
            categorize_sentiment)
        category_counts = df_sentiment['category'].value_counts().reset_index()
        category_counts.columns = ['category', 'count']

        # Define colors
        color_map = {'Positive': '#2ecc71',
                     'Neutral': '#95a5a6', 'Negative': '#e74c3c'}

        fig = px.pie(
            category_counts,
            values='count',
            names='category',
            title='Sentiment Distribution',
            color='category',
            color_discrete_map=color_map
        )

        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Sentiment histogram
        fig = px.histogram(
            df_sentiment,
            x='sentiment_score',
            nbins=30,
            title='Sentiment Score Distribution',
            labels={'sentiment_score': 'Sentiment Score', 'count': 'Articles'},
            color_discrete_sequence=['#3498db']
        )

        fig.add_vline(x=0, line_dash="dash", line_color="gray",
                      annotation_text="Neutral")
        fig.update_layout(
            xaxis_title="Sentiment Score (-1 to 1)",
            yaxis_title="Number of Articles"
        )

        st.plotly_chart(fig, use_container_width=True)


def render_top_sources(df: pd.DataFrame):
    """Visualization 3: Top news sources."""

    st.subheader("🏆 Top News Sources")

    # Count articles by source
    source_counts = df['source'].value_counts().head(10).reset_index()
    source_counts.columns = ['source', 'article_count']

    if source_counts.empty:
        st.warning("No source data available")
        return

    fig = px.bar(
        source_counts,
        x='article_count',
        y='source',
        orientation='h',
        title='Top 10 News Sources by Article Count',
        labels={'source': 'Source', 'article_count': 'Articles'},
        color='article_count',
        color_continuous_scale='Blues'
    )

    fig.update_layout(
        yaxis={'categoryorder': 'total ascending'},
        xaxis_title="Number of Articles",
        yaxis_title="Source",
        showlegend=False
    )

    st.plotly_chart(fig, use_container_width=True)

    # Add source diversity metric
    total_sources = df['source'].nunique()
    top_3_share = source_counts.head(3)['article_count'].sum() / len(df) * 100
    st.caption(
        f"**Source Diversity:** {total_sources} unique sources | Top 3 sources account for {top_3_share:.1f}% of articles")


def render_pipeline_health(logs_df: pd.DataFrame):
    """Show pipeline health and recent activity."""

    st.subheader("🔧 Pipeline Health")

    if logs_df.empty:
        st.info(
            "No pipeline logs available yet. Trigger the ETL pipeline to see logs here.")
        return

    col1, col2 = st.columns([2, 1])

    with col1:
        # Log level distribution
        level_counts = logs_df['log_level'].value_counts().reset_index()
        level_counts.columns = ['level', 'count']

        color_map = {'INFO': '#2ecc71',
                     'WARNING': '#f39c12', 'ERROR': '#e74c3c'}

        fig = px.pie(
            level_counts,
            values='count',
            names='level',
            title='Log Level Distribution (Last 50 Entries)',
            color='level',
            color_discrete_map=color_map
        )

        st.plotly_chart(fig, use_container_width=True)

    with col2:
        # Recent errors/warnings
        issues = logs_df[logs_df['log_level'].isin(
            ['WARNING', 'ERROR'])].head(5)

        if not issues.empty:
            st.markdown("**Recent Issues:**")
            for _, row in issues.iterrows():
                emoji = "⚠️" if row['log_level'] == 'WARNING' else "❌"
                st.markdown(f"{emoji} {row['message'][:50]}...")
        else:
            st.success("No recent warnings or errors!")

        # Last run time
        last_run = logs_df['run_timestamp'].max()
        if pd.notna(last_run):
            st.markdown(f"**Last Activity:** {last_run}")


def render_sidebar(df: pd.DataFrame):
    """Render sidebar with filters and info."""

    st.sidebar.header("Filters")

    # Date range filter
    if not df['published_at'].isna().all():
        min_date = df['published_at'].min().date()
        max_date = df['published_at'].max().date()

        date_range = st.sidebar.date_input(
            "Date Range",
            value=(min_date, max_date),
            min_value=min_date,
            max_value=max_date
        )

        if len(date_range) == 2:
            start_date, end_date = date_range
            mask = (df['published_at'].dt.date >= start_date) & (
                df['published_at'].dt.date <= end_date)
            df = df[mask]

    # Source filter
    sources = ['All'] + sorted(df['source'].dropna().unique().tolist())
    selected_source = st.sidebar.selectbox("Source", sources)

    if selected_source != 'All':
        df = df[df['source'] == selected_source]

    st.sidebar.divider()
    st.sidebar.header("About")
    st.sidebar.markdown("""
    This dashboard visualizes data from an automated news ETL pipeline.

    **Features:**
    - Daily article ingestion tracking
    - Sentiment analysis visualization
    - Source diversity metrics
    - Pipeline health monitoring

    **Data refreshes every 5 minutes.**
    """)

    return df


def main():
    """Main application entry point."""
    render_header()

    # Load data
    with st.spinner("Loading data..."):
        df = load_articles()
        logs_df = load_pipeline_logs()

    if df.empty:
        st.warning(
            "No articles found in the database. Run the ETL pipeline to ingest data.")
        st.stop()

    # Apply filters from sidebar
    filtered_df = render_sidebar(df)

    # Render metrics
    render_metrics(filtered_df)

    st.divider()

    # Render visualizations
    render_articles_over_time(filtered_df)

    st.divider()

    render_sentiment_trends(filtered_df)

    st.divider()

    render_top_sources(filtered_df)

    st.divider()

    render_pipeline_health(logs_df)

    # Footer
    st.divider()
    st.caption(
        f"Dashboard last refreshed: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")


if __name__ == "__main__":
    main()

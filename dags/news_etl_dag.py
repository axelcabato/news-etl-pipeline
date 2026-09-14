from datetime import datetime, timedelta
from airflow import DAG
from airflow.providers.docker.operators.docker import DockerOperator
from docker.types import Mount

# Define default arguments that apply to all tasks in this DAG
default_args = {
    'owner': 'airflow',
    'depends_on_past': False,
    'email_on_failure': False,
    'email_on_retry': False,
    'retries': 1,
    'retry_delay': timedelta(minutes=5),
}

# Create the DAG
with DAG(
    dag_id='news_etl_pipeline',
    default_args=default_args,
    description='Daily ETL pipeline that fetches news articles and stores them in PostgreSQL',
    schedule_interval='@daily',
    start_date=datetime(2026, 2, 1),
    catchup=False,
    tags=['etl', 'news'],
) as dag:

    # Define the task that runs your ETL container
    run_etl = DockerOperator(
        task_id='run_news_etl',
        image='news-etl-etl_app:latest',
        force_pull=False,
        container_name='airflow_triggered_etl',
        api_version='auto',
        auto_remove=True,
        docker_url='unix://var/run/docker.sock',
        network_mode='news-etl-pipeline_default',
        environment={
            'NEWS_API_KEY': '{{ var.value.NEWS_API_KEY }}',
            'POSTGRES_URL': 'postgresql://user:password@postgres:5432/news_db',
        },
        mount_tmp_dir=False,
    )

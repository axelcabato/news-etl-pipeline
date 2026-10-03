-- Create a separate database for Airflow metadata
CREATE DATABASE airflow_db;

-- Grant privileges to user
GRANT ALL PRIVILEGES ON DATABASE airflow_db TO "user";
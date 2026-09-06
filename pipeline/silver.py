"""Silver layer: cleaned, conformed entities."""

from pyspark.sql import SparkSession

spark = SparkSession.builder.getOrCreate()

SESSION_TIMEOUT_MIN = 45


def clean_sessions():
    """Sessionise raw events. Writes main.silver.sessions."""
    events = spark.table("main.bronze.raw_events")
    events.createOrReplaceTempView("ev")

    sessions = spark.sql(
        f"""
        SELECT
            user_id,
            session_id,
            MIN(event_ts)                AS started_at,
            MAX(event_ts)                AS ended_at,
            COUNT(*)                     AS event_count,
            SUM(revenue_cents) / 100.0   AS revenue,
            FIRST(country)               AS country
        FROM ev
        WHERE event_ts IS NOT NULL
          AND datediff(minute, event_ts, now()) < {SESSION_TIMEOUT_MIN * 60}
        GROUP BY user_id, session_id
        """
    )
    sessions.write.mode("overwrite").saveAsTable("main.silver.sessions")


def clean_users():
    spark.sql(
        """
        CREATE OR REPLACE TABLE main.silver.users AS
        SELECT
            CAST(id AS BIGINT)   AS user_id,
            lower(email)         AS email,
            signup_date,
            plan_tier
        FROM main.bronze.raw_users
        WHERE id IS NOT NULL
        """
    )

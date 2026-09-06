"""Gold layer: business aggregates that dashboards read."""

from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.getOrCreate()

CATALOG = "main"
GOLD = f"{CATALOG}.gold"


def daily_revenue():
    """Revenue rolled up per day and plan tier."""
    sessions = spark.table("main.silver.sessions")
    users = spark.read.table("main.silver.users")

    joined = sessions.join(users, on="user_id", how="left")
    agg = (
        joined.groupBy(F.to_date("started_at").alias("day"), "plan_tier")
        .agg(
            F.sum("revenue").alias("revenue"),
            F.countDistinct("session_id").alias("sessions"),
        )
    )
    agg.write.mode("overwrite").saveAsTable(f"{GOLD}.daily_revenue")


def user_retention():
    spark.sql(
        """
        CREATE OR REPLACE TABLE main.gold.user_retention AS
        SELECT
            u.plan_tier,
            u.signup_date,
            COUNT(DISTINCT s.user_id) AS returning_users
        FROM main.silver.sessions s
        JOIN main.silver.users u USING (user_id)
        WHERE s.event_count > 1
        GROUP BY u.plan_tier, u.signup_date
        """
    )


def refresh_country_rollup():
    spark.sql(
        "INSERT OVERWRITE main.gold.revenue_by_country "
        "SELECT country, SUM(revenue) AS revenue "
        "FROM main.silver.sessions GROUP BY country"
    )

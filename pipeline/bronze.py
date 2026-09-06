"""Bronze layer: raw ingest from the events landing zone."""

from pyspark.sql import SparkSession, functions as F

spark = SparkSession.builder.getOrCreate()

LANDING = "/Volumes/main/landing/events"


def ingest_raw_events():
    df = (
        spark.read.format("json")
        .option("inferSchema", "true")
        .load(LANDING)
    )
    df = df.withColumn("_ingested_at", F.current_timestamp())
    df.write.mode("overwrite").saveAsTable("main.bronze.raw_events")


def ingest_users():
    df = spark.read.format("csv").option("header", "true").load(
        "/Volumes/main/landing/users"
    )
    df.write.mode("overwrite").saveAsTable("main.bronze.raw_users")

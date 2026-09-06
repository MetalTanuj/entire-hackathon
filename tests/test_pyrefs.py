import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinel.pyrefs import table_refs_in_python


def _tables(source, direction=None):
    refs = table_refs_in_python(source)
    return {r.table for r in refs if direction is None or r.direction == direction}


def test_save_as_table_is_a_write():
    assert _tables('df.write.saveAsTable("main.bronze.raw_events")') == {
        "main.bronze.raw_events"
    }


def test_spark_table_is_a_read():
    src = 'events = spark.table("main.bronze.raw_events")'
    assert _tables(src, "READS_TABLE") == {"main.bronze.raw_events"}


def test_fstring_is_folded_through_module_constants():
    src = '\n'.join([
        'CATALOG = "main"',
        'GOLD = f"{CATALOG}.gold"',
        'df.write.saveAsTable(f"{GOLD}.daily_revenue")',
    ])
    refs = table_refs_in_python(src)
    assert [(r.table, r.resolution) for r in refs] == [
        ("main.gold.daily_revenue", "inferred")
    ]


def test_unresolvable_placeholder_yields_no_reference():
    # Half a table name is worse than none: a partial match would join to the
    # wrong lineage node, or to nothing, and look like a real answer either way.
    src = 'df.write.saveAsTable(f"{unknown_prefix}.daily_revenue")'
    assert table_refs_in_python(src) == []


def test_embedded_sql_is_read_through_the_sql_extractor():
    src = 'spark.sql("CREATE OR REPLACE TABLE main.silver.users AS SELECT * FROM main.bronze.raw_users")'
    assert _tables(src, "WRITES_TABLE") == {"main.silver.users"}
    assert _tables(src, "READS_TABLE") == {"main.bronze.raw_users"}


def test_storage_paths_are_not_tables():
    assert table_refs_in_python('spark.read.table("/Volumes/main/landing/events")') == []


def test_unparseable_source_yields_nothing():
    assert table_refs_in_python("def broken(:\n") == []

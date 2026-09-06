import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from sentinel.sqlrefs import table_refs


def test_dashboard_select():
    refs = table_refs("SELECT day FROM main.gold.daily_revenue WHERE day > 1")
    assert refs.reads == {"main.gold.daily_revenue"}
    assert refs.writes == frozenset()


def test_create_or_replace_names_its_target():
    refs = table_refs(
        """
        CREATE OR REPLACE TABLE main.silver.users AS
        SELECT CAST(id AS BIGINT) AS user_id FROM main.bronze.raw_users
        """
    )
    assert refs.writes == {"main.silver.users"}
    assert refs.reads == {"main.bronze.raw_users"}


def test_insert_overwrite_is_a_write_not_a_create():
    refs = table_refs(
        "INSERT OVERWRITE main.gold.revenue_by_country "
        "SELECT country FROM main.silver.sessions GROUP BY country"
    )
    assert refs.writes == {"main.gold.revenue_by_country"}
    assert refs.reads == {"main.silver.sessions"}


def test_join_contributes_a_read():
    refs = table_refs(
        """
        CREATE OR REPLACE TABLE main.gold.user_retention AS
        SELECT u.plan_tier FROM main.silver.sessions s
        JOIN main.silver.users u USING (user_id)
        """
    )
    assert refs.reads == {"main.silver.sessions", "main.silver.users"}
    assert refs.writes == {"main.gold.user_retention"}


def test_cte_is_not_a_stored_table():
    refs = table_refs(
        """
        WITH recent AS (SELECT * FROM main.silver.sessions)
        SELECT * FROM recent
        """
    )
    assert refs.reads == {"main.silver.sessions"}


def test_comments_and_literals_are_not_dependencies():
    refs = table_refs(
        """
        -- rebuild FROM main.dead.old_table
        SELECT 'FROM main.fake.quoted' AS note
        FROM main.silver.sessions
        /* FROM main.commented.block */
        """
    )
    assert refs.reads == {"main.silver.sessions"}


def test_unqualified_and_backticked_names():
    refs = table_refs("SELECT * FROM `main`.`silver`.`sessions` JOIN events USING (id)")
    assert refs.reads == {"main.silver.sessions", "events"}


def test_unrecognised_shape_yields_nothing_rather_than_a_guess():
    assert not table_refs("SHOW TABLES IN main.silver")

from __future__ import annotations

import importlib
from types import SimpleNamespace

import sqlalchemy as sa
from alembic.config import Config
from alembic.migration import MigrationContext
from alembic.operations import Operations
from alembic.script import ScriptDirectory

from server.infrastructure.mysql.models import AuthCodeModel


def test_migration_graph_has_one_head_after_all_feature_branches_are_merged() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))

    assert scripts.get_heads() == ["20260914_55_email_registration"]
    assert scripts.get_revision("20260914_55_email_registration").down_revision == (
        "20260912_54_usage_cache_fix"
    )
    assert scripts.get_revision("20260912_54_usage_cache_fix").down_revision == (
        "20260910_53_whiteboard_library"
    )
    assert scripts.get_revision("20260905_49_phone_schema_repair").down_revision == (
        "20260904_48_developer_merge"
    )
    assert scripts.get_revision("20260907_50_merge_database_heads").down_revision == (
        "20260904_49_billable_features",
        "20260905_49_phone_schema_repair",
    )
    assert scripts.get_revision("20260907_49_reset_permission").down_revision == (
        "20260904_49_billable_features"
    )
    assert scripts.get_revision("20260907_50_obs_indexes").down_revision == (
        "20260907_49_reset_permission"
    )
    assert scripts.get_revision("20260907_51_merge_database_heads").down_revision == (
        "20260907_50_merge_database_heads",
        "20260907_50_obs_indexes",
    )
    assert scripts.get_revision("20260904_49_billable_features").down_revision == (
        "20260904_48_developer_merge"
    )
    assert scripts.get_revision("20260904_48_developer_merge").down_revision == (
        "20260903_46_remove_dev_sessions",
        "20260903_47_sms_send_locks",
    )
    assert scripts.get_revision("20260903_46_remove_dev_sessions").down_revision == (
        "20260901_45_audit_quota_merge"
    )
    assert scripts.get_revision("20260903_47_sms_send_locks").down_revision == (
        "20260903_46_fixed_role_backfill"
    )
    assert scripts.get_revision("20260903_46_fixed_role_backfill").down_revision == (
        "20260902_45_merge_auth_quota"
    )
    assert scripts.get_revision("20260902_45_merge_auth_quota").down_revision == (
        "20260901_44_quota_summary",
        "20260831_43_auth_code_identity",
    )
    assert scripts.get_revision("20260831_43_auth_code_identity").down_revision == (
        "20260831_42_merge_heads"
    )
    assert scripts.get_revision("20260901_44_quota_summary").down_revision == (
        "20260901_43_role_credit_ops",
        "20260831_40_summary_merge",
    )
    assert scripts.get_revision("20260901_43_role_credit_ops").down_revision == (
        "20260831_42_quota_daily_weekly"
    )
    assert scripts.get_revision("20260830_43_quota_scope_lock").down_revision == (
        "20260830_42_quota_phase4"
    )
    assert scripts.get_revision("20260830_42_quota_phase4").down_revision == (
        "20260830_41_quota_menu"
    )
    assert scripts.get_revision("20260830_41_quota_menu").down_revision == (
        "20260830_40_quota_phase3"
    )
    assert scripts.get_revision("20260831_39_feedback_student").down_revision == (
        "20260831_38_feedback_write"
    )
    assert scripts.get_revision("20260831_40_summary_merge").down_revision == (
        "20260831_39_feedback_student",
        "20260831_39_summary_backoff",
    )
    assert scripts.get_revision("20260831_39_feedback_student").down_revision == "20260831_38_feedback_write"
    assert scripts.get_revision("20260831_38_feedback_write").down_revision == "20260831_37_feedback_meta"
    assert scripts.get_revision("20260831_37_feedback_meta").down_revision == "20260829_36_usage_indexes"
    assert scripts.get_revision("20260831_39_summary_backoff").down_revision == "20260830_38_session_title_manual"
    assert scripts.get_revision("20260830_38_session_title_manual").down_revision == "20260829_37_session_summary"
    assert scripts.get_revision("20260829_37_session_summary").down_revision == "20260829_36_usage_indexes"
    assert scripts.get_revision("20260829_36_usage_indexes").down_revision == "20260829_35_user_mgmt_menus"
    assert scripts.get_revision("20260829_35_user_mgmt_menus").down_revision == "20260828_34_auth_codes"
    assert scripts.get_revision("20260828_34_auth_codes").down_revision == "20260828_33_user_phone"
    assert scripts.get_revision("20260828_33_user_phone").down_revision == "20260827_32_book_merge"
    assert scripts.get_revision("20260827_32_book_merge").down_revision == (
        "20260826_29",
        "20260827_31_book_assets",
    )


def test_migration_revision_ids_fit_alembic_version_column() -> None:
    scripts = ScriptDirectory.from_config(Config("alembic.ini"))

    assert all(len(revision.revision) <= 32 for revision in scripts.walk_revisions())


def test_auth_code_subject_accepts_full_length_email_addresses() -> None:
    assert AuthCodeModel.__table__.c.subject.type.length == 254


def test_email_registration_migration_expands_auth_code_subject(monkeypatch) -> None:
    migration = importlib.import_module(
        "migrations.versions.20260914_55_email_registration"
    )
    alterations: list[tuple[str, str, dict[str, object]]] = []
    fake_op = SimpleNamespace(
        alter_column=lambda table, column, **kwargs: alterations.append(
            (table, column, kwargs)
        ),
        execute=lambda statement: None,
    )
    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration, "_user_columns", lambda: {"email", "email_normalized"})
    monkeypatch.setattr(
        migration,
        "_has_table",
        lambda name: name
        in {"nlp_auth_codes", "nlp_email_send_audits", "nlp_email_send_locks"},
    )

    migration.upgrade()

    assert len(alterations) == 1
    table, column, options = alterations[0]
    assert (table, column) == ("nlp_auth_codes", "subject")
    assert options["existing_type"].length == 64
    assert options["type_"].length == 254
    assert options["existing_nullable"] is False


def test_usage_cache_backfill_repairs_only_provable_legacy_facts(
    monkeypatch,
) -> None:
    migration = importlib.import_module(
        "migrations.versions.20260912_54_usage_cache_attribution_backfill"
    )
    added_columns: list[tuple[str, sa.Column]] = []
    statements: list[str] = []
    fake_op = SimpleNamespace(
        add_column=lambda table, column: added_columns.append((table, column)),
        execute=lambda statement: statements.append(str(statement)),
    )
    monkeypatch.setattr(migration, "op", fake_op)
    monkeypatch.setattr(migration, "_usage_columns", lambda: set())

    migration.upgrade()

    assert added_columns[0][0] == "nlp_usage_events"
    assert added_columns[0][1].name == "cache_status"
    sql = "\n".join(statements)
    assert "usage_source = 'provider'" in sql
    assert "cache_miss_input_tokens > 0" in sql
    assert "preset LIKE 'coordinator-%'" in sql
    assert "preset LIKE 'worker-%'" in sql
    assert "nlp_observability_records" in sql
    assert "$.payload.attributes.operation_id" in sql
    assert "$.payload.worker_id" in sql
    assert "route = 'utility'" in sql
    assert "route = 'vision-worker'" in sql
    assert "WHERE purpose <> 'worker'" in sql


def test_knowledge_book_page_text_columns_have_no_mysql_default() -> None:
    migration = importlib.import_module(
        "migrations.versions.20260825_25_knowledge_book_pages"
    )
    tables: list[sa.Table] = []

    def capture_table(name: str, *columns: sa.Column, **kwargs: object) -> None:
        tables.append(sa.Table(name, sa.MetaData(), *columns))

    migration.op = SimpleNamespace(create_table=capture_table)
    migration.upgrade()

    draft_markdown = tables[0].c.draft_markdown
    assert draft_markdown.server_default is None


def test_quota_daily_weekly_migration_renames_legacy_monthly_rows() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    sa.Table(
        "nlp_quota_policies",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("monthly_limit_micro", sa.BigInteger()),
    )
    for table_name in (
        "nlp_quota_buckets",
        "nlp_quota_grants",
        "nlp_quota_adjustments",
        "nlp_quota_credit_operations",
    ):
        sa.Table(
            table_name,
            metadata,
            sa.Column("id", sa.String(), primary_key=True),
            sa.Column("bucket_type", sa.String(), nullable=False),
        )
    metadata.create_all(engine)

    with engine.begin() as connection:
        for table_name in (
            "nlp_quota_buckets",
            "nlp_quota_grants",
            "nlp_quota_adjustments",
            "nlp_quota_credit_operations",
        ):
            connection.execute(
                metadata.tables[table_name].insert().values(
                    id=table_name, bucket_type="monthly"
                )
            )
        migration_context = MigrationContext.configure(connection)
        migration = importlib.import_module(
            "migrations.versions.20260831_42_quota_daily_weekly"
        )
        migration.op = Operations(migration_context)

        migration.upgrade()

        columns = {
            item["name"]
            for item in sa.inspect(connection).get_columns("nlp_quota_policies")
        }
        assert "weekly_limit_micro" in columns
        assert "monthly_limit_micro" not in columns
        for table_name in (
            "nlp_quota_buckets",
            "nlp_quota_grants",
            "nlp_quota_adjustments",
            "nlp_quota_credit_operations",
        ):
            assert connection.execute(
                sa.select(metadata.tables[table_name].c.bucket_type)
            ).scalar_one() == "weekly"


def test_phone_schema_repair_adds_missing_normalized_column_and_backfills() -> None:
    engine = sa.create_engine("sqlite:///:memory:")
    metadata = sa.MetaData()
    users = sa.Table(
        "nlp_users",
        metadata,
        sa.Column("id", sa.String(), primary_key=True),
        sa.Column("phone_number", sa.String(20)),
        sa.Column("created_at", sa.DateTime(), nullable=False),
    )
    metadata.create_all(engine)

    migration = importlib.import_module(
        "migrations.versions.20260905_49_repair_user_phone_schema_drift"
    )
    with engine.begin() as connection:
        connection.execute(
            users.insert().values(
                id="user-1",
                phone_number="138 0013 8000",
                created_at=sa.text("CURRENT_TIMESTAMP"),
            )
        )
        migration_context = MigrationContext.configure(connection)
        operations = Operations(migration_context)

        migration.op = SimpleNamespace(
            get_bind=operations.get_bind,
            add_column=operations.add_column,
            create_index=operations.create_index,
            create_unique_constraint=lambda name, table, columns: connection.exec_driver_sql(
                f'CREATE UNIQUE INDEX "{name}" ON "{table}" ("{columns[0]}")'
            ),
        )

        migration.upgrade()

        columns = {
            item["name"]
            for item in sa.inspect(connection).get_columns("nlp_users")
        }
        assert "phone_number_normalized" in columns
        assert connection.execute(
            sa.text(
                "SELECT phone_number_normalized FROM nlp_users WHERE id='user-1'"
            )
        ).scalar_one() == "+8613800138000"

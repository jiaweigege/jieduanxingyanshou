import click
from sqlalchemy import text

from app import db
from app.models import KnowledgeEntry
from app.retrieval import (
    ensure_search_capabilities,
    initialize_search_index,
    replace_entry_index,
)
from app.seed import seed_database
from app.solver import ensure_all_default_skills


def register_commands(app):
    @app.cli.command("init-db")
    def init_db():
        try:
            db.create_all()
            initialize_search_index()
            ensure_all_default_skills()
            if app.config["AI_PLATFORM_ENABLED"]:
                from app.platform_resources import initialize_platform
                initialize_platform()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
        app.logger.info("Database initialized")

    @app.cli.command("backfill-knowledge-index")
    def backfill_knowledge_index():
        """Create or refresh chunks and FTS rows for every knowledge entry."""
        try:
            initialize_search_index()
            db.session.commit()
        except Exception as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc

        entry_ids = list(
            db.session.scalars(
                db.select(KnowledgeEntry.id).order_by(KnowledgeEntry.id.asc())
            )
        )
        db.session.commit()
        succeeded = 0
        failures = []
        for entry_id in entry_ids:
            try:
                with db.session.begin():
                    entry = db.session.get(KnowledgeEntry, entry_id)
                    replace_entry_index(entry)
                succeeded += 1
            except Exception as exc:
                db.session.rollback()
                failures.append((entry_id, str(exc)))
                app.logger.error("Index backfill failed for entry %s: %s", entry_id, exc)

        click.echo(f"Indexed {succeeded} knowledge entries; {len(failures)} failed.")
        if failures:
            failed_ids = ", ".join(str(entry_id) for entry_id, _ in failures)
            raise click.ClickException(f"Backfill failed for entries: {failed_ids}")

    @app.cli.command("check-search")
    def check_search():
        """Report whether SQLite has the required FTS5 trigram support."""
        try:
            ensure_search_capabilities()
            version = db.session.execute(text("SELECT sqlite_version()")).scalar_one()
            db.session.rollback()
        except Exception as exc:
            db.session.rollback()
            raise click.ClickException(str(exc)) from exc
        click.echo(f"SQLite {version}: FTS5 trigram support available")

    @app.cli.command("seed")
    def seed():
        seed_database()
        app.logger.info("Seed data created")

    @app.cli.command("init-platform")
    def init_platform():
        from app.platform_resources import initialize_platform
        db.create_all()
        initialize_platform()
        click.echo("AI platform initialized")

    @app.cli.command("cleanup-platform-traces")
    def cleanup_platform_traces():
        from app.platform_trace import cleanup_traces
        click.echo(f"Removed {cleanup_traces()} expired traces")

    @app.cli.command("recover-platform-runs")
    def recover_platform_runs():
        from datetime import timedelta
        from app.platform_models import ConversationRun, AppConversation, now
        stale = db.session.scalars(db.select(ConversationRun).where(
            ConversationRun.status == "running", ConversationRun.created_at < now() - timedelta(seconds=app.config["AI_RUN_TIMEOUT"])
        )).all()
        for run in stale:
            run.status, run.error = "interrupted", "run_interrupted"
            db.session.execute(db.update(AppConversation).where(AppConversation.active_run_id == run.id).values(active_run_id=None))
        db.session.commit()
        click.echo(f"Interrupted {len(stale)} stale runs; no calls replayed")

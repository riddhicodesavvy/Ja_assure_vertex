"""Supabase Repository — all database reads/writes.

The only module that knows the DB schema.
"""

from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any
from uuid import UUID, uuid4

from app.research.enums import ChangeStatus, RunStatus
from app.research.models import Evidence, Finding, Conflict, ResearchResult

logger = logging.getLogger("ja_assure")


class ResearchRepository:
    """Repository for research run persistence using Supabase."""

    def __init__(self, supabase_url: str, supabase_key: str):
        from supabase import create_client
        self._client = create_client(supabase_url, supabase_key)

    # ── Research Runs ─────────────────────────────────────────────

    def create_run(
        self,
        brand: str,
        market: str,
        research_type: str,
        objective: str | None,
        request_hash: str,
        lookback_days: int,
        status: str = RunStatus.IDLE.value,
    ) -> UUID:
        """Create a new research run row. Returns the run ID."""
        run_id = uuid4()
        data = {
            "id": str(run_id),
            "brand": brand,
            "market": market,
            "research_type": research_type,
            "objective": objective,
            "request_hash": request_hash,
            "lookback_days": lookback_days,
            "status": status,
            "started_at": datetime.now(timezone.utc).isoformat(),
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        try:
            self._client.table("research_runs").insert(data).execute()
            logger.info(f"Created research run: id={run_id}")
            return run_id
        except Exception as e:
            logger.error(f"Failed to create run: {e}")
            raise

    def update_run_status(self, run_id: UUID, status: str):
        """Update the status of a research run."""
        try:
            self._client.table("research_runs").update(
                {"status": status}
            ).eq("id", str(run_id)).execute()
        except Exception as e:
            logger.error(f"Failed to update run status: {e}")
            raise

    def attach_plan(self, run_id: UUID, plan_dict: dict):
        """Attach the research plan to a run."""
        try:
            self._client.table("research_runs").update(
                {"plan": plan_dict}
            ).eq("id", str(run_id)).execute()
        except Exception as e:
            logger.error(f"Failed to attach plan: {e}")
            raise

    def complete_run(
        self,
        run_id: UUID,
        status: str,
        metrics: dict,
        error_message: str | None = None,
        metadata: dict | None = None,
    ):
        """Set the terminal state and metrics of a run."""
        update = {
            "status": status,
            "completed_at": datetime.now(timezone.utc).isoformat(),
            "sources_checked": metrics.get("sources_checked", 0),
            "unique_sources": metrics.get("unique_sources", 0),
            "relevant_sources": metrics.get("relevant_sources", 0),
            "new_findings": metrics.get("new_findings", 0),
            "changed_findings": metrics.get("changed_findings", 0),
            "unchanged_findings": metrics.get("unchanged_findings", 0),
            "tavily_calls": metrics.get("tavily_calls", 0),
            "groq_calls": metrics.get("groq_calls", 0),
            "dropped_findings": metrics.get("dropped_findings", 0),
            "confidence_score": metrics.get("confidence_score"),
            "error_message": error_message,
            "metadata": metadata or {},
        }
        try:
            self._client.table("research_runs").update(update).eq("id", str(run_id)).execute()
            logger.info(f"Completed run {run_id}: status={status}")
        except Exception as e:
            logger.error(f"Failed to complete run: {e}")
            raise

    def set_run_failed(self, run_id: UUID, error_message: str):
        """Mark a run as FAILED."""
        self.complete_run(
            run_id, RunStatus.FAILED.value,
            metrics={}, error_message=error_message,
        )

    def get_run(self, run_id: UUID) -> dict | None:
        """Get a research run by ID."""
        try:
            result = self._client.table("research_runs").select("*").eq(
                "id", str(run_id)
            ).execute()
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to get run: {e}")
            raise

    def find_prior_completed_run(
        self, brand: str, market: str, research_type: str
    ) -> dict | None:
        """Find the most recent COMPLETED run for the same (brand, market, type)."""
        try:
            result = (
                self._client.table("research_runs")
                .select("*")
                .eq("brand", brand)
                .eq("market", market)
                .eq("research_type", research_type)
                .eq("status", RunStatus.COMPLETED.value)
                .order("completed_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                return result.data[0]
            return None
        except Exception as e:
            logger.error(f"Failed to find prior run: {e}")
            return None

    def find_inflight_run(self, request_hash: str) -> UUID | None:
        """Check for an in-flight run with the same request_hash."""
        in_flight_statuses = [
            RunStatus.PLANNING.value, RunStatus.RETRIEVING.value,
            RunStatus.NORMALIZING.value, RunStatus.FILTERING.value,
            RunStatus.DETECTING_CHANGES.value, RunStatus.ANALYZING.value,
        ]
        try:
            result = (
                self._client.table("research_runs")
                .select("id, status, started_at")
                .eq("request_hash", request_hash)
                .in_("status", in_flight_statuses)
                .order("started_at", desc=True)
                .limit(1)
                .execute()
            )
            if result.data:
                row = result.data[0]
                # Check if started within last 5 minutes
                started = datetime.fromisoformat(row["started_at"].replace("Z", "+00:00"))
                now = datetime.now(timezone.utc)
                age_minutes = (now - started).total_seconds() / 60
                if age_minutes <= 5:
                    return UUID(row["id"])
            return None
        except Exception as e:
            logger.error(f"Failed to check inflight: {e}")
            return None

    def get_latest_runs_status(self) -> list[dict]:
        """Get the most recent run for each (brand, market, research_type) combo."""
        try:
            # Get all runs ordered by completed_at descending
            result = (
                self._client.table("research_runs")
                .select("id, brand, market, research_type, status, completed_at, new_findings, changed_findings, unchanged_findings")
                .order("completed_at", desc=True)
                .limit(50)
                .execute()
            )
            # Deduplicate by (brand, market, research_type), keeping the most recent
            seen: set[str] = set()
            latest: list[dict] = []
            for row in result.data:
                key = f"{row['brand']}:{row['market']}:{row['research_type']}"
                if key not in seen:
                    seen.add(key)
                    latest.append(row)
            return latest
        except Exception as e:
            logger.error(f"Failed to get status: {e}")
            return []

    # ── Evidence ──────────────────────────────────────────────────

    def save_evidence(self, run_id: UUID, evidence_list: list[Evidence]):
        """Persist all evidence for a run."""
        if not evidence_list:
            return

        rows = []
        for e in evidence_list:
            rows.append({
                "research_run_id": str(run_id),
                "evidence_ref": e.id,
                "source_type": e.source_type.value if hasattr(e.source_type, 'value') else str(e.source_type),
                "source_name": e.source_name,
                "source_quality": e.source_quality,
                "title": e.title,
                "url": e.display_url or e.url,
                "normalized_url": e.url,
                "url_hash": e.url_hash,
                "content_hash": e.content_hash,
                "content": e.content,
                "published_at": e.published_at.isoformat() if e.published_at else None,
                "retrieved_at": e.retrieved_at.isoformat() if e.retrieved_at else datetime.now(timezone.utc).isoformat(),
                "market": e.market,
                "competitor": e.competitor,
                "topic": e.topic,
                "query": e.query,
                "tavily_operation": e.tavily_operation,
                "relevance": e.relevance.value if hasattr(e.relevance, 'value') else str(e.relevance),
                "relevance_score": e.relevance_score,
                "change_status": e.change_status.value if hasattr(e.change_status, 'value') else str(e.change_status),
                "metadata": e.metadata,
            })

        try:
            self._client.table("research_evidence").insert(rows).execute()
            logger.info(f"Saved {len(rows)} evidence rows for run {run_id}")
        except Exception as e:
            logger.error(f"Failed to save evidence: {e}")
            raise

    def get_evidence_for_run(self, run_id: UUID) -> list[dict]:
        """Get all evidence for a run."""
        try:
            result = (
                self._client.table("research_evidence")
                .select("*")
                .eq("research_run_id", str(run_id))
                .execute()
            )
            return result.data
        except Exception as e:
            logger.error(f"Failed to get evidence: {e}")
            raise

    def get_prior_evidence(self, run_id: UUID) -> list[Evidence]:
        """Load evidence from a prior run for change detection."""
        rows = self.get_evidence_for_run(run_id)
        evidence_list: list[Evidence] = []
        for row in rows:
            e = Evidence(
                id=row.get("evidence_ref", ""),
                url_hash=row.get("url_hash", ""),
                content_hash=row.get("content_hash", ""),
            )
            evidence_list.append(e)
        return evidence_list

    # ── Findings ──────────────────────────────────────────────────

    def save_findings(self, run_id: UUID, findings: list[Finding]):
        """Persist all findings for a run."""
        if not findings:
            return

        rows = []
        for f in findings:
            rows.append({
                "id": str(f.id or uuid4()),
                "research_run_id": str(run_id),
                "identity_key": f.identity_key,
                "finding_type": f.finding_type.value if hasattr(f.finding_type, 'value') else str(f.finding_type),
                "title": f.title,
                "summary": f.summary,
                "why_it_matters": f.why_it_matters,
                "opportunity": f.opportunity,
                "entities": f.entities,
                "importance_score": f.importance_score,
                "relevance_score": f.relevance_score,
                "confidence_score": f.confidence_score,
                "ai_confidence": f.ai_confidence,
                "change_status": f.change_status.value if hasattr(f.change_status, 'value') else str(f.change_status),
                "conflicts": [{"description": c.description, "evidence_ids": c.evidence_ids} for c in f.conflicts],
                "supporting_evidence_ids": f.supporting_evidence_ids,
                "metadata": f.metadata,
                "created_at": f.created_at.isoformat() if f.created_at else datetime.now(timezone.utc).isoformat(),
            })

        try:
            self._client.table("research_findings").insert(rows).execute()
            logger.info(f"Saved {len(rows)} findings for run {run_id}")
        except Exception as e:
            logger.error(f"Failed to save findings: {e}")
            raise

    def get_findings_for_run(
        self, run_id: UUID, change_status: str | None = None, min_confidence: int | None = None
    ) -> list[dict]:
        """Get findings for a run, optionally filtered."""
        try:
            query = (
                self._client.table("research_findings")
                .select("*")
                .eq("research_run_id", str(run_id))
            )
            if change_status:
                query = query.eq("change_status", change_status)
            if min_confidence is not None:
                query = query.gte("confidence_score", min_confidence)

            result = query.order("importance_score", desc=True).execute()
            return result.data
        except Exception as e:
            logger.error(f"Failed to get findings: {e}")
            raise

    # ── Competitors ───────────────────────────────────────────────

    def get_competitor_domains(self, brand: str, market: str) -> set[str]:
        """Get known competitor domains for source quality classification."""
        try:
            result = (
                self._client.table("competitors")
                .select("domain")
                .eq("brand", brand)
                .eq("market", market)
                .not_.is_("domain", "null")
                .execute()
            )
            return {row["domain"] for row in result.data if row.get("domain")}
        except Exception:
            return set()

    def save_discovered_competitors(
        self, brand: str, market: str, names: list[str]
    ):
        """Save discovered competitors (not confirmed)."""
        for name in names:
            try:
                self._client.table("competitors").upsert(
                    {
                        "name": name,
                        "brand": brand,
                        "market": market,
                        "discovered": True,
                        "confirmed": False,
                    },
                    on_conflict="name,brand,market",
                ).execute()
            except Exception as e:
                logger.warning(f"Failed to save competitor '{name}': {e}")

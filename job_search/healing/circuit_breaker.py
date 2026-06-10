"""Self-healing ladder for adapter failures.

Failure classes (from spec §10):
  transient     → retry with backoff (handled in base adapter via tenacity)
  silent_drift  → alert + re-run discovery
  endpoint_moved → re-run deterministic fingerprint; commit new config if found
  anti_bot      → back off, reduce frequency, quarantine (NEVER escalate evasion)
  persistent    → circuit open, quarantine, weekly re-probe
"""

from __future__ import annotations

import json
import logging
from datetime import date, timedelta
from sqlite3 import Connection

logger = logging.getLogger(__name__)

PERSISTENT_FAILURE_THRESHOLD = 5  # consecutive failures before circuit opens
QUARANTINE_DAYS = 7
SILENT_DRIFT_ZERO_THRESHOLD = 3   # consecutive zero-result runs flagged as drift


class CircuitBreaker:
    def __init__(self, db: Connection):
        self.db = db

    def record_success(self, source: str, firm_id: str | None, records: int) -> None:
        self.db.execute(
            """
            UPDATE firms SET consecutive_failures = 0,
                             last_successful_fetch = datetime('now'),
                             circuit_state = 'closed',
                             quarantine_until = NULL
            WHERE firm_id = ?
            """,
            (firm_id,),
        )
        if records == 0:
            self._check_silent_drift(source, firm_id)

    def record_failure(
        self,
        source: str,
        firm_id: str | None,
        error_class: str,
        error_detail: str,
        old_config: dict | None = None,
    ) -> None:
        self.db.execute(
            """
            INSERT INTO source_health (source, firm_id, status, error_class, error_detail, old_config)
            VALUES (?, ?, 'error', ?, ?, ?)
            """,
            (source, firm_id, error_class, error_detail, json.dumps(old_config) if old_config else None),
        )

        if not firm_id:
            return

        row = self.db.execute(
            "SELECT consecutive_failures, circuit_state FROM firms WHERE firm_id = ?",
            (firm_id,),
        ).fetchone()

        if not row:
            return

        failures = (row["consecutive_failures"] or 0) + 1
        self.db.execute(
            "UPDATE firms SET consecutive_failures = ? WHERE firm_id = ?",
            (failures, firm_id),
        )

        if error_class == "anti_bot":
            # Back off but do NOT escalate evasion
            logger.warning("Anti-bot block for %s — will quarantine for %d days", firm_id, QUARANTINE_DAYS)
            self._open_circuit(firm_id, "anti_bot block — never escalate evasion")
        elif failures >= PERSISTENT_FAILURE_THRESHOLD:
            logger.error("Persistent failures for %s (%d) — opening circuit", firm_id, failures)
            self._open_circuit(firm_id, f"persistent failure after {failures} attempts")
        elif error_class == "endpoint_moved":
            logger.info("Endpoint moved for %s — scheduling re-fingerprint", firm_id)
            self._schedule_refingerprint(firm_id)

    def _open_circuit(self, firm_id: str, reason: str) -> None:
        quarantine_until = (date.today() + timedelta(days=QUARANTINE_DAYS)).isoformat()
        self.db.execute(
            """
            UPDATE firms
            SET circuit_state = 'open',
                quarantine_until = ?
            WHERE firm_id = ?
            """,
            (quarantine_until, firm_id),
        )
        logger.warning("Circuit OPEN for %s until %s: %s", firm_id, quarantine_until, reason)

    def _check_silent_drift(self, source: str, firm_id: str | None) -> None:
        """Alert on anomalous zero-result runs — silent zeros are more dangerous than loud 500s."""
        if not firm_id:
            return
        recent_zeros = self.db.execute(
            """
            SELECT count(*) as cnt FROM source_health
            WHERE firm_id = ? AND records_fetched = 0
              AND run_at >= datetime('now', '-7 days')
            """,
            (firm_id,),
        ).fetchone()
        if recent_zeros and recent_zeros["cnt"] >= SILENT_DRIFT_ZERO_THRESHOLD:
            logger.warning(
                "SILENT DRIFT detected for %s: %d consecutive zero-result runs",
                firm_id, recent_zeros["cnt"],
            )
            self._schedule_refingerprint(firm_id)

    def _schedule_refingerprint(self, firm_id: str) -> None:
        """Mark firm for re-fingerprinting on next discovery run."""
        self.db.execute(
            "UPDATE firms SET last_fingerprinted = NULL WHERE firm_id = ?",
            (firm_id,),
        )
        logger.info("Re-fingerprint scheduled for %s", firm_id)

    def is_open(self, firm_id: str) -> bool:
        """Return True if the circuit is open (firm is quarantined)."""
        row = self.db.execute(
            "SELECT circuit_state, quarantine_until FROM firms WHERE firm_id = ?",
            (firm_id,),
        ).fetchone()
        if not row or row["circuit_state"] == "closed":
            return False
        if row["quarantine_until"] and row["quarantine_until"] < date.today().isoformat():
            # Quarantine expired — reset to closed so next run can probe
            self.db.execute(
                "UPDATE firms SET circuit_state = 'closed' WHERE firm_id = ?",
                (firm_id,),
            )
            return False
        return True

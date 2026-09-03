from __future__ import annotations

import asyncio
import hashlib
import logging
from typing import Any, AsyncIterator

from app.venues.solana import PUMP_PROGRAM_ID, SolanaResearchError
from app.venues.solana_rpc import SolanaRpcClient, SolanaRpcPumpStream

log = logging.getLogger("edge_lab.solana_rpc_sampled")

# Current Alchemy pricing assigns 40 CU to each of these Solana HTTP methods.
# Keep the safety budget explicit and fail closed if configuration would exceed it.
SIGNATURES_REQUEST_CU = 40
TRANSACTION_REQUEST_CU = 40


class SolanaRpcSampledPumpStream:
    """Bounded, read-only Pump launch discovery over standard Solana HTTP RPC.

    The previous standard-RPC path subscribed to every log mentioning the Pump
    programs and filtered InitializeMint2 only after the provider had delivered
    the payload. Bandwidth-priced WebSockets make that pattern unbounded.

    This sampler instead polls only the Pump creation program, keeps a moving
    signature watermark, deterministically samples a small number of new
    program transactions, and fetches transaction bodies only for that sample.
    It intentionally does no historical backfill on startup. That preserves a
    forward-only research population while imposing a hard estimated CU ceiling.
    """

    def __init__(
        self,
        *,
        http_url: str,
        program_ids: list[str] | None = None,
        commitment: str = "confirmed",
        timeout_seconds: float = 10.0,
        poll_seconds: float = 60.0,
        signatures_per_program: int = 1000,
        max_transactions_per_poll: int = 3,
        hourly_cu_budget: int = 10_000,
    ) -> None:
        if not http_url.strip():
            raise ValueError("SOLANA_RPC_HTTP_URL is required")
        if commitment not in {"processed", "confirmed", "finalized"}:
            raise ValueError("invalid Solana commitment")
        if poll_seconds < 1:
            raise ValueError("poll_seconds must be >= 1")
        if not 1 <= signatures_per_program <= 1000:
            raise ValueError("signatures_per_program must be between 1 and 1000")
        if max_transactions_per_poll < 0:
            raise ValueError("max_transactions_per_poll must be >= 0")
        if hourly_cu_budget <= 0:
            raise ValueError("hourly_cu_budget must be positive")

        self.http_url = http_url.strip()
        self.program_ids = list(program_ids or [PUMP_PROGRAM_ID])
        if not self.program_ids:
            raise ValueError("at least one program id is required")
        self.commitment = commitment
        self.timeout_seconds = timeout_seconds
        self.poll_seconds = float(poll_seconds)
        self.signatures_per_program = int(signatures_per_program)
        self.max_transactions_per_poll = int(max_transactions_per_poll)
        self.hourly_cu_budget = int(hourly_cu_budget)

        if self.estimated_hourly_cu > self.hourly_cu_budget:
            raise ValueError(
                "sampled Solana discovery exceeds hourly RPC CU budget: "
                f"estimated={self.estimated_hourly_cu} budget={self.hourly_cu_budget}"
            )

    @property
    def estimated_cu_per_poll(self) -> int:
        return (
            len(self.program_ids) * SIGNATURES_REQUEST_CU
            + self.max_transactions_per_poll * TRANSACTION_REQUEST_CU
        )

    @property
    def estimated_hourly_cu(self) -> int:
        return int(self.estimated_cu_per_poll * (3600.0 / self.poll_seconds))

    @staticmethod
    def _signature_rank(signature: str) -> bytes:
        return hashlib.sha256(signature.encode("utf-8")).digest()

    def _select_transactions(self, rows: list[tuple[str, int]]) -> list[tuple[str, int]]:
        unique: dict[str, int] = {}
        for signature, slot in rows:
            unique.setdefault(signature, slot)
        ranked = sorted(unique.items(), key=lambda item: self._signature_rank(item[0]))
        return ranked[: self.max_transactions_per_poll]

    async def _signature_rows(
        self,
        rpc: SolanaRpcClient,
        *,
        program_id: str,
        until: str | None,
    ) -> list[dict[str, Any]]:
        config: dict[str, Any] = {
            "commitment": self.commitment,
            "limit": self.signatures_per_program,
        }
        if until:
            config["until"] = until
        result = await rpc.call("getSignaturesForAddress", [program_id, config])
        if not isinstance(result, list):
            raise SolanaResearchError("Solana getSignaturesForAddress returned invalid result")
        return [row for row in result if isinstance(row, dict)]

    async def poll_once(
        self,
        rpc: SolanaRpcClient,
        watermarks: dict[str, str],
    ) -> tuple[list[dict[str, Any]], dict[str, int]]:
        candidates: list[tuple[str, int]] = []
        signature_calls = 0
        transaction_calls = 0
        rows_seen = 0
        saturated_windows = 0

        for program_id in self.program_ids:
            previous = watermarks.get(program_id)
            try:
                rows = await self._signature_rows(rpc, program_id=program_id, until=previous)
                signature_calls += 1
            except SolanaResearchError as exc:
                log.warning("sampled Solana signature poll failed for %s: %s", program_id, exc)
                continue

            if not rows:
                continue
            newest = rows[0].get("signature")
            if newest:
                watermarks[program_id] = str(newest)

            # Startup is forward-only: establish the latest watermark without
            # paying to re-fetch a historical window that the prior live stream
            # may already have observed.
            if previous is None:
                continue

            rows_seen += len(rows)
            if len(rows) >= self.signatures_per_program:
                saturated_windows += 1
            for row in rows:
                if row.get("err") is not None:
                    continue
                signature = row.get("signature")
                slot = row.get("slot")
                if signature and slot is not None:
                    candidates.append((str(signature), int(slot)))

        selected = self._select_transactions(candidates)
        notifications: list[dict[str, Any]] = []
        for signature, slot in selected:
            try:
                transaction_calls += 1
                tx = await rpc.get_transaction(signature, commitment=self.commitment)
            except SolanaResearchError as exc:
                log.debug("sampled Solana transaction fetch failed for %s: %s", signature, exc)
                continue
            if tx is None:
                continue
            meta = tx.get("meta")
            if not isinstance(meta, dict):
                continue
            if not SolanaRpcPumpStream._candidate(
                {"err": meta.get("err"), "logs": meta.get("logMessages")}
            ):
                continue
            normalized = SolanaRpcPumpStream._normalize_notification(signature, slot, tx)
            if normalized is not None:
                notifications.append(normalized)

        estimated_cu = signature_calls * SIGNATURES_REQUEST_CU + transaction_calls * TRANSACTION_REQUEST_CU
        telemetry = {
            "signature_calls": signature_calls,
            "transaction_calls": transaction_calls,
            "rows_seen": rows_seen,
            "selected_transactions": len(selected),
            "launches": len(notifications),
            "saturated_windows": saturated_windows,
            "estimated_cu": estimated_cu,
        }
        return notifications, telemetry

    async def stream(self) -> AsyncIterator[dict[str, Any]]:
        watermarks: dict[str, str] = {}
        async with SolanaRpcClient(
            http_url=self.http_url,
            timeout_seconds=self.timeout_seconds,
        ) as rpc:
            while True:
                try:
                    notifications, telemetry = await self.poll_once(rpc, watermarks)
                    log.info(
                        "sampled Solana discovery: signature_calls=%s transaction_calls=%s "
                        "rows_seen=%s selected=%s launches=%s saturated_windows=%s "
                        "estimated_cu=%s ceiling_cu_per_hour=%s",
                        telemetry["signature_calls"],
                        telemetry["transaction_calls"],
                        telemetry["rows_seen"],
                        telemetry["selected_transactions"],
                        telemetry["launches"],
                        telemetry["saturated_windows"],
                        telemetry["estimated_cu"],
                        self.estimated_hourly_cu,
                    )
                    for notification in notifications:
                        yield notification
                except asyncio.CancelledError:
                    raise
                except Exception:
                    log.exception("sampled Solana discovery cycle failed")
                await asyncio.sleep(self.poll_seconds)

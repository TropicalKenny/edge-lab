import asyncio
import json

import httpx
import pytest

from app.venues.solana import PUMP_AMM_PROGRAM_ID, PUMP_PROGRAM_ID, SolanaResearchError
from app.venues.solana_rpc import SolanaRpcAssetClient, SolanaRpcClient, SolanaRpcPumpStream

MINT = "Mint111111111111111111111111111111111111111"
CREATOR = "Creator11111111111111111111111111111111111"


def test_standard_rpc_stream_uses_one_logs_subscription_per_program():
    stream = SolanaRpcPumpStream(
        http_url="https://example.invalid/rpc",
        ws_url="wss://example.invalid/ws",
    )
    payloads = [json.loads(item) for item in stream.subscribe_messages()]
    assert len(payloads) == 2
    assert all(item["method"] == "logsSubscribe" for item in payloads)
    mentions = {item["params"][0]["mentions"][0] for item in payloads}
    assert mentions == {PUMP_PROGRAM_ID, PUMP_AMM_PROGRAM_ID}
    assert all(item["params"][1]["commitment"] == "confirmed" for item in payloads)


def test_standard_rpc_stream_filters_before_transaction_fetch_and_normalizes():
    assert SolanaRpcPumpStream._candidate(
        {"err": None, "logs": ["Program log: Instruction: InitializeMint2"]}
    )
    assert not SolanaRpcPumpStream._candidate(
        {"err": None, "logs": ["Program log: Instruction: Buy"]}
    )
    assert not SolanaRpcPumpStream._candidate(
        {"err": {"InstructionError": [0, "failed"]}, "logs": ["Program log: Instruction: InitializeMint2"]}
    )

    normalized = SolanaRpcPumpStream._normalize_notification(
        "sig-1",
        123,
        {
            "slot": 124,
            "meta": {"logMessages": ["Program log: Instruction: InitializeMint2"]},
            "transaction": {"message": {"accountKeys": [CREATOR, MINT, PUMP_PROGRAM_ID]}},
        },
    )
    assert normalized is not None
    result = normalized["params"]["result"]
    assert result["signature"] == "sig-1"
    assert result["slot"] == 124
    assert result["transaction"]["transaction"]["message"]["accountKeys"][1] == MINT


def test_standard_rpc_asset_client_parses_spl_mint_metadata():
    seen = []

    async def handler(request: httpx.Request):
        body = json.loads(request.content)
        seen.append(body)
        assert body["method"] == "getAccountInfo"
        assert body["params"][0] == MINT
        assert body["params"][1]["encoding"] == "jsonParsed"
        return httpx.Response(
            200,
            json={
                "jsonrpc": "2.0",
                "id": body["id"],
                "result": {
                    "context": {"slot": 1},
                    "value": {
                        "owner": "Tokenkeg1111111111111111111111111111111111",
                        "data": {
                            "program": "spl-token",
                            "parsed": {
                                "type": "mint",
                                "info": {
                                    "decimals": 6,
                                    "supply": "1000000000",
                                    "mintAuthority": CREATOR,
                                    "freezeAuthority": None,
                                },
                            },
                        },
                    },
                },
            },
        )

    async def run():
        async with SolanaRpcAssetClient(
            http_url="https://example.invalid/rpc",
            transport=httpx.MockTransport(handler),
        ) as client:
            asset = await client.get_asset(MINT)
            assert asset.decimals == 6
            assert asset.supply_atomic == 1_000_000_000
            assert asset.mint_authority == CREATOR
            assert asset.freeze_authority is None
            assert asset.cached_price_usd is None

    asyncio.run(run())
    assert len(seen) == 1


def test_standard_rpc_client_has_no_transaction_submission_path():
    async def handler(_: httpx.Request):
        raise AssertionError("forbidden method should not reach the provider")

    async def run():
        async with SolanaRpcClient(
            http_url="https://example.invalid/rpc",
            transport=httpx.MockTransport(handler),
        ) as client:
            with pytest.raises(SolanaResearchError):
                await client.call("sendTransaction", ["anything"])
            assert not hasattr(client, "sign_transaction")
            assert not hasattr(client, "send_transaction")

    asyncio.run(run())


def test_deployment_accepts_standard_rpc_without_hard_helius_dependency():
    compose = open("deploy/compose.solana-forward.yml", encoding="utf-8").read()
    preflight = open("deploy/preflight-forward.sh", encoding="utf-8").read()
    starter = open("deploy/start-forward.sh", encoding="utf-8").read()
    env_example = open("deploy/.env.forward.example", encoding="utf-8").read()

    assert "SOLANA_RPC_HTTP_URL" in compose
    assert "SOLANA_RPC_WS_URL" in compose
    assert "HELIUS_API_KEY: ${HELIUS_API_KEY:-}" in compose
    assert "SOLANA_RPC_HTTP_URL + SOLANA_RPC_WS_URL or HELIUS_API_KEY" in preflight
    assert "SOLANA_RPC_HTTP_URL + SOLANA_RPC_WS_URL or legacy HELIUS_API_KEY" in starter
    assert "SOLANA_RPC_HTTP_URL=" in env_example
    assert "SOLANA_RPC_WS_URL=" in env_example

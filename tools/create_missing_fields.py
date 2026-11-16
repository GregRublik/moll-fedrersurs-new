"""Create missing smart-process fields required by the collector.

Reads the trade smart-process type id from Bitrix (crm.type.getByEntityTypeId
for BITRIX_ENTITY_TRADE), then checks userfieldconfig for that entity and
creates only the fields that are absent. Dry-run by default; pass --apply.

Usage:
    uv run python tools/create_missing_fields.py
    uv run python tools/create_missing_fields.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import settings  # noqa: E402
from fedresurs.bitrix.client import BitrixClient  # noqa: E402


def required_fields(type_id: int) -> list[dict]:
    entity_id = f"CRM_{type_id}"
    return [
        {
            "entityId": entity_id,
            "fieldName": f"UF_CRM_{type_id}_STATUS",
            "userTypeId": "string",
            "multiple": "N",
            "mandatory": "N",
            "showFilter": "Y",
            "showInList": "Y",
            "isSearchable": "Y",
            "sort": 500,
            "editFormLabel": {"ru": "Статус торгов", "en": "Trade status"},
            "helpMessage": {"ru": "Статус торгов из ЕФРСБ", "en": "EFRSB trade status"},
        },
        {
            "entityId": entity_id,
            "fieldName": f"UF_CRM_{type_id}_PRICE_FORM",
            "userTypeId": "string",
            "multiple": "N",
            "mandatory": "N",
            "showFilter": "Y",
            "showInList": "Y",
            "isSearchable": "Y",
            "sort": 510,
            "editFormLabel": {
                "ru": "Форма подачи предложения о цене",
                "en": "Price offer form",
            },
            "helpMessage": {
                "ru": "Открытая/закрытая форма подачи предложения о цене",
                "en": "Open/closed price offer form",
            },
        },
    ]


async def trade_type_id(client: BitrixClient) -> int:
    response = await client.call(
        "crm.type.getByEntityTypeId",
        {"entityTypeId": settings.bitrix.entity_trade},
    )
    return int(response["result"]["type"]["id"])


async def existing_field_names(client: BitrixClient, entity_id: str) -> set[str]:
    response = await client.call(
        "userfieldconfig.list",
        {
            "moduleId": "crm",
            "select": {"0": "*", "language": "ru"},
            "filter": {"entityId": entity_id},
            "order": {"id": "ASC"},
        },
    )
    fields = response.get("result", {}).get("fields", [])
    return {str(field.get("fieldName")) for field in fields}


async def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--apply", action="store_true", help="actually create missing fields")
    args = parser.parse_args()

    async with aiohttp.ClientSession() as session:
        client = BitrixClient(session, settings.bitrix.webhook_base)
        type_id = await trade_type_id(client)
        entity_id = f"CRM_{type_id}"
        print(
            f"entityTypeId {settings.bitrix.entity_trade} -> crm.type.id {type_id} "
            f"({entity_id})"
        )
        if type_id != 138:
            print(
                "WARNING: config/bitrix_fieldmap.toml and tests currently use "
                "crm.type.id 138 (UF_CRM_138_*). Update the field map on this portal."
            )

        names = await existing_field_names(client, entity_id)
        print(f"{entity_id}: {len(names)} fields present")

        for field in required_fields(type_id):
            name = field["fieldName"]
            if name in names:
                print(f"  exists   {name}")
                continue
            if not args.apply:
                print(f"  MISSING  {name} (dry-run; pass --apply to create)")
                continue
            response = await client.call(
                "userfieldconfig.add", {"moduleId": "crm", "field": field}
            )
            created = response.get("result", {}).get("field", {})
            print(f"  created  {created.get('fieldName')} id={created.get('id')}")

    return 0


if __name__ == "__main__":
    raise SystemExit(asyncio.run(main()))

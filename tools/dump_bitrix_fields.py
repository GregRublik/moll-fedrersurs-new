"""Read-only discovery of Bitrix24 smart-process fields.

Calls crm.item.fields / crm.type.getByEntityTypeId / crm.category.list for
entityTypeId 1078 (trade) and 1120 (lot), saves raw JSON and prints a compact
summary. Writes nothing to Bitrix.

Usage: uv run python tools/dump_bitrix_fields.py
"""

from __future__ import annotations

import asyncio
import json
import sys
from pathlib import Path
from urllib.parse import urlparse

import aiohttp

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))

from config import settings  # noqa: E402

OUT = ROOT / "var" / "discovery"
ENTITIES = {1078: "trade", 1120: "lot"}
INTERESTING = ("xmlId", "parentId1078", "parentId1120", "categoryId", "stageId")


def webhook_base() -> str:
    base = settings.bitrix.base_url.rstrip("/")
    return f"{base}/rest/{settings.bitrix.user_id}/{settings.bitrix.key_202}"


def safe_url(url: str) -> str:
    parts = urlparse(url)
    return f"{parts.scheme}://{parts.netloc}/.../{parts.path.rsplit('/', 2)[-1]}"


async def call(session: aiohttp.ClientSession, method: str, payload: dict) -> dict:
    url = f"{webhook_base()}/{method}.json"
    async with session.post(url, json=payload, timeout=aiohttp.ClientTimeout(total=60)) as resp:
        text = await resp.text()
        try:
            data = json.loads(text)
        except json.JSONDecodeError as exc:
            raise RuntimeError(f"{method}: non-JSON response, HTTP {resp.status}") from exc
        if resp.status != 200 or data.get("error"):
            raise RuntimeError(
                f"{method}: HTTP {resp.status}, error={data.get('error')!r}, "
                f"description={data.get('error_description')!r}"
            )
        return data


def dump(name: str, payload: dict) -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    path = OUT / f"{name}.json"
    path.write_text(json.dumps(payload, ensure_ascii=False, indent=2), encoding="utf-8")
    print(f"  saved {path.relative_to(ROOT)} ({path.stat().st_size} bytes)")


def print_fields(entity_type_id: int, label: str, fields: dict) -> None:
    print(f"\n--- {entity_type_id} ({label}): {len(fields)} fields")
    for name in sorted(fields):
        info = fields[name]
        if not isinstance(info, dict):
            continue
        print(
            f"  {name:40} type={info.get('type', '?'):12} "
            f"required={'Y' if info.get('isRequired') else 'n'} "
            f"multiple={'Y' if info.get('isMultiple') else 'n'} "
            f"title={info.get('title', '')!r}"
        )


async def main() -> None:
    print(f"Portal: {urlparse(settings.bitrix.base_url).netloc}")
    async with aiohttp.ClientSession() as session:
        for entity_type_id, label in ENTITIES.items():
            print(f"\n=== entityTypeId {entity_type_id} ({label}) ===")

            data = await call(
                session,
                "crm.item.fields",
                {"entityTypeId": entity_type_id, "useOriginalUfNames": "Y"},
            )
            dump(f"crm.item.fields_{entity_type_id}", data)
            fields = data.get("result", {}).get("fields", {})
            print_fields(entity_type_id, label, fields)

            missing = [name for name in INTERESTING if name not in fields]
            print(f"  key fields present: {[n for n in INTERESTING if n in fields]}")
            if missing:
                print(f"  key fields MISSING: {missing}")

            for method, payload in (
                ("crm.type.getByEntityTypeId", {"entityTypeId": entity_type_id}),
                ("crm.category.list", {"entityTypeId": entity_type_id}),
            ):
                try:
                    response = await call(session, method, payload)
                except RuntimeError as exc:
                    print(f"  {method}: FAILED — {exc}")
                    continue
                dump(f"{method}_{entity_type_id}", response)
                result = response.get("result", {})
                if method == "crm.type.getByEntityTypeId":
                    type_info = result.get("type", {})
                    print(
                        f"  type.id={type_info.get('id')} title={type_info.get('title')!r} "
                        f"categories={type_info.get('isCategoriesEnabled')} "
                        f"relations={type_info.get('relations')}"
                    )
                else:
                    categories = result.get("categories", [])
                    print(f"  categories: {[(c.get('id'), c.get('name')) for c in categories]}")

    print("\nDone. No changes were made to Bitrix.")


if __name__ == "__main__":
    asyncio.run(main())

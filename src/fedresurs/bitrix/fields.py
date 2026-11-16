from __future__ import annotations

import json
import tomllib
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any


def to_api_name(original: str) -> str:
    """Convert an original UF name to Bitrix camelCase.

    UF_CRM_138_1744310779 -> ufCrm138_1744310779
    UF_CRM_138_STATUS     -> ufCrm138Status
    UF_CRM_138_PRICE_FORM -> ufCrm138PriceForm
    """
    if not original.upper().startswith("UF_CRM_"):
        return original
    parts = original[len("UF_CRM_"):].split("_")
    if not parts or not parts[0]:
        return original
    result = "ufCrm" + parts[0]
    for part in parts[1:]:
        if not part:
            continue
        result += ("_" + part) if part.isdigit() else part.capitalize()
    return result


@dataclass(slots=True)
class EntityMap:
    entity_type_id: int
    crm_type_id: int
    category_id: int
    xml_id_prefix: str
    title_template: str
    fields: dict[str, str] = field(default_factory=dict)
    parent_field: str | None = None
    field_types: dict[str, str] = field(default_factory=dict)

    def api_fields(self) -> dict[str, str]:
        return {logical: to_api_name(original) for logical, original in self.fields.items()}

    def type_of(self, logical: str) -> str | None:
        original = self.fields.get(logical)
        return self.field_types.get(original) if original else None


@dataclass(slots=True)
class FieldMap:
    trade: EntityMap
    lot: EntityMap
    required_fields: dict[str, Any] = field(default_factory=dict)
    xml_id_field: str = "xmlId"
    category_field: str = "categoryId"
    stage_field: str = "stageId"

    @classmethod
    def load(cls, path: str | Path, discovery_dir: str | Path | None = None) -> "FieldMap":
        data = tomllib.loads(Path(path).read_text(encoding="utf-8"))

        def entity(key: str) -> EntityMap:
            section = data[key]
            return EntityMap(
                entity_type_id=int(section["entity_type_id"]),
                crm_type_id=int(section["crm_type_id"]),
                category_id=int(section["category_id"]),
                xml_id_prefix=str(section.get("xml_id_prefix", "")),
                title_template=str(section.get("title_template", "")),
                fields={name: str(value) for name, value in section.get("fields", {}).items()},
                parent_field=section.get("parent_field"),
            )

        trade = entity("trade")
        lot = entity("lot")

        if discovery_dir:
            for entity_map in (trade, lot):
                path_json = Path(discovery_dir) / f"crm.item.fields_{entity_map.entity_type_id}.json"
                if path_json.exists():
                    payload = json.loads(path_json.read_text(encoding="utf-8"))
                    fields = payload.get("result", {}).get("fields", {})
                    entity_map.field_types = {
                        name: str(info.get("type"))
                        for name, info in fields.items()
                        if isinstance(info, dict)
                    }

        common = data.get("common", {})
        return cls(
            trade=trade,
            lot=lot,
            required_fields=dict(common.get("required_fields", {})),
            xml_id_field=str(common.get("xml_id_field", "xmlId")),
            category_field=str(common.get("category_field", "categoryId")),
            stage_field=str(common.get("stage_field", "stageId")),
        )


def xml_id_for(entity: EntityMap, key: str) -> str:
    return f"{entity.xml_id_prefix}{key}"

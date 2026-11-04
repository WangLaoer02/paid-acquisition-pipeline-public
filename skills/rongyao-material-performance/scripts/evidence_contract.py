"""Pure offline evidence helpers. No inference can promote its own source type."""
from __future__ import annotations

import math
from typing import Any
from urllib.parse import urlsplit

EVIDENCE_TYPES = {"backend_metric", "material_name", "backend_label", "source_video",
                  "transcript", "user_input", "generated_proposal"}


def number(value: Any) -> float | None:
    if value is None or isinstance(value, bool):
        return None
    try:
        result = float(str(value).strip().replace(",", "").removesuffix("%"))
    except (ValueError, TypeError):
        return None
    return result if math.isfinite(result) else None


def rounded(value: float | None, digits: int = 2) -> float | None:
    return None if value is None else round(value, digits)


def difference(left: float | None, right: float | None) -> float | None:
    return None if left is None or right is None else round(left - right, 2)


def ratio(numerator: float | None, denominator: float | None) -> float | None:
    return None if numerator is None or denominator in (None, 0) else numerator / denominator


def source_link(raw: Any) -> dict:
    # Preserve the exact source, including incomplete parameters. Never reconstruct.
    valid = False
    if isinstance(raw, str):
        try:
            parsed = urlsplit(raw)
            valid = parsed.scheme in {"http", "https"} and bool(parsed.netloc)
        except ValueError:
            pass
    return {"demand_url": raw, "source_extracted": raw not in (None, ""),
            "url_syntax_valid": valid, "page_accessible": None, "video_playable": None}


def coverage(scope: dict | None) -> dict:
    scope = dict(scope or {})
    included = set(map(str, scope.get("included_projects", [])))
    visible = set(map(str, scope.get("visible_projects", [])))
    failed = set(map(str, scope.get("failed_projects", [])))
    excluded = scope.get("excluded_projects", [])
    complete = bool(scope.get("enumeration_verified") and visible and included == visible
                    and not failed and not excluded and scope.get("date_range")
                    and scope.get("material_range"))
    return {**scope, "included_projects": sorted(included), "visible_projects": sorted(visible),
            "failed_projects": sorted(failed), "excluded_projects": excluded,
            "all_visible_projects_covered": complete,
            "history_complete": False,
            "label": "本次可见项目完整覆盖" if complete else "本次已列项目范围（非全部历史项目）"}


def validate_finding(finding: dict, facts: dict[str, dict]) -> list[str]:
    errors = []
    ids = finding.get("support_fact_ids", [])
    if any(key not in facts for key in ids):
        return ["unknown_fact_id"]
    sources = [facts[key] for key in ids]
    kind = finding.get("evidence_type")
    if kind not in EVIDENCE_TYPES:
        return ["invalid_evidence_type"]
    if kind != "generated_proposal" and not any(x.get("evidence_type") == kind for x in sources):
        errors.append("source_type_mismatch")
    if kind == "source_video" and not any(x.get("observed") is True and x.get("locator") for x in sources if x.get("evidence_type") == kind):
        errors.append("video_observation_required")
    if kind == "transcript" and not any(x.get("locator") for x in sources if x.get("evidence_type") == kind):
        errors.append("transcript_locator_required")
    if finding.get("claim_scope") == "historical_absence":
        errors.append("search_cannot_prove_historical_absence")
    if finding.get("claim_scope") == "observed_content" and kind not in {"source_video", "transcript", "user_input"}:
        errors.append("content_observation_required")
    if kind == "generated_proposal" and finding.get("validated") is not False:
        errors.append("proposal_must_be_unvalidated")
    if finding.get("claim_scope") == "all_projects" and not coverage(finding.get("coverage"))["all_visible_projects_covered"]:
        errors.append("project_coverage_incomplete")
    if not finding.get("boundary"):
        errors.append("boundary_required")
    return errors

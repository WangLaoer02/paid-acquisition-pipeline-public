#!/usr/bin/env python3
"""Explicitly gated one-day, one-project, one-request read-only smoke test."""
import argparse
import json
from pathlib import Path
import readonly_capture as capture

def smoke(args):
    if not args.login_confirmed:
        return {"ok": False, "status": "blocked", "reason": "user_login_confirmation_required",
                "authenticated_session_verified": False, "query_count": 0}
    date_range = capture.parse_date_range(args.date_range, "投放日期")
    if len(set(date_range.split("-"))) != 1:
        raise capture.CaptureError("冒烟仅允许单日投放范围")
    result = capture.run_batch({"requests": [{"id": "smoke", "date": date_range,
        "date2": args.material_range, "gid": [args.gid], "include": "summary",
        "filters": {"pagesize": 1}}]}, transport="active", state_file=args.state_file,
        timeout=30, retries=0, concurrency=1)
    return {**result, "authenticated_session_verified": bool(result.get("ok")),
            "query_count": 1, "validation_scope": "single_day_single_project_summary_only"}

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--login-confirmed", action="store_true")
    parser.add_argument("--date-range", required=True)
    parser.add_argument("--material-range", required=True)
    parser.add_argument("--gid", required=True)
    parser.add_argument("--state-file", default=str(capture.DEFAULT_STATE))
    parser.add_argument("--output", required=True)
    args = parser.parse_args()
    try:
        result = smoke(args)
    except capture.CaptureError as error:
        result = {"ok": False, "status": "blocked", "reason": str(error),
                  "authenticated_session_verified": False, "replayed": False}
    capture.write_result(Path(args.output).resolve(), result)
    print(json.dumps(result, ensure_ascii=False))
    return 0 if result.get("ok") else 2

if __name__ == "__main__":
    raise SystemExit(main())

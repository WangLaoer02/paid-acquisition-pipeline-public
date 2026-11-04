#!/usr/bin/env python3
"""Read-only next-action list; a saved receipt never substitutes for live final review."""
import argparse
from collections import Counter
import hashlib
import json
from pathlib import Path


def classify(job, batch):
    job_id = job['id']
    record_path = batch / 'records' / (job_id + '.json')
    rejected_path = batch / 'records' / (job_id + '-rejected.json')
    if not record_path.is_file():
        if rejected_path.is_file():
            return 'blocked_recorded_rejection'
        return 'awaiting_generation_record'
    record = json.loads(record_path.read_text())
    path = Path(record['path'])
    if not path.is_absolute():
        path = batch / path
    if not path.is_file():
        return 'output_file_missing'
    digest = hashlib.sha256(path.read_bytes()).hexdigest()
    if digest != record.get('sha256'):
        return 'output_changed_needs_review'
    checkpoint_path = batch / 'asset-extensions-checkpoints' / (job_id + '.json')
    if not checkpoint_path.is_file():
        return 'needs_delivery_gate_then_prepare_upload'
    checkpoint = json.loads(checkpoint_path.read_text())
    if checkpoint.get('sha256') != digest:
        return 'output_changed_needs_review'
    status = checkpoint.get('status')
    if status == 'native_byte_verified' and checkpoint.get('remote_byte_match') is True:
        return 'saved_receipt_verified'
    if status in ('prepared', 'upload_failed_or_unknown'):
        return 'probe_original_upload_id_before_any_new_post'
    if status == 'confirmed_pending_not_uploaded':
        return 'confirmed_failed_prepare_new_upload'
    if status in ('uploaded', 'page_created'):
        return 'find_existing_row_then_resume_mount'
    if status == 'files_property_failed':
        return 'repair_existing_row_files_property'
    if status in ('byte_check_failed', 'mounted', 'mounted_and_page_verified'):
        return 'refresh_original_page_then_recheck_bytes'
    return 'inspect_checkpoint_without_reupload'


def build_report(jobs, batch):
    rows = [dict(id=job['id'], look_id=job.get('look_id'),
                 next_action=classify(job, batch)) for job in jobs]
    counts = dict(Counter(row['next_action'] for row in rows))
    return {'mode': 'read_only', 'expected_jobs': len(jobs), 'counts': counts,
            'saved_receipts_are_live_feishu_verification': False,
            'pending': [row for row in rows if row['next_action'] != 'saved_receipt_verified']}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('batch', type=Path)
    parser.add_argument('--jobs', required=True, type=Path,
                        help='JSON array of jobs with stable id, optionally look_id')
    args = parser.parse_args()
    jobs = json.loads(args.jobs.read_text())
    print(json.dumps(build_report(jobs, args.batch.resolve()), ensure_ascii=False, indent=2))


if __name__ == '__main__':
    main()

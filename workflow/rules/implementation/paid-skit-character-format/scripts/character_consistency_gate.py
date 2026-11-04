#!/usr/bin/env python3
"""Read-only preparation/delivery gate. It checks recorded evidence, not pixels."""
import argparse
import hashlib
import json
import math
from pathlib import Path

BODY_MARKS = ('crown_y', 'chin_y', 'shoulder_y', 'waist_y', 'hip_y', 'knee_y', 'ankle_y', 'sole_y')
MAX_NORMALIZED_ERROR = 0.005
RECONSTRUCTION_MARKS = ('crown_y', 'chin_y', 'shoulder_y', 'sole_y')
MAX_RECONSTRUCTION_ERROR = 0.015

def check_accepted_extension(contract, stage, base):
    """Keep a verified reconstruction snapshot, then bind each extension to accepted pixels."""
    errors = []
    def need(ok, message):
        if not ok: errors.append(message)
    def key(ref): return (str((base / ref.get('path', '')).resolve()), ref.get('sha256'))
    def file_ok(ref, label):
        p = Path(key(ref)[0])
        need(p.is_file() and hashlib.sha256(p.read_bytes()).hexdigest() == ref.get('sha256'), label + ': file missing or changed')
    try:
        parent_path = (base / contract['source_contract_path']).resolve()
        parent = json.loads(parent_path.read_text())
        receipt = json.loads((base / contract['acceptance_receipt_path']).read_text())
    except (OSError, ValueError, KeyError):
        return ['extension: source snapshot or user acceptance receipt missing']
    need(parent.get('method') == 'multi_reference_reconstruction', 'extension: verified reconstruction source required')
    if parent.get('method') == 'multi_reference_reconstruction':
        errors.extend(check_reconstruction(parent, 'delivery', parent_path.parent))
    need(bool(receipt.get('user_quote')) and bool(receipt.get('recorded_at')), 'extension: explicit user acceptance missing')
    need(contract.get('generation_authorized') is True and bool(contract.get('generation_authorization_quote')), 'extension: generation authorization missing')
    originals = {x['look_id']: x for x in parent.get('looks', [])}
    accepted = {x.get('look_id'): key(x) for x in receipt.get('accepted_files', [])}
    looks = contract.get('looks', [])
    need(len(looks) == len(originals) and {x.get('look_id') for x in looks} == set(originals), 'extension: original five designs must be preserved')
    face = parent['identity']['anchors']['face']
    body = parent['reconstruction']['calibration']
    target = body['visible_pixel_marks']
    target = {k:(v-target['crown_y'])/(target['sole_y']-target['crown_y']) for k,v in target.items()}
    for look in looks:
        tag = look.get('look_id', 'unknown'); original = originals.get(tag)
        if not original: continue
        master = original['assets'][0]
        need(accepted.get(tag) == key(master) and key(look.get('accepted_master', {})) == key(master), tag + ': exact accepted master not bound')
        refs = look.get('outfit_references', [])
        raw_keys = {key(x) for x in original['outfit_references']}
        need(bool(refs) and all(key(x) in raw_keys for x in refs), tag + ': outfit must use original verified sources')
        required = {key(x) for x in [master, face, body] + refs}
        def inputs_ok(record):
            inputs = record.get('generation_inputs', [])
            for ref in inputs: file_ok(ref, tag + ' input')
            need(required.issubset({key(x) for x in inputs}), tag + ': accepted master, shared face/body or outfit input missing')
        inputs_ok(look)
        if stage != 'delivery': continue
        assets = look.get('assets', [])
        need(sorted(x.get('kind') for x in assets) == sorted(look.get('expected_asset_kinds', [])), tag + ': requested extension files missing or duplicated')
        for asset in assets:
            file_ok(asset, tag + ' output'); inputs_ok(asset)
            head_visible = asset.get('kind') not in ('detail_clothing', 'detail_footwear')
            need(asset.get('head_visual_review') == ('passed' if head_visible else 'not_visible') and asset.get('structure_review') == 'passed', tag + ': output visual review missing')
            need(bool(asset.get('prompt')) and bool(asset.get('quality_limits')), tag + ': prompt or inference disclosure missing')
            need(asset.get('user_art_approved') is False, tag + ': future extension must not inherit front-master acceptance')
            if asset.get('kind') == 'turnaround':
                panels = asset.get('panels', [])
                need([p.get('view') for p in panels] == ['front', 'left_profile', 'back'], tag + ': three-view order or direction invalid')
                heights = []
                for panel in panels:
                    marks = panel.get('visible_pixel_marks', {})
                    valid = all(type(marks.get(k)) in (int,float) and math.isfinite(marks[k]) for k in RECONSTRUCTION_MARKS)
                    valid = valid and all(marks[a] < marks[b] for a,b in zip(RECONSTRUCTION_MARKS,RECONSTRUCTION_MARKS[1:]))
                    need(valid and panel.get('direction_review') == 'passed' and bool(panel.get('measurement_note')), tag + ': panel geometry or direction not reviewed')
                    if not valid: continue
                    height = marks['sole_y']-marks['crown_y']; heights.append(height)
                    for k in RECONSTRUCTION_MARKS:
                        need(abs((marks[k]-marks['crown_y'])/height-target[k]) <= MAX_RECONSTRUCTION_ERROR, tag + ': panel proportion drift ' + k)
                need(len(heights) == 3 and (max(heights)-min(heights))/max(heights) <= MAX_RECONSTRUCTION_ERROR, tag + ': panel body heights differ')
            elif asset.get('kind') == 'detail_plate':
                need(asset.get('detail_panels') == ['face', 'clothing', 'footwear'], tag + ': three detail panels missing')
            elif asset.get('kind') in ('detail_face', 'detail_clothing', 'detail_footwear'):
                need(bool(asset.get('detail_review_note')), tag + ': detail-source comparison missing')
            elif asset.get('kind') in ('action_wave', 'action_walk', 'action_lookback', 'action_seated', 'action_point', 'action_surprise'):
                need(asset.get('action_review') == 'passed' and asset.get('geometry_review') == 'pose_adjusted_visual_comparison' and bool(asset.get('geometry_review_note')), tag + ': pose or body comparison missing')
            else:
                need(False, tag + ': unrequested extension kind')
    return errors

def check_reconstruction(contract, stage, base):
    """Explicitly authorized reconstruction; never certify raw anatomy or art approval."""
    errors = []
    def need(ok, message):
        if not ok:
            errors.append(message)
    def file_ok(record, label):
        p = (base / record.get('path', '')).resolve()
        need(p.is_file(), label + ': actual file missing')
        if p.is_file():
            need(hashlib.sha256(p.read_bytes()).hexdigest() == record.get('sha256'), label + ': file hash mismatch')
        return p
    def source(record, label):
        file_ok(record, label)
        need(record.get('source_role') in ('raw_photo', 'raw_frame'), label + ': original source required')
        need(record.get('public_work_binding') == 'verified' and bool(record.get('source_url'))
             and bool(record.get('source_work_id') or record.get('source_video_id')), label + ': work provenance missing')
        need(record.get('author_sec_uid') == contract.get('creator', {}).get('sec_uid'), label + ': source author mismatch')
        if record.get('source_role') == 'raw_photo':
            need(type(record.get('photo_index')) is int and record['photo_index'] > 0
                 and record.get('frame_time_seconds') is None, label + ': photo provenance invalid')
        else:
            t = record.get('frame_time_seconds')
            need(type(t) in (int,float) and math.isfinite(t) and t >= 0, label + ': frame time missing')
    def bindings(record, required, label):
        inputs = record.get('generation_inputs', [])
        keys = set()
        for ref in inputs:
            p = file_ok(ref, label + ' input')
            keys.add((str(p), ref.get('sha256')))
        for ref in required:
            need((str((base / ref.get('path','')).resolve()), ref.get('sha256')) in keys,
                 label + ': shared or outfit reference not directly bound')
    def visible_marks(record, label):
        marks = record.get('visible_pixel_marks', {})
        need(record.get('geometry_normalization') == 'crown_to_sole', label + ': normalization missing')
        inferred = record.get('inferred_landmarks', [])
        need(not inferred or (set(inferred).issubset({'crown_y', 'shoulder_y'})
                             and bool(record.get('landmark_inference_note'))
                             and record.get('geometry_measurement') == 'visible_and_disclosed_reconstructed_landmarks'),
             label + ': inferred landmark disclosure missing or invalid')
        good = all(type(marks.get(k)) in (int,float) and math.isfinite(marks[k]) and marks[k] >= 0 for k in RECONSTRUCTION_MARKS)
        good = good and all(marks[a] < marks[b] for a,b in zip(RECONSTRUCTION_MARKS,RECONSTRUCTION_MARKS[1:]))
        need(good, label + ': visible output measurements missing')
        if not good: return {}
        return {k:(marks[k]-marks['crown_y'])/(marks['sole_y']-marks['crown_y']) for k in RECONSTRUCTION_MARKS}
    method = contract.get('reconstruction', {})
    need(method.get('user_method_authorized') is True and bool(method.get('authorization_quote')),
         'reconstruction: explicit user method authorization missing')
    need(method.get('art_approved') is False and method.get('raw_body_certified') is False,
         'reconstruction: candidate must not claim approval or raw anatomy certification')
    need(bool(method.get('limitations')), 'reconstruction: inferred parts not disclosed')
    creator = contract.get('creator', {})
    need(creator.get('verified') is True and bool(creator.get('sec_uid')), 'creator: public identity unverified')
    try:
        receipt = json.loads((base / creator.get('intake_receipt','')).read_text())
    except (OSError, ValueError):
        receipt = {}
    need(any(r.get('status') in ('verified','committed') and r.get('sec_uid') == creator.get('sec_uid')
             and r.get('name') == creator.get('nickname')
             and r.get('verification',{}).get('method') in ('public-profile-html','public-work-and-profile-html','in-app-browser','native-browser')
             for r in receipt.get('items',[])), 'creator: matching verified intake receipt missing')
    identity = contract.get('identity', {})
    need(bool(identity.get('character_id')), 'identity: missing character id')
    need(identity.get('height_cm') is None or bool(identity.get('height_cm_source')), 'body: unsupported real height')
    face = identity.get('anchors', {}).get('face', {})
    source(face, 'face')
    need(face.get('visual_review') == 'passed', 'face: visual source review missing')
    refs = method.get('body_references', [])
    need(len(refs) >= 2 and len({x.get('path') for x in refs}) >= 2, 'body: at least two distinct original references required')
    for ref in refs:
        source(ref, 'body reference')
        need(bool(ref.get('visible_parts')) and bool(ref.get('limitations')), 'body: visible regions and limitations missing')
    calibration = method.get('calibration', {})
    calibration_id = method.get('calibration_look_id')
    looks = contract.get('looks', [])
    need(len(looks) == contract.get('expected_looks', 5), 'looks: requested count not met')
    need(len({x.get('look_id') for x in looks}) == len(looks), 'looks: duplicate look id')
    need(any(x.get('look_id') == calibration_id for x in looks), 'calibration: selected look missing')
    target = {}
    if calibration.get('path'):
        file_ok(calibration, 'calibration')
        calibration_look = next((x for x in looks if x.get('look_id') == calibration_id), {})
        bindings(calibration, [face] + refs + calibration_look.get('outfit_references', []), 'calibration actual')
        need(calibration.get('source_role') == 'reconstruction_candidate', 'calibration: wrong evidence classification')
        need(calibration.get('visual_review') == 'passed' and calibration.get('user_art_approved') is False,
             'calibration: candidate review missing or approval misrepresented')
        target = visible_marks(calibration, 'calibration')
    elif stage == 'delivery':
        need(False, 'calibration: actual image missing')
    for look in looks:
        tag = look.get('look_id', 'unknown')
        need(look.get('character_id') == identity.get('character_id'), tag + ': mixed identity')
        need(look.get('same_identity_review') == 'passed', tag + ': source identity not reviewed')
        need(look.get('face_anchor_id') == face.get('id') and bool(face.get('id')), tag + ': face anchor mismatch')
        need(look.get('body_anchor_id') == method.get('calibration_id') and bool(method.get('calibration_id')), tag + ': provisional body reference mismatch')
        need(bool(look.get('reconstruction_limits')), tag + ': reconstruction disclosure missing')
        outfit = look.get('outfit_references', [])
        need(bool(outfit), tag + ': outfit evidence missing')
        for ref in outfit: source(ref, tag + ' outfit')
        required = [face] + outfit
        if look.get('look_id') != calibration_id and calibration.get('path'):
            required.append(calibration)
        else:
            required.extend(refs)
        bindings(look, required, tag + ' planned')
        if stage == 'delivery':
            assets = look.get('assets', [])
            need(len([x for x in assets if x.get('kind') == 'front_master']) == 1, tag + ': one actual front master required')
            for asset in assets:
                file_ok(asset, tag + ' output')
                need(asset.get('head_visual_review') == 'passed' and bool(asset.get('prompt')), tag + ': head review or exact prompt missing')
                need(asset.get('face_anchor_id') == face.get('id') and asset.get('body_anchor_id') == method.get('calibration_id'), tag + ': output binding mismatch')
                bindings(asset, required, tag + ' actual')
                measured = visible_marks(asset, tag + ' output')
                for k in RECONSTRUCTION_MARKS:
                    need(k in target and k in measured and abs(target[k]-measured[k]) <= MAX_RECONSTRUCTION_ERROR,
                         tag + ': visible proportion drift ' + k)
    return errors

def normalize_body_marks(pixel_marks):
    """Normalize manually observed y coordinates by skeletal body height."""
    if not isinstance(pixel_marks, dict) or not all(
        type(pixel_marks.get(k)) in (int, float) and math.isfinite(pixel_marks[k])
        and pixel_marks[k] >= 0 for k in BODY_MARKS
    ):
        raise ValueError('eight finite, nonnegative pixel landmarks required')
    if not all(pixel_marks[a] < pixel_marks[b] for a, b in zip(BODY_MARKS, BODY_MARKS[1:])):
        raise ValueError('pixel landmarks must run from crown to sole in order')
    crown, sole = pixel_marks['crown_y'], pixel_marks['sole_y']
    return {k: (pixel_marks[k] - crown) / (sole - crown) for k in BODY_MARKS}

def check(contract, stage='generate', base=Path('.')):
    if contract.get('method') == 'partial_evidence_clothed_reconstruction':
        from partial_evidence_character_gate import check as check_partial
        return check_partial(contract, stage, base)
    if contract.get('method') == 'accepted_master_extension':
        return check_accepted_extension(contract, stage, base)
    if contract.get('method') == 'multi_reference_reconstruction':
        return check_reconstruction(contract, stage, base)
    errors = []
    def require(ok, message):
        if not ok:
            errors.append(message)
    def evidence_file(record, label):
        path = record.get('path')
        p = (base / path).resolve() if path else None
        require(bool(p and p.is_file()), label + ': actual file missing')
        if p and p.is_file():
            require(hashlib.sha256(p.read_bytes()).hexdigest() == record.get('sha256'), label + ': file changed or hash missing')
        return p
    def measured_marks(record, label):
        require(record.get('geometry_normalization') == 'crown_to_sole', label + ': body-height normalization missing')
        try:
            derived = normalize_body_marks(record.get('pixel_marks'))
        except ValueError as exc:
            require(False, label + ': ' + str(exc))
            return {}
        saved = record.get('normalized_marks', {})
        require(all(type(saved.get(k)) in (int, float) and math.isfinite(saved[k])
                    and abs(saved[k] - derived[k]) <= 1e-9 for k in BODY_MARKS),
                label + ': normalized landmarks do not match recorded pixels')
        return derived
    def generation_inputs(record, required, label):
        inputs = record.get('generation_inputs', [])
        require(bool(inputs), label + ': direct generation inputs missing')
        bound = set()
        for ref in inputs:
            p = evidence_file(ref, label + ' input')
            if p:
                bound.add((str(p), ref.get('sha256')))
        for ref in required:
            if ref.get('path'):
                key = (str((base / ref['path']).resolve()), ref.get('sha256'))
                require(key in bound, label + ': common face/body or original outfit input not directly bound')
    def source_provenance(record, label, expected_work=None):
        work = record.get('source_work_id') or record.get('source_video_id')
        require(bool(work) and (expected_work is None or work == expected_work),
                label + ': source work missing or mismatched')
        if record.get('source_role') == 'raw_photo':
            index = record.get('photo_index')
            require(type(index) is int and index >= 0 and bool(record.get('source_url'))
                    and record.get('public_work_binding') == 'verified',
                    label + ': original photo provenance missing')
            require(record.get('frame_time_seconds') is None,
                    label + ': still photo must not claim a video timepoint')
        else:
            t = record.get('frame_time_seconds')
            require(type(t) in (int, float) and math.isfinite(t) and t >= 0,
                    label + ': source frame provenance missing')
    creator = contract.get('creator', {})
    require(creator.get('verified') is True and bool(creator.get('sec_uid')) and bool(creator.get('nickname')), 'creator: live public identity unverified')
    receipt_path = creator.get('intake_receipt')
    receipt = None
    if receipt_path:
        try:
            receipt = json.loads((base / receipt_path).read_text())
        except (OSError, ValueError):
            pass
    # Canonical intake stores the verified author directly on each item;
    # a nested candidate is not a verified/importable author record.
    matches = [r for r in (receipt or {}).get('items', []) if r.get('status') in ('verified', 'committed') and r.get('sec_uid') == creator.get('sec_uid') and r.get('name') == creator.get('nickname') and r.get('verification', {}).get('method') in ('public-profile-html', 'public-work-and-profile-html', 'in-app-browser', 'native-browser')]
    require(bool(matches), 'creator: matching verified intake receipt missing')
    identity = contract.get('identity', {})
    require(bool(identity.get('character_id')), 'identity: character id missing; creator is not a character')
    anchors = identity.get('anchors', {})
    for kind in ('face', 'body'):
        a = anchors.get(kind, {})
        require(bool(a.get('id')), kind + ': anchor id missing')
        require(a.get('source_role') in ('raw_frame', 'raw_photo', 'clean_master'), kind + ': derivative cannot be identity evidence')
        if a.get('source_role') == 'clean_master':
            require(a.get('user_art_approved') is True, kind + ': clean master has no user art approval')
        require(a.get('visual_review') == 'passed', kind + ': visual review missing')
        source_provenance(a, kind)
        evidence_file(a, kind)
    require(anchors.get('body', {}).get('full_body_observed') is True, 'body: head-to-foot evidence missing')
    target = measured_marks(anchors.get('body', {}), 'body')
    require(anchors.get('body', {}).get('geometry_measurement') == 'recorded_from_source', 'body: source proportion measurements missing')
    valid_target = all(type(target.get(k)) in (int, float) and math.isfinite(target[k]) and 0 <= target[k] <= 1 for k in BODY_MARKS)
    require(valid_target, 'body: normalized source landmarks missing or invalid')
    if valid_target:
        require(all(target[a] < target[b] for a, b in zip(BODY_MARKS, BODY_MARKS[1:])), 'body: source landmarks out of order')
    require(identity.get('height_cm') is None or bool(identity.get('height_cm_source')), 'body: unsupported real-world height')
    looks = contract.get('looks', [])
    require(type(contract.get('expected_looks', 5)) is int and contract.get('expected_looks', 5) > 0, 'looks: requested count invalid')
    require(len(looks) == contract.get('expected_looks', 5), 'looks: requested count not met')
    require(len({r.get('look_id') for r in looks}) == len(looks), 'looks: duplicate or missing look ids')
    for look in looks:
        tag = look.get('look_id', 'unknown')
        require(bool(look.get('look_id')), 'looks: look id missing')
        require(look.get('character_id') == identity.get('character_id') and bool(identity.get('character_id')), tag + ': mixed character identity')
        require(look.get('author_sec_uid') == creator.get('sec_uid') and bool(creator.get('sec_uid')), tag + ': source author mismatch')
        selected_work = look.get('source_work_id') or look.get('source_video_id')
        require(bool(selected_work) and bool(look.get('source_url')), tag + ': selected work missing')
        require(look.get('same_identity_review') == 'passed', tag + ': face/character identity not checked')
        for kind in ('face', 'body'):
            require(look.get(kind + '_anchor_id') == anchors.get(kind, {}).get('id') and bool(look.get(kind + '_anchor_id')), tag + ': anchor mismatch')
        require(bool(look.get('outfit_references')), tag + ': outfit evidence missing')
        for ref in look.get('outfit_references', []):
            require(ref.get('source_role') in ('raw_frame', 'raw_photo'), tag + ': outfit reference is generated')
            source_provenance(ref, tag + ' outfit frame provenance', selected_work)
            evidence_file(ref, tag + ' outfit')
        required_inputs = [anchors.get('face', {}), anchors.get('body', {})] + look.get('outfit_references', [])
        generation_inputs(look, required_inputs, tag + ' planned')
        if stage == 'delivery':
            assets = look.get('assets', [])
            require(any(a.get('kind') == 'front_master' for a in assets), tag + ': actual front master missing')
            for a in assets:
                evidence_file(a, tag + ' output')
                require(a.get('face_anchor_id') == anchors.get('face', {}).get('id') and a.get('body_anchor_id') == anchors.get('body', {}).get('id'), tag + ': output ancestry missing or changed')
                require(a.get('head_visual_review') == 'passed', tag + ': head drift/noise review missing')
                require(bool(a.get('prompt')), tag + ': exact generation prompt missing')
                generation_inputs(a, required_inputs, tag + ' actual')
                if a.get('kind') in ('front_master', 'view_front', 'view_side', 'view_back'):
                    measured = measured_marks(a, tag + ' output')
                    require(a.get('geometry_measurement') == 'recorded_from_output', tag + ': geometry not measured from actual output')
                    for key in BODY_MARKS:
                        x, y = target.get(key), measured.get(key)
                        valid = type(x) in (int, float) and type(y) in (int, float) and math.isfinite(x) and math.isfinite(y) and 0 <= x <= 1 and 0 <= y <= 1
                        require(valid and abs(x-y) <= MAX_NORMALIZED_ERROR, tag + ': proportion drift or missing measurement ' + key)
                    if all(type(target.get(k)) in (int, float) and type(measured.get(k)) in (int, float) for k in ('crown_y','chin_y','sole_y')):
                        th, oh = target['sole_y']-target['crown_y'], measured['sole_y']-measured['crown_y']
                        require(th > 0 and oh > 0 and abs((target['chin_y']-target['crown_y'])/th-(measured['chin_y']-measured['crown_y'])/oh) <= MAX_NORMALIZED_ERROR, tag + ': head/body ratio drift')
    return errors

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument('contract', type=Path)
    ap.add_argument('--stage', choices=('generate', 'delivery'), default='generate')
    args = ap.parse_args()
    contract = json.loads(args.contract.read_text())
    errors = check(contract, args.stage, args.contract.resolve().parent)
    print(json.dumps({'ready': not errors, 'stage': args.stage, 'errors': errors, 'pixel_identity_verified': False, 'art_approved': False}, ensure_ascii=False, indent=2))
    return 2 if errors else 0

if __name__ == '__main__':
    raise SystemExit(main())

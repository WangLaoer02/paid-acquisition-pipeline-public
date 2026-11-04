"""Designer evidence and visible-field acceptance; no filename identity guesses."""
from upload_page import Stop


def intended_designer(item):
    provenance=item.get('provenance') or {}
    source=provenance.get('source_native_fields') or {}
    if isinstance(source,list):
        source={x['text'].partition('：')[0].strip():x['text'].partition('：')[2].strip()
                for x in source if isinstance(x,dict) and 'text' in x}
    original=source.get('设计师')
    explicit=provenance.get('designer_name')
    if explicit and original and explicit!=original and not provenance.get('designer_override_authorization'):
        raise Stop('DESIGNER_SOURCE_CONFLICT')
    name=explicit or original
    if not isinstance(name,str) or not name.strip() or name!=name.strip() or len(name)>80 or any(ord(c)<32 for c in name):
        raise Stop('DESIGNER_SOURCE_REQUIRED')
    if explicit and not original and not provenance.get('designer_source'):
        raise Stop('DESIGNER_EVIDENCE_REQUIRED')
    return name


def expected_fields(parameters,designer,selects):
    def label(key):
        value=parameters.get(key)
        options=selects.get(key,{}).get('options',[])
        matches=[x['text'] for x in options if x.get('value','')==value]
        return matches[0] if len(matches)==1 else None
    return {'分类':label('category_type'),'所用AI':label('ai_source'),
            '第二设计师':label('region_type'),'需求人':parameters.get('demand_name'),
            '设计师':designer,'创作类型':{'1':'迭代','2':'原创'}.get(parameters.get('origin_type')),
            '角色/标签':parameters.get('role'),'一类':parameters.get('source_type'),
            '二类':parameters.get('source_direction'),'素材ip':parameters.get('source_ip')}


def acceptance(fields,parameters,designer=None,selects=None):
    expected=expected_fields(parameters,designer,selects or {})
    checks={}
    for label,value in expected.items():
        if value is None or label not in fields:checks[label]={'status':'missing','expected':value,'actual':fields.get(label)};continue
        actual=fields[label]
        if isinstance(value,list):
            actual=actual if isinstance(actual,list) else ([actual] if actual else [])
            matched=sorted(actual)==sorted(value)
        else:matched=actual==value
        checks[label]={'status':'matched' if matched else 'mismatch','expected':value,'actual':actual}
    return {'checks':checks,'verified':all(x['status']=='matched' for x in checks.values()),
            'all_parameters_verified':False,'ignored_fields':['类型'],
            'unexposed_parameters':['gid','is_redbag'],'semantic_tool_provenance_verified':False}

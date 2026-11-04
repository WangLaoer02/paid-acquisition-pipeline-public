"""Derive a bounded A preset from the installed current Adobe EPR schema."""
from pathlib import Path
from fractions import Fraction
import argparse,hashlib,json,xml.etree.ElementTree as ET

BASE=Path('/Applications/Adobe Premiere Pro 2026/Adobe Premiere Pro 2026.app/Contents/Settings/Frame.io/EncoderPresets/shareforreview-h264.epr')
def main():
    p=argparse.ArgumentParser(description=__doc__)
    p.add_argument('--width',required=True,type=int);p.add_argument('--height',required=True,type=int)
    p.add_argument('--fps',required=True);p.add_argument('--output',required=True);p.add_argument('--base',default=str(BASE))
    a=p.parse_args();out=Path(a.output);assert not out.exists(),'Do not overwrite an adopted preset'
    ticks=Fraction(254016000000)/Fraction(a.fps);assert ticks.denominator==1
    assert 16<=a.width<=16384 and 16<=a.height<=8192
    base=Path(a.base);root=ET.parse(base).getroot()
    assert root.find('CaptionParamContainer') is not None,'Legacy EPR lacks current caption schema'
    values={'ADBEVideoWidth':str(a.width),'ADBEVideoHeight':str(a.height),'ADBEVideoFPS':str(int(ticks)),
            'ADBEVideoAspect':'1,1','ADBECaptionExportOption':'2'}
    found=set()
    for node in root.iter('ExporterParam'):
        key=node.findtext('ParamIdentifier')
        if key in values:
            node.find('ParamValue').text=values[key];found.add(key)
            disabled=node.find('ParamIsDisabled')
            if disabled is not None:disabled.text='false'
    assert found==set(values)
    assert all(root.findtext(key)=='true' for key in ('DoAudio','DoVideo','DoCaptions'))
    root.find('PresetName').text=f'Paid Skit A {a.width}x{a.height} {a.fps} Native Captions'
    out.parent.mkdir(parents=True,exist_ok=True);ET.indent(root,space='\t')
    ET.ElementTree(root).write(out,encoding='UTF-8',xml_declaration=True)
    print(json.dumps({'preset':str(out.resolve()),'sha256':hashlib.sha256(out.read_bytes()).hexdigest(),
                     'base_sha256':hashlib.sha256(base.read_bytes()).hexdigest(),'parameters':values,
                     'requires_native_output_verification':True},ensure_ascii=False))

if __name__=='__main__':main()

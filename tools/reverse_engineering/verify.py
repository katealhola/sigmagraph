# SPDX-License-Identifier: GPL-3.0-or-later
"""Reproduce the supplied reference-corpus analysis and numerical checks."""
import argparse
import copy
import json
from pathlib import Path
from analyze import analyze, compare_netlist, write_json
from adau1701 import parameter_image
from asm1701 import disassemble, assemble
from coefficients import regenerate


def verify(source, output):
    summary=analyze(source,output)
    program=(output/'StereoPA2tie010.program.bin').read_bytes()
    text=disassemble(program)
    (output/'StereoPA2tie010.asm').write_text(text)
    records=json.loads((output/'StereoPA2tie010.parameters.json').read_text())
    layout=[{k:r[k] for k in ('name','cell','address')} for r in records]
    write_json(output/'StereoPA2tie010.layout.json',layout)
    project=json.loads((output/'StereoPA2tie011.project.json').read_text())
    derived=regenerate(project,layout)
    write_json(output/'regenerated-parameters.json',derived)
    (output/'StereoPA2tie011.reconstructed.parameters.bin').write_bytes(parameter_image(derived))
    expected=json.loads((output/'StereoPA2tie011.parameters.json').read_text())
    actual_by_name={r['name']:r['data_hex'] for r in derived}
    result={
        'program_reassembly_matches_010':assemble(text)==program,
        '011_coefficients_from_project':{
            'matches':sum(actual_by_name.get(r['name'])==r['data_hex'] for r in expected),
            'total':len(expected)},
        '011_graph_vs_010_netlist':compare_netlist(project['lowered_graph'],source/'StereoPA2tie010_NetList.xml'),
    }
    variant=copy.deepcopy(project)
    for cell in variant['cells']:
        if cell['name'] in ('NFilter2','NFilter2_2'):
            cell['Frequency']=32.0
    image=parameter_image(regenerate(variant,layout))
    result['changing_two_highpass_cutoffs_to_32_hz_matches_010_parameter_image']=image==(output/'StereoPA2tie010.parameters.bin').read_bytes()
    assert result['program_reassembly_matches_010']
    assert result['011_coefficients_from_project']=={'matches':254,'total':254}
    assert result['011_graph_vs_010_netlist']['edges_match']
    assert result['011_graph_vs_010_netlist']['algorithm_names_match']
    assert result['changing_two_highpass_cutoffs_to_32_hz_matches_010_parameter_image']
    write_json(output/'validation.json',result)
    return result


if __name__=='__main__':
    ap=argparse.ArgumentParser(description=__doc__)
    ap.add_argument('source',type=Path)
    ap.add_argument('-o','--output',type=Path,default=Path(__file__).resolve().parent/'analysis')
    args=ap.parse_args()
    print(json.dumps(verify(args.source,args.output),indent=2))

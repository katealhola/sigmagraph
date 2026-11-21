# SPDX-License-Identifier: GPL-3.0-or-later
"""Bundled, processor-filtered toolbox metadata and functional symbol mapping."""
import json
from functools import lru_cache
from importlib.resources import files


@lru_cache
def catalog():
    data=json.loads(files('sigmagraph').joinpath('data/catalog.json').read_text())
    presets=json.loads(files('sigmagraph').joinpath('data/example-presets.json').read_text())
    result={}
    for entry in data['entries']:
        entry=entry.copy()
        entry['preset']=presets.get(entry['id'],{})
        entry['symbol']=classify(entry['type_name'],entry['label'],entry['category'])
        result[entry['id']]=entry
    return result


def definition(type_or_id):
    if type_or_id in catalog():return catalog()[type_or_id]
    return next((v for v in catalog().values() if v['type_name']==type_or_id),None)


def classify(name,label='',category=''):
    text=(name+' '+label).lower()
    exact={'ICSigma100In':'input','ICSigma100Out':'output','SWGain1940DBAlg':'gain',
           'ExtSWGainDB':'external_gain','PEQ1Chan':'peq','NthOrderDouble':'filter',
           'FistOrderSingle':'first_order','CrossoverFilter2WayAlgDP':'crossover',
           'MultCtrlDel1940Alg':'delay','AdderAlg':'add','SubAlg':'subtract','MultAlg':'multiply',
           'AbsAlg':'absolute','EQ1940Invert':'invert','DCInpAlg':'dc','GPIAlg':'gpio',
           'RegReadAlgADCIn':'auxadc','ExtIntInAlg':'interface_in','RegReadIntOutAlg':'interface_out',
           'ToggleOneAlg':'counter','ToggleCountAlg':'counter','PushButtonVolAlg':'button_volume',
           'RotaryVolAlg':'encoder','sin_lookupAlg1940':'sine','TriAlg':'triangle',
           'WhiteNAlgNew':'noise','SingleCtrlMixer1940':'mixer','SingleCtrlMixerNEW1940':'mixer'}
    if name in exact:return exact[name]
    if name.startswith('ICSigma') and name.endswith('In'):return 'input'
    if name.startswith('ICSigma') and name.endswith('Out'):return 'output'
    if 'mux' in text or 'crossfade' in text or 'cross fade' in text:return 'mux'
    if 'splitter' in text:return 'splitter'
    if 'crossover' in text or 'xover' in text:return 'crossover'
    if 'delay' in text or 'delgrow' in text or 'ctrldel' in text:return 'delay'
    if 'dynamics' in category.lower():return 'compressor'
    if 'level' in category.lower() or 'envelope' in text:return 'meter'
    if 'lookup' in text or 'lut' in text:return 'lookup'
    if category=='GPIO Conditioning':return 'encoder' if 'rotary' in text else 'counter'
    if category=='Counters' or 'counter' in text:return 'counter'
    if 'gpio' in text or name.startswith('GPI'):return 'gpio'
    if 'adc' in text:return 'auxadc'
    if 'interface' in text:return 'interface_in' if 'in' in text else 'interface_out'
    if category=='Filters':return 'biquad'
    if 'invert' in text or 'negat' in text:return 'invert'
    if 'multiply' in text or 'multalg' in text:return 'multiply'
    if 'subtract' in text:return 'subtract'
    if 'signal mix' in text or 'adder' in text:return 'add'
    if 'mixer' in text or 'merger' in text:return 'mixer'
    if 'division' in text or 'divide' in text:return 'divide'
    if 'square root' in text or 'squareroot' in text:return 'sqrt'
    if 'absolute' in text or name.startswith('Abs'):return 'absolute'
    if 'log' in text:return 'log'
    if 'exp' in text:return 'exp'
    if category=='Non Linear Processors' or 'clip' in text:return 'clip'
    if any(s in text for s in ['logic','nand',' and ',' or ','xor','comparator']):return 'logic'
    if category=='Sources':
        if 'noise' in text:return 'noise'
        if 'triangle' in text:return 'triangle'
        if 'square' in text or 'pulse' in text:return 'square'
        if 'saw' in text:return 'saw'
        if 'dc ' in text or name.startswith('DC'):return 'dc'
        if 'switch' in text:return 'switch'
        if 'chime' in text or 'beep' in text:return 'chime'
        return 'sine'
    if 'gain' in text or 'volume' in text:return 'linear_gain'
    if category=='Mixers/Splitters':return 'mixer'
    return 'function'


def defaults(entry):
    kind=entry['symbol']
    if kind in ('sine','triangle','square','saw','chime'):return {'frequency':500.,'amplitude':1.,'source_on':True}
    if kind=='dc':return {'value':1.}
    if kind=='noise':return {'amplitude':.1,'source_on':True}
    if kind in ('linear_gain','mixer'):return {'linear_gain':1.}
    if kind=='switch':return {'source_on':True}
    if kind=='clip':return {'threshold':1.}
    if kind=='compressor':return {'threshold_db':-12.,'ratio':4.,'attack_ms':10.,'release_ms':100.}
    if kind=='lookup':return {'table_points':16}
    if kind=='counter':return {'initial_value':0,'modulo':4}
    return {}

"""Submit the Qwen-Image all-in-one (7 萬事通) API graph with overrides.
usage: aio.py --tag NAME [--img K=FILE ...] [--prompt FILE | --text STR] [--pe 0|1|2] [--sampler 0|1|2]
              [--size 0|1] [--aspect '3:2 (Photo)'] [--mp 1.0] [--seed N] [--dry]
K 是圖的編號 1～5。pe：0 關、1 一般強化、2 角色設定表。sampler：0 自訂、1 Pruna 8 步、2 Fix。size：0 跟著圖 1、1 自訂比例與 MP。"""
import argparse
import json
import re
import sys
import urllib.request
from pathlib import Path

HERE = Path(__file__).parent
HOST = 'http://127.0.0.1:8188'
ap = argparse.ArgumentParser()
ap.add_argument('--tag', required=True)
ap.add_argument('--img', action='append', default=[])
ap.add_argument('--prompt')
ap.add_argument('--text')
ap.add_argument('--pe', type=int, default=0)
ap.add_argument('--sampler', type=int, default=1)
ap.add_argument('--size', type=int, default=1)
ap.add_argument('--aspect')
ap.add_argument('--mp', type=float)
ap.add_argument('--seed', type=int)
ap.add_argument('--res2', type=int, help='圖 2～5 的解析度（新版萬事通；0＝同圖 1）')
ap.add_argument('--count', type=int, help='張數（新版萬事通）')
ap.add_argument('--graph', default='all-in-one.json', help='API 圖，相對於這個資料夾（可給絕對路徑）')
ap.add_argument('--attention', help='pytorch attention／comfy kitchen attention：插一個 ModelAttentionBackend 在本體載入之後')
ap.add_argument('--patch', help='JSON 檔名或 JSON 字串：{"class_type": {"input": value 或 {"舊值": "新值"}}}')
ap.add_argument('--res1', type=int, help='圖 1 的參考解析度（跟著圖 1 時也是輸出大小；BFS 作者建議 1448≈2 MP）')
ap.add_argument('--lora', action='append', default=[], help='打開 Power Lora Loader 裡這個檔名的那一列（可多次；檔名:強度 可改強度）')
ap.add_argument('--no-kitchen', action='store_true', help='新版：關掉內建的 kitchen 注意力開關')
ap.add_argument('--neg', help='負面提示詞（新版；只有取樣「自訂」時有作用）')
ap.add_argument('--dry', action='store_true')
a = ap.parse_args()
p = json.loads((HERE / a.graph).read_text(encoding='utf-8'))['prompt']


def nodes(cls, pred=lambda n: True):
    return [k for k, n in p.items() if n['class_type'] == cls and pred(n)]


def combo(prefix, index):
    k, = nodes('CustomCombo', lambda n: n['inputs']['option1'].startswith(prefix))
    p[k]['inputs']['index'] = index
    p[k]['inputs']['choice'] = p[k]['inputs'][f'option{index + 1}']


combo('關（直接用你寫的）', a.pe)
combo('自訂（下面的一般取樣）', a.sampler)
combo('跟著圖 1', a.size)
loads, bools = nodes('LoadImage'), nodes('PrimitiveBoolean')     # 圖 1～5；開關 1～5，之後是去格紋（新版再加 kitchen）
if any('_meta' in n for n in p.values()):
    # 新版 API 圖帶標題：圖 K 的開關與載圖照標題找，不靠順序（加了開關也不會對錯位置）
    def _t(k):
        return p[k].get('_meta', {}).get('title', '')
    bools = [next(k for k in bools if _t(k).startswith(f'圖 {i}：用這張')) for i in range(1, 6)]
    loads = [next(k for k in loads if _t(k).startswith(f'圖 {i}（')) for i in range(1, 6)]
else:
    assert len(loads) == 5 and len(bools) == 6, (len(loads), len(bools))
for spec in a.img:
    k, f = spec.split('=', 1)
    p[loads[int(k) - 1]]['inputs']['image'] = f
    p[bools[int(k) - 1]]['inputs']['value'] = True
rs, = nodes('ResolutionSelector')
if a.aspect:
    p[rs]['inputs']['aspect_ratio'] = a.aspect
if a.mp:
    p[rs]['inputs']['megapixels'] = a.mp
text = (HERE / a.prompt).read_text(encoding='utf-8').strip() if a.prompt else a.text
if text is not None:
    k, = nodes('PrimitiveStringMultiline', lambda n: n['inputs']['value'].startswith('A lone lighthouse'))
    p[k]['inputs']['value'] = text
if a.seed is not None:
    for k in nodes('PrimitiveInt', lambda n: n['inputs']['value'] == 20260929):
        p[k]['inputs']['value'] = a.seed
if a.res2 is not None:
    k, = nodes('PrimitiveInt', lambda n: n['inputs']['value'] == 512)    # 新版萬事通「圖 2～5 的解析度」預設 512
    p[k]['inputs']['value'] = a.res2
if a.count is not None:
    k, = [k for k in nodes('PrimitiveInt', lambda n: n['inputs']['value'] == 1)
          if any(m['class_type'] == 'RepeatLatentBatch' and m['inputs'].get('amount') == [k, 0] for m in p.values())]
    p[k]['inputs']['value'] = a.count
if a.patch:
    spec = a.patch if a.patch.lstrip().startswith('{') else (HERE / a.patch).read_text(encoding='utf-8')
    for cls, vals in json.loads(spec).items():
        for k in nodes(cls):
            for name, v in vals.items():
                if isinstance(v, dict):
                    if p[k]['inputs'].get(name) in v:
                        p[k]['inputs'][name] = v[p[k]['inputs'][name]]
                else:
                    p[k]['inputs'][name] = v
if a.attention:
    unet, = nodes('UnetLoaderGGUF') or nodes('UNETLoader')
    p['attn'] = {'class_type': 'ModelAttentionBackend', 'inputs': {'model': [unet, 0], 'attention': a.attention}}
    for k, n in p.items():
        if k != 'attn' and n['inputs'].get('model') == [unet, 0]:
            n['inputs']['model'] = ['attn', 0]
if a.res1:
    # 照標題找（API 圖有 _meta.title）；舊圖才退回找預設值 1024。不能只看值：--res2 也可能設成 1024
    k, = (nodes('PrimitiveInt', lambda n: n.get('_meta', {}).get('title', '').startswith('參考圖解析度'))
          or nodes('PrimitiveInt', lambda n: n['inputs']['value'] == 1024))
    p[k]['inputs']['value'] = a.res1
for spec in a.lora:
    name, _, st = spec.partition(':')
    hit = False
    for k in nodes('Power Lora Loader (rgthree)'):
        for key, row in p[k]['inputs'].items():
            if key.startswith('lora_') and isinstance(row, dict) and row.get('lora') == name:
                row['on'] = True
                if st:
                    row['strength'] = float(st)
                hit = True
    assert hit, f'Power Lora Loader 裡沒有 {name}'
if a.no_kitchen:
    k, = [k for k in nodes('PrimitiveBoolean') if p[k].get('_meta', {}).get('title', '').startswith('kitchen')]
    p[k]['inputs']['value'] = False
if a.neg is not None:
    k, = [k for k in nodes('PrimitiveStringMultiline') if p[k].get('_meta', {}).get('title', '').startswith('負面提示詞')]
    p[k]['inputs']['value'] = a.neg
for k in nodes('SaveImage'):
    head, last = p[k]['inputs']['filename_prefix'].rsplit('/', 1)
    # 新格式 qw/<日期>-<名稱>：保留日期、名稱換成 tag；舊格式 …/<日期>/qwen：整段換成 tag
    p[k]['inputs']['filename_prefix'] = head + '/' + (f'{last[:10]}-{a.tag}' if re.match(r'\d{4}-\d{2}-\d{2}-', last) else a.tag)
(HERE / f'aio-{a.tag}.json').write_text(json.dumps({'prompt': p}, ensure_ascii=False, indent=1), encoding='utf-8')
if a.dry:
    sys.exit(0)
q = json.loads(urllib.request.urlopen(HOST + '/queue').read())
print('queue running', len(q['queue_running']), 'pending', len(q['queue_pending']))
req = urllib.request.Request(HOST + '/prompt', json.dumps({'prompt': p}).encode('utf-8'), {'Content-Type': 'application/json'})
try:
    r = json.loads(urllib.request.urlopen(req).read())
except urllib.error.HTTPError as e:
    print(e.read().decode('utf-8')[:3000])
    sys.exit(1)
print(a.tag, r['prompt_id'], r['node_errors'])
with open(HERE / 'aio-runs.txt', 'a', encoding='utf-8') as f:
    f.write(f"{a.tag} {r['prompt_id']}\n")

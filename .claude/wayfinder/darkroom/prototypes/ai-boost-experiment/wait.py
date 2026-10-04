"""Wait for one ComfyUI prompt to finish and print status, wall time, s/it and output files.
usage: wait.py <prompt_id> [--timeout 秒]（預設 3600）
aio.py／board.py 送出後會印 prompt_id；也會記在 aio-runs.txt／board-runs.txt。"""
import argparse
import json
import re
import sys
import time
import urllib.request

HOST = 'http://127.0.0.1:8188'
ap = argparse.ArgumentParser()
ap.add_argument('pid')
ap.add_argument('--timeout', type=int, default=3600)
a = ap.parse_args()


def get(path):
    return json.loads(urllib.request.urlopen(HOST + path, timeout=30).read())


t0 = time.time()
while True:
    h = get(f'/history/{a.pid}').get(a.pid)
    if h and h.get('status', {}).get('completed') is not None and h['status'].get('status_str'):
        break
    if time.time() - t0 > a.timeout:
        sys.exit(f'等了 {a.timeout} 秒還沒完成（佇列：{len(get("/queue")["queue_running"])} 執行中）')
    time.sleep(5)
st = h['status']
ts = {x[0]: x[1].get('timestamp') for x in st['messages']}
end = ts.get('execution_success') or ts.get('execution_error') or ts.get('execution_interrupted') or 0
print(st['status_str'], f"{(end - ts.get('execution_start', end)) / 1000:.0f}s")
for x in st['messages']:
    if x[0] == 'execution_error':
        print('ERROR', x[1].get('node_type'), x[1].get('exception_message', '')[:500])
its = []
for e in get('/internal/logs/raw')['entries']:
    for m in re.findall(r'(\d+)/(\d+) \[[^\]]*?, *([\d.]+)s/it\]', e.get('m', '')):
        if m[0] == m[1]:
            its.append(f'{m[1]} steps {m[2]}s/it')
if its:
    print('steps:', '; '.join(dict.fromkeys(its[-4:])))
for o in h['outputs'].values():
    for kind in ('images', 'videos', 'gifs', 'audio'):
        for f in o.get(kind, []):
            print('output:', f"outputs/comfyui/{f.get('subfolder', '')}/{f['filename']}".replace('\\', '/'))

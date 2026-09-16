"""Match Test Drive II functions against the named Test Drive (1987) functions.

Both games share DSI's assembly graphics/platform library and the Microsoft C runtime. Every function
is disassembled with its immediates and displacements masked; each TD2 function is scored against
each TD1 function by the share of its 6-instruction windows that also occur in the TD1 function.
The best TD1 match above the threshold becomes a candidate name (to be confirmed in the specs).

usage: td1match.py TD1_DIR [TD2 index base, default port/td2ega]
       TD1_DIR is the Test Drive (1987) repo (work/TDEGA_unp.exe, port/tdega_functions.json,
       port/symbols.csv). Writes <base>_td1_matches.csv.
"""
import csv, json, os, re, struct, sys
from collections import defaultdict
from capstone import Cs, CS_ARCH_X86, CS_MODE_16

N = 6
THRESHOLD = 0.5
td1_dir = sys.argv[1]
base = sys.argv[2] if len(sys.argv) > 2 else 'port/td2ega'
md = Cs(CS_ARCH_X86, CS_MODE_16)
NUM = re.compile(r'0x[0-9a-f]+|\b\d+\b')


def image(path):
    d = open(path, 'rb').read()
    return d[struct.unpack_from('<H', d, 8)[0] * 16:]


def grams(code):
    ops = [mn + ' ' + NUM.sub('#', op) for _, _, mn, op in md.disasm_lite(code, 0)]
    return ops, {tuple(ops[k:k + N]) for k in range(len(ops) - N + 1)}


td1_img = image(os.path.join(td1_dir, 'work/TDEGA_unp.exe'))
names = {}
for r in csv.DictReader(open(os.path.join(td1_dir, 'port/symbols.csv'))):
    if r['kind'] == 'func':
        names[int(r['address'], 16)] = r['name']
td1 = []
index = defaultdict(set)            # gram -> TD1 function ids
for f in json.load(open(os.path.join(td1_dir, 'port/tdega_functions.json'))):
    s, e = int(f['start'], 16), int(f['end'], 16)
    ops, g = grams(td1_img[s:e])
    if len(ops) < N + 2:
        continue
    fid = len(td1)
    td1.append((s, names.get(s, 'fn_%04x' % s), len(ops), g))
    for x in g:
        index[x].add(fid)

j = json.load(open(base + '_functions.json'))
td2_img = image(j['exe'])
rows = []
for f in j['functions']:
    s = int(f['image'], 16)
    ops, g = grams(td2_img[s:s + f['size']])
    if len(ops) < N + 2 or not g:
        continue
    votes = defaultdict(int)
    for x in g:
        for fid in index.get(x, ()):
            votes[fid] += 1
    if not votes:
        continue
    fid, v = max(votes.items(), key=lambda kv: kv[1] / max(len(g), len(td1[kv[0]][3])))
    score = v / max(len(g), len(td1[fid][3]))
    if score >= THRESHOLD:
        rows.append((f['start'], f['image'], td1[fid][1], '0x%04x' % td1[fid][0], '%.2f' % score, len(ops), td1[fid][2]))

with open(base + '_td1_matches.csv', 'w', newline='') as o:
    w = csv.writer(o)
    w.writerow(['td2_start', 'td2_image', 'td1_name', 'td1_address', 'score', 'td2_insns', 'td1_insns'])
    w.writerows(rows)
print('%d of %d TD2 functions matched a TD1 function (score >= %.2f)' % (len(rows), len(j['functions']), THRESHOLD))
for r in rows:
    print('  %s  %-28s %s  %s' % (r[0], r[2], r[3], r[4]))

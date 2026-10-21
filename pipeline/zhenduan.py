import json
d = json.load(open('inventory.json', encoding='utf-8'))

desc_keys = {(x['classid'], x['instanceid']) for x in d['descriptions']}
missing = []
for a in d['assets']:
    key = (a['classid'], a['instanceid'])
    if key not in desc_keys:
        missing.append((a['assetid'], a['classid'], a['instanceid']))

print('assets 总数:', len(d['assets']))
print('descriptions 总数:', len(d['descriptions']))
print('缺 description 的 assets:', len(missing))
for m in missing[:10]:
    print(' ', m)
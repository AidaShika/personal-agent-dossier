#!/usr/bin/env python3
"""Render a dossier into the Notion page body: human sections generated FROM the yaml, then the yaml block.
The human sections are never written by hand, so they cannot drift from the yaml.
Usage: render_notion.py FILE.dossier.md > page.md"""
import sys, yaml
src = open(sys.argv[1], encoding='utf-8').read()
raw = src.split('---\n', 2)[1]
d = yaml.safe_load(raw)
o = ['## 交接档案（%s · 导出于 %s）' % (d['name'], d['exported_at']), '', '### 一、职能全文（profile.description 原文）', '', '```text', d['role'], '```', '', '### 二、反职责', '']
o += ['- ' + a for a in d.get('anti_jobs') or ['无']]
o += ['', '### 三、定时任务', '']
if d['routines'] is None: o.append('未导出（不等于没有）。')
elif not d['routines']: o.append('无。')
else:
    for r in d['routines']:
        o += ['**%s**（%s，%s）' % (r['name'], r['schedule'], r['state']), '', '```text', r['prompt'], '```', '']
o += ['', '### 四、长期记忆（只含与职能相关的事实；私人信息不导出）', '']
if d['memory'] is None: o.append('未导出（不等于没有）。')
else: o += ['- [%s] %s' % (m['kind'], m['fact']) for m in d['memory']] or ['无。']
o += ['', '### 五、依赖 skill', '', '、'.join(d.get('skills') or ['无']) , '', '### 六、未导出的内容', '', d.get('excluded') or '无', '']
o += ['## 机器可读版（%s）' % d['spec'], '', '下面这段 YAML 是权威版本，上面的六段由它自动生成。导入时读这一段。', '', '```yaml', raw.rstrip('\n'), '```', '']
print('\n'.join(o))

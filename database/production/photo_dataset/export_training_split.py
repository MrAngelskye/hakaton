"""Export expert-reviewed examples grouped by source series, never auto-label."""
import argparse
import csv
import hashlib
import json
from pathlib import Path


def build_split(manifest, annotations):
    assets={r['asset_id']:r for r in manifest['assets']}
    approved=[];seen=set()
    for row in annotations:
        photo_id=row['photo_id']
        if photo_id in seen:raise ValueError('Повторная аннотация: '+photo_id)
        seen.add(photo_id)
        if photo_id not in assets:raise ValueError('Неизвестная фотография: '+photo_id)
        if row.get('review_status')!='expert_reviewed':continue
        if row.get('defect_visible') not in ('yes','no') or not row.get('reviewer_code') or not row.get('evidence'):
            raise ValueError('Эксперт должен указать видимый дефект, код проверяющего и обоснование.')
        asset=assets[photo_id]
        approved.append({'photo_id':photo_id,'relative_path':asset['file_path'],
            'sha256':asset['sha256'],'split_group':asset['split_group'],
            'defect_visible':row['defect_visible'],'defect_label':row.get('defect_label',''),
            'reviewer_code':row['reviewer_code'],'review_status':row['review_status'],
            'evidence':row['evidence'],'license_id':asset['license'],
            'license_url':asset['license_url'],'changes':asset['changes'],
            'attribution':asset['attribution'],'source_page':asset['source_page_url']})
    groups=sorted({row['split_group'] for row in approved},key=lambda s:hashlib.sha256(('naryadai-v1:'+s).encode()).hexdigest())
    if len(groups)<3:raise ValueError('Нужны экспертные аннотации минимум трёх независимых групп. Модель не обучена.')
    valid=max(1,len(groups)//5);test=max(1,len(groups)//5)
    assignment={g:'validation' if i<valid else 'test' if i<valid+test else 'train' for i,g in enumerate(groups)}
    result={name:[] for name in ('train','validation','test')}
    for row in approved:result[assignment[row['split_group']]].append(row)
    result['note']='Исследовательский набор. Разделение не подтверждает качество, применимость на предприятии или выполненный ремонт.'
    return result


if __name__=='__main__':
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--annotations',required=True,type=Path)
    parser.add_argument('--output',required=True,type=Path)
    args=parser.parse_args();root=Path(__file__).resolve().parent
    try:
        manifest=json.loads((root/'manifest.json').read_text(encoding='utf-8'))
        with args.annotations.open(encoding='utf-8-sig',newline='') as stream:annotations=list(csv.DictReader(stream))
        result=build_split(manifest,annotations)
        args.output.parent.mkdir(parents=True,exist_ok=True)
        with args.output.open('x',encoding='utf-8') as stream:json.dump(result,stream,ensure_ascii=False,indent=2)
        print(json.dumps({k:len(result[k]) for k in ('train','validation','test')}))
    except (ValueError,OSError) as error:parser.exit(1,str(error)+'\n')

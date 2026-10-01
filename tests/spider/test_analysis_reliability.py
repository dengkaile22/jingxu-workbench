"""Preserve grouping semantics while pruning impossible similarity candidates."""
import random
from dataclasses import replace
from difflib import SequenceMatcher
from core.analyzer import ProductAnalyzer
from core.models import VideoProductItem, OccurrenceFilterConfig
from core.text_utils import clean_product_title, calculate_jaccard_similarity
from core.config import AppConfig
from core.exporter import DataExporter
from ecommerce_spider.analyzer_component import ProductAnalyzerComponent
import pytest
from openpyxl import load_workbook

def item(name, i=0, platform='douyin'):
    return VideoProductItem(platform,'演示账号',f'account-{i%2}',f'video-{i}','演示',f'https://example.test/{i}',
                            1710000000,'2024-03-09 12:00:00','product-'+str(i),name,like_count=i)
def legacy_similarity(a,b):
    a=clean_product_title(a).lower(); b=clean_product_title(b).lower()
    if a==b: return 1.
    short,long=min(len(a),len(b)),max(len(a),len(b))
    if short>=4 and (a in b or b in a) and short/long>=.5:
        return round(.75+.25*short/long,4)
    return round(.5*SequenceMatcher(None,a,b).ratio()+.5*calculate_jaccard_similarity(a,b),4)
def legacy_group(items,threshold):
    clusters=[]; reps=[]
    for it in items:
        name=clean_product_title(it.product_name); best=-1; score=0.
        for i,rep in enumerate(reps):
            if clusters[i][0].platform!=it.platform: continue
            sim=legacy_similarity(name,rep)
            if sim>=threshold and sim>score: best=i; score=sim
        if best>=0:
            clusters[best].append(it)
            if len(name)<len(reps[best]) and len(name)>=4: reps[best]=name
        else: clusters.append([it]); reps.append(name)
    return [[x.video_id for x in group] for group in clusters]
@pytest.mark.parametrize('threshold',[0,.49,.5,.50001,.50005,.5001,.75,.85,1.])
def test_optimized_grouping_matches_reference(threshold):
    rng=random.Random(314159)
    names=['洗衣液','洗衣液3kg','【推荐】天然茶籽洗衣液5kg','天然茶籽洗衣液','----','------','AB--','ＡＢＣ','x','X']
    names += [''.join(rng.choices('ABCDEF天然纯棉洗衣液xyz123',k=rng.randint(4,25))) for _ in range(75)]
    items=[item(name,i,'douyin' if i%3 else 'kuaishou') for i,name in enumerate(names+names[:15])]
    actual=ProductAnalyzer(OccurrenceFilterConfig(fuzzy_threshold=threshold)).group_products([replace(x) for x in items])
    assert [[x.video_id for x in group] for group in actual]==legacy_group(items,threshold)

def test_likes_threshold_survives_save_and_reload(tmp_path):
    config=AppConfig(str(tmp_path/'config.json'))
    config.filter_config.min_like_count=1234
    config.save()
    assert AppConfig(config.config_path).filter_config.min_like_count==1234

def test_analyzer_reads_exported_raw_items_without_losing_titles(tmp_path):
    import json
    source=[item('天然茶籽洗衣液',0),item('天然茶籽洗衣液',1)]
    retained,_=ProductAnalyzer(OccurrenceFilterConfig(min_account_count=2)).aggregate_and_filter(source)
    path=tmp_path/'results.json'; DataExporter.export_to_json(str(path),retained,source)
    data=json.loads(path.read_text(encoding='utf-8'))
    recovered,_=ProductAnalyzerComponent(min_account_count=2).analyze(data['all_items'])
    assert len(recovered)==1 and recovered[0].product_name=='天然茶籽洗衣液'
    assert recovered[0].video_count==2 and recovered[0].account_count==2

def test_external_excel_text_cannot_become_a_formula(tmp_path):
    source=[item('=1+2',0)]
    retained,_=ProductAnalyzer(OccurrenceFilterConfig(min_account_count=1)).aggregate_and_filter(source)
    path=tmp_path/'results.xlsx'; DataExporter.export_to_excel(str(path),retained,source)
    workbook=load_workbook(path,data_only=False)
    assert workbook.worksheets[0]['B2'].value=='=1+2'
    assert workbook.worksheets[0]['B2'].data_type=='s'
    assert workbook.worksheets[1]['H2'].data_type=='s'

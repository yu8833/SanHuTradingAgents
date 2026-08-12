"""候选池编排服务：行业 → 个股 → 择时 三层流水线。

- industry_layer.py      第1层：强势行业轮动分数（本地行业字段反查）
- stock_score_layer.py   第2层：个股多因子质量分
- timing_layer.py        第3层：三买三卖择时确认（复用）
"""
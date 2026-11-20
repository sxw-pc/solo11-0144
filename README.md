# 景区步道通行采录台

本地合成的步道区段、巡检险情和摆渡班次证据工程。面向护林巡检与接驳调度，决定步行路线和断路后实际人数是否可在时限内离场；不处理售票、真实定位或外网地图。

## 运行

Python 3.11+，仓库根目录：

```powershell
python -m pip install . --no-build-isolation --no-deps
$env:PYTHONPATH=(Resolve-Path -LiteralPath src).Path
python -m trail demo --db data/demo.sqlite
python -m unittest discover -s tests -v
```

独立采录入口：

```powershell
python -m trail import-segment --db data/demo.sqlite --input fixtures/trail/segment_good.json
python -m trail import-patrol --db data/demo.sqlite --input fixtures/trail/patrol_clear.json
python -m trail import-shuttle --db data/demo.sqlite --input fixtures/trail/shuttle_good.json
python -m trail report --db data/demo.sqlite --as-of 2026-11-17T10:00:00Z
python -m trail build-map --db data/demo.sqlite --as-of 2026-11-17T10:00:00Z --contract survey --levels levels.json
python -m trail hit-map --db data/demo.sqlite --x 1 --y 1 --radius 0.4 --level handheld
```

`build-map` 按交付合同独立裁定多尺度离线包。`--contract survey` 是测绘近似图，每级坐标误差严格受控；`--contract schematic` 是示意导航图，允许更大形状偏移，但正式路口、桥/桥下分层、不可换乘关系与单向指向仍须保真。两种合同对同一原图分别出包，示意图不会被冒充成测绘图。`--levels` 是 JSON 数组，每级给出 `level`、`tolerance`、`max_points`、`min_gap`（可选 `quantum`）。

区段事件可带 `shape`（二维坐标折线）与整数 `layer`（高度层，默认 0）。简化采用带固定点的 Ramer-Douglas-Peucker：端点与正式路口永不删除；删点同时重算两侧相邻线段的整体偏差，不做逐段局部判断。每个缩放级独立核证：

- 共用正式路口的相邻形状，路口必须落在同一量化坐标，否则屏幕点击产生两个假断点；
- 同源不相连的同层路段，简化后不得出现新交叉、屏幕格重合（山脊被压成同线即判假换乘）或小于 `min_gap` 的间距；违反时按最大偏差逐轮回补原图点，仍无法解除则该级 `not_published`；
- 不同高度层的平面投影交叉只登记为 `grade_separated_crossings`，命中索引按层返回各自路段，不产生换乘节点；
- 总包点数超过 `max_points` 时拒绝出包，并标注导致矛盾的原段与缩放级，绝不输出看似正常的错误地图。

包内除简化坐标外，`hit_index` 为每段回溯 `segment_id`、`event_id`、原图点序（`original_vertex_order`）、方向、高度层与构建所用 `map_version`；`hit-map` 或 `mapbundle.hit_query` 做屏幕命中查询。重复构建对同一原图产生相同 `map_version` 与稳定摘要（`mapbundle.stable_summary`）。

区段账按版本、方向和封闭窗口构造可走边；险情账仅在有整改照片摘要、不同人员复核且摘要一致时解除限制；摆渡账按真实需求人数、上车站、发车和最晚离场时点分配有限席位。报告汇合三种独立决定，从原始事件按时点重算并留下签发回执。

## 可复现边界

`segment_stale.json` 的旧区段版次不能撤销新版开放边。`patrol_conflict.json` 的整改人自签让险情重新限制区段。`shuttle_full.json` 撤销原满额车次，只剩 2 席位，3 人需求留下 1 人未保障；若区段已封闭，通行结论从 `shuttle_only` 变 `closed`。错站、超时和多个需求竞争也有测试；不能只数车次而不核对人数与时间窗。

原始 JSON 与 SHA-256 存 SQLite；同事件 ID、同内容幂等，异内容整批拒绝。`src/trail/store.py` 幂等建表。未来边界见 `docs/initial-requirements.md`。

共用原图反例（见 `tests/test_multiscale.py`）：`S5=[[0,0],[1,1],[2,0]]` 与远离的 `S6=[[0,3],[2,3]]` 不相交，总点数上限 4。测绘误差上限 0.1 时 S5 必须保留峰点，两段至少 5 点，测绘图判 `package_size_exceeded` 不出包；示意误差上限 1.1 时 S5 只留两端点、S6 两点，无假连通，示意图正常出包。山脊假重合、共享路口 J、桥上桥下、单向箭头与重复构建稳定性均有验收测试：`python -B -m pytest -q -p no:cacheprovider`。

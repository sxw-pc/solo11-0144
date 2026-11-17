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
```

区段账按版本、方向和封闭窗口构造可走边；险情账仅在有整改照片摘要、不同人员复核且摘要一致时解除限制；摆渡账按真实需求人数、上车站、发车和最晚离场时点分配有限席位。报告汇合三种独立决定，从原始事件按时点重算并留下签发回执。

## 可复现边界

`segment_stale.json` 的旧区段版次不能撤销新版开放边。`patrol_conflict.json` 的整改人自签让险情重新限制区段。`shuttle_full.json` 撤销原满额车次，只剩 2 席位，3 人需求留下 1 人未保障；若区段已封闭，通行结论从 `shuttle_only` 变 `closed`。错站、超时和多个需求竞争也有测试；不能只数车次而不核对人数与时间窗。

原始 JSON 与 SHA-256 存 SQLite；同事件 ID、同内容幂等，异内容整批拒绝。`src/trail/store.py` 幂等建表。未来边界见 `docs/initial-requirements.md`。

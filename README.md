# 榆湾材料试验室双段质控归档

白班两台架各交一段实采读数。站员按同一份采样清册核定段内变化并冻结证据。夜班关闭源站后，凭接纳号补算接缝告警及整程次数。次班勘误后仍可凭原报告号核对当时的读数修订及结论。

## 运行

使用 Python 3.11 和标准库。物化工程提供 `check_project.py` 作为完整回归入口。

```sh
python3 -B check_project.py
python3 -B demo.py
```

演示从 `examples/day_shift.json` 读取固定班次样例，在独立临时目录建立两份站库和一份中心库，结束时清理。原读数 0、0、1、1 在门槛和变化上限均为 1 时签出一次告警。后段改为 0、0 后另签零次，重开中心仍可按两个原号领取。演示输出的场景记录来自断言核对后的实际报告及领取结果。

## 业务接口

用 `database.connect(path)` 打开连接，调用者负责关闭。各写入口拥有自己的事务，调用时连接应处于事务外。先对各库执行 `plan.catalog.initialize_catalog(db)`。站库再执行 `ledger.storage.initialize_ledger(db, origin)` 和 `station.storage.initialize_station(db)`。中心库执行 `intake.registry.initialize_intake(db)` 和 `review.storage.initialize_review(db)`。初始化可以重复执行，已有站点绑定及业务数据保留。

1. 班长用 `plan.tasks.open_task(db, name, unit, threshold, max_change, segments)` 登记任务。`segments` 依序提供两个 `plan.layout.SegmentLayout(slot, origin, rig, beats)`，段位为 1、2，拍位为整数。每段非空且连续，前末与后首相邻。规程需具名，变化上限非负。非法定义抛出 `ValueError`。
2. `plan.catalog.get_task(db, task_id)` 领取不可变快照，`install_task_snapshot(db, snapshot)` 在各站和中心安装同一快照。相同快照重放返回原号，同号异内容抛出 `ValueError`。未知任务号抛出 `KeyError`。
3. `ledger.ingest.record_segment(db, task_id, slot, samples, parent_id=None)` 登记整段。`samples` 是 `(拍位, 读数)` 对的可迭代对象，提交次序任意，每个计划拍位须恰好出现一次。读数、门槛和变化上限接受整数、`Fraction` 和精确有理数字符串，如 `-1/3`、`0.5`。空值、浮点值、零分母、错误拍位或站点归属抛出 `ValueError`。`ledger.query.get_revision(db, revision_id)` 按号取得清册顺序的原读数。勘误指定同任务同段同台架的父修订并新增一版，错误归属抛出 `ValueError`，未知任务或父号抛出 `KeyError`。
4. `station.freeze.freeze_segment(db, revision_id)` 检查该版每对相邻读数的绝对差。等于变化上限可以冻结，超限抛出 `ValueError`，原修订保留。告警从严格低于门槛到达到或超过门槛时计一次，首拍自身零次。`station.export.export_segment(db, piece_id)` 按号导出稳定的 V1 字节，未知修订或站件号抛出 `KeyError`。
5. `intake.registry.accept_segment(db, payload)` 校验 V1 与登记任务，保存首份字节并返回接纳号。`get_accepted_piece(db, acceptance_id)` 领取身份、解码值、首份原文及回执。同站同件号的等内容重投沿用原接纳号，允许 JSON 空白及字段次序不同。坏件、任务或站点不匹配、同号异内容抛出 `ValueError`。
6. `review.issue.issue_review(db, task_id, front_id, back_id, *, before_commit=None)` 用有序选件的实际前末和后首核算接缝，返回 `(report_id, receipt)`。接缝合法才签发，两段次数与接缝次数合计为整程次数。未知号抛出 `KeyError`，重复、逆序、异任务选件或接缝超限抛出 `ValueError`。可选的无参 `before_commit` 在报告与回执已暂存时运行，抛出的异常连同存储错误一起传播，此次签发回滚。
7. `review.history.get_review(db, report_id)` 返回固定任务、有序选件、两段计数、接缝实值与差值、接缝计数、整程计数及原回执。未知报告号抛出 `KeyError`。源站勘误、重开中心或重复初始化后照常领取旧报告。

V1 UTF-8 JSON 使用固定字段顺序 `version, origin, piece_id, task_id, slot, revision_id, first, last, crossings`。`version` 为整数 1，编号为正整数，段位为整数 1 或 2，`first` 与 `last` 为约分后的 `分子/分母` 字符串。站内件号按站点命名，中心接纳号与签发号各自只在其中心库内使用。中心核对站件的任务归属和摘要形状，站内逐拍检查由登记站承担。

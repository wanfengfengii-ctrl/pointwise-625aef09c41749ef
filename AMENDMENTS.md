# 正式报告的勘误差异

同一试验的前后段可以分别勘误。次班要凭勘误前后的两份正式报告核定哪些拍对新增或取消了告警。签发差异时两站均可关闭。任务的清册、精确有理读数、冻结资格、接纳原件及正式报告仍沿用 README.md 中的规则。

## 站端发行与中心接纳

- `station.export.export_committed_segment(db, piece_id)` 接受已有冻结件号，返回 `(payload, commitment)`，两项均为 `bytes`。`payload` 等于 `export_segment(db, piece_id)` 的 V1 字节。承诺由该件的确切冻结修订生成，覆盖清册全段，绑定任务、站点、段位、站件号、读数修订和直接父修订。首版的父修订为空。承诺须能支撑按拍位验证读值和两版未变范围。承诺正文只交验证材料，端点原值沿用 V1 站件字段。
- `station.export.export_change_proof(db, old_piece_id, new_piece_id)` 返回 `bytes`。按旧新顺序使用同任务、同段且修订直接相承的两个冻结件。证明须对应两个具体站件，包含验证本段变更及其邻拍所需的材料。两个导出入口按 V1 规则对未知件号抛出 `KeyError`，错配或不满足直接勘误条件抛出 `ValueError`。
- `intake.registry.accept_committed_segment(db, payload, commitment)` 返回可传给原 `issue_review` 的接纳号。中心核对 V1 资格、承诺结构与站件绑定，首次接纳在一次事务中固定原件、承诺及回执。站件身份沿用站点与件号两项。同身份、同站件语义及同承诺内容重投返回原接纳号，保留首次原文及承诺。JSON 空白和对象字段顺序不改变内容。同身份异内容或试图给已按纯 V1 接纳的件补挂承诺，抛出 `ValueError`。原 `accept_segment` 对相同 V1 站件的等价重投仍返回原号，已有承诺资格由首次接纳固定。

承诺与证明使用 UTF-8 JSON 对象字节，重复字段无效。交付时说明所选编码和开放拍位的表示，便于站端和中心交换。读值精度沿用 V1 的约分有理数。沿用 V1 的登记站信任边界，由站方保证发行时依据真实冻结修订。比较方用首纳证据验证后续传来的证明。最小披露按传输及留存的原值字段核对。

## 差异签发与领取

`review.issue.issue_amendment(db, old_report_id, new_report_id, proofs, *, before_commit=None)` 返回 `(amendment_id, receipt)`，`receipt` 为 `(amendment_id, task_id)`。输入是本中心已签发、同一任务的旧新正式报告号。每段选件取自这两份报告。各段要么复用同一接纳号，要么选择新件且其首纳声明的直接父修订为该段旧件的修订。四个选件位置都须有首纳承诺，重复使用的接纳号只需其已有承诺。`proofs` 是以换件段位整数为键、以对应证明字节为值的字典，键集合须恰好等于换件段。换件但读数相同也提交该段证明。

中心用两版承诺核对整个计划段，确认所有变更拍及原位读值，未公开的位置须能核实两版相同。每个变更拍最多影响紧邻的前后两条边。证明只公开变更拍及这些拍对所用邻拍的内部原值。内部邻拍相同的值可共用一次公开材料，但须能核对两版。V1 已公开的端点可用于核算，所用变更段端点也须与对应承诺一致。坏件、缺证、错配、漏报变更或超出范围的内部原值均拒绝。

以计划拍位为相邻拍对的身份。旧版和新版分别用本版的一对读值，沿用从严格低于门槛到达到或超过门槛的告警判定。同一拍对每版只结算一次，包括两个变更拍共用一条边、两个段的端点同时变更以及只有一侧换件的接缝。在新版有告警而旧版没有的拍对列入新增，旧版有而新版没有的列入取消。两个列表各按拍位升序。结果为空也签发。

`review.history.get_amendment(db, amendment_id)` 读取已保存的字典：

| 键 | 值 |
| --- | --- |
| `amendment_id`, `task_id` | 差异号与任务号 |
| `reports` | `(old_report_id, new_report_id)` |
| `acceptances` | `((old_front, old_back), (new_front, new_back))`，元素为接纳号 |
| `revisions` | 对应 `acceptances` 的同形状二元组，元素为读数修订号 |
| `proof_digests` | 按段位升序的 `(slot, digest)` 元组序列，摘要取签发所用证明字节的 SHA-256 小写十六进制 |
| `added`, `removed` | 各为 `(left_beat, right_beat)` 的有序元组序列，空时为 `()` |
| `receipt` | 固定回执 `(amendment_id, task_id)` |

结果、来源与回执同次提交。`before_commit` 沿用原签发无参钩子语义，在差异及回执已暂存时执行。坏件、旧件、错配或缺证报 `ValueError`。编号查询沿用 V1 的 `KeyError` 约定。提交失败传播原异常，回滚本次新增，同一输入可重试。后续更正及重开中心后按原差异号读取存值，读取时无需再取证明或重算。初始化可重复执行，保留 V1 接口、旧库数据、V1 字节及原回归。

## 调用和手算样例

`python3 -B amendment_cases.py` 演示 V1 总数为何不足以核对迁位。该脚本提供 `prepare_case(center, (west, east), case)`，返回任务号及按段排列的 `(旧件号, 新件号)`，未换件时两号相同。三组样例的门槛与变化上限均为 1。

| 样例 | 旧前段 → 新前段 | 旧后段 → 新后段 | V1 总数旧 → 新 | 新增 | 取消 |
| --- | --- | --- | --- | --- | --- |
| `MOVED` | `(0,1,0,0,0,0)` → `(0,0,1,0,0,0)` | `(0,)` 复用原件 | `1 → 1` | `((1,2),)` | `((0,1),)` |
| `NO_CHANGE` | 与 `MOVED` 的旧前段同值，新增直接勘误 | `(0,)` 复用原件 | `1 → 1` | `()` | `()` |
| `SEAM` | `(0,0)` → `(0,1)` | `(1,1)` → `(0,1)` | `1 → 2` | `((0,1),(2,3))` | `((1,2),)` |

以 `MOVED` 为例，前段在拍 1 和 2 变更，所需拍对是 `(0,1)`、`(1,2)`、`(2,3)`，内部拍 4 无需公开原值。先在西站用 `export_committed_segment(west, old_piece)` 和 `export_committed_segment(west, new_piece)` 导出两件，再用 `export_change_proof(west, old_piece, new_piece)` 生成 `proof`。东站导出一份带承诺的原件。关闭站库，中心用 `accept_committed_segment(center, payload, commitment)` 逐件接纳，调用 `issue_review` 签出两份正式报告，后段使用同一接纳号。此时用 `issue_amendment(center, old_report_id, new_report_id, {1: proof})` 比较，再以返回的差异号调用 `get_amendment`。`SEAM` 两段都换件，证明字典含段位 1 和 2，两个站内新增各自归原拍对，同一接缝只取消一次。

沿 `.pointwise-runtime.json` 接通真实核验和演示。`verify` 运行完整原回归及新增业务核验，失败用非零退出码。`demo` 用实际报告展示总数相同而拍对变化、两站关闭后签发及中心重开后领取。沿用清单的版本、种类及命令数组格式。

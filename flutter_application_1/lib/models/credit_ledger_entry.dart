import '../core/json_utils.dart';

/// 积分流水的类型
///
/// 对应《工程文档.md》§7.3 的 `credit_ledger.kind`。
///
/// 【为什么要有五种，而不是简单记一笔「充了」「扣了」】
/// 因为在**冻结/结算/退回**这套三段式下，一次生成会留下最多三条记录：
/// 下单时冻结 40 → 生成完结算 35 → 退回多冻结的 5。
/// 如果把这三条压成一条「扣了 35」，一旦用户来问
/// 「为什么我刚下单就少了 40」，账本上根本查不出来 —— 这是对账能力的底线。
enum CreditLedgerKind {
  /// 赠送（注册送 50 积分就记这个）
  grant('grant', '赠送'),

  /// 冻结（下单预扣，钱还在，只是不能用了）
  freeze('freeze', '冻结'),

  /// 结算（按实际成片时长扣走）
  settle('settle', '结算'),

  /// 退回（任务失败全退，或成功时退回多冻结的部分）
  refund('refund', '退回'),

  /// 人工调整（客服补积分等，App 端只读）
  adjust('adjust', '调整');

  const CreditLedgerKind(this.wire, this.label);

  /// 与后端约定的字符串。
  final String wire;

  /// 给用户看的中文标签。
  final String label;

  static CreditLedgerKind fromWire(String wire) {
    for (final k in CreditLedgerKind.values) {
      if (k.wire == wire) return k;
    }
    throw FormatException(
      '未知的流水类型 "$wire"。定义在 lib/models/credit_ledger_entry.dart。',
    );
  }

  /// 这一笔是否**减少可用余额**。
  ///
  /// 【仔细看，只有 settle 是 true】这是整套冻结机制最容易理解错的地方：
  /// · `freeze` 不减余额，它只是把「可用」搬到了「冻结」—— 总额没变；
  /// · `settle` 才是真正把钱花掉（从冻结里扣走）；
  /// · `refund` 把冻结里没用掉的部分搬回可用。
  ///
  /// 所以流水页里给 freeze 画一个红色的「−40」是**错的**，
  /// 用户会以为被扣了两次（冻结一次、结算一次）。UI 的显示方式要跟着这个区分走。
  bool get reducesAvailable => this == CreditLedgerKind.settle;

  /// 这一笔是否只影响「冻结中」的数额，不动总余额。
  bool get affectsFrozenOnly =>
      this == CreditLedgerKind.freeze || this == CreditLedgerKind.refund;
}

/// 一条积分流水
///
/// 对应 §7.3 的 `credit_ledger` 表。积分页的流水列表读它。
///
/// ─────────────────────────────────────────────────────────
/// 【关于 amount 的符号，这里有个契约缺口】
///
/// §7.3 只写了有一列 `amount`，**没定义它是正数还是带符号的**。
/// 单靠一个 `amount` 也表达不了 freeze 这种「余额不变、冻结增加」的情况 ——
/// 它到底该记 +40 还是 −40？
///
/// 本项目的拍板是：**`amount` 恒为正数**，表示「这一笔涉及多少积分」；
/// 具体动的是可用余额还是冻结额，**看 [kind]**（见 [CreditLedgerKind.reducesAvailable]）。
/// 真正的权威快照是 [balanceAfter] / [frozenAfter] 两个字段，
/// 界面显示余额时应该信它们，而不是自己拿 amount 去累加。
///
/// 接真后端前需与后端确认一次这条约定。
/// ─────────────────────────────────────────────────────────
class CreditLedgerEntry {
  const CreditLedgerEntry({
    required this.id,
    required this.kind,
    required this.amount,
    this.adjustmentDebit = false,
    this.balanceAfter,
    this.frozenAfter,
    this.taskId,
    this.note,
    this.createdAt,
  });

  final String id;
  final CreditLedgerKind kind;

  /// 这一笔涉及的积分数，**恒为正数**。方向看 [kind]。
  final int amount;
  final bool adjustmentDebit;

  /// 这一笔之后的总余额。**权威快照**，显示时以它为准。
  final int? balanceAfter;

  /// 这一笔之后的冻结额。**权威快照**。
  final int? frozenAfter;

  /// 关联的任务。赠送/调整类流水没有它。
  ///
  /// 【为什么流水要能点进任务详情】用户在流水页看到「结算 −35」时，
  /// 下一个问题必然是「哪个视频扣的」。有这个 id 才能跳过去看成品。
  final String? taskId;

  /// 备注（如「新用户注册赠送」）。
  final String? note;

  final DateTime? createdAt;

  factory CreditLedgerEntry.fromJson(Map<String, dynamic> json) =>
      CreditLedgerEntry(
        id: json.requireInt(json['id'], field: 'id').toString(),
        kind: CreditLedgerKind.fromWire(json.stringOr(json['kind'], 'adjust')),
        amount: json.requireInt(json['amount'], field: 'amount'),
        adjustmentDebit: json.boolOr(json['adjustment_debit'], false),
        balanceAfter:
            json.asIntOrNull(json['balance_after'], field: 'balance_after'),
        frozenAfter:
            json.asIntOrNull(json['frozen_after'], field: 'frozen_after'),
        taskId: json.asStringOrNull(json['task_id']),
        note: json.asStringOrNull(json['note']),
        createdAt: json.asDateTimeOrNull(json['created_at']),
      );
}

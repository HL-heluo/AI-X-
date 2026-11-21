import '../core/json_utils.dart';

/// 一次生成的价格预估
///
/// 对应 §12.1 的 `GET /generation/cost`，返回 `{min, max, freeze}`。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么价格是一个**区间**加一个冻结额，而不是一个确定的数字】
///
/// 这是这个产品计费设计里最关键的一点，值得写清楚：
///
/// 视频的**实际时长由 provider 侧的 Agent 自主决定** —— 我们下单时说「来个 5 秒的」，
/// 它可能交回来 5.2 秒。而计费是按**成片秒数**算的（§7.2）。
/// 所以下单那一刻，**谁也不知道最终会扣多少**，包括后端。
///
/// 于是设计成：先**冻结**一个偏高的数（`freeze`，保证扣得起），
/// 生成完后按实际时长**结算**，多冻结的部分**退回**（§7）。
///
/// 【这就是为什么按钮下面绝不能写「预计消耗 20 积分」】
/// §13.4 明令禁止在按钮下显示确定数字 —— 那个数字注定是错的，
/// 用户会因为「说好 20 结果扣了 21」来投诉。正确的写法是
/// **区间**（`min`~`max`，明确表达了不确定性）或「计算中…」（还没问到价）。
/// 文案的唯一出处是 `lib/core/format/credit_format.dart`。
///
/// 【前端类比】≈ 打车软件下单前显示的预估价区间 +「预扣 XX 元」。
/// ─────────────────────────────────────────────────────────
class TaskCostEstimate {
  const TaskCostEstimate({
    required this.minCredits,
    required this.maxCredits,
    required this.freezeCredits,
  });

  /// 预估下限（最少可能扣这么多）。
  ///
  /// 字段名用 `Credits` 后缀而不是照抄后端的 `min`：一来 §2 术语锁定要求
  /// 代码里出现的是 `credit` 这个词，二来裸的 `min` 会盖住 `dart:math` 的 `min` 函数，
  /// 在这个类里想用数学函数时会有歧义。
  final int minCredits;

  /// 预估上限。
  final int maxCredits;

  /// 下单时会**冻结**的积分。通常等于（或略高于）上限。
  final int freezeCredits;

  /// 上下限是否相同。
  ///
  /// 【为什么值得单独有个 getter】因为文案要分两种写法：
  /// 相同时写「本次冻结 20 积分」比「本次冻结 20~20 积分」自然得多。
  /// 判断逻辑收在这里，免得每个页面自己写 `min == max ?`。
  bool get isFixed => minCredits == maxCredits;

  factory TaskCostEstimate.fromJson(Map<String, dynamic> json) =>
      TaskCostEstimate(
        minCredits: json.requireInt(json['min'], field: 'min'),
        maxCredits: json.requireInt(json['max'], field: 'max'),
        freezeCredits: json.requireInt(json['freeze'], field: 'freeze'),
      );
}

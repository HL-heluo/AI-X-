import '../core/json_utils.dart';

/// 积分账户
///
/// 对应《工程文档.md》§7.3 的 `credit_accounts` 表。整个 App 的变现方式只有一件事：
/// **卖积分**。所以这个类就是「用户的钱包」，首页右上角的胶囊、积分页的余额都读它。
///
/// ─────────────────────────────────────────────────────────
/// 【⚠️ available 为什么是算出来的，而不是一个字段】
///
/// 表里只有两个数：`balance`（总余额）和 `frozen`（冻结中）。
/// 但界面要显示的是**可用余额** —— 也就是「现在还能拿多少去下单」。
///
/// 这三个数的关系是：`available = balance − frozen`
///
/// 【为什么不把它也存成一个字段】
/// 因为一旦存下来，就有了两个必须永远保持同步的真身。
/// 后端加一个「赠送积分」的场景忘了更新其中一个，就会出现
/// 「余额显示 100，可用显示 80」这种对不上的数字，而且**没有任何报错**。
/// 现算则永远不可能不一致 —— 这是「派生数据不要存」这条规矩的一个具体例子。
///
/// 【顺带一个真实的坑】用户很容易把「有余额」和「能用」当成一回事。
/// 有任务在跑时，被冻结的那部分不能再用，所以余额 100、冻结 40 时，
/// 他只能再花 60。UI 上必须把「冻结中」单独显示出来，否则用户会觉得钱被吞了。
/// ─────────────────────────────────────────────────────────
class CreditAccount {
  const CreditAccount({
    required this.balance,
    required this.frozen,
    this.updatedAt,
  });

  /// 总余额（含冻结中）。
  final int balance;

  /// 冻结中：已经被进行中的任务预扣、还没结算的那部分。
  final int frozen;

  final DateTime? updatedAt;

  /// 可用余额 —— **现算**，见类注释。
  ///
  /// 【为什么不做成 `-` 运算符或工具函数】
  /// 它就是这个类自身的一个属性（「这个账户现在能用多少」），
  /// 挂在类上语义最准确，也保证了全项目只有一种算法。
  int get available => balance - frozen;

  /// 空账户，用于「还没拉到数据」时的占位。
  ///
  /// 【注意】UI 里**不要**拿它当「用户余额为 0」来显示 ——
  /// 那是在撒谎。要用 `CreditAccount?` 的 null 表示「还不知道」，
  /// 拉到了才显示数字。首页那个胶囊在没数据时显示「积分」两个字而不是「0 积分」，
  /// 就是为这个。
  static const CreditAccount empty = CreditAccount(balance: 0, frozen: 0);

  factory CreditAccount.fromJson(Map<String, dynamic> json) => CreditAccount(
        // 金额字段一律 requireInt：解析不出来就炸，绝不静默退化成 0。
        // 少显示一个 0 只是难看，按错误金额记账是事故。
        balance: json.requireInt(json['balance'], field: 'balance'),
        frozen: json.requireInt(json['frozen'], field: 'frozen'),
        updatedAt: json.asDateTimeOrNull(json['updated_at']),
      );

  @override
  String toString() =>
      'CreditAccount(balance: $balance, frozen: $frozen, available: $available)';
}

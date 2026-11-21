import '../../models/credit_ledger_entry.dart';
import '../../models/task.dart';
import '../../models/task_cost_estimate.dart';
import '../constants/task_status.dart';

/// 计费文案 —— **全项目唯一出处**
///
/// 对应《工程文档.md》§13.4。这个文件存在的唯一理由，是这条硬规则：
///
/// > **绝不在生成按钮下方显示一个确定的积分数字。**
///
/// ─────────────────────────────────────────────────────────
/// 【为什么这条规则这么严格】
///
/// 视频的最终时长由 provider 侧的 Agent 自主决定 —— 用户下单说「5 秒」，
/// 交回来可能是 5.2 秒，而计费按成片秒数走。所以下单那一刻**连后端都不知道**
/// 最终会扣多少。
///
/// 如果按钮下写「预计消耗 20 积分」，就必然出现「说好 20 却扣了 21」。
/// 用户对这个的容忍度极低 —— 这不是文案不好看的问题，是会引发投诉和退款的问题。
///
/// 所以只能有两种写法：
///   · 还没问到价 → **`计算中…`**（诚实地说不知道）
///   · 问到了价   → **区间 + 冻结额 + 多余退回的承诺**（把不确定性讲明白）
///
/// 【为什么必须集中在一个文件】
/// 这三句话要在**四个地方**出现（首页生成按钮下、图片生成页、视频生成页、参数胶囊），
/// 分散写迟早会漂移成四种说法。更要紧的是：只要有一处漏改成定值，
/// B7 那条「全 lib/ 不得出现『预计消耗』」的防回归测试就会失效 ——
/// 因为它只能扫字面量，扫不到拼接出来的东西。
/// ─────────────────────────────────────────────────────────
class CreditFormat {
  /// 私有构造：只装静态方法，不该被 new。
  CreditFormat._();

  /// 「还没问到价」。
  ///
  /// 【为什么用省略号而不是『--』或『加载中』】
  /// `--` 看起来像「零」或「出错」，`加载中` 又让人以为在转圈具体的东西。
  /// `计算中…` 准确表达了「我们在向后端问价，马上就有区间」。
  static const String calculating = '计算中…';

  /// 积分单位。所有涉及积分的句子都从这里取单位词，
  /// 免得出现「20 积分」和「20 分」两种写法。
  static const String unit = '积分';

  /// 区间文案，如 `20~25`。上下限相同时只显示一个数。
  static String costRange(TaskCostEstimate estimate) => estimate.isFixed
      ? '${estimate.minCredits}'
      : '${estimate.minCredits}~${estimate.maxCredits}';

  /// 「问价这件事本身失败了」。
  ///
  /// 【为什么不能退回 [calculating]】那会让用户看着「计算中…」永远转下去，
  /// 以为再等等就有数字 —— 实际上那个请求已经失败了，不会再回来。
  ///
  /// 【为什么也不能写一个数字或区间】§13.4 的那条禁令和「不知道」无关，
  /// 它禁止的是**确定性的数字**。而这里我们连区间都没有，
  /// 唯一诚实的说法就是「按实际消耗结算」—— 那本来也是真实的计费方式。
  static const String costUnavailable = '暂时拿不到报价 · 提交后按实际消耗结算';

  /// 生成按钮下方那句话。
  ///
  /// [estimate] 为 null 表示还没问到价 → 返回 [calculating]。
  ///
  /// 有话术模板：`本次冻结 X 积分 · 按成片时长结算，多余自动退回`
  ///
  /// 【这句话为什么要包含三件事】
  /// 「冻结」解释钱去哪了（不是扣走）、「按成片时长结算」解释为什么是个区间、
  /// 「多余自动退回」打消用户唯一的顾虑。少任何一句，用户都会来问。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【B6：图片为什么要单独一句话】
  ///
  /// 图片是**按张固定价**（§7.2：freeze 就等于结算额，Mock 里 min = max = freeze）。
  /// 这种时候「按成片时长结算，多余自动退回」是错的 ——
  /// 图片没有时长，而且根本不会有「多余」退回来。
  ///
  /// 一句和事实不符的承诺，比没有承诺更糟：用户会等着那笔退款。
  /// 所以 [TaskCostEstimate.isFixed] 时换一句话说 ——
  /// 「固定价、生成完直接结算」才是这件事的真实样子。
  /// ─────────────────────────────────────────────────────────
  static String generationHint(TaskCostEstimate? estimate) {
    if (estimate == null) return calculating;
    if (estimate.isFixed) {
      return '本次冻结 ${costRange(estimate)} $unit · 固定价，生成完直接结算';
    }
    return '本次冻结 ${costRange(estimate)} $unit · 按成片时长结算，多余自动退回';
  }

  /// 任务结束后，在详情里说明这笔实际花了多少。
  ///
  /// 【为什么和上面的 [generationHint] 分开】
  /// 上面那句是**下单前**说的（还没发生，只能说区间）；
  /// 这句是**结束后**说的（已经发生，必须给确定数）。两句话的时态和语气都不同，
  /// 硬塞进一个方法会变成一堆 if。
  static String settlementText(Task task) {
    return switch (task.status) {
      // 成功：说清实际扣了多少 + 退回了多少
      TaskStatus.succeeded => task.refundAmount > 0
          ? '本次消耗 ${task.chargedAmount} $unit，已退回 ${task.refundAmount} $unit'
          : '本次消耗 ${task.chargedAmount} $unit',

      // 失败/被拒/取消/过期：全额退回，要明确说出来
      TaskStatus.failed ||
      TaskStatus.rejected ||
      TaskStatus.canceled ||
      TaskStatus.expired =>
        '本次未消耗积分，已退回 ${task.freezeAmount} $unit',

      // 还在跑：退回多少还不知道，只能报冻结额
      TaskStatus.pending || TaskStatus.queued || TaskStatus.submitted =>
        '已冻结 ${task.freezeAmount} $unit',
    };
  }

  /// 流水条目的金额显示。
  ///
  /// 【这里有个容易做错的地方，值得写清楚】
  /// 只有 `settle` 才是真正把钱花掉。`freeze` **不减余额**——
  /// 它只是把「可用」搬到了「冻结」，总额没变。
  ///
  /// 所以流水列表里给 freeze 画一个红色的「−40」是**错的**：
  /// 用户会看到「冻结 −40」+「结算 −35」，以为自己被扣了 75。
  /// 冻结那行必须写成「冻结 40」，不带负号。
  static String ledgerAmountText(CreditLedgerEntry entry) {
    return switch (entry.kind) {
      CreditLedgerKind.grant => '+${entry.amount}',
      CreditLedgerKind.settle => '-${entry.amount}',
      CreditLedgerKind.refund => '+${entry.amount}',
      // 不带符号：余额没变，详见上面的注释
      CreditLedgerKind.freeze => '冻结 ${entry.amount}',
      CreditLedgerKind.adjust => '${entry.adjustmentDebit ? '-' : '+'}${entry.amount}',
    };
  }

  /// 余额的简短显示，如 `120`。
  ///
  /// 【为什么要单独一个方法而不直接 `'$balance'`】
  /// 因为 [CreditAccount] 拿不到时**不能显示成 0** —— 那是在撒谎
  /// （用户会以为积分被清零了）。这个方法负责把「不知道」和「真的是 0」区分开。
  static String balanceText(int? balance) =>
      balance == null ? calculating : '$balance';

  /// 带单位的余额，如 `120 积分`。拿不到时只显示「积分」。
  static String balanceWithUnit(int? balance) =>
      balance == null ? unit : '$balance $unit';
}

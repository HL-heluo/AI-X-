import '../models/chain_summary.dart';
import '../models/credit_ledger_entry.dart';
import '../models/paged.dart';

/// 积分流水（§7.3 / §12.1）
abstract interface class CreditRepository {
  /// 拉取积分流水，按时间倒序，分页。
  ///
  /// 【关于 [page] 从 1 开始】这是**接口约定**，不是实现细节。
  /// 传 0 的话用户会看到「第一页是空的，第二页才有东西」。
  /// 定义在 `Paged.page` 的注释里，这里再强调一次是因为它是跨层契约。
  Future<Paged<CreditLedgerEntry>> fetchLedger({
    int page = 1,
    int pageSize = 20,
  });

  /// 影子链凭证（方案 B）：钱包地址、合约地址、链上余额、最近上链记录。
  ///
  /// 环境没开链上映射时返回 `enabled=false` 的摘要，不是错误。
  Future<ChainSummary> fetchChainSummary();

  // 【这里为什么没有充值】
  // 因为 v1 **不接支付**（§7.6 的充值档位明确标注「此处为 v3 预留」）。
  // 谁要是往这里加一个 `purchaseCredits()`，就是把 v3 的功能提前做了，
  // 而支付通道的手续费、对账、退款流程一个都还没设计。
  // 当前积分只能来自：注册赠送、管理员发放（服务端脚本）。
}

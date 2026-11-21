import '../core/json_utils.dart';

/// 一条链上影子操作（对应后端 `chain_ops`）。
class ChainOp {
  const ChainOp({
    required this.id,
    required this.kind,
    required this.amount,
    required this.status,
    required this.ref,
    this.txHash,
    this.createdAt,
  });

  final int id;

  /// `mint`（发放/赠送）或 `consume`（消耗）。
  final String kind;
  final int amount;
  final String status;
  final String ref;
  final String? txHash;
  final String? createdAt;

  String get kindLabel => switch (kind) {
        'mint' => '发放',
        'consume' => '消耗',
        _ => kind,
      };

  String get statusLabel => switch (status) {
    'done' => '已确认',
    'submitted' => '待确认',
    'failed' => '同步失败',
    'superseded' => '已归档',
    _ => '待同步',
  };

  factory ChainOp.fromJson(Map<String, dynamic> json) {
    return ChainOp(
      id: json.requireInt(json['id'], field: 'recent_ops[].id'),
      kind: json.asStringOrNull(json['kind']) ?? '',
      amount: json.requireInt(json['amount'], field: 'recent_ops[].amount'),
      status: json.asStringOrNull(json['status']) ?? '',
      ref: json.asStringOrNull(json['ref']) ?? '',
      txHash: json.asStringOrNull(json['tx_hash']),
      createdAt: json.asStringOrNull(json['created_at']),
    );
  }
}

/// 影子链凭证：`GET /credits/chain`。
///
/// 【这一屏给用户的价值】
/// 平台说「你的积分在链上」时，用户不需要信这句话 —— 他拿 [address] 和
/// [contract] 自己去链上查 `balanceOf` 就能核对；[recentOps] 里的
/// [ChainOp.txHash] 是每笔消耗的真实交易哈希。
class ChainSummary {
  const ChainSummary({
    required this.enabled,
    required this.ledgerBalance,
    this.chainId,
    this.availableBalance,
    this.syncStatus,
    this.contract,
    this.address,
    this.onChainBalance,
    this.totalSupply,
    this.recentOps = const [],
    this.error,
  });

  final bool enabled;
  final int ledgerBalance;
  final int? chainId;
  final int? availableBalance;
  final String? syncStatus;
  final String? contract;
  final String? address;
  final int? onChainBalance;
  final int? totalSupply;
  final List<ChainOp> recentOps;
  final String? error;

  /// 链上余额与平台账本一致（差 0）才算对账成功。
  bool get reconciled => syncStatus == 'synced' ||
      (syncStatus == null && enabled && onChainBalance == ledgerBalance);

  String get statusLabel => switch (syncStatus) {
    'unavailable' => '测试链离线',
    'failed' => '同步失败',
    'paused' => '已暂停',
    'setup_required' => '待初始化',
    'out_of_sync' => '待对账',
    _ => reconciled ? '已对账' : '同步中',
  };

  factory ChainSummary.fromJson(Map<String, dynamic> json) {
    final ops = (json['recent_ops'] as List<dynamic>? ?? const [])
        .map((e) => ChainOp.fromJson(json.asJsonMap(e, field: 'recent_ops[]')))
        .toList(growable: false);
    return ChainSummary(
      enabled: json.boolOr(json['enabled'], false),
      ledgerBalance: json.requireInt(json['ledger_balance'], field: 'ledger_balance'),
      chainId: json.asIntOrNull(json['chain_id'], field: 'chain_id'),
      availableBalance: json.asIntOrNull(json['available_balance'], field: 'available_balance'),
      syncStatus: json.asStringOrNull(json['sync_status']),
      contract: json.asStringOrNull(json['contract']),
      address: json.asStringOrNull(json['address']),
      onChainBalance: json.asIntOrNull(json['on_chain_balance'], field: 'on_chain_balance'),
      totalSupply: json.asIntOrNull(json['total_supply'], field: 'total_supply'),
      recentOps: ops,
      error: json.asStringOrNull(json['error']),
    );
  }
}

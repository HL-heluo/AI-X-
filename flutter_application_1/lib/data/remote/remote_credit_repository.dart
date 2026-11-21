import '../../core/constants/api_paths.dart';
import '../../core/network/api_client.dart';
import '../../models/chain_summary.dart';
import '../../models/credit_ledger_entry.dart';
import '../../models/paged.dart';
import '../../repositories/credit_repository.dart';

/// [CreditRepository] 的真实实现
class RemoteCreditRepository implements CreditRepository {
  RemoteCreditRepository(this._client);

  final ApiClient _client;

  @override
  Future<Paged<CreditLedgerEntry>> fetchLedger({
    int page = 1,
    int pageSize = 20,
  }) async {
    final json = await _client.get(
      ApiPaths.creditLedger,
      query: <String, dynamic>{
        // 【参数名照抄契约】下划线风格 `page_size`，不是 `pageSize`
        'page': page,
        'page_size': pageSize,
      },
    );
    return Paged.fromJson(json, CreditLedgerEntry.fromJson);
  }

  @override
  Future<ChainSummary> fetchChainSummary() async {
    final json = await _client.get(ApiPaths.creditChain);
    return ChainSummary.fromJson(json);
  }
}

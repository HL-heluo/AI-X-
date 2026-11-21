import '../../core/constants/api_paths.dart';
import '../../core/network/api_client.dart';
import '../../core/network/api_exception.dart';
import '../../models/task.dart';
import '../../models/task_cost_estimate.dart';
import '../../repositories/generation_repository.dart';

/// [GenerationRepository] 的真实实现
class RemoteGenerationRepository implements GenerationRepository {
  RemoteGenerationRepository(this._client);

  final ApiClient _client;

  @override
  Future<TaskCostEstimate> estimateCost({
    required TaskKind kind,
    int? durationSec,
    String? ratio,
  }) async {
    final json = await _client.get(
      ApiPaths.generationCost,
      query: <String, dynamic>{
        // 【这三个查询参数是本项目拍板冻结的】§12.1 只写了返回值 `{min,max,freeze}`，
        // 没规定传什么。详见 api_paths.dart 里 generationCost 的注释。
        'kind': kind.wire,
        'duration': ?durationSec,
        'ratio': ?ratio,
      },
    );
    return TaskCostEstimate.fromJson(json);
  }

  @override
  Future<Task> submitImage({
    required String prompt,
    required String idempotencyKey,
    String? aspectRatio,
  }) {
    return _submitOrReuse(() => _client.post(
          ApiPaths.generateImage,
          body: <String, dynamic>{
            'prompt': prompt,
            'idempotency_key': idempotencyKey,
            // 【图片用 aspect_ratio，视频用 ratio】这不是笔误 ——
            // §12.1 的表格里两个接口的字段名就是不一样。
            // 对外照抄契约，对内统一归一成 TaskParams.ratio（见 models/task.dart）。
            'aspect_ratio': ?aspectRatio,
          },
        ));
  }

  @override
  Future<Task> submitVideo({
    required String prompt,
    required String sourceAssetId,
    required String idempotencyKey,
    int durationSec = 5,
    String? ratio,
  }) {
    return _submitOrReuse(() => _client.post(
          ApiPaths.generateVideo,
          body: <String, dynamic>{
            'prompt': prompt,
            'source_asset_id': sourceAssetId,
            'duration': durationSec,
            'idempotency_key': idempotencyKey,
            'ratio': ?ratio,
          },
        ));
  }

  /// 提交，并把「幂等键重复」当成**成功**处理。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【为什么这里要专门接住一个「错误」】
  ///
  /// §12.3 里 `DUPLICATE_REQUEST` 的「客户端行为」一栏写的是
  /// **「静默复用已存在的任务」** —— 注意「静默」两个字：
  /// 用户双击了生成按钮，正确的表现是**什么都没发生**，
  /// 而不是弹一个红框说「重复请求」。
  ///
  /// 所以这一层必须把 409 翻译成「返回那个已存在的任务」。
  /// 如果不接住它，错误会一路冒到 UI：
  /// * 用户的感受是「我点了一下生成，它报错了」—— 但其实任务已经在跑了；
  /// * 更糟的是，用户会再点一次，而如果那次换了新的幂等键，就真的重复扣钱了。
  ///
  /// 【为什么是 catch 而不是在通信层把 409 抹平成 200】
  /// 因为 409 是**服务端在说实话**（确实没有新任务产生），
  /// 把它抹平会让通信层变得不诚实 —— 排查日志时你会看到一片 200，
  /// 完全看不出发生过重复提交。让它以错误的形式传到这一层，
  /// 由**最懂业务语义的地方**决定怎么解释，是更清楚的分工。
  /// ─────────────────────────────────────────────────────────
  Future<Task> _submitOrReuse(
    Future<Map<String, dynamic>> Function() send,
  ) async {
    try {
      return Task.fromJson(await send());
    } on AppException catch (e) {
      if (!e.isDuplicateRequest) rethrow;

      final taskJson = e.body?['task'];
      if (taskJson == null) {
        // 【契约没兑现时怎么办】§12.3 说「复用已存在的任务」，
        // 那就必须在错误响应里把任务带回来，否则客户端无从复用。
        // 后端没带的话，我们只能把错误原样抛出去 ——
        // 这比随便造一个空任务好得多（那样用户会看到一个 id 为空的假任务）。
        rethrow;
      }
      return Task.fromJson((taskJson as Map).cast<String, dynamic>());
    }
  }
}

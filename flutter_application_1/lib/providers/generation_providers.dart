import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/task.dart';
import '../models/task_cost_estimate.dart';
import 'app_providers.dart';
import 'asset_providers.dart';
import 'me_providers.dart';
import 'task_providers.dart';

/// 一次问价的参数
///
/// 【为什么用 record 而不是自己写一个带 == 的类】
/// 因为 family 的 key 必须支持值相等（不然每次重建都是一个新的 provider
/// 实例，缓存永远命中不了）。Dart 的 record **天生**就有结构化的
/// `==` / `hashCode`，手写一个类则要记得实现这两个方法 ——
/// 忘了的话表现为「每次 build 都重新发一次请求」，而且不报错。
/// 让语言来保证不会忘。
typedef CostQuery = ({TaskKind kind, int? durationSec, String? ratio});

/// 下单前问价（`GET /generation/cost`）
///
/// ─────────────────────────────────────────────────────────
/// 【这个 provider 存在的唯一理由是 §13.4】
///
/// §13.4 禁止在生成按钮下方显示一个确定的积分数字 ——
/// 因为视频的成片时长由 provider 侧的 Agent 自主决定，下单那一刻
/// **连后端都不知道**最终会扣多少。而正确的说法（区间 + 冻结额 +
/// 多余退回的承诺）**只有服务端算得出来**，定价表在后端。
///
/// 所以在拿到这个结果之前，界面只能显示「计算中…」。这个
/// 「还没有 → 有了」的两态，正是 `CreditFormat.generationHint` 直接支持的：
/// 传 null 得到「计算中…」，传估值得到那句完整的承诺。
///
/// 【为什么是 autoDispose】参数一变就是一个新的 provider 实例。
/// 不 autoDispose 的话，用户在图片/视频之间来回切几次就攒下一串
/// 永远不会再看的报价缓存。
/// ─────────────────────────────────────────────────────────
final costEstimateProvider =
    FutureProvider.autoDispose.family<TaskCostEstimate, CostQuery>(
  (ref, query) async {
    // 没登录就没报价可言。这里断掉比让服务端回 401 干净 ——
    // 而且错误信息也更有意义（见 `MeProfileNotifier.build` 里同样的处理）。
    final token = ref.watch(authTokenProvider);
    if (token == null) throw AppException.unauthorized();

    return ref.read(generationRepositoryProvider).estimateCost(
          kind: query.kind,
          durationSec: query.durationSec,
          ratio: query.ratio,
        );
  },
  retry: noAutoRetry,
);

/// 提交生成的入口
///
/// ─────────────────────────────────────────────────────────
/// 【它为什么不是一个 Notifier】
///
/// 因为提交这件事**没有需要保留的状态**。页面上的「按钮在转圈」「红色的
/// 错误提示」是**表单状态**，它属于那个 widget，而且**必须随着页面消失**——
/// 一个已经提交出去的任务，它的真相在服务端，不在这份界面状态里
/// （§8.4）。把提交中的标志放进一个活过页面的 Notifier，只会制造
/// 「上次提交失败的红字，下次打开还挂在那里」这种怪事。
///
/// 那它为什么又不能干脆不要、让页面直接调 repository？
/// 因为提交成功后要做**三件事**：刷新进行中列表、让余额重新拉、
/// 让作品列表重新拉。这三件事要是靠每个页面自己记得做，
/// 迟早有一个页面漏掉 —— 表现为「提交完了，首页顶上的余额还是旧的」。
/// 收在这里，就只有一份。
/// ─────────────────────────────────────────────────────────
class GenerationSubmitter {
  GenerationSubmitter(this._ref);

  final Ref _ref;

  /// 提交文生图。
  ///
  /// [idempotencyKey] 由**调用方**在「用户按下生成按钮」的那一刻生成一次，
  /// 并在重试时复用。为什么不能在这里自动生成，见
  /// `GenerationRepository.submitImage` 上那段长注释 ——
  /// 一句话：自动生成会让防连点双扣的那道闸门彻底失效。
  Future<Task> submitImage({
    required String prompt,
    required String idempotencyKey,
    String? aspectRatio,
  }) async {
    final task = await _ref.read(generationRepositoryProvider).submitImage(
          prompt: prompt,
          idempotencyKey: idempotencyKey,
          aspectRatio: aspectRatio,
        );
    _afterSubmit();
    return task;
  }

  /// 提交图生视频。
  Future<Task> submitVideo({
    required String prompt,
    required String sourceAssetId,
    required String idempotencyKey,
    required int durationSec,
    String? ratio,
  }) async {
    final task = await _ref.read(generationRepositoryProvider).submitVideo(
          prompt: prompt,
          sourceAssetId: sourceAssetId,
          idempotencyKey: idempotencyKey,
          durationSec: durationSec,
          ratio: ratio,
        );
    _afterSubmit();
    return task;
  }

  /// 提交成功后让三份数据作废。
  ///
  /// 【为什么是作废重拉而不是本地插一条】因为冻结已经真的发生了 ——
  /// 余额、冻结额、进行中列表**都在服务端变了**。本地插一条假的任务，
  /// 就等于把任务状态存进了 App 内存，正是 §8.4 禁止的那件事。
  /// 重拉一次很便宜（就三个请求），而且拿到的必定是服务端的真相。
  void _afterSubmit() {
    _ref.invalidate(activeTasksProvider);
    _ref.invalidate(userAssetsProvider);
    // 余额：提交会**冻结**积分，右上角的「可用积分」立刻就该变小
    _ref.invalidate(meProfileProvider);
  }
}

final generationSubmitterProvider = Provider<GenerationSubmitter>(
  (ref) => GenerationSubmitter(ref),
);

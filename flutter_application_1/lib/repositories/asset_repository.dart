import '../models/asset.dart';
import '../models/paged.dart';
import '../models/video_evidence.dart';

/// 作品与参考图（§12.1 / §11.2）
abstract interface class AssetRepository {
  /// 拉取作品列表（分页，含缩略图）。
  ///
  /// 【为什么列表里必须带缩略图】一屏要摆九个视频。
  /// 每个都直接加载视频文件当封面的话，流量和内存都会炸。
  /// 后端会为每个视频额外落一张 `thumbnail` 资产（见 FakeApiClient 的
  /// `_createAssetsFor`），列表读它，点开才读视频。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【⚠️ 关于 [taskId]：这是本项目拍板冻结的一个契约补充】
  ///
  /// §12.1 的 `GET /assets` 只写了分页参数，但结果页和任务详情都需要
  /// 「**这个任务产出了什么**」—— 而产物在 `assets` 表里是独立的一行，
  /// 只能靠 `task_id` 关联。
  ///
  /// 不在客户端拉全表再筛的理由很简单：作品会越攒越多。现在几条的时候筛一下
  /// 没事，等用户有 200 张图时，为了看一个结果要下 200 条记录。
  ///
  /// 所以按最自然的方式冻结成查询参数 `GET /assets?task_id=<id>`，
  /// 和 `GET /generation/cost` 的 kind/duration/ratio 是同一类处理
  /// （见 `api_paths.dart` 里 `generationCost` 的注释）。
  /// **Mock 先按这个实现，接真后端前需与后端确认一次。**
  /// ─────────────────────────────────────────────────────────
  Future<Paged<Asset>> fetchAssets({
    int page = 1,
    int pageSize = 20,
    String? taskId,
    bool certifiedOnly = false,
  });

  Future<VideoEvidence> fetchEvidence(String assetId);

  /// 删除作品。
  ///
  /// 【注意它删的是「资产」不是「任务」】任务记录要留着 ——
  /// 它是积分流水的凭据。用户把视频删了，但「这笔花了 24 积分」的记录
  /// 必须还在，否则账就没法对。
  Future<void> delete(String id);

  /// 上传参考图，返回它的 `asset_id`。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【⚠️ 这里有一个 §12.1 没说清的地方】
  ///
  /// 文档的接口表里，`POST /uploads/image` 写的是「返回**公网 URL**」，
  /// 但 `POST /generation/video` 要的参数却是 `source_asset_id` ——
  /// 一个说要给 URL，一个说要给 id。
  ///
  /// 本项目的处理：让服务端**两个都给**，这个方法只返回 id
  /// （因为提交时要用的是 id），需要预览时用 `public_url`。
  /// **接真后端前要与后端确认到底以哪个为准。**
  ///
  /// 【为什么收 bytes 不收文件路径】
  /// 这份代码要同时跑 Android 和 Web，而 Web 上**没有文件路径**，
  /// 只有内存里的字节。收 bytes 两边都能用。
  /// ─────────────────────────────────────────────────────────
  Future<String> uploadImage({
    required List<int> bytes,
    required String filename,
    String? mimeType,
  });
}

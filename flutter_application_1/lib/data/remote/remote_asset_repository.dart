import '../../core/constants/api_paths.dart';
import '../../core/network/api_client.dart';
import '../../models/asset.dart';
import '../../models/paged.dart';
import '../../models/video_evidence.dart';
import '../../repositories/asset_repository.dart';

/// [AssetRepository] 的真实实现
class RemoteAssetRepository implements AssetRepository {
  RemoteAssetRepository(this._client);

  final ApiClient _client;

  @override
  Future<Paged<Asset>> fetchAssets({
    int page = 1,
    int pageSize = 20,
    String? taskId,
    bool certifiedOnly = false,
  }) async {
    final json = await _client.get(
      ApiPaths.assets,
      query: <String, dynamic>{
        'page': page,
        'page_size': pageSize,
        // 【注意 `?taskId` 这个写法】Dart 3.10 的 null-aware element：
        // 值为 null 时**整个键都不出现**，而不是发一个 `task_id=`。
        // 后者在有些后端会被解析成空字符串筛选，于是「不筛」变成「筛空」，
        // 列表永远是空的 —— 那种 bug 只在真后端上才暴露。
        // （Mock 那边按 `query?['task_id']` 读，两种写法都能接住。）
        'task_id': ?taskId,
        if (certifiedOnly) 'certified_only': true,
      },
    );
    return Paged.fromJson(json, Asset.fromJson);
  }

  @override
  Future<VideoEvidence> fetchEvidence(String assetId) async {
    final json = await _client.get(ApiPaths.assetEvidence(assetId));
    return VideoEvidence.fromJson(json);
  }

  @override
  Future<void> delete(String id) async {
    await _client.delete(ApiPaths.assetDetail(id));
  }

  @override
  Future<String> uploadImage({
    required List<int> bytes,
    required String filename,
    String? mimeType,
  }) async {
    final json = await _client.upload(
      ApiPaths.uploadImage,
      bytes: bytes,
      filename: filename,
      mimeType: mimeType,
    );
    // 【⚠️ 契约缺口】§12.1 说这个接口「返回公网 URL」，
    // 但提交视频时要用的是 `source_asset_id` → 所以这里取 id。
    // 本项目让服务端两个都给（见 FakeApiClient.upload 的注释），
    // **接真后端前要与后端确认**。取不到 id 就直接炸 ——
    // 返回空字符串的话，用户会看到一个「提交成功但服务端说参考图不存在」的怪错。
    final id = json['asset_id'];
    if (id == null) {
      throw StateError(
        '上传接口没有返回 asset_id（只返回了 ${json.keys.join(", ")}）。'
        '§12.1 只写了「返回公网 URL」，但提交视频需要的是 asset_id —— '
        '这条契约必须和后端确认清楚。',
      );
    }
    return '$id';
  }
}

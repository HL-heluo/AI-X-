/// 通信层的唯一抽象点
///
/// ─────────────────────────────────────────────────────────
/// 【这个接口是整个 App 最重要的一个接缝】
///
/// 它只有四个方法，但**「用 Mock 还是用真后端」这一个决定就发生在实现它的地方**。
/// 上层（repository、provider、页面）全部只认这个接口，不知道下面是内存还是网络。
///
/// 所以切后端时**只改一个 provider**（`app_providers.dart` 里的 `apiClientProvider`），
/// 业务代码一行不动。反过来说：如果接真后端时发现要改别的地方，
/// 说明这里漏了抽象，该回头修接口而不是改调用方。
///
/// 【为什么 Mock 实现的是这一层，而不是 Repository 层】
/// 如果 Mock 掉 Repository，那么 DTO 解析、错误码映射、分页拼装、
/// 幂等处理这些**最容易写错的部分**就全都绕过去了，
/// Mock 阶段一路绿灯，接真后端当天集中爆雷。
/// 让 FakeApiClient 老老实实返回「和文档逐字一致的 JSON」，
/// 就能逼着上面那几层走真实代码路径。
/// ─────────────────────────────────────────────────────────
///
/// **实现约定**（两个实现都必须守）：
/// * 成功：返回解码后的 JSON 对象。响应体是数组的实现应包成 `{items: [...]}`。
/// * 失败：抛 [AppException]。**绝对不要**把 HTTP 错误码当返回值往外传 ——
///   如果让调用方自己判断状态码，每个 repository 都要写一遍
///   「401 就登出、429 就提示」，迟早各处不一致。
/// * 4xx/5xx 里带业务错误码的，必须映射成 `AppException.code`（见 §12.3）。
/// * 还没实现的后端会在 [AppException.code] 为 null 时给出可读的 message。
abstract interface class ApiClient {
  /// GET。查询参数放 [query]，值为 null 的项会被忽略。
  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
  });

  /// POST。[body] 会以 JSON 编码发送。
  ///
  /// 【为什么 body 是 `Object?` 而不是 `Map`】因为有些接口的参数就是一个数组，
  /// 用 `Map` 会逼着调用方包一层没意义的壳。
  Future<Map<String, dynamic>> post(String path, {Object? body});

  /// DELETE。
  Future<Map<String, dynamic>> delete(String path);

  /// 上传文件（目前只有参考图走它，见 §12.1 `/uploads/image`）。
  ///
  /// 【为什么收 bytes 而不是文件路径】
  /// 因为这份代码要同时跑在 Android 和 Web 上，而 Web 上**没有文件路径**这个概念，
  /// 只有内存里的字节。收 `List<int> bytes` 两边都能用；
  /// 收 `String filePath` 的话，Web 端就得为了这个接口单独写一套。
  /// 调用方负责把选中的图读成字节。
  ///
  /// 【[filename] 为什么必填】后端要靠它拿扩展名来判断格式，
  /// 而且对象存储里的 key 也需要一个像样的名字。
  Future<Map<String, dynamic>> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    String? mimeType,
  });
}

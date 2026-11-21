import 'dart:convert';

import 'package:dio/dio.dart';

import 'api_client.dart';
import 'api_exception.dart';

/// [ApiClient] 的真实实现（走 dio）
///
/// ─────────────────────────────────────────────────────────
/// 【本轮的状态：写完了，但一次都没跑过】
///
/// 后端还不存在，所以这个类**没有被任何测试或真实请求验证过**。
/// 它不是「骨架」—— 骨架意味着故意留空；它的每一行都是我按
/// dio 5.x 的 API 认真写的，只是**没有对手可以打**。
///
/// 把它写出来的价值在于：`apiClientProvider` 里那个三元判断的两条分支
/// 都是完整代码，而不是 `throw UnimplementedError()`。
/// 接后端那天要做的事因此缩小成「确认 baseUrl 和鉴权头」，
/// 而不是「从零写一个网络层」。
///
/// **接后端时第一个该怀疑的地方**：下面的 `_decode` 和 `_toException`
/// 对响应体形状做了假设（详见各自注释）。真实后端一旦不按这个形状返回，
/// 错一定在这里，不在页面。**先修这两个方法，不要改调用方。**
/// ─────────────────────────────────────────────────────────
class DioApiClient implements ApiClient {
  DioApiClient({
    required this.baseUrl,
    this.tokenProvider,
    Dio? dio,
  }) : _dio = dio ?? Dio() {
    _dio.options
      ..baseUrl = baseUrl
      // 【超时必须有】dio 默认不超时。没有超时的话，
      // 网络一断，请求会**永远挂着**，用户看到的是一辈子转不完的圈，
      // 而 catch 块永远等不到异常。
      ..connectTimeout = const Duration(seconds: 10)
      ..receiveTimeout = const Duration(seconds: 30)
      ..sendTimeout = const Duration(seconds: 60) // 上传参考图可能慢
      // 【不要设成 throw】非 2xx 让 dio 抛异常没错，
      // 但我们要自己决定怎么解释它（见 _toException），
      // 所以先放行、拿到 Response 自己判断。
      ..validateStatus = (_) => true;

    // 【鉴权头在这里统一加】不能让每个 repository 自己拼 `Authorization` ——
    // 那样 13 个接口就有 13 处可能写错（少个空格、写成 `Bearer:`），
    // 而且登录态变化时要改 13 个地方。
    _dio.interceptors.add(
      InterceptorsWrapper(
        onRequest: (options, handler) {
          final token = tokenProvider?.call();
          if (token != null && token.isNotEmpty) {
            options.headers['Authorization'] = 'Bearer $token';
          }
          handler.next(options);
        },
      ),
    );
  }

  final String baseUrl;

  /// 取当前 token。返回 null 表示未登录（则该请求不带鉴权头）。
  ///
  /// 【为什么是一个函数，而不是一个 String 字段】
  /// 因为 token 会变（登录、登出、刷新）。如果在构造时把 token 定死，
  /// 那 `DioApiClient` 的生命周期就绑死在某一时刻的登录态上了 ——
  /// 用户重新登录后必须重建整个 client，这是很容易漏掉的一步。
  /// 传函数则每次都读最新的。
  ///
  /// B4 接上 TokenStore 后，这里传的就该是 `() => tokenStore.token`。
  final String? Function()? tokenProvider;

  final Dio _dio;

  @override
  Future<Map<String, dynamic>> get(
    String path, {
    Map<String, dynamic>? query,
  }) async {
    // 【null 项别发出去】`?page=null` 这种东西会让后端 400，
    // 而调用方写 `if (x != null) 'k': x` 又啰嗦，所以在这里统一过滤。
    final q = query?..removeWhere((_, v) => v == null);
    return _send(() => _dio.get<dynamic>(path, queryParameters: q));
  }

  @override
  Future<Map<String, dynamic>> post(String path, {Object? body}) {
    return _send(() => _dio.post<dynamic>(path, data: body));
  }

  @override
  Future<Map<String, dynamic>> delete(String path) {
    return _send(() => _dio.delete<dynamic>(path));
  }

  @override
  Future<Map<String, dynamic>> upload(
    String path, {
    required List<int> bytes,
    required String filename,
    String? mimeType,
  }) {
    return _send(() async {
      final form = FormData.fromMap(<String, dynamic>{
        // 【字段名 `file`】§12.1 没规定。等后端定了要改这里，
        // 也是全项目唯一需要改的地方。
        'file': MultipartFile.fromBytes(
          bytes,
          filename: filename,
          contentType: mimeType == null ? null : DioMediaType.parse(mimeType),
        ),
      });
      return _dio.post<dynamic>(path, data: form);
    });
  }

  /// 统一发请求 + 解包 + 错误映射。
  ///
  /// 所有方法都从这里过，是为了保证**「失败一律抛 [AppException]」这条约定
  /// 只有一个实现点**。`api_client.dart` 的接口注释专门写了这一条：
  /// 不能让调用方见到 HTTP 状态码。分散在四个方法里各写一遍映射，
  /// 迟早有一处漏掉，那一处就会把 DioException 冒到 UI 上。
  Future<Map<String, dynamic>> _send(
    Future<Response<dynamic>> Function() request,
  ) async {
    final Response<dynamic> res;
    try {
      res = await request();
    } on DioException catch (e) {
      // 【只有「没拿到响应」才是网络问题】拿到响应但状态码不对的，
      // 已经走下面的分支了 —— 那种情况下把 message 归成「网络异常」
      // 会把「积分不足」这种业务问题伪装成网络问题，害人排查半天。
      throw AppException.network(e.message ?? '网络请求失败');
    }

    final status = res.statusCode ?? 0;
    if (status < 200 || status >= 300) {
      throw _toException(status, res.data);
    }
    return _decode(res.data);
  }

  /// 把响应体解成 `Map`。
  ///
  /// 【形状假设 —— 接后端时第一个要核对的地方】
  /// §12.1 的表格只写了「返回 `{token}`」「返回 `{min,max,freeze}`」，
  /// **没说外面有没有包一层信封**（比如 `{code:0, data:{...}}`）。
  /// 本项目按**无信封**实现：响应体就是那个对象本身。
  /// 如果后端其实有信封，改这里一处即可 —— 这正是把解码收在这里的原因。
  ///
  /// 【数组怎么办】接口约定（见 `api_client.dart`）是数组一律包成 `{items:[...]}`。
  /// 这样调用方永远拿到 Map，不用到处 `if (body is List)`。
  Map<String, dynamic> _decode(dynamic data) {
    if (data == null) return <String, dynamic>{};
    if (data is Map) return data.cast<String, dynamic>();
    if (data is List) return <String, dynamic>{'items': data};
    if (data is String && data.isNotEmpty) {
      // 【后端有时会以 text/plain 返回 JSON】dio 不会自动解，要自己来。
      final decoded = jsonDecode(data);
      if (decoded is Map) return decoded.cast<String, dynamic>();
      if (decoded is List) return <String, dynamic>{'items': decoded};
    }
    throw AppException.parse('响应不是 JSON 对象：${data.runtimeType}');
  }

  /// 非 2xx → [AppException]。
  ///
  /// 【错误码从哪读】§12.3 定义了 8 个业务错误码（`INSUFFICIENT_CREDITS` 等），
  /// 但**没规定它放在响应体的哪个字段**。这里按 `code` 读，
  /// 依次退到 `error.code`（兼容 JSON:API 风格的嵌套）。
  /// 与 `_decode` 同理：形状假设集中在这里，接后端时只改这一处。
  AppException _toException(int status, dynamic data) {
    // 【401 单独走一条】因为它不是「业务错误码」而是一种登录态信号，
    // §12.3 根本没给它编错误码。走 fromResponse 的话 code 会是 null 但
    // message 会变成一句开发味很重的兜底文案；走 unauthorized() 才能
    // 保证「401 一定是这个形状」，让上层可以放心用 isUnauthorized。
    if (status == AppException.unauthorizedStatus) {
      return AppException.unauthorized();
    }

    Map<String, dynamic>? body;
    if (data is Map) {
      body = data.cast<String, dynamic>();
    } else if (data is String && data.isNotEmpty) {
      // 【解析失败别让它盖住真正的问题】后端返回一坨 HTML 错误页时，
      // jsonDecode 会抛 —— 但那是「错误响应长得不像 JSON」，
      // 不能因此把「422 内容被拒」这个真正的业务信息丢掉。
      try {
        final decoded = jsonDecode(data);
        if (decoded is Map) body = decoded.cast<String, dynamic>();
      } on FormatException {
        body = null;
      }
    }

    final errorObj = body?['error'];
    final errorMap = errorObj is Map ? errorObj.cast<String, dynamic>() : null;

    final codeWire = body?['code'] ??
        errorMap?['code'] ??
        (errorObj is String ? errorObj : null);

    final message = body?['message'] ??
        errorMap?['message'] ??
        errorMap?['detail'] ??
        // 【兜底文案要说清是兜底】不要编一个像模像样的中文，
        // 那会让人以为是后端返回的。
        '服务端返回 HTTP $status，且响应体里没有 message 字段';

    return AppException.fromResponse(
      httpStatus: status,
      codeWire: codeWire?.toString(),
      message: message.toString(),
      body: body,
    );
  }
}

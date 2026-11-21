import '../../core/constants/api_paths.dart';
import '../../core/network/api_client.dart';
import '../../models/auth_session.dart';
import '../../repositories/auth_repository.dart';

/// [AuthRepository] 的真实实现
///
/// 【为什么它这么薄】因为该在别处做的事都已经在别处做了：
/// HTTP 细节在 [ApiClient] 里，JSON 解析在 `AuthSession.fromJson` 里，
/// 身份校验在服务端。这一层剩下的工作就是**把业务语义翻译成一次请求**。
///
/// 薄是好事 —— 它意味着没有第三处地方需要知道「注册要用哪个路径」。
class RemoteAuthRepository implements AuthRepository {
  RemoteAuthRepository(this._client);

  final ApiClient _client;

  @override
  Future<AuthSession> register({
    required String inviteCode,
    required String username,
    required String password,
  }) async {
    final json = await _client.post(
      ApiPaths.register,
      body: <String, dynamic>{
        // 【参数名照抄 §12.1】`invite_code` 是下划线风格，别顺手写成驼峰 ——
        // 发送出去的是**契约**，不是 Dart 标识符，§2 的术语锁定管不到这里。
        'invite_code': inviteCode,
        'username': username,
        'password': password,
      },
    );
    return AuthSession.fromJson(json);
  }

  @override
  Future<AuthSession> login({
    required String username,
    required String password,
  }) async {
    final json = await _client.post(
      ApiPaths.login,
      body: <String, dynamic>{
        'username': username,
        'password': password,
      },
    );
    return AuthSession.fromJson(json);
  }
}

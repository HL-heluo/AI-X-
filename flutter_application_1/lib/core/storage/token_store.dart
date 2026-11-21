import 'package:flutter_secure_storage/flutter_secure_storage.dart';

/// ─────────────────────────────────────────────────────────
/// Token 的持久化接缝
///
/// 【为什么只存 token，不存整个登录态】
/// 因为「存下来的用户信息」一定会过期，而**过期的那一刻没人知道**。
/// 存了积分余额，用户在别处花掉积分后，这个 App 冷启动显示的
/// 还是上次的旧数，而且看起来像真的。所以这里只存 token，
/// 其余一切（用户、积分、任务）每次启动都重新拉。
///
/// 这和 §8.4「任务状态只存在于服务端」是同一条纪律的延伸：
/// **App 里不保存任何「服务端真相」的快照。**
///
/// 【为什么是接口】
/// 因为 Web 和移动端的持久化能力差着一整个量级，而且**测试不能碰真实密钥库**
/// （CI 上没有，Android 上还可能有各种机型问题）。有了接口，
/// 测试注入内存实现，一行代码都不用改业务。
/// ─────────────────────────────────────────────────────────
abstract interface class TokenStore {
  /// 读 token。没有（或已被清）返回 null。
  ///
  /// 【为什么用 null 表示「没登录」，而不是空字符串】
  /// 空字符串是个合法的可能值（后端理论上可能返回），
  /// 用它兼任「无」会让 `token.isEmpty` 这种判断散落各处。
  Future<String?> read();

  /// 写入（登录/注册成功后）。
  Future<void> write(String token);

  /// 清除（登出，或发现 token 已失效时）。
  ///
  /// 【为什么登出不需要请求服务端】见 `AuthRepository` 的注释：
  /// JWT 是无状态的，「登出」在客户端就是把这行删掉。服务端没有吊销列表，
  /// 造一个 `/auth/logout` 只会让人误以为 token 真的作废了。
  Future<void> clear();
}

/// 真实实现：写进系统密钥库 / Web 的加密存储
///
/// 【平台差异由 flutter_secure_storage 兜住】
/// Android 走 EncryptedSharedPreferences，iOS/macOS 走 Keychain，
/// Web 走 WebCrypto + localStorage。
///
/// 【⚠️ Web 上有个约束要记住】WebCrypto 只在**安全上下文**里可用，
/// 也就是 https 或 localhost。`flutter run -d chrome` 走的正是 localhost，
/// 所以开发时没事；但如果你把 Web 产物挂到一个 http 的内网地址上演示，
/// 这里会**抛异常**而不是静默降级。
/// 真要那种场景，就在 `app_providers` 里换成 [InMemoryTokenStore]
/// （代价是刷新页面就要重新登录）。
class SecureTokenStore implements TokenStore {
  SecureTokenStore({FlutterSecureStorage? storage})
      : _storage = storage ?? const FlutterSecureStorage();

  final FlutterSecureStorage _storage;

  /// 【key 名字带包名前缀】密钥库是整个 App 共用的命名空间，
  /// 用 `token` 这种通用名将来接了别的 SDK 很容易撞。
  static const String _key = 'aivideo.auth_token';

  @override
  Future<String?> read() async {
    final value = await _storage.read(key: _key);
    // 【空串当没登录】见接口里那条注释：空串不该被当成有效 token
    // 传给 `Authorization: Bearer `（那会得到一个很怪的 401）。
    return (value == null || value.isEmpty) ? null : value;
  }

  @override
  Future<void> write(String token) => _storage.write(key: _key, value: token);

  @override
  Future<void> clear() => _storage.delete(key: _key);
}

/// 内存实现：测试用，也给「Web 不安全上下文」当降级出口
///
/// 【它不是玩具】它的语义和真实实现**完全一致**，只是活得短。
/// 测试用它才能做到「不碰真实密钥库」；这一点很重要 ——
/// 单元测试写进系统 Keychain 会污染开发机，而且并行跑测试时会互相踩。
class InMemoryTokenStore implements TokenStore {
  InMemoryTokenStore([this._token]);

  String? _token;

  @override
  Future<String?> read() async => _token;

  @override
  Future<void> write(String token) async => _token = token;

  @override
  Future<void> clear() async => _token = null;
}

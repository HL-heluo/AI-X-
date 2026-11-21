import '../models/auth_session.dart';

/// 注册与登录（§6.1）
///
/// 【为什么这一层要有接口，不直接让页面调 ApiClient】
/// 因为「注册要带邀请码」「密码不能记在本地」这类**业务规矩**
/// 需要有地方落脚。页面只管调 `register(...)`，
/// 不用知道要走哪个路径、参数叫什么名字。
///
/// 这一层**只声明业务语义，不碰 HTTP**：路径、序列化、错误映射都在实现里。
/// 好处是换协议（比如将来加个 gRPC）时，这一层一个字都不用改。
abstract interface class AuthRepository {
  /// 注册。
  ///
  /// [inviteCode] 是**邀请码**，不是可有可无的装饰 —— §6.1 把它列为注册的硬门槛：
  /// 内测控量，而且**邀请制本身就是花销上限**（§7.5 第 4 道闸）。
  /// 所以它和用户名密码一样是必填参数。
  ///
  /// 成功后服务端会赠送 50 积分并**写一条流水**（§12.1 + §7.3）。
  Future<AuthSession> register({
    required String inviteCode,
    required String username,
    required String password,
  });

  /// 登录。
  Future<AuthSession> login({
    required String username,
    required String password,
  });

  // 【这里为什么没有 logout】
  // 因为 v1 的登出**不需要请求服务端** —— JWT 是无状态的，
  // 「登出」在客户端就是「把 token 从 flutter_secure_storage 里删掉」。
  // 为了对称而造一个没人调的 `/auth/logout` 接口，只会让人以为
  // 服务端真的会把 token 作废（它不会，JWT 没有吊销列表）。
  // 登出由 AuthController 直接操作 TokenStore 完成（见 B4）。
}

import '../core/json_utils.dart';
import 'credit_account.dart';
import 'user.dart';

/// 一次登录的结果
///
/// 对应 §12.1 的 `POST /auth/register` 和 `POST /auth/login`。
///
/// 【为什么把 token 和用户信息放在一起返回，而不是只回 token】
/// 因为登录后马上要显示首页，而首页右上角就有积分胶囊。
/// 如果登录只拿到 token，紧接着必须再发一个 `GET /me`，
/// 用户会看到「进去了 → 积分那栏空一下 → 数字才出来」的闪烁。
/// 注册/登录一次把用户信息和积分总览带回来，首页可以直接渲染。
///
/// 【这一条已经超出了 §12.1 的字面】文档写的是 `POST /auth/login` → `{token}`。
/// 这里按上面那个理由拍板成 `{token, user, credit_account}`。
/// **接真后端前需与后端确认**（最坏情况是登录后再补一次 `/me`，成本很低）。
class AuthSession {
  const AuthSession({
    required this.token,
    required this.user,
    required this.creditAccount,
  });

  /// JWT。存进 `flutter_secure_storage`，**不要**存 SharedPreferences ——
  /// 那是明文的，root 过的机器上直接可读。
  final String token;

  final User user;
  final CreditAccount creditAccount;

  factory AuthSession.fromJson(Map<String, dynamic> json) => AuthSession(
        token: json.stringOr(json['token']),
        user: User.fromJson(json.asJsonMap(json['user'], field: 'user')),
        creditAccount: CreditAccount.fromJson(
          json.asJsonMap(json['credit_account'], field: 'credit_account'),
        ),
      );
}

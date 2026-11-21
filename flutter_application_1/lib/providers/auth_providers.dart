import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/auth_session.dart';
import 'app_providers.dart';

/// ─────────────────────────────────────────────────────────
/// 登录态
///
/// 【为什么是 sealed class，不是 enum】
/// 因为 `authenticated` 这个分支**带着数据**（用户是谁、有多少积分），
/// enum 装不下。sealed 还能让 `switch` 穷尽检查 ——
/// 将来加了第三种状态（比如「被封禁」），所有 switch 会编译报错，
/// 逼你去处理它。用 bool + nullable 字段是做不到这一点的。
///
/// 【为什么没有 `unknown` 这个状态】
/// 冷启动时「还不知道登没登录」这件事，已经由 `AsyncValue` 的 loading 表达了
/// （这个 provider 是 `AsyncNotifier<AuthState>`）。
/// 再在 AuthState 里放一个 `unknown`，就会出现「AsyncLoading 里装着
/// unknown」这种两种 loading 表示法并存的局面，读代码的人得同时理解两套。
/// ─────────────────────────────────────────────────────────
sealed class AuthState {
  const AuthState();
}

/// 未登录（含「token 失效被踢出来」）
final class Unauthenticated extends AuthState {
  const Unauthenticated();
}

/// 已登录
final class Authenticated extends AuthState {
  const Authenticated({this.session});

  /// 登录/注册成功时是**非 null**（服务端刚把用户和积分一起给了我们）。
  ///
  /// 【为什么允许 null】冷启动恢复登录时，我们手里只有 token，
  /// 用户档案要另发一次 `GET /me` 才能拿到。**如果那次请求失败（断网），
  /// 不该把用户踢到登录页** —— 那会变成「一断网就退出登录」，
  /// 而 token 其实是好的。
  ///
  /// 所以：`session == null` 的准确含义是「**token 已被信任，档案还没到手**」。
  /// 需要档案的页面（我的、积分）自己去拉，并且自己处理失败 ——
  /// 它们本来就该这么做，因为档案是会变的（用户刚花掉积分）。
  final AuthSession? session;
}

/// 登录、注册、登出、冷启动恢复
///
/// 【它不管什么】不管 token 怎么存（那是 [tokenStoreProvider]），
/// 不管 HTTP 怎么发（那是 repository），不管界面怎么显示。
/// 它只负责**决定当前是哪个 AuthState**，并在变化时通知出去。
class AuthController extends AsyncNotifier<AuthState> {
  @override
  Future<AuthState> build() async {
    final token = await ref.read(tokenStoreProvider).read();
    if (token == null) return const Unauthenticated();

    // 【先把 token 装进内存】必须在发请求之前 —— 下面这次 `/me`
    // 是要带鉴权头的，而头是从 [authTokenProvider] 读的。
    // 顺序反了的话，恢复登录这一步会必然拿到 401。
    ref.read(authTokenProvider.notifier).setToken(token);

    try {
      final me = await ref.read(meRepositoryProvider).fetchProfile();
      return Authenticated(
        session: AuthSession(
          token: token,
          user: me.user,
          creditAccount: me.creditAccount,
        ),
      );
    } on AppException catch (e) {
      if (e.isUnauthorized) {
        // token 真的坏了（过期/被清）—— 清掉，别每次启动都拿它撞一次墙
        await _forget();
        return const Unauthenticated();
      }
      // 其余情况（断网、超时、服务端 5xx）都**保留登录态**。
      // 见 [Authenticated.session] 的注释：这里踢人 = 一断网就退出登录。
      return const Authenticated();
    }
  }

  /// 登录。
  ///
  /// 【失败为什么是抛异常，而不是把 state 置成 AsyncError】
  /// ─────────────────────────────────────────────────────────
  /// 因为**登录失败不是「应用出错了」，是「这次输入不对」** ——
  /// 用户名密码错、邀请码无效，都是要贴着输入框显示给用户看的一句话。
  ///
  /// 更重要的是：如果这里把 state 置成 AsyncLoading，
  /// `app.dart` 的分发会立刻把登录页换成 Splash —— 用户正打字打到一半，
  /// 界面突然整页一闪，回来时输入框还空了。这是很难查的体验 bug。
  ///
  /// 所以规矩是：**这个 provider 只在「登录态真的变了」时才改 state。**
  /// 提交中的转圈、错误提示，都由登录页自己用一个局部变量管。
  /// 调用方（登录页）负责 catch。
  /// ─────────────────────────────────────────────────────────
  Future<void> login({
    required String username,
    required String password,
  }) async {
    final session = await ref.read(authRepositoryProvider).login(
          username: username,
          password: password,
        );
    await _adopt(session);
  }

  /// 注册。成功后服务端赠送 50 积分并写一条流水（§12.1）。
  Future<void> register({
    required String inviteCode,
    required String username,
    required String password,
  }) async {
    final session = await ref.read(authRepositoryProvider).register(
          inviteCode: inviteCode,
          username: username,
          password: password,
        );
    await _adopt(session);
  }

  /// 登出。
  ///
  /// 【为什么不请求服务端】JWT 无状态，服务端没有吊销列表 ——
  /// 详见 `AuthRepository` 里那段注释。
  Future<void> logout() async {
    await _forget();
    state = const AsyncData(Unauthenticated());
  }

  /// 把一次成功的登录落下来。
  ///
  /// 【写入顺序是刻意的，不能反】先落盘，再写内存。
  /// 反过来的话，如果落盘失败（密钥库异常），内存里已经有了 token，
  /// 用户这次运行一切正常、下次启动却「莫名其妙没登录」——
  /// 而且日志里什么都没有。按这个顺序，失败会立刻暴露在登录这一步。
  Future<void> _adopt(AuthSession session) async {
    await ref.read(tokenStoreProvider).write(session.token);
    ref.read(authTokenProvider.notifier).setToken(session.token);
    state = AsyncData(Authenticated(session: session));
  }

  /// 抹掉本地登录痕迹。
  ///
  /// 【顺序和 _adopt 相反，也是刻意的】先清内存，再清盘。
  /// 这样「清盘失败」时内存已经是干净的，本次运行不会带着旧 token 发请求；
  /// 最坏情况是下次启动还能恢复出登录态（可接受），
  /// 而不是登出之后还拿着旧 token 到处请求。
  Future<void> _forget() async {
    ref.read(authTokenProvider.notifier).setToken(null);
    await ref.read(tokenStoreProvider).clear();
  }

  // ─────────────────────────────────────────────────────────
  // 【这里**故意**不 invalidate 任何 provider】—— 但这不是漏了
  //
  // 登出必须让「按用户缓存」的数据作废，否则 A 登出、B 登录之后，
  // B 会看到 A 的用户名和积分，而且不报任何错。
  //
  // 原本的计划是在这个方法里 invalidate 一张清单。**B5 改了做法**：
  // 与其维护一张「记得来改」的清单，不如让每个用户相关的 provider
  // 自己 `ref.watch(authTokenProvider)` —— 登录态一变，它自己作废并重拉
  // （见 `MeProfileNotifier.build` 上面那段）。理由是清单会漏：
  // 以后每加一个 provider 都得回来补一行，而漏掉时**什么都不会发生**，
  // 只是某天有人看到别人的数据。依赖关系不会漏。
  //
  // 【那为什么不能在这里 invalidate】因为时机不对：`_forget()` 已经把
  // token 清空了，此时重拉会拿着 null token 去打服务端；而等
  // `state = Unauthenticated` 让界面树拆完再 invalidate，又没有可靠的挂点。
  // 顺带一提，`logout()` 之后**不能**再 pop 栈上的页面来补救 ——
  // 那由 `app.dart` 里 MaterialApp 的 key 负责，见那里的注释。
  //
  // 【新增数据 provider 时的规矩】**凡是「这是谁的数据」的 provider，
  // 都必须在 build 里 `ref.watch(authTokenProvider)`。**
  // ─────────────────────────────────────────────────────────
}

/// 登录态的**唯一读取入口**。
///
/// 页面一律 `ref.watch(authControllerProvider)`，拿到 `AsyncValue<AuthState>`
/// 自己分发 loading / data。**不要**在页面里自己判断 token 有没有。
final authControllerProvider =
    AsyncNotifierProvider<AuthController, AuthState>(AuthController.new);

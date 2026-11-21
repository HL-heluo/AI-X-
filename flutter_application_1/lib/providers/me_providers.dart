import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../core/network/api_exception.dart';
import '../models/me_profile.dart';
import 'app_providers.dart';

/// 「我的」页要的那一份数据：用户 + 积分账户。
///
/// ─────────────────────────────────────────────────────────
/// 【为什么 build 里要 watch [authTokenProvider]】
///
/// 因为这个 provider 是**非 autoDispose** 的：它活过整次会话。
/// 如果它不关心「现在是谁」，就会发生下面这件事：
///
///   A 登录 → 打开「我的」（拉回 A 的资料，缓存住）→ A 登出 → B 登录
///   → B 打开「我的」→ **看到 A 的用户名和积分**
///
/// 而且不报任何错。这类串号极难被发现，因为测试通常只登录一个用户。
///
/// 把 token 声明成依赖，等于把「这份数据是**在哪个身份下**取回来的」
/// 变成 provider 的一部分：登录态一变，这份缓存**自动作废并重拉**。
/// 这比「登出时记得手动 invalidate 一张清单」可靠 —— 清单会漏，
/// 依赖关系不会。
///
/// 【为什么余额跟着 /me 一起拉，而不是单独开一个余额 provider】
/// 余额是「谁的钱」的一部分，必须和 user 同一次响应回来。拆成两个 provider
/// 会让「换了用户但余额还是上一个的」成为可能（两条请求的返回顺序没保证）。
///
/// 【为什么用 AsyncNotifier 而不是 FutureProvider】需要 `refresh()` 这个动作。
/// ─────────────────────────────────────────────────────────
class MeProfileNotifier extends AsyncNotifier<MeProfile> {
  @override
  Future<MeProfile> build() {
    final token = ref.watch(authTokenProvider);

    // 没登录的时候，世界上不该存在任何一份「我的资料」。
    // 【为什么不发请求让服务端来拒绝】那会白烧一次往返，而且 Mock 和真后端
    // 会用两种方式拒绝（前者抛 401、后者可能被网关拦成 403）。
    // 这是个纯粹的**客户端前提**，在这里断掉最干净。
    // （登出后确实会走到这里一次 —— 那时没有任何页面在 watch 它，
    //   这个错误态谁也看不见，B 登录时 token 一变就会被重拉覆盖。）
    if (token == null) throw AppException.unauthorized();

    return ref.read(meRepositoryProvider).fetchProfile();
  }

  /// 重新拉一次。下拉刷新和错误页的「重试」共用这一个。
  Future<void> refresh() async {
    // 【为什么只在「手上什么都没有」时才切到 loading】
    // 下拉刷新时屏幕上已经有内容，切 loading 会把它换成骨架再换回来，
    // 闪一下 —— 而下拉指示器自己就在转圈，不缺这个反馈。
    // 但「加载失败后点重试」时屏幕上只有一句错误文案，
    // 不给动静的话用户会以为按钮是坏的。
    if (!state.hasValue) state = const AsyncValue.loading();
    state = await AsyncValue.guard(
      () => ref.read(meRepositoryProvider).fetchProfile(),
    );
  }
}

final meProfileProvider = AsyncNotifierProvider<MeProfileNotifier, MeProfile>(
  MeProfileNotifier.new,
  // 见 `noAutoRetry` 的注释：默认的自动重试会让「重试」按钮变成假的
  retry: noAutoRetry,
);

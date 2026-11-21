import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import 'app_shell.dart';
import 'core/constants/app_info.dart';
import 'pages/auth/login_page.dart';
import 'pages/splash/splash_page.dart';
import 'providers/auth_providers.dart';
import 'router/app_router.dart';
import 'theme/app_theme.dart';

/// 根组件
///
/// 【它只做两件事】挂主题、**按登录态决定第一屏是什么**。
/// 业务代码一行都不该写在这里。
///
/// ─────────────────────────────────────────────────────────
/// 【这里的 `home` 就是整个 App 的路由分发点】
///
/// 公开核验有独立路由。常规首页由三个登录状态分支决定：
///
///   AsyncLoading  → SplashPage   还不知道登没登录
///   Unauthenticated → LoginPage  确定没登录
///   Authenticated → AppShell     确定登录了
///
/// 【为什么这个分发放在这里，而不是一个「守卫」中间件里】
/// 因为它是**声明式**的：登录态一变，`ref.watch` 自动重建，界面自动切。
/// 守卫式的写法（在路由回调里判断+跳转）是命令式的，它会引入
/// 「跳转发生在哪一帧」「能不能返回」这类只有时序相关的问题 ——
/// 而这些问题在登录/登出这种高频路径上一定会出。
///
/// 【一个副作用要注意】用户不能从 AppShell「返回」到登录页 ——
/// 因为登录页根本不是上一页，它是同一层里的**另一个分支**。
/// 这正是我们要的：登录后按返回键不该退出登录。
/// ─────────────────────────────────────────────────────────
class AiVideoApp extends ConsumerWidget {
  const AiVideoApp({super.key});

  @override
  Widget build(BuildContext context, WidgetRef ref) {
    final auth = ref.watch(authControllerProvider);

    // 登录态的**粗粒度**标识：只有「已登录 / 未登录 / 还不知道」三种，
    // 不跟着 session 里的字段变。它唯一的作用是当下面那个 key。
    final authPhase = switch (auth) {
      AsyncValue(:final value?) =>
        value is Authenticated ? 'authenticated' : 'unauthenticated',
      _ => 'unknown',
    };

    return MaterialApp(
      // ───────────────────────────────────────────────────────
      // 【为什么要按登录态换 key】
      //
      // 因为 push 出来的页面**待在 Navigator 的栈上**，而 `home` 只是栈底那一层。
      // 用户走到「我的 → 设置 → 退出登录」时，设置页是 push 上来的；
      // 登录态一变，`home` 会被换成登录页 —— 但栈顶的设置页还在，
      // 用户会**停在设置页上**，明明已经退出了却还看得见账号界面。
      //
      // 换 key 会让 MaterialApp 连它内部的 Navigator 一起重建，栈随之清空。
      //
      // 【为什么不在「退出登录」的按钮里手动 popUntil】
      // 那样每个可能触发登出的地方都要记得做一次，漏一处就是
      // 「退出了但还停在原页面」；而且**被动登出**（token 过期被踢）时
      // 根本没有那个调用点 —— 它对用户来说同样是「登录态变了」。
      // 把这件事挂在登录态本身上，就和 `home` 的分发用的是同一个信号，
      // 不会出现两处判断不一致。
      //
      // 【代价】登录态切换时整棵树重建，AppShell 里 Tab 的选中位置等
      // 界面状态会归零。这正是我们要的：换了个人，不该接着上一个人的界面。
      // ───────────────────────────────────────────────────────
      key: ValueKey(authPhase),

      title: AppInfo.appTitle,

      // 关掉右上角那个红色的 DEBUG 横幅。
      // 它只是提示你当前是调试模式，开发时挡视线，影响你看真实效果。
      debugShowCheckedModeBanner: false,

      // 全局主题。在这里挂一次，所有页面自动生效。
      theme: AppTheme.light,
      onGenerateRoute: AppRoutes.publicRoute,

      home: switch (auth) {
        // 【为什么要判 hasValue 而不是先 match AsyncData】
        // 因为刷新期间 AsyncValue 会同时带着「旧数据」和「isLoading」，
        // 这时应该继续显示旧界面，而不是闪回启动页。
        // 用 `valueOrNull` 拿「已知的最新结论」，有就先用着。
        AsyncValue(:final value?) => switch (value) {
            Authenticated() => const AppShell(),
            Unauthenticated() => const LoginPage(),
          },
        // 冷启动读 token / 验证 token 期间
        AsyncLoading() => const SplashPage(),
        // 走到这里说明验证登录态这件事本身炸了（密钥库读不出来、
        // Web 不在安全上下文……）。**不能白屏**，得给一条出路。
        AsyncError(:final error) => _StartupErrorPage(
            error: error,
            onRetry: () => ref.invalidate(authControllerProvider),
          ),
      },
    );
  }
}

/// 启动失败页
///
/// 【为什么值得为「启动失败」单独做一个页面】
/// 因为它是**应用最没有退路的地方**：这一刻还没有任何界面可以操作，
/// 崩在这里就是一个白屏，用户能做的只有卸载重装。
///
/// 而真实世界里有几种很像的事故：Web 部署在 http（非安全上下文）
/// 导致密钥库抛异常、磁盘满、系统权限被改。
/// 这些情况下**「重试」往往真的能好**，所以这个页面不是一个死胡同。
class _StartupErrorPage extends StatelessWidget {
  const _StartupErrorPage({required this.error, required this.onRetry});

  final Object error;
  final VoidCallback onRetry;

  @override
  Widget build(BuildContext context) {
    return Scaffold(
      backgroundColor: AppColors.bgWarm,
      body: Center(
        child: Padding(
          padding: const EdgeInsets.symmetric(horizontal: 40),
          child: Column(
            mainAxisSize: MainAxisSize.min,
            children: [
              const Icon(Icons.cloud_off_outlined,
                  size: 40, color: AppColors.taupe),
              const SizedBox(height: 16),
              const Text(
                '启动时出了点问题',
                style: TextStyle(
                  fontSize: 15,
                  fontWeight: FontWeight.w600,
                  color: AppColors.charcoal,
                ),
              ),
              const SizedBox(height: 8),
              // 【把技术细节也显示出来】因为这一页只有开发者和内测用户会看到，
              // 而「出错了」三个字对排查毫无帮助。等正式上线前
              // 要改成只在 kDebugMode 下显示。
              Text(
                '$error',
                textAlign: TextAlign.center,
                style: const TextStyle(
                  fontSize: 11.5,
                  height: 1.5,
                  color: AppColors.taupe,
                ),
              ),
              const SizedBox(height: 20),
              TextButton(
                onPressed: onRetry,
                child: const Text(
                  '重试',
                  style: TextStyle(
                    fontSize: 14,
                    fontWeight: FontWeight.w600,
                    color: AppColors.sage,
                  ),
                ),
              ),
            ],
          ),
        ),
      ),
    );
  }
}

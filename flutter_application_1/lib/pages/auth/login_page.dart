import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../core/constants/app_info.dart';
import '../../core/network/api_exception.dart';
import '../../providers/app_providers.dart';
import '../../providers/auth_providers.dart';
import '../../router/app_router.dart';
import '../../theme/app_theme.dart';
import '../../widgets/app_background.dart';
import '../../widgets/glass_card.dart';

/// 登录 / 注册（§6.1）
///
/// 【为什么注册要求邀请码，而且和用户名密码一样是必填】
/// 这不是防刷的装饰。§7.5 把「邀请制」列为第四条闸门：
/// **邀请制本身就是花销上限** —— 每个注册用户都会被赠送 50 积分，
/// 而积分是真金白银买来的算力。没有邀请码，任何人都能无限注册领积分。
///
/// 【为什么两模式在同一个页面，而不是两个页面】
/// 它们**共用两个字段**（用户名、密码），而且用户经常是「以为注册过了，
/// 试了一下发现没有，那就注册」—— 分成两个页面就得让用户自己找到那个入口，
/// 还要把已经输好的用户名密码重打一遍。一个页面切一下，输入框原样保留。
class LoginPage extends ConsumerStatefulWidget {
  const LoginPage({super.key});

  @override
  ConsumerState<LoginPage> createState() => _LoginPageState();
}

class _LoginPageState extends ConsumerState<LoginPage> {
  // ── 这些是**纯界面状态**，不是业务数据 ─────────────────────
  // 判断标准很简单：它们刷新页面就该没了，而且服务端完全不知道它们存在。
  // 任务、积分、用户档案一律不在这里（§8.4 硬规则）。

  final _inviteController = TextEditingController();
  final _usernameController = TextEditingController();
  final _passwordController = TextEditingController();

  /// 当前是注册模式还是登录模式。默认登录（老用户回来的概率更高）。
  bool _isRegister = false;

  /// 提交中。用来禁用按钮 —— **防连点的第一道防线**。
  ///
  /// 【为什么它是局部变量，而不是把全局 authState 置成 loading】
  /// 见 `AuthController.login` 上面那段注释：那会把整页换成 Splash。
  bool _pending = false;

  /// 就地显示的错误。null 表示没有错误。
  String? _error;

  /// 密码是否可见。
  bool _obscure = true;

  @override
  void dispose() {
    _inviteController.dispose();
    _usernameController.dispose();
    _passwordController.dispose();
    super.dispose();
  }

  /// 切换登录/注册。**保留已输入的字段**（见类注释里那条理由）。
  void _switchMode(bool register) {
    if (_pending) return; // 提交中不让切，否则会把成功的响应切到一个已经不存在的模式上
    setState(() {
      _isRegister = register;
      // 【错误要清掉】上一模式的错误（比如「用户名已被占用」）
      // 留到登录模式下就成了误导。
      _error = null;
    });
  }

  Future<void> _submit() async {
    if (_pending) return;

    final username = _usernameController.text.trim();
    final password = _passwordController.text;
    final inviteCode = _inviteController.text.trim();

    // ── 本地校验 ──────────────────────────────────────────
    // 【为什么要在这里校验，服务端不是也会校验吗】
    // 因为服务端校验一来一回要几百毫秒，还会真的建一次连接。
    // 空用户名这种错在这里就能挡掉。
    //
    // 【但本地校验永远只是「提前提示」，不是「把关」】服务端的校验才是权威的
    // ——客户端可以被绕过、也可能和服务的规则版本不一致。所以下面所有
    // 校验都只是**不发这个请求**，没有任何「本地通过就一定是对的」的假设。
    final localError = _validate(
      username: username,
      password: password,
      inviteCode: inviteCode,
    );
    if (localError != null) {
      setState(() => _error = localError);
      return;
    }

    setState(() {
      _pending = true;
      _error = null;
    });

    try {
      final auth = ref.read(authControllerProvider.notifier);
      if (_isRegister) {
        await auth.register(
          inviteCode: inviteCode,
          username: username,
          password: password,
        );
      } else {
        await auth.login(username: username, password: password);
      }
      // 【成功之后这里什么都不用做 —— 一行导航都不写】
      // `app.dart` 在 watch `authControllerProvider`，state 一变，
      // 它自己会把整棵树换成 AppShell。
      //
      // 如果这里再 `Navigator.push` 一下，结果会是两层：先被 home 换掉，
      // 又 push 一个壳上去，返回键会退到「一个已经无主的登录页」。
      //
      // 【也不用 setState 把 _pending 改回 false】因为这一页马上就被销毁了。
      // 真去改的话，会在 dispose 之后碰 State，抛异常。
      // 下面的 finally 会兜住 —— 但只有失败时才真的需要它。
    } on AppException catch (e) {
      if (!mounted) return;
      setState(() {
        _pending = false;
        _error = _friendlyMessage(e);
      });
    }
  }

  /// 把异常翻成**这个页面上说得通的一句话**。
  ///
  /// ─────────────────────────────────────────────────────────
  /// 【为什么不直接用 `e.userMessage`】
  ///
  /// 因为 `userMessage` 是**为「已登录的会话」写的**，套到登录页上会撒谎：
  ///
  /// * 登录时密码打错 → 服务端返回 **401**。而 `userMessage` 对 401 的说法是
  ///   **「登录已过期，请重新登录」** —— 用户刚打开 App 还没登录过，
  ///   哪来的过期？他会去找「我已经登录了呀」这个根本不存在的状态。
  /// * 注册时用户名被占用 → 服务端返回 **409**，但 §12.3 里没有
  ///   「用户名已存在」这个错误码，于是 `code` 是 null，
  ///   `userMessage` 退回成**「出错了，请稍后重试」** —— 用户会一直重试，
  ///   永远试不出结果。
  ///
  /// 两处都不是 `userMessage` 写错了，是**它回答的问题不一样**：
  /// 它回答「我的会话怎么了」，而这个页面要回答「我这次输入怎么了」。
  /// 所以语境相关的话术归语境相关的地方管。
  ///
  /// 【⚠️ 这里的 401/409 判断是在补 §12.3 的缺口】
  /// 正确的修法是让后端定义 `INVALID_CREDENTIALS` / `USERNAME_TAKEN`
  /// 两个错误码，那时这里就能改成按 `e.code` 分支，不再看 HTTP 状态码。
  /// **接真后端前要与后端确认。**
  /// ─────────────────────────────────────────────────────────
  String _friendlyMessage(AppException e) {
    if (!_isRegister && e.isUnauthorized) return '用户名或密码不正确';
    if (_isRegister && e.httpStatus == 409) return '这个用户名已经被占用了，换一个试试';

    // 断网、超时之类没有错误码的情况，给一句能指导行动的话
    if (e.code == null) return '连不上服务器，检查一下网络再试';

    return e.userMessage;
  }

  /// 本地校验。返回 null 表示可以提交。
  String? _validate({
    required String username,
    required String password,
    required String inviteCode,
  }) {
    if (_isRegister && inviteCode.isEmpty) return '请填写邀请码';
    if (username.isEmpty) return '请填写用户名';
    if (username.length < 3) return '用户名至少 3 个字符';
    if (password.length < 6) return '密码至少 6 位';
    // 【这里不校验「用户名只能是字母数字」之类的规则】
    // 因为 §6.1 没规定，我自己编一条只会和真后端的规则打架 ——
    // 那会出现「本地过了、服务端拒绝」这种最难解释的失败。
    // 规则该由服务端定义，客户端等它给了错误码再跟上。
    return null;
  }

  @override
  Widget build(BuildContext context) {
    final useMock = ref.watch(appConfigProvider).useMock;

    return AppBackground(
      child: Scaffold(
        backgroundColor: Colors.transparent,
        body: SafeArea(
          child: Center(
            // 【为什么外面要包一层滚动】
            // 键盘弹起来时可视高度会掉到原来的 40% 左右，
            // 固定高度的 Column 会直接溢出报黄黑条。
            // SingleChildScrollView 让它在矮屏上能滚，用户至少够得着按钮。
            child: SingleChildScrollView(
              padding: const EdgeInsets.symmetric(horizontal: 24, vertical: 32),
              child: ConstrainedBox(
                // 宽屏（Web / 平板）上限 420，否则输入框会被拉成一条横贯全屏的线
                constraints: const BoxConstraints(maxWidth: 420),
                child: Column(
                  mainAxisSize: MainAxisSize.min,
                  children: [
                    _buildBrand(),
                    const SizedBox(height: 28),
                    GlassCard(
                      radius: AppRadius.hero,
                      padding: const EdgeInsets.all(22),
                      child: Column(
                        crossAxisAlignment: CrossAxisAlignment.stretch,
                        children: [
                          _buildModeSwitch(),
                          const SizedBox(height: 20),
                          // 注册才要邀请码，且放在**最前面** ——
                          // 它是这道闸门的实际手感，不该藏在最后。
                          if (_isRegister) ...[
                            _buildField(
                              key: const Key('login.inviteCode'),
                              controller: _inviteController,
                              label: '邀请码',
                              hint: '内测需要邀请码',
                              icon: Icons.confirmation_number_outlined,
                            ),
                            const SizedBox(height: 12),
                          ],
                          _buildField(
                            key: const Key('login.username'),
                            controller: _usernameController,
                            label: '用户名',
                            icon: Icons.person_outline,
                          ),
                          const SizedBox(height: 12),
                          _buildField(
                            key: const Key('login.password'),
                            controller: _passwordController,
                            label: '密码',
                            icon: Icons.lock_outline,
                            obscure: _obscure,
                            trailing: IconButton(
                              onPressed: () =>
                                  setState(() => _obscure = !_obscure),
                              icon: Icon(
                                _obscure
                                    ? Icons.visibility_off_outlined
                                    : Icons.visibility_outlined,
                                size: 18,
                                color: AppColors.taupe,
                              ),
                              tooltip: _obscure ? '显示密码' : '隐藏密码',
                            ),
                            onSubmitted: _submit,
                          ),
                          if (_error != null) ...[
                            const SizedBox(height: 14),
                            _buildError(_error!),
                          ],
                          const SizedBox(height: 20),
                          _buildSubmitButton(),
                        ],
                      ),
                    ),
                    const SizedBox(height: 16),
                    TextButton.icon(
                      onPressed: () =>
                          Navigator.of(context)
                              .pushNamed<void>(AppRoutes.verify),
                      icon: const Icon(Icons.verified_outlined, size: 18),
                      label: const Text('公开存证核验'),
                    ),
                    if (useMock) _buildMockHint(),
                  ],
                ),
              ),
            ),
          ),
        ),
      ),
    );
  }

  Widget _buildBrand() {
    return Column(
      children: [
        Container(
          width: 58,
          height: 58,
          decoration: BoxDecoration(
            borderRadius: BorderRadius.circular(19),
            gradient: const LinearGradient(
              begin: Alignment.topLeft,
              end: Alignment.bottomRight,
              colors: [AppColors.sageSoft, AppColors.sage],
            ),
          ),
          child: const Icon(Icons.auto_awesome, color: Colors.white, size: 26),
        ),
        const SizedBox(height: 14),
        const Text(
          AppInfo.appTitle,
          style: TextStyle(
            fontSize: 30,
            fontWeight: FontWeight.w800,
            color: AppColors.charcoal,
            letterSpacing: 0.5,
          ),
        ),
        const SizedBox(height: 6),
        const Text(
          'AI 图片与视频创作',
          style: TextStyle(fontSize: 13, color: AppColors.taupe),
        ),
      ],
    );
  }

  /// 登录 / 注册 两段式切换
  Widget _buildModeSwitch() {
    return Container(
      padding: const EdgeInsets.all(4),
      decoration: BoxDecoration(
        color: AppColors.sunken,
        borderRadius: BorderRadius.circular(AppRadius.pill),
      ),
      child: Row(
        children: [
          Expanded(
            child: _buildModeTab(
              key: const Key('login.tab.login'),
              label: '登录',
              selected: !_isRegister,
              isRegister: false,
            ),
          ),
          Expanded(
            child: _buildModeTab(
              key: const Key('login.tab.register'),
              label: '注册',
              selected: _isRegister,
              isRegister: true,
            ),
          ),
        ],
      ),
    );
  }

  Widget _buildModeTab({
    required Key key,
    required String label,
    required bool selected,
    required bool isRegister,
  }) {
    return GestureDetector(
      key: key,
      onTap: () => _switchMode(isRegister),
      behavior: HitTestBehavior.opaque,
      child: AnimatedContainer(
        duration: const Duration(milliseconds: 160),
        padding: const EdgeInsets.symmetric(vertical: 9),
        decoration: BoxDecoration(
          // 选中态才用白底浮起来。未选中是透明的，让底色透出来
          color: selected ? AppGlass.strong : Colors.transparent,
          borderRadius: BorderRadius.circular(AppRadius.pill),
        ),
        child: Text(
          label,
          textAlign: TextAlign.center,
          style: TextStyle(
            fontSize: 13.5,
            fontWeight: selected ? FontWeight.w600 : FontWeight.w500,
            color: selected ? AppColors.charcoal : AppColors.taupe,
          ),
        ),
      ),
    );
  }

  Widget _buildField({
    required Key key,
    required TextEditingController controller,
    required String label,
    required IconData icon,
    String? hint,
    bool obscure = false,
    Widget? trailing,
    VoidCallback? onSubmitted,
  }) {
    return Column(
      key: key,
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        Text(
          label,
          style: const TextStyle(
            fontSize: 12,
            fontWeight: FontWeight.w500,
            color: AppColors.taupe,
          ),
        ),
        const SizedBox(height: 6),
        TextField(
          controller: controller,
          obscureText: obscure,
          // 用户名/密码在手机上不该首字母大写、也不该被输入法自动纠错
          autocorrect: false,
          enableSuggestions: !obscure,
          textInputAction: onSubmitted == null
              ? TextInputAction.next
              : TextInputAction.done,
          onSubmitted: onSubmitted == null ? null : (_) => onSubmitted(),
          style: const TextStyle(fontSize: 14.5, color: AppColors.charcoal),
          decoration: InputDecoration(
            hintText: hint,
            hintStyle: TextStyle(
              fontSize: 14,
              color: AppColors.taupe.withValues(alpha: 0.55),
            ),
            prefixIcon: Icon(icon, size: 18, color: AppColors.taupe),
            suffixIcon: trailing,
            filled: true,
            fillColor: AppColors.sunken,
            isDense: true,
            contentPadding: const EdgeInsets.symmetric(vertical: 13),
            border: OutlineInputBorder(
              borderRadius: BorderRadius.circular(AppRadius.lg),
              borderSide: BorderSide.none,
            ),
            // 聚焦时描一圈主色 —— 否则这个几乎无色的输入框聚焦了也看不出来
            focusedBorder: OutlineInputBorder(
              borderRadius: BorderRadius.circular(AppRadius.lg),
              borderSide: const BorderSide(
                color: AppColors.sageSoft,
                width: 1.4,
              ),
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildError(String message) {
    return Row(
      crossAxisAlignment: CrossAxisAlignment.start,
      children: [
        const Icon(Icons.error_outline, size: 15, color: AppColors.danger),
        const SizedBox(width: 6),
        Expanded(
          child: Text(
            message,
            style: const TextStyle(
              fontSize: 12.5,
              color: AppColors.danger,
              height: 1.4,
            ),
          ),
        ),
      ],
    );
  }

  Widget _buildSubmitButton() {
    return SizedBox(
      height: 46,
      child: FilledButton(
        key: const Key('login.submit'),
        // 提交中时 onPressed 传 null —— Flutter 会自动把它变成禁用态，
        // 既灰掉外观，也**真的不响应点击**（防连点第一道防线）
        onPressed: _pending ? null : _submit,
        style: FilledButton.styleFrom(
          backgroundColor: AppColors.sage,
          disabledBackgroundColor: AppColors.sageSoft,
          foregroundColor: Colors.white,
          shape: RoundedRectangleBorder(
            borderRadius: BorderRadius.circular(AppRadius.lg),
          ),
        ),
        child: _pending
            ? const SizedBox(
                width: 18,
                height: 18,
                child: CircularProgressIndicator(
                  strokeWidth: 2,
                  valueColor: AlwaysStoppedAnimation<Color>(Colors.white),
                ),
              )
            : Text(
                _isRegister ? '注册' : '登录',
                style: const TextStyle(
                  fontSize: 14.5,
                  fontWeight: FontWeight.w600,
                ),
              ),
      ),
    );
  }

  /// 演示模式提示
  ///
  /// 【为什么要在正式界面上放一句「这是演示数据」】
  /// 因为后端还不存在，这一版是给内测的人看的。如果不写，
  /// 测试的人会以为「邀请码 MOCK」是真实规则，或者反复尝试一个真邀请码，
  /// 然后来问「为什么我的邀请码无效」。
  ///
  /// 【为什么只在 useMock 时显示】它由编译期开关控制，
  /// 接了真后端这个分支永远不会被编译进去那种误导。
  ///
  /// 【为什么不说「注册送 50 积分」】那个数字是服务端的事（§12.1）。
  /// 写死在客户端的话，哪天服务端又调了，界面就开始撒谎了 ——
  /// 这和 §13.4 禁止在生成按钮下写确定数字是同一条纪律。
  /// （这条纪律不是纸上谈兵：赠送额**真的**从 20 调到了 50，
  /// 而正因为这里没写死，这一屏一个字都不用改。）
  Widget _buildMockHint() {
    return Text(
      '演示模式：数据存在本机内存，邀请码填任意内容即可',
      textAlign: TextAlign.center,
      style: TextStyle(
        fontSize: 11.5,
        height: 1.5,
        color: AppColors.taupe.withValues(alpha: 0.7),
      ),
    );
  }
}

import 'package:flutter/material.dart';
import 'package:flutter_riverpod/flutter_riverpod.dart';

import '../../models/task.dart';
import '../../providers/me_providers.dart';
import '../../providers/shell_providers.dart';
import '../../providers/task_providers.dart';
import '../../router/app_router.dart';
import 'widgets/active_task_bar.dart';
import 'widgets/create_hero_card.dart';
import 'widgets/create_tools_section.dart';
import 'widgets/home_header.dart';
import 'widgets/recent_works_section.dart';

/// 首页 · 创作
///
/// 对应原型 `home`，是整个 App 最重要的一条主线 ——
/// 用户在这里输入提示词，先出图；满意后再把图变成视频。
///
/// 【这一页由 5 块拼成】自上而下：
///   1. 问候 + 头像 + 积分入口   → HomeHeader
///   2. 进行中任务条（有任务时才出现）→ ActiveTaskBar
///   3. 创作输入卡              → CreateHeroCard
///   4. 创作场景 / 风格（横向一排）→ CreateToolsSection
///   5. 最近作品（两列）         → RecentWorksSection
///
/// 【这一轮删掉了两块，不是漏了】
///   - 课程 Banner「本期热招」：课程业务已砍（变现方式只有卖积分）
///   - 4 个快捷入口：课程 / 报名 / 考核 / 接单，四个全废
/// 判断标准是工程文档 §1.5 的非目标清单：这个功能是否服务于「个人创作者做出视频」。
///
/// 【为什么不用自己的 Scaffold】
/// 外层 AppShell 已经提供了 Scaffold（还挂着底部毛玻璃 Tab 栏）。
/// 这里再套一个，只会多出一层不透明的表面，把 AppBackground 的渐变背景挡掉。
/// 页面自己只需要「避开顶部状态栏 + 能纵向滚动」这两件事。
///
/// ─────────────────────────────────────────────────────────
/// 【B6：它为什么变成了 ConsumerStatefulWidget】
///
/// **State 这一半**：提示词输入框和「图片 / 视频」两个模式必须跨帧保留 ——
/// 用户在首页打了一半的描述，切一下模式、或者去看看下面的作品，
/// 回来那段字还得在。所以 `TextEditingController` 和 `_mode` 归这里。
///
/// 【为什么输入框不留在 CreateHeroCard 里（B5 时就在那儿）】
/// 因为「创作场景」那一排要能把一句话**追加到**提示词后面
/// （点「电影感」= 在描述里补上「电影感，浅景深」）。
/// 两个组件要操作同一个 controller 时，唯一正确的做法是把它提到
/// 它们**共同的父节点**上。放在子组件里就得往上传回调，见
/// `selectedTabProvider` 注释里对「回调链」的评价。
///
/// **Consumer 这一半**：这一页现在要读三份数据 ——
/// 「我的资料」（问候语头像 + 可用积分）、「进行中的任务」（顶上那条）、
/// 「最近作品」（底部网格）。三份都是**服务端的真相**，
/// 一律通过 provider 拿，一个都不许存在这个 State 里（§8.4）。
/// ─────────────────────────────────────────────────────────
class CreatePage extends ConsumerStatefulWidget {
  const CreatePage({super.key});

  @override
  ConsumerState<CreatePage> createState() => _CreatePageState();
}

class _CreatePageState extends ConsumerState<CreatePage> {
  /// 提示词。跨帧保留 —— 见类注释。
  final _prompt = TextEditingController();

  /// 当前模式。取值见 [CreateMode]。
  int _mode = CreateMode.image;

  @override
  void dispose() {
    // 【为什么必须 dispose】TextEditingController 挂了监听和原生资源，
    // 不释放会泄漏。这是 Flutter 里最常见的疏漏之一。
    _prompt.dispose();
    super.dispose();
  }

  /// 把一句「场景 / 风格」补到提示词末尾。
  ///
  /// 【为什么要判重】用户点了「电影感」，又点了一次 ——
  /// 描述里就会出现「…，电影感，浅景深，电影感，浅景深」。
  /// 那会实实在在地影响生成结果（提示词越长越糊），
  /// 而且看起来像界面出了 bug。
  ///
  /// 【为什么用「，」而不是空格连接】用户在首页输入的通常是
  /// 逗号分隔的短语串（见输入框的占位示例），拼接要跟着这个习惯走。
  void _appendPhrase(String phrase) {
    final current = _prompt.text.trim();
    if (current.contains(phrase)) return;

    final next = current.isEmpty ? phrase : '$current，$phrase';
    _prompt.text = next;
    // 【为什么要手动摆光标】`text` 的 setter 会把光标复位到开头，
    // 用户接着打字就会打在整段话的最前面。
    _prompt.selection = TextSelection.collapsed(offset: next.length);
  }

  /// 去下一步（选参数 + 真正提交）。
  ///
  /// 【为什么不在这里做校验】提示词是不是空的、超没超 2000 字、
  /// 比例合不合法 —— 这些都在下一页校验，因为**下一页才是提交的那一页**。
  /// 在首页拦一道会出现「首页说不行，下一页说行」这种两处口径不一致；
  /// 而且用户很可能就是想在下一页边看参数边写。
  ///
  /// 【为什么把已经打的字带过去】不带的话，用户得重新打一遍 ——
  /// 而首页这个框看起来就像「在这里写」。
  void _goGenerate() {
    final prompt = _prompt.text.trim();
    Navigator.of(context).push<void>(
      _mode == CreateMode.video
          ? AppRoutes.videoGenRoute<void>(prompt: prompt)
          : AppRoutes.imageGenRoute<void>(prompt: prompt),
    );
  }

  @override
  Widget build(BuildContext context) {
    final profile = ref.watch(meProfileProvider);
    final active = ref.watch(activeTasksProvider);

    // 【为什么要先摊平再取第一个】`AsyncValue.value` 在 loading / error 时是 null，
    // 而「拿不到数据」和「一个任务都没有」在这一条横幅上表现是一样的：
    // 都不显示。多一个 loading 骨架反而会让首页每次冷启动都闪一下。
    final tasks = active.value ?? const <Task>[];
    final first = tasks.isEmpty ? null : tasks.first;
    final composer = CreateHeroCard(
      mode: _mode,
      promptController: _prompt,
      onModeChanged: (index) => setState(() => _mode = index),
      onGenerate: _goGenerate,
    );
    final recentWorks = RecentWorksSection(
      onSeeAll: () {
        ref
            .read(worksSegmentProvider.notifier)
            .select(WorksSegmentNotifier.done);
        ref
            .read(selectedTabProvider.notifier)
            .select(SelectedTabNotifier.worksTab);
      },
    );
    final wide = MediaQuery.sizeOf(context).width >= 860;

    return SafeArea(
      // top: true —— 这一页没有 AppBar，不避开顶部的话问候语会顶到状态栏里。
      // bottom: false —— 底部由 AppShell 的 Scaffold 负责（body 本来就排在
      // 底部 Tab 栏上方，不会重叠），这里再避一次反而会多出一条空白。
      bottom: false,
      child: ListView(
        // 这里只留「上下」的边距，左右留白交给各个区块自己加。
        // 【为什么】「创作场景」那排卡片要能贴着屏幕边缘滑出去，
        // 如果整页一起缩进 20，它就永远贴不到边了。
        padding: const EdgeInsets.only(top: 16, bottom: 20),
        children: [
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: HomeHeader(
              // 资料还没回来时是 null：头像退化成一个人形图标、
              // 积分入口不显示数字。**不编一个值**（见 HomeHeader 的注释）。
              name: profile.value?.user.username,
              // 头部显示的是**可用**积分（余额 − 冻结中）：
              // 有任务在跑时被冻结的那部分不能再花，显示可用才诚实。
              creditBalance: profile.value?.creditAccount.available,
              onCreditTap: () =>
                  Navigator.of(context)
                      .push<void>(AppRoutes.creditsRoute<void>()),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: ActiveTaskBar(
              task: first,
              activeCount: tasks.length,
              // 点进详情页 —— 那里有排队位次、结算明细和「取消」。
              // 首页这条只负责「让你知道有这么回事」。
              onTap: first == null
                  ? null
                  : () => Navigator.of(context)
                        .push<void>(AppRoutes.taskDetailRoute<void>(first.id)),
            ),
          ),
          Padding(
            padding: const EdgeInsets.symmetric(horizontal: 20),
            child: wide
                ? Row(
                    crossAxisAlignment: CrossAxisAlignment.start,
                    children: [
                      Expanded(flex: 6, child: composer),
                      const SizedBox(width: 20),
                      Expanded(flex: 4, child: recentWorks),
                    ],
                  )
                : composer,
          ),
          CreateToolsSection(onPick: _appendPhrase),
          if (!wide)
            Padding(
              padding: const EdgeInsets.symmetric(horizontal: 20),
              child: recentWorks,
            ),
        ],
      ),
    );
  }
}

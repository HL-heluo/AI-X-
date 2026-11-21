import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'shell_harness.dart';

/// 首页的渲染冒烟测试
///
/// 【为什么单单要为它写一个】
/// 首页是目前唯一一个「布局复杂到可能自己撑爆自己」的页面：
/// 有横向滚动的卡片排、有按比例算高度的两列网格、有嵌套的滚动容器。
/// 这几种东西最典型的翻车方式就是「无界高度」和「溢出」，
/// 而这两类错误**只在真正渲染时才会暴露**——`flutter analyze` 是看不出来的。
///
/// 【为什么要手动改窗口尺寸】
/// 测试环境默认是 800×600（横屏比例），很多只在窄屏才出现的溢出
/// 在那个尺寸下根本触发不了。所以这里显式设成原型用的 390×844。
///
/// 运行：flutter test
void main() {
  testWidgets('桌面宽屏将创作表单和最近作品并排', (tester) async {
    tester.view.physicalSize = const Size(1440, 900);
    tester.view.devicePixelRatio = 1;
    addTearDown(tester.view.reset);

    await pumpLoggedInShell(tester);
    final prompt = tester.getRect(find.byKey(const Key('home.prompt')));
    final recentWorks = tester.getRect(find.byKey(const Key('home.seeAll')));
    final nav = tester.getRect(find.byType(NavigationBar));

    expect(prompt.right, lessThan(recentWorks.left));
    expect(prompt.bottom, lessThan(nav.top));
    expect(tester.takeException(), isNull);
    await unmountAndDrain(tester);
  });

  testWidgets('首页在手机尺寸下能渲染、能滚到底、不溢出', (WidgetTester tester) async {
    // 设成手机尺寸并放大 3 倍（模拟高 DPI 屏）
    tester.view.physicalSize = const Size(390 * 3, 844 * 3);
    tester.view.devicePixelRatio = 3.0;
    // 测试结束把窗口尺寸还原，免得影响别的测试
    addTearDown(tester.view.reset);

    // 【为什么是 helper 而不是裸 pump AppShell】B5 之后「我的」页要读 provider，
    // 裸 pump 会缺 ProviderScope。见 `shell_harness.dart`。
    await pumpLoggedInShell(tester);

    // 首页现在就是默认那一屏（下标 0），不用再点 Tab 切过去。

    // ── 1. 首屏该在的几块内容 ───────────────────────────
    expect(find.text('开始创作'), findsOneWidget); // 顶部问候
    expect(find.text('开始生成'), findsOneWidget); // 生成按钮

    // ── 2. 这一轮删掉的旧业务，必须真的不在了 ─────────────
    //
    // 这几条是**反向断言**：它们守的是「别把砍掉的东西又捞回来」。
    expect(find.text('本期热招'), findsNothing); // 课程招生 Banner
    expect(find.text('课程'), findsNothing);
    expect(find.text('接单'), findsNothing);

    // ── 3. 创作卡的两处改造 ─────────────────────────────
    //
    // (a) 模式从三个减到两个 —— 音频整条线都不在 v1 范围里
    expect(find.text('图片'), findsOneWidget);
    expect(find.text('视频'), findsOneWidget);
    expect(find.text('音频'), findsNothing);

    // (b) 计费文案不许出现确定数字。
    //
    // 【B6 改了这条断言】原来这里断言的是「计算中…」——那时报价还没接上。
    // 现在报价真的会回来（`costEstimateProvider`），所以正确的断言变成
    // 「这句话是一句关于**冻结**的话」。两件事都要守：
    //   · 不能出现「预计消耗」这种永远不准的承诺（§13.4）；
    //   · 报价到手后，说的必须是冻结 + 结算 + 退回，而不是一个光秃秃的数字。
    expect(find.textContaining('预计消耗'), findsNothing);
    final costHint = tester.widget<Text>(
      find.byKey(const Key('home.costHint')),
    );
    expect(costHint.data, contains('冻结'));

    // (c) 图片是固定价 —— 不能说「按成片时长结算」（图片没有时长）。
    expect(costHint.data, contains('固定价'));

    // ── 4. 输入区是真输入框，不是画出来的假框 ───────────────
    // 能敲字 = 能聚焦 + 有 controller。这里点一下、打一段，验证它真的收字。
    await tester.tap(find.byKey(const Key('home.prompt')));
    await tester.pump();
    await tester.enterText(find.byKey(const Key('home.prompt')), '一只猫在沙滩上奔跑');
    await tester.pump();
    expect(find.text('一只猫在沙滩上奔跑'), findsOneWidget);

    // ── 5. 一路滚到底 ──────────────────────────────────
    // 这一趟会把「创作场景」的横向列表和「最近作品」的两列网格都建出来。
    // 只要有任何一处高度算错，就会在这里抛异常。
    await tester.drag(find.byType(ListView).first, const Offset(0, -1200));
    await tester.pumpAndSettle();

    expect(find.text('最近作品'), findsOneWidget);
    expect(find.text('创作场景'), findsOneWidget);

    // ── 6. 没有任何异常被抛出 ──────────────────────────
    // 溢出（overflow）、无界高度这类错误都会被记成异常，在这里兜底。
    expect(tester.takeException(), isNull);

    // 主界面在树里 → 收尾，理由见 `unmountAndDrain`
    await unmountAndDrain(tester);
  });

  // ────────────────────────────────────────────────────────────
  // B6：首页真的接上数据之后，几条「接线对不对」的断言
  // ────────────────────────────────────────────────────────────

  testWidgets('点「电影感」把描述补进提示词，且不会补两遍', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(390 * 3, 844 * 3);
    tester.view.devicePixelRatio = 3.0;
    addTearDown(tester.view.reset);

    await pumpLoggedInShell(tester);

    Finder promptField() => find.byKey(const Key('home.prompt'));
    Finder sceneChip() => find.byKey(const Key('scene.电影感'));

    String promptText() =>
        tester.widget<TextField>(promptField()).controller!.text;

    // 先写一半描述 —— 这是最常见的用法：主体自己写，风格交给下面的卡片
    await tester.enterText(promptField(), '一只猫在沙滩上奔跑');
    await tester.pump();

    await tester.tap(sceneChip());
    await tester.pump();
    // 【为什么是「追加」而不是「替换」】替换会把用户打的字删掉
    expect(promptText(), startsWith('一只猫在沙滩上奔跑'));
    expect(promptText(), contains('电影感'));
    // 拼接符是中文逗号，和输入框里的示例保持一致
    expect(promptText(), contains('，'));

    // 【再点一次不能变成「…，电影感，浅景深，电影感，浅景深」】
    // 那会实实在在地影响生成结果（提示词越长越糊），而且看起来像 bug。
    final once = promptText();
    await tester.tap(sceneChip());
    await tester.pump();
    expect(promptText(), once);

    await unmountAndDrain(tester);
  });

  testWidgets('切到「视频」模式：报价跟着换，参数提示也换', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(390 * 3, 844 * 3);
    tester.view.devicePixelRatio = 3.0;
    addTearDown(tester.view.reset);

    await pumpLoggedInShell(tester);

    // 图片：固定价、参数只有「画面比例」
    expect(find.text('画面比例在下一步选'), findsOneWidget);

    await tester.tap(find.byKey(const Key('home.mode.1')));
    await tester.pumpAndSettle();

    // 视频：报的是一个区间（成片时长由 provider 决定，下单时算不出来），
    // 而且参数提示要多列出时长和清晰度
    expect(find.text('时长、比例、清晰度在下一步选'), findsOneWidget);
    final hint = tester
        .widget<Text>(find.byKey(const Key('home.costHint')))
        .data!;
    expect(hint, contains('冻结'));
    expect(hint, isNot(contains('固定价')));

    await unmountAndDrain(tester);
  });

  testWidgets('「全部 ›」切到作品页的「已完成」分段', (WidgetTester tester) async {
    tester.view.physicalSize = const Size(390 * 3, 844 * 3);
    tester.view.devicePixelRatio = 3.0;
    addTearDown(tester.view.reset);

    await pumpLoggedInShell(tester);

    // 先滚到「最近作品」，让那个「全部 ›」真的在屏幕上
    // （不在屏幕上的组件 `tester.tap` 会点到空白处，而且**不会报错** ——
    //  这是最容易写出「假绿」的一种情况，所以要先 ensureVisible）
    final seeAll = find.byKey(const Key('home.seeAll'));
    await tester.ensureVisible(seeAll);
    await tester.pumpAndSettle();

    await tester.tap(seeAll);
    await tester.pumpAndSettle();

    // 落点是作品页的「已完成」，不是「进行中」——
    // 【为什么这条值得测】切到「进行中」的话，用户看到的是
    // 「现在没有进行中的任务」，会以为自己的作品没了。
    expect(find.byKey(const Key('works.segment.1')), findsOneWidget);
    expect(find.byKey(const Key('works.segment.0')), findsOneWidget);
    // 「已完成」分段特有的那一块（作品网格或它的空状态）
    expect(
      find.byKey(const Key('works.done.body')),
      findsOneWidget,
      reason: '点了「全部 ›」应当落在「已完成」分段上',
    );

    await unmountAndDrain(tester);
  });
}

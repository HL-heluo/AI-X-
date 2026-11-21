import 'package:flutter/material.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/pages/credits/credits_page.dart';
import 'package:flutter_application_1/pages/generate/image_gen_page.dart';
import 'package:flutter_application_1/pages/generate/image_result_page.dart';
import 'package:flutter_application_1/pages/generate/video_gen_page.dart';
import 'package:flutter_application_1/pages/generate/video_result_page.dart';
import 'package:flutter_application_1/providers/app_providers.dart';
import 'package:flutter_application_1/providers/asset_providers.dart';
import 'package:flutter_application_1/widgets/ai_generated_badge.dart';
import 'package:flutter_application_1/widgets/work_thumbnail.dart';

import 'shell_harness.dart';

/// ─────────────────────────────────────────────────────────
/// 生成主链路的端到端测试：首页 → 出图 → 结果 → 转视频 → 播放
///
/// 【为什么这一条比别的测试都重要】
/// 因为它是这个产品的**唯一主线**（§13.2）：用户写一句话、拿到一张图、
/// 再把它变成视频。前面每一批的测试都在测零件（「这个 provider 对不对」
/// 「这一页能不能渲染」），而零件全对、拼起来走不通，是很常见的事 ——
/// 路由名字接错了、幂等键传丢了、结果页查错了任务，都会表现为「每一步单测都过，
/// 但用户点下去什么都不发生」。
///
/// 【为什么走的是 Mock 的极简模式】`FakeApiClient()` 不带 latency 时
/// **立刻把任务走完全程**（见它的类注释）。这样一次测试里能真的看到
/// 「提交 → 出结果」的完整闭环，而不是停在一个永远转圈的等待页上。
/// 真实的时间推进由 `fake_api_client_test.dart` 里的状态机测试覆盖。
///
/// 【三条用例分别守什么】
///   1. **主线能走通** —— 从一句话走到会播放的视频（注册送的 50 就够）。
///   2. **作品页收得到货** —— 生成的东西真的出现在用户能找到的地方。
///   3. **没钱时说的话是对的** —— 新用户选 10 秒视频买不起
///      （注册送 50 < 冻结 52），这是个**真实存在**的死路，
///      界面必须把它说清楚、并给出下一步。
///
/// 【第 3 条为什么是 10 秒而不是 5 秒】赠送额原本是 20，那时**任何**视频都买不起
/// （5 秒就要冻 32），死路在「第一次」。现在提到 50，5 秒买得起了，
/// 于是死路退到「选更长的那一档」。**这条用例守的从来不是那个数字，
/// 是「余额不足这条路径的界面还在、还说人话」** —— 所以它必须跟着
/// 定价现实一起挪，而不是删掉。
/// ─────────────────────────────────────────────────────────

/// 一个能装下整页内容的窗口。
///
/// 【为什么不用真机尺寸 390×844】这一页从上到下是「描述 + 参数 + 积分 +
/// 按钮」，在 844 的高上按钮会落到屏幕外，于是每次点击前都要先滚动 ——
/// 那些滚动会把测试写得又长又脆。窗口给高一点，链路本身才是被测的东西。
/// （首页那个「会不会溢出」的测试仍然用真机尺寸，见 create_page_test。）
void useTallWindow(WidgetTester tester) {
  tester.view.physicalSize = const Size(390, 1400);
  tester.view.devicePixelRatio = 1.0;
  addTearDown(tester.view.reset);
}

/// 从首页写一句话、提交、落到图片结果页。
///
/// 【为什么要抽出来】这三条用例里有两条是从这里起步的 ——
/// 抽出来之后，每条用例读起来都是「它自己关心的那件事」，
/// 而不是淹没在八行导航代码里。
Future<void> generateAnImage(WidgetTester tester, String prompt) async {
  await tester.enterText(find.byKey(const Key('home.prompt')), prompt);
  await tester.pump();

  await tester.ensureVisible(find.byKey(const Key('home.generate')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('home.generate')));
  await tester.pumpAndSettle();

  await tester.ensureVisible(find.byKey(const Key('gen.submit')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('gen.submit')));
  await tester.pumpAndSettle();
}

/// 从图片结果页点「做成视频」，落到视频生成页。
Future<void> openVideoGen(WidgetTester tester) async {
  await tester.ensureVisible(find.byKey(const Key('result.toVideo')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('result.toVideo')));
  await tester.pumpAndSettle();
}

/// 点生成页底部的提交按钮。
Future<void> submitGeneration(WidgetTester tester) async {
  await tester.ensureVisible(find.byKey(const Key('gen.submit')));
  await tester.pumpAndSettle();
  await tester.tap(find.byKey(const Key('gen.submit')));
  await tester.pumpAndSettle();
}

void main() {
  testWidgets('首页写一句话 → 出图 → 结果页 → 做成视频 → 视频结果页', (tester) async {
    useTallWindow(tester);
    // 【不再需要补积分】注册送 50 就够跑完这一条：
    // 图片 4 + 视频冻结 32 = 36 ≤ 50。（赠送额是 20 时这里得先演一遍
    // §15.1 的「管理员发积分」。）
    await pumpLoggedInShell(tester);

    // ── 1. 首页：写一句话，点生成 ─────────────────────────
    const prompt = '一只猫在沙滩上奔跑';
    await tester.enterText(find.byKey(const Key('home.prompt')), prompt);
    await tester.pump();

    await tester.ensureVisible(find.byKey(const Key('home.generate')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('home.generate')));
    await tester.pumpAndSettle();

    // ── 2. 图片生成页：打好的字被带过来了 ──────────────────
    expect(find.byType(ImageGenPage), findsOneWidget);
    // 【为什么这条要测】首页那个框看起来就像「在这里写」—— 不带过来的话
    // 用户得重新打一遍，而他会以为刚才那段字丢了。
    expect(
      tester.widget<TextField>(find.byKey(const Key('gen.prompt'))).controller!.text,
      prompt,
    );

    // 提交前不能有确定的价格数字（§13.4），但必须有报价或「计算中…」
    expect(find.textContaining('预计消耗'), findsNothing);

    await submitGeneration(tester);

    // ── 3. 图片结果页 ────────────────────────────────────
    // 【为什么是 pushReplacement】提交流程是把表单页换成结果页，
    // 用户从结果页返回应当回到首页，而不是回到一个已经提交过的表单。
    expect(find.byType(ImageResultPage), findsOneWidget);
    expect(find.byType(ImageGenPage), findsNothing);

    // 生成出来的图必须带「AI 生成」标识（§10.1 是法律义务）
    expect(find.byType(AiGeneratedBadge), findsWidgets);
    expect(find.text(AiGeneratedBadge.label), findsWidgets);

    // 「做成视频」是主线上的下一步
    expect(find.byKey(const Key('result.toVideo')), findsOneWidget);

    // ── 4. 做成视频 ──────────────────────────────────────
    await openVideoGen(tester);

    expect(find.byType(VideoGenPage), findsOneWidget);
    // 【为什么参考图已经选好了】「做成视频」是从**一张具体的图**出发的，
    // 所以进去时那张图就是参考图 —— 不能让用户再选一次。
    expect(find.byKey(const Key('gen.source.selected')), findsOneWidget);
    expect(find.byKey(const Key('gen.source.empty')), findsNothing);
    // 描述也带过来了，改一句就能再提交
    expect(
      tester.widget<TextField>(find.byKey(const Key('gen.prompt'))).controller!.text,
      prompt,
    );

    // ── 5. 提交视频 ─────────────────────────────────────
    await submitGeneration(tester);

    // 【这条断言存在，是因为它大概率会被破坏】万一哪天的改动让提交失败，
    // 用户看到的会是「点了一下，没反应」——
    // 先断言错误条没出现，失败时就能一眼分清是「没提交」还是「提交被拒」。
    expect(find.byKey(const Key('gen.error')), findsNothing);
    expect(find.byType(VideoResultPage), findsOneWidget);

    // ── 6. 视频结果页：封面 + 播放按钮 ─────────────────────
    // 【为什么只断言按钮存在、不点它】`VideoPlayerController.initialize()`
    // 要过平台通道，测试环境里没有 —— 点了这一页的所有测试都会挂，
    // 而且报的是一个和界面无关的平台错误。播放这件事由
    // 「点了才初始化」这个设计保证（见 VideoResultPage 的类注释）。
    expect(find.byKey(const Key('result.play')), findsOneWidget);
    expect(find.byType(AiGeneratedBadge), findsWidgets);

    // 一路走下来不该有未捕获的异常（溢出、无界高度、空指针都会在这里露出来）
    expect(tester.takeException(), isNull);

    await unmountAndDrain(tester);
  });

  testWidgets('作品页：完成的作品出现在网格里，AI 产物带 AI 标识', (tester) async {
    useTallWindow(tester);
    await pumpLoggedInShell(tester);

    // 先真的造一件作品出来（走一遍提交，而不是往 Mock 里塞数据）
    await generateAnImage(tester, '一只猫在沙滩上');

    // 从结果页退回去，然后切到「作品」Tab
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tab.1')));
    await tester.pumpAndSettle();

    // 作品页默认停在「进行中」，切到「已完成」
    await tester.tap(find.byKey(const Key('works.segment.1')));
    await tester.pumpAndSettle();

    // 作品出现，而且是缩略图（不是任务记录那一行）
    expect(find.byType(WorkThumbnail), findsWidgets);
    // AI 出来的那张必须有「AI 生成」标识
    expect(find.text(AiGeneratedBadge.label), findsWidgets);

    await unmountAndDrain(tester);
  });

  /// ─────────────────────────────────────────────────────────
  /// 作品页上「AI 产物」和「用户上传的原图」混在同一格网格里
  ///
  /// 【这条守的是哪件事】守的是**反向**的那半边标识办法：
  /// 铁律说的是「AI 产物必须有标」（漏标 = 违规），而这一条说的是
  /// 「**用户自己拍的/传的图不能被标成 AI**」—— 同样在那部办法的射程里，
  /// 而且是更难解释的那一侧。作品的网格是唯一一处两种东西**混装**的地方：
  /// `GET /assets` 里既有生成出来的图/视频，也有用户为了做视频上传的参考图
  /// （`assets.is_ai_generated = false`，`task_id` 为 null）。
  ///
  /// 【为什么这条以前是绿的、而缺陷是真的】因为当时没有任何东西读
  /// `asset.isAiGenerated`：`WorkThumbnail.showBadge` 默认 `true`，
  /// 于是每一格都打标 —— 上传的那格也打。测试当时只造了 AI 产物，
  /// 所以「每一格都带标」这句话在那条用例里恰好成立，
  /// **把「恒打标」这个 bug 当成了不变量钉住**。这条用例补上另一种资产。
  ///
  /// 【为什么走 repository 上传，而不是往 Mock 里塞一条假资产】
  /// 因为「上传的那条记录是不是 is_ai_generated=false」是**数据层**的事，
  /// 已经由 `fake_api_client_test.dart` / `models_test.dart` 钉住了。
  /// 这条用例要证的只有一件事：**画面上读不读那个字段**。
  /// 从 repository 走一遍，拿到的是和页面上完全一样的那条数据。
  ///
  /// 【断言为什么是「逐格拿它自己的 asset 对」而不是数个数】
  /// 因为「恰好一格有标、一格没有」在将来加了更多资产时会变成假红，
  /// 而真正该永远成立的是**每一格**都满足「有标 ⟺ 它是 AI 产物」。
  /// ─────────────────────────────────────────────────────────
  testWidgets('作品页：上传的参考图不带「AI 生成」标识，AI 产物带', (tester) async {
    useTallWindow(tester);
    final container = await pumpLoggedInShell(tester);

    // ① 一件 AI 产物（走真提交）
    await generateAnImage(tester, '一只猫在沙滩上');

    // ② 一张用户自己上传的图 —— 走页面背后同一条 repository
    await container.read(assetRepositoryProvider).uploadImage(
          bytes: List<int>.filled(2048, 7),
          filename: 'my-photo.png',
          mimeType: 'image/png',
        );
    // 【为什么要主动 refresh】上传走的是 repository，不经过
    // `userAssetsProvider` 的通知链路 —— 它手上的那份列表还是上传前的。
    await container.read(userAssetsProvider.notifier).refresh();

    // ③ 回作品页看
    await tester.pageBack();
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('tab.1')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('works.segment.1')));
    await tester.pumpAndSettle();

    final thumbs =
        tester.widgetList<WorkThumbnail>(find.byType(WorkThumbnail)).toList();

    // 【先钉住两种资产都真的在网格里】不然下面的循环可能在「零格」上空转通过
    expect(thumbs.where((t) => t.asset.isAiGenerated), isNotEmpty,
        reason: 'AI 出的那张应该在网格里');
    expect(thumbs.where((t) => !t.asset.isAiGenerated), isNotEmpty,
        reason: '上传的那张应该在网格里 —— 它是这个缺陷的载体');

    for (final thumb in thumbs) {
      final badge = find.descendant(
        of: find.byWidget(thumb),
        matching: find.byType(AiGeneratedBadge),
      );
      // 【两个方向都要断】只断言「上传的没有标」的话，把整个标识删掉也能过
      expect(
        badge,
        thumb.asset.isAiGenerated ? findsOneWidget : findsNothing,
        reason: 'isAiGenerated=${thumb.asset.isAiGenerated} 的那一格'
            '（${thumb.asset.id}）标识对不对',
      );
    }

    await unmountAndDrain(tester);
  });

  /// ─────────────────────────────────────────────────────────
  /// 新用户买不起 10 秒视频：界面必须把这件事说清楚
  ///
  /// 【为什么这条测的是一条「失败」路径】
  /// 因为它不是异常分支，而是 **v1 的常态**：
  /// 注册送 50 积分（§12.1）< 10 秒视频要冻结的 52（§7.1 + §7.2），
  /// 而 v1 没有充值入口（§7.6）—— 新用户把时长往上拨一档就会撞上这堵墙。
  ///
  /// 这种分支最容易烂：写的时候随手弹一句「操作失败」，
  /// 之后再没有人走到过那里，直到上线当天所有新用户都看见它。
  /// 所以让它进测试，并且断言的不只是「弹了个框」，
  /// 而是**框里有没有把话说到位**（为什么不够、怎么办），
  /// 以及那条「去看积分」是不是真的能走到积分页。
  ///
  /// 【⚠️ 这条用例是 F8 重建过的，不是从 5 秒改个数字】
  /// 赠送额 20→50 之后，5 秒视频（冻结 32）买得起了，「新用户第一次必然撞墙」
  /// 这个事实消失了。如果只是把断言里的数字改掉，就会把这条路径的覆盖
  /// **悄悄删掉** —— 而它正是 B7′ 花了半批功夫修好的那条「假承诺」
  /// （原文案让用户去点一个不存在的「充值」入口）。
  /// 所以改成走「选更长的一档」这条路：死路还在，只是退后了一步。
  /// ─────────────────────────────────────────────────────────
  testWidgets('新用户选 10 秒视频：积分不足要解释清楚，并能一键去看积分', (tester) async {
    useTallWindow(tester);
    // ⚠️ 这一条**故意只走注册赠送的 50 积分** —— 要的就是新用户的原样。
    await pumpLoggedInShell(tester);

    await generateAnImage(tester, '一只猫在沙滩上');
    await openVideoGen(tester);

    // 把时长从默认的 5 秒拨到 10 秒 —— 这一拨就是撞墙的那一下：
    // 5 秒冻结 32（50 买得起），10 秒冻结 (10 + 3) × 4 = 52 > 50。
    await tester.ensureVisible(find.byKey(const Key('gen.duration.10')));
    await tester.pumpAndSettle();
    await tester.tap(find.byKey(const Key('gen.duration.10')));
    await tester.pumpAndSettle();

    await submitGeneration(tester);

    // 没有跳到结果页 —— 提交被拒了，用户还在原地（这点很重要：
    // 有些实现会先把用户导航走再报错，那他就回不来了）
    expect(find.byType(VideoResultPage), findsNothing);
    expect(find.byType(VideoGenPage), findsOneWidget);

    // 弹框：标题说清是什么问题
    //
    // 【为什么是 2 个而不是 1 个】这句话会出现两次：按钮上方的错误条
    // 一次、弹框标题一次。这是刻意的 —— 弹窗关掉之后错误条还在，
    // 用户回头看一眼还知道自己刚才被什么挡住了；
    // 而两处说不一样的话，他会怀疑是不是两个问题。
    expect(find.text('可用积分不足'), findsNWidgets(2));
    // 正文要回答「为什么冻结的比看到的多」——这是用户最想问的那句
    expect(find.textContaining('冻结'), findsWidgets);
    // 并且给出下一步，而不是只有一句「知道了」
    expect(find.byKey(const Key('gen.errorAction')), findsOneWidget);

    // 【这条是 B7 在浏览器里真走了一遍才补上的】
    // 原来错误条写的是「积分不足，**请先充值**」，而 v1 根本没有充值入口
    // （§7.6，积分页一个入口都没有）—— 用户会去找一个不存在的东西。
    // 现在改成「可用积分不足」，并在这里钉死：
    // **这一屏上不许出现「充值」两个字**，因为点了也没地方可去。
    expect(find.textContaining('充值'), findsNothing);

    // 点「去看积分」，真的到积分页
    await tester.tap(find.byKey(const Key('gen.errorAction')));
    await tester.pumpAndSettle();
    expect(find.byType(CreditsPage), findsOneWidget);

    expect(tester.takeException(), isNull);

    await unmountAndDrain(tester);
  });
}

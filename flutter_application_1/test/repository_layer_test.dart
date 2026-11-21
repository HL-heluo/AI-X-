import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/core/constants/error_codes.dart';
import 'package:flutter_application_1/core/network/api_client.dart';
import 'package:flutter_application_1/core/network/api_exception.dart';
import 'package:flutter_application_1/core/network/dio_api_client.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/models/models.dart';
import 'package:flutter_application_1/providers/app_providers.dart';

import 'live_backend.dart';

/// ─────────────────────────────────────────────────────────
/// B3 的**验收测试**：整条数据层通路
///
/// 【它和 fake_api_client_test.dart 的分工】
/// 那个文件测的是「Mock 这个假服务端讲不讲道理」（记账、配额、幂等表）。
/// 这个文件测的是**从 provider → repository → ApiClient 这一整条缝**
/// 有没有接通：
///
///     测试  →  authRepositoryProvider  →  RemoteAuthRepository
///                                          ↓
///                                    apiClientProvider  →  ApiClient
///
/// 【为什么这个测试比看起来重要】
/// 它跑的是**接真后端那天一模一样的那条路径**（Remote* 实现 + DTO 解析 +
/// 错误映射）。它绿，说明「换掉 apiClientProvider 就能上后端」这句话
/// 是真的；它红，说明 DI 某处断了 —— 而这种断法在 Mock 模式下
/// 页面照样能跑（因为页面拿到了数据），只是接后端时才会暴露。
/// 所以**必须在一个不依赖 UI 的地方把它钉住**。
///
/// ─────────────────────────────────────────────────────────
/// 【B2b：这份断言现在会跑两遍】
///
///     默认           flutter test
///       └→ apiClientProvider 给 FakeApiClient，下面 19 条断言全绿
///
///     第二层契约门禁  flutter test --dart-define=USE_MOCK=false \
///                              --dart-define=API_BASE_URL=http://127.0.0.1:8000
///       └→ apiClientProvider 给 DioApiClient，**同样这 19 条**打真后端
///
/// 两份断言一个字都不用改，因为上面那句「接真后端那天一模一样的那条路径」
/// 本来就是这么设计的：切后端只该改一个 if 分支，不该改调用方。
/// 现在这个说法**可以被执行**了 —— 在那之前它只是一句承诺。
///
/// 真有哪条断言两边的结果不同，那正是 B2b 要找的东西：要么后端
/// 不合契约，要么这条断言其实在测 Mock 的实现细节。
/// 门禁的命令与语义见 `live_backend.dart`。
/// ─────────────────────────────────────────────────────────

/// 起一个容器。**Mock 还是真后端由命令行决定**，见 [testContainer]。
///
/// 【用 ProviderContainer.test 而不是 ProviderContainer】
/// 前者是 Riverpod 3.x 提供的测试构造，会在测试结束时自动 dispose 容器。
/// 手写 `addTearDown(container.dispose)` 也行，但漏一次就会让
/// 「容器没 dispose」的检查在整个测试套件末尾才爆出来，很难定位。
ProviderContainer _container() => testContainer();

/// 注册一个用户并返回容器（后续调用都带着登录态）。
///
/// 【为什么走 `registeredContainer` 而不是在这里调 repository】
/// 因为它替我们把登录态**按线上那条路**装好了（落盘 + 写内存副本）。
/// 直接调 repository 的话，真后端模式下每个请求都是裸奔的 —— 全 401。
/// 详见 `live_backend.dart` 里那段说明，那是实测撞出来的。
Future<ProviderContainer> _registered({String username = 'alice'}) =>
    registeredContainer(username: username);

void main() {
  // 【第二层为什么每条用例前都要清库】真后端是**跨用例共享的状态**，
  // 而 Mock 不是（每个容器一个实例）。不重置的话第二条用例注册 `alice`
  // 会撞上第一条留下的 `alice`，失败原因和被测代码毫无关系。
  // 见 `resetLiveBackend` 的注释。Mock 模式下这个 setUp 什么都不做。
  setUp(() async {
    if (isLiveBackend) await resetLiveBackend();
  });

  group('DI 根', () {
    test('apiClientProvider 按配置给出对应的实现', () {
      final c = _container();
      final client = c.read(apiClientProvider);

      // ─────────────────────────────────────────────────────
      // 【这条断言是整个架构承诺的兑现处】
      //
      // 全项目唯一决定「Mock 还是真后端」的地方就是
      // `app_providers.dart` 里 `apiClientProvider` 的那个 if。
      // 所以这里断的不是「拿到了一个客户端」，而是
      // **那个 if 真的按 --dart-define 走了正确的一支**。
      //
      // 上一句 `isA<ApiClient>()` 也不是废话：它钉住的是
      // 「上层只认接口」这条 —— 谁哪天让这个 provider 返回了
      // 一个不是 ApiClient 的东西，这里就红。
      // ─────────────────────────────────────────────────────
      expect(client, isA<ApiClient>());

      if (isLiveBackend) {
        expect(client, isA<DioApiClient>(), reason: 'USE_MOCK=false 必须走真实现');
        expect((client as DioApiClient).baseUrl, runConfig.baseUrl);
      } else {
        expect(client, isA<FakeApiClient>(), reason: '默认必须走 Mock');
      }
    });

    test('每个容器有自己的 ApiClient（一个容器的登录态不泄漏到另一个）', () {
      final a = _container();
      final b = _container();
      expect(identical(a.read(apiClientProvider), b.read(apiClientProvider)),
          isFalse);
    });

    test('同一个容器内重复读拿到同一个实例（Provider 是缓存的）', () {
      final c = _container();
      expect(identical(c.read(apiClientProvider), c.read(apiClientProvider)),
          isTrue);
    });
  });

  group('鉴权通路', () {
    test('注册能解析成 AuthSession，并带上赠送的 50 积分', () async {
      final c = _container();
      final session = await c.read(authRepositoryProvider).register(
            inviteCode: 'MOCK',
            username: 'alice',
            password: 'pw123456',
          );

      expect(session.token, isNotEmpty);
      expect(session.user.username, 'alice');
      expect(session.creditAccount.balance, 50, reason: '§12.1 注册赠 50');
      expect(session.creditAccount.frozen, 0);
      // 【available 是现算的】§7.3：绝不落库，永远 balance − frozen
      expect(session.creditAccount.available, 50);
    });

    test('未登录时受保护接口抛的是「未登录」，而不是别的错误', () async {
      final c = _container();
      await expectLater(
        c.read(meRepositoryProvider).fetchProfile(),
        throwsA(isA<AppException>().having((e) => e.isUnauthorized, '是 401', isTrue)),
      );
    });

    test('注册后 fetchProfile 能解析成 MeProfile', () async {
      final c = await _registered();
      final me = await c.read(meRepositoryProvider).fetchProfile();
      expect(me.user.username, 'alice');
      expect(me.creditAccount.available, 50);
    });
  });

  group('积分通路', () {
    test('流水能解析成 Paged<CreditLedgerEntry>', () async {
      final c = await _registered();
      final page = await c.read(creditRepositoryProvider).fetchLedger();

      expect(page.items, isNotEmpty);
      expect(page.page, 1);
      // 注册赠送那一条
      expect(page.items.first.kind, CreditLedgerKind.grant);
      expect(page.items.first.amount, 50);
    });

    test('estimateCost 走的是 /generation/cost，不是本地定价表', () async {
      final c = await _registered();

      final image = await c.read(generationRepositoryProvider).estimateCost(
            kind: TaskKind.textToImage,
          );
      expect(image.freezeCredits, 4);
      expect(image.isFixed, isTrue, reason: '图片成本固定，应显示「本次冻结 4 积分」');

      final video = await c.read(generationRepositoryProvider).estimateCost(
            kind: TaskKind.imageToVideo,
            durationSec: 5,
          );
      // §7.2：freeze = (输入时长 + 请求时长上限) × 每秒单价
      // 720P 是 4 积分/秒，预留 3 秒余量 → (5 + 3) × 4 = 32
      expect(video.minCredits, 20);
      expect(video.freezeCredits, 32);
      expect(video.isFixed, isFalse, reason: '视频必须显示区间，§13.4 禁止确定数字');
    });

    test('积分不足时抛的是 INSUFFICIENT_CREDITS，UI 才能分支', () async {
      final c = await _registered();
      final gen = c.read(generationRepositoryProvider);

      // 【参考图必须是真的】以前这里写的是 `sourceAssetId: '1'`（Mock 里
      // 谁都不校验，蒙对了）。真后端上那个 id 不存在，而校验顺序是
      // **提示词 → 参考图 → 幂等 → 配额 → 余额**，于是这条用例撞的是
      // 404 NOT_FOUND —— 它仍然会让 `expectLater` 抛出，只是抛的不是
      // 它声称在测的那个码。**一条测 A 却因为 B 而红的用例，比没有更糟**：
      // 它绿的时候你会以为 A 被守住了。
      final refId = await c.read(assetRepositoryProvider).uploadImage(
            bytes: List<int>.filled(1024, 0),
            filename: 'ref.png',
            mimeType: 'image/png',
          );

      // 【为什么是 10 秒】赠送额 20→50 之后，5 秒视频（冻结 32）已经买得起，
      // 但 10 秒的冻结 (10 + 3) × 4 = 52 > 50。
      // 要守的东西没变：**余额不足时 UI 拿得到一个可分支的错误码**。
      await expectLater(
        gen.submitVideo(
          prompt: '一只猫在沙滩上奔跑',
          sourceAssetId: refId,
          durationSec: 10,
          idempotencyKey: 'k-fail',
        ),
        throwsA(isA<AppException>().having(
          (e) => e.code,
          'code',
          ApiErrorCode.insufficientCredits,
        )),
      );

      // 【副作用断言】失败不能扣钱。这是最容易被写错的地方：
      // 先扣再校验，一旦校验失败余额就凭空少了。
      final me = await c.read(meRepositoryProvider).fetchProfile();
      expect(me.creditAccount.balance, 50);
      expect(me.creditAccount.frozen, 0);
    });
  });

  group('生成通路', () {
    test('出图 → 资产可查 → 拿资产 id 去出视频（v1 主链路）', () async {
      final c = await _registered();
      final gen = c.read(generationRepositoryProvider);
      // 【不需要补积分了】注册送的 50 够跑完这一整条链路：
      // 图片 4 + 视频冻结 32 = 36 ≤ 50。（赠送额还是 20 的时候，
      // 这里得先调 `debugGrantCredits(30)` 演一遍 §15.1 的「管理员发积分」。）

      final imageTask = await gen.submitImage(
        prompt: '一只猫在沙滩上奔跑',
        idempotencyKey: 'k1',
      );
      expect(imageTask.kind, TaskKind.textToImage);
      expect(imageTask.status, TaskStatus.succeeded);

      // 从作品列表里找回那张图 —— 提交视频要用它的 asset id
      final assets = await c.read(assetRepositoryProvider).fetchAssets();
      final image = assets.items.firstWhere((a) => a.kind == AssetKind.image);

      final videoTask = await gen.submitVideo(
        prompt: '让它跑起来',
        sourceAssetId: image.id,
        idempotencyKey: 'k2',
      );
      expect(videoTask.kind, TaskKind.imageToVideo);
      expect(videoTask.status, TaskStatus.succeeded);

      // 【这个用例只验「链路通不通」】具体那笔账
      // （50 − 4 − 24 = 22）在下面「余额 = 起步积分 − 实际消耗」里单独验，
      // 免得一条用例同时管两件事，失败了看不出是哪件坏了。
    });

    test('图标资产里没有 provider_url（那是会过期的，不能当真相）', () async {
      final c = await _registered();
      await c.read(generationRepositoryProvider).submitImage(
            prompt: '一只猫在沙滩上奔跑',
            idempotencyKey: 'k1',
          );

      final assets = await c.read(assetRepositoryProvider).fetchAssets();
      expect(assets.items, isNotEmpty);

      // 【为什么去读原始 JSON 而不是查 Asset 的属性】
      // 因为「没有 provider_url 字段」是**契约级**的保证，不是运行时值。
      // 查 Asset 属性只能证明「模型没暴露它」，读原始 JSON 才能证明
      // 服务端（这里是 Mock）也没往下发 —— 两件事都重要，
      // 而模型侧那半已经被「Asset 类里根本没有这个字段」在编译期钉死了。
      final raw = await c.read(apiClientProvider).get('/assets');
      final item = (raw['items'] as List).first as Map<String, dynamic>;
      expect(item.containsKey('provider_url'), isFalse);
      expect(item.containsKey('available'), isFalse,
          reason: 'available 是现算的，不该出现在任何一层的 JSON 里');
    });

    test('作品列表能解析（/tasks 不是分页接口，别套 Paged）', () async {
      final c = await _registered();
      final tasks = c.read(taskRepositoryProvider);
      await c.read(generationRepositoryProvider).submitImage(
            prompt: '一只猫在沙滩上奔跑',
            idempotencyKey: 'k1',
          );

      final done = await tasks.fetchDone();
      expect(done, hasLength(1));
      expect(done.single.status, TaskStatus.succeeded);

      final detail = await tasks.fetchDetail(done.single.id);
      expect(detail.id, done.single.id);
    });

    test('上传参考图返回的是 asset_id（提交视频要用的那个）', () async {
      final c = await _registered();
      final id = await c.read(assetRepositoryProvider).uploadImage(
            bytes: List<int>.filled(1024, 0),
            filename: 'ref.png',
            mimeType: 'image/png',
          );
      expect(id, isNotEmpty);
    });
  });

  group('幂等键 —— 这一组是本批次最该有的测试', () {
    test('同一个 key 提交两次：不报错、不重复扣费、返回同一个任务', () async {
      final c = await _registered();
      final gen = c.read(generationRepositoryProvider);

      final a = await gen.submitImage(prompt: '一只猫', idempotencyKey: 'same');
      final b = await gen.submitImage(prompt: '一只猫', idempotencyKey: 'same');

      // 【为什么断言「不报错」而不是「报 409」】
      // §12.3 规定 DUPLICATE_REQUEST 的客户端行为是**静默复用**。
      // 用户双击了按钮，正确表现是「什么都没发生」，
      // 而不是弹一个红框说他重复了 —— 那会让他以为任务没提交成功，
      // 然后再点一次，那一次如果换了新 key，就真的重复扣钱了。
      expect(b.id, a.id, reason: '必须复用同一个任务，而不是新建一个');

      final me = await c.read(meRepositoryProvider).fetchProfile();
      expect(me.creditAccount.balance, 46, reason: '50 − 4，只扣一次');
      expect(me.creditAccount.frozen, 0);
    });

    test('不同 key 是两次真提交（防双击不能误伤正常重试）', () async {
      final c = await _registered();
      final gen = c.read(generationRepositoryProvider);

      final a = await gen.submitImage(prompt: '一只猫', idempotencyKey: 'k1');
      final b = await gen.submitImage(prompt: '一只猫', idempotencyKey: 'k2');

      expect(b.id, isNot(a.id));
      final me = await c.read(meRepositoryProvider).fetchProfile();
      expect(me.creditAccount.balance, 42, reason: '扣两次');
    });

    test('链路端到端：余额 = 起步积分 − 实际消耗（§15.1 的那笔账）', () async {
      final c = await _registered();
      final me = c.read(meRepositoryProvider);
      final gen = c.read(generationRepositoryProvider);

      // 【起步积分就是注册赠送的 50】§15.1 剧本原来要在注册后再补一笔
      // 「管理员脚本发 50」；赠送额提到 50 之后，注册这一步直接落在这里，
      // 剧本那一步就不需要了 —— 验收算式（余额 = 50 − 实际消耗）原样成立。
      expect((await me.fetchProfile()).creditAccount.balance, 50);

      final image = await gen.submitImage(prompt: '一只猫', idempotencyKey: 'k1');
      expect(image.chargedAmount, 4);

      final assets = await c.read(assetRepositoryProvider).fetchAssets();
      final video = await gen.submitVideo(
        prompt: '跑起来',
        sourceAssetId: assets.items.firstWhere((a) => a.isVideo == false).id,
        idempotencyKey: 'k2',
      );

      // 视频结算额 = (实际输入 0s + 实际输出 6s) × 4 = 24
      // 【为什么是 6 秒】请求 5 秒，两侧都把成片时长算成「请求时长 + 1」——
      // 这里曾经写成「输入 1s + 输出 5s」，那个拆法是错的（输入恒为 0，
      // 图生视频的输入是**一张图**，没有时长）。总数一样是 24，但
      // 「24 是怎么来的」必须写对，否则哪天它变成 20 就没人看得出该查哪儿。
      // 冻结是 32，所以退回 8
      expect(video.freezeAmount, 32);
      expect(video.settledAmount, 24);
      expect(video.refundAmount, 8);
      expect(video.chargedAmount, 24);

      // ★ 这就是 §15.1 的那一行：余额 = 50 − 4 − 24 = 22
      expect((await me.fetchProfile()).creditAccount.balance, 22);
      expect((await me.fetchProfile()).creditAccount.available, 22);
    });

    test('流水记全了三步：冻结 → 结算 → 退回', () async {
      final c = await _registered();

      final image = await c
          .read(generationRepositoryProvider)
          .submitImage(prompt: '一只猫', idempotencyKey: 'k1');

      final ledger = await c.read(creditRepositoryProvider).fetchLedger();
      final kinds = ledger.items
          .where((e) => e.taskId == image.id)
          .map((e) => e.kind)
          .toSet();

      expect(kinds, containsAll(<CreditLedgerKind>[
        CreditLedgerKind.freeze,
        CreditLedgerKind.settle,
      ]));
    });
  });

  group('错误映射', () {
    test('参数写错（少了必填）不该变成业务错误码', () async {
      final c = await _registered();
      await expectLater(
        c.read(generationRepositoryProvider).submitImage(
              prompt: '',
              idempotencyKey: 'k1',
            ),
        throwsA(isA<AppException>().having(
          (e) => e.code,
          'code',
          ApiErrorCode.invalidPrompt,
        )),
      );
    });

    test('userMessage 说人话，message 留给开发', () async {
      final c = _container();
      try {
        await c.read(meRepositoryProvider).fetchProfile();
        fail('应该抛异常');
      } on AppException catch (e) {
        expect(e.userMessage, '登录已过期，请重新登录');
        expect(e.isUnauthorized, isTrue);
      }
    });
  });
}

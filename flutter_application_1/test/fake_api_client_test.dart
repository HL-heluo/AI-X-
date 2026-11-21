import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/core/constants/api_paths.dart';
import 'package:flutter_application_1/core/constants/error_codes.dart';
import 'package:flutter_application_1/core/network/api_exception.dart';
import 'package:flutter_application_1/data/mock/fake_api_client.dart';
import 'package:flutter_application_1/models/models.dart';

/// B3 的验收测试：FakeApiClient
///
/// 【这批测试测的不是「Mock 好不好用」，而是三件契约有没有做对】
///
/// 用户选了「极简 Mock：立即返回成功」，所以状态机、退避、通知这些**可以不真做**。
/// 但下面这三件**不能缩水**，因为它们不是 UX 保真而是**计费与安全的契约**：
///
///   1. 幂等键去重      —— 防连点双扣，写错了用户真的会被扣两次钱
///   2. 冻结→结算→退回  —— 三个数必须真的算，否则接真后端那天账目对不上
///   3. 配额抛 RATE_LIMITED —— 不抛的话，UI 里那些「已达上限」的分支从未被执行过
///
/// 另外还测一条比较容易忽略的：**Mock 返回的 JSON 能不能被 B2 的模型解析**。
/// 这正是「Mock 实现 ApiClient 而不是 Repository」的价值 ——
/// 解析这一层在 Mock 阶段就被真实地走了一遍。
void main() {
  /// 注册并登录一个用户，返回可以直接用的客户端。
  Future<FakeApiClient> loggedIn({
    FakeApiClient? client,
    int grantMore = 0,
  }) async {
    final api = client ?? FakeApiClient();
    await api.post(ApiPaths.register, body: {
      'invite_code': 'MOCK',
      'username': 'tester',
      'password': 'pw123456',
    });
    // 垫积分：v1 不接支付、App 里没有充值入口，所以「手头有很多积分」
    // 这个前提在测试里只能用管理员的调试入口造。
    //
    // 【⚠️ 注册赠送从 20 提到 50 之后，这一段的调用点都相应减了 30】
    // 它们当初的数值不是随便写的，是为了把余额垫到某个总数（比如 120），
    // 好让后面的减法断言（120 − 32）对得上。赠送额变了而垫款不动，
    // 总数就会悄悄漂移 30，断言反而要跟着改 —— 那是本末倒置：
    // 被测的是那句减法，不是垫了多少钱。
    if (grantMore > 0) api.debugGrantCredits(grantMore);
    return api;
  }

  group('认证 §6.1', () {
    test('没登录时任何需要身份接口都抛 401', () async {
      final api = FakeApiClient();
      await expectLater(
        api.get(ApiPaths.me),
        throwsA(isA<AppException>().having((e) => e.isUnauthorized, '是 401', true)),
      );
      await expectLater(
        api.get(ApiPaths.assets),
        throwsA(isA<AppException>().having((e) => e.isUnauthorized, '是 401', true)),
      );
    });

    test('注册送 50 积分，并且**写了流水**', () async {
      final api = await loggedIn();

      final me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.user.username, 'tester');
      expect(me.creditAccount.balance, 50);
      expect(me.creditAccount.frozen, 0);
      expect(me.creditAccount.available, 50);

      // 【为什么这条要单独测】§7.3 要求每一笔都写流水。
      // 只加余额不写流水的话，用户会看到余额 50 但流水是空的，
      // 第一反应是「这钱哪来的」—— 对账能力就是从这种地方崩掉的。
      final ledger = Paged.fromJson(
        await api.get(ApiPaths.creditLedger),
        CreditLedgerEntry.fromJson,
      );
      expect(ledger.items, hasLength(1));
      expect(ledger.items.single.kind, CreditLedgerKind.grant);
      expect(ledger.items.single.amount, 50);
      expect(ledger.items.single.balanceAfter, 50);
    });

    test('缺省三种参数任何一个都要炸 —— 这是调用方的 bug', () async {
      final api = FakeApiClient();
      await expectLater(
        api.post(ApiPaths.register, body: {
          'username': 'a',
          'password': 'b',
          // 少 invite_code
        }),
        throwsA(isA<ArgumentError>()),
      );
    });

    test('用户名重复返回 409', () async {
      final api = await loggedIn();
      await expectLater(
        api.post(ApiPaths.register, body: {
          'invite_code': 'MOCK',
          'username': 'tester',
          'password': 'other',
        }),
        throwsA(isA<AppException>()
            .having((e) => e.httpStatus, '状态码', 409)),
      );
    });

    test('密码错和用户名不存在返回同一句话（不给攻击者当探测器用）', () async {
      final api = await loggedIn();

      String messageOf(Object e) => (e as AppException).message;

      Object? wrongPassword;
      Object? noSuchUser;
      try {
        await api.post(ApiPaths.login,
            body: {'username': 'tester', 'password': 'wrong'});
      } catch (e) {
        wrongPassword = e;
      }
      try {
        await api.post(ApiPaths.login,
            body: {'username': 'nobody', 'password': 'pw123456'});
      } catch (e) {
        noSuchUser = e;
      }

      expect(messageOf(wrongPassword!), messageOf(noSuchUser!));
    });
  });

  group('第 2 道闸 · 幂等键去重（§7.5）', () {
    test('同一个 key 提交两次，第二次抛 DUPLICATE_REQUEST 而不是又建一个任务', () async {
      final api = await loggedIn();

      const key = 'idem-key-0001';
      final first = Task.fromJson(await api.post(
        ApiPaths.generateImage,
        body: {
          'prompt': '一只猫在沙滩上奔跑',
          'aspect_ratio': '1:1',
          'idempotency_key': key,
        },
      ));

      // 第二次：模拟用户双击了生成按钮
      Object? caught;
      try {
        await api.post(ApiPaths.generateImage, body: {
          'prompt': '一只猫在沙滩上奔跑',
          'aspect_ratio': '1:1',
          'idempotency_key': key,
        });
      } catch (e) {
        caught = e;
      }

      final error = caught! as AppException;
      expect(error.code, ApiErrorCode.duplicateRequest);
      expect(error.isDuplicateRequest, isTrue);
      // §12.3 的客户端行为是「静默复用已存在的任务」，所以错误里必须带上任务本体
      expect(error.body?['task'], isNotNull);
      final reused = Task.fromJson(
        (error.body!['task'] as Map).cast<String, dynamic>(),
      );
      expect(reused.id, first.id);

      // 【最要紧的一条断言】只扣了一次钱
      final me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.creditAccount.balance, 50 - 4, reason: '重复提交不能扣两次');
      expect(me.creditAccount.frozen, 0);

      final tasks = await api.get(ApiPaths.tasks);
      expect((tasks['items'] as List), hasLength(1), reason: '不能建出两个任务');
    });

    test('不同的 key 是两次独立提交', () async {
      final api = await loggedIn();
      for (final key in ['k1', 'k2']) {
        await api.post(ApiPaths.generateImage, body: {
          'prompt': '猫',
          'aspect_ratio': '1:1',
          'idempotency_key': key,
        });
      }
      final tasks = await api.get(ApiPaths.tasks);
      expect((tasks['items'] as List), hasLength(2));
    });
  });

  group('第 1 道闸 + §7.2 · 冻结 → 结算 → 退回的真实算术', () {
    test('文生图：成本固定 4 积分，冻结额等于结算额，没有退回', () async {
      final api = await loggedIn();

      final task = Task.fromJson(await api.post(
        ApiPaths.generateImage,
        body: {
          'prompt': '一只猫',
          'aspect_ratio': '1:1',
          'idempotency_key': 'img-1',
        },
      ));

      expect(task.kind, TaskKind.textToImage);
      expect(task.status, TaskStatus.succeeded);
      expect(task.freezeAmount, 4);
      expect(task.settledAmount, 4);
      expect(task.refundAmount, 0);

      final me = MeProfile.fromJson(await api.get(ApiPaths.me));
      // 50（注册赠送）− 4（图片固定价）= 46
      expect(me.creditAccount.balance, 46);
      expect(me.creditAccount.frozen, 0, reason: '结算后冻结必须释放干净');
    });

    test('5 秒 720P 视频：冻结 32、结算 24、退回 8（§7.1 定价）', () async {
      // §15.1 剧本的起步额 50 —— 现在**注册送的就是 50**，
      // 剧本第 2 步那句「管理员脚本发积分」不再需要（赠送额是 20 时才要补 30）。
      final api = await loggedIn();
      var me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.creditAccount.balance, 50);

      // 先出一张图（剧本第 5 步），再拿它去转视频
      await api.post(ApiPaths.generateImage, body: {
        'prompt': '一只猫在沙滩上奔跑',
        'aspect_ratio': '16:9',
        'idempotency_key': 'img-a',
      });

      final upload = await api.upload(
        ApiPaths.uploadImage,
        bytes: List<int>.filled(1024, 0),
        filename: 'cat.png',
      );
      final sourceAssetId = '${upload['asset_id']}';

      final video = Task.fromJson(await api.post(
        ApiPaths.generateVideo,
        body: {
          'prompt': '让这只猫跑起来',
          'source_asset_id': sourceAssetId,
          'ratio': '16:9',
          'duration': 5,
          'idempotency_key': 'vid-a',
        },
      ));

      // 冻结 = (请求时长 5 + 预留 3) × 4 积分/秒 = 32
      expect(video.freezeAmount, 32);
      // 结算 = (输入 0 + 实际成片 6) × 4 = 24（Mock 模拟 Agent 多给了 1 秒）
      expect(video.settledAmount, 24);
      // 退回 = 32 − 24 = 8
      expect(video.refundAmount, 8);

      me = MeProfile.fromJson(await api.get(ApiPaths.me));
      // §15.1 的验收点：余额 = 50 − 实际消耗（图 4 + 视频 24 = 28）= 22
      expect(me.creditAccount.balance, 50 - 4 - 24);
      expect(me.creditAccount.frozen, 0);
    });

    test('三笔流水齐全：freeze → settle → refund', () async {
      final api = await loggedIn();

      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1, 2, 3], filename: 'a.png');
      await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'duration': 5,
        'idempotency_key': 'v',
      });

      final ledger = Paged.fromJson(
        await api.get(ApiPaths.creditLedger),
        CreditLedgerEntry.fromJson,
      );
      final kinds = ledger.items.map((e) => e.kind).toList();

      // 最新的在前面，所以是倒序：refund, settle, freeze, grant, adjust
      expect(kinds, containsAll(<CreditLedgerKind>[
        CreditLedgerKind.freeze,
        CreditLedgerKind.settle,
        CreditLedgerKind.refund,
      ]));

      final freeze = ledger.items.firstWhere((e) => e.kind == CreditLedgerKind.freeze);
      final settle = ledger.items.firstWhere((e) => e.kind == CreditLedgerKind.settle);
      final refund = ledger.items.firstWhere((e) => e.kind == CreditLedgerKind.refund);

      expect(freeze.amount, 32);
      expect(settle.amount, 24);
      expect(refund.amount, 8);
      // settle 和 refund 是同一笔事务的两半，冻结额的释放要对得上
      expect(settle.amount + refund.amount, freeze.amount);

      // §7.3 要求落 balance_after / frozen_after 便于对账
      expect(settle.balanceAfter, isNotNull);
      expect(settle.frozenAfter, 0, reason: '结算后冻结应为 0');
    });

    test('冻结期间「可用」小于「余额」—— 这正是要显示冻结中金额的原因', () async {
      // 【为什么要开 latency 才能测】极简模式下任务瞬间完成，
      // 冻结状态根本来不及被观察到。这是极简 Mock 的已知代价。
      final stage = const Duration(seconds: 5);
      var now = DateTime.utc(2026, 10, 12, 8);
      final api = FakeApiClient(latency: stage, clock: () => now);
      await loggedIn(client: api);

      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'duration': 5,
        'idempotency_key': 'v',
      });

      // 立刻查：任务还在排队，钱处于冻结状态
      var me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.creditAccount.balance, 50, reason: '冻结不动余额');
      expect(me.creditAccount.frozen, 32);
      expect(me.creditAccount.available, 18, reason: '可用 = 余额 − 冻结');

      // 时间走过两个阶段，任务完成
      now = now.add(stage * 3);
      me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.creditAccount.balance, 50 - 24);
      expect(me.creditAccount.frozen, 0);
    });
  });

  group('第 3 道闸 · 配额（§7.5 / §8.2）', () {
    test('每日上限 20 个，第 21 个抛 RATE_LIMITED', () async {
      // 【这条为什么重要】它是**唯一一条不需要开 latency 就能触发的闸门**。
      // 如果 Mock 不抛它，UI 里「已达今日生成上限」那个分支将永远没被执行过。
      final api = await loggedIn(grantMore: 470);

      for (var i = 0; i < 20; i++) {
        await api.post(ApiPaths.generateImage, body: {
          'prompt': '第 $i 张',
          'aspect_ratio': '1:1',
          'idempotency_key': 'daily-$i',
        });
      }

      await expectLater(
        api.post(ApiPaths.generateImage, body: {
          'prompt': '第 21 张',
          'aspect_ratio': '1:1',
          'idempotency_key': 'daily-20',
        }),
        throwsA(isA<AppException>()
            .having((e) => e.code, '错误码', ApiErrorCode.rateLimited)),
      );
    });

    test('图片与视频分开计数 —— 视频在跑时仍然能出图（§8.2）', () async {
      // 混在一个闸门里的话，用户排了个十分钟的视频之后连图都生成不了，
      // 图片会被视频饿死。
      final stage = const Duration(seconds: 5);
      var now = DateTime.utc(2026, 10, 12, 8);
      final api = FakeApiClient(latency: stage, clock: () => now);
      await loggedIn(client: api, grantMore: 70);

      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'duration': 5,
        'idempotency_key': 'v1',
      });

      // 视频还在排队，此时出图应该畅通无阻
      await api.post(ApiPaths.generateImage, body: {
        'prompt': '猫',
        'aspect_ratio': '1:1',
        'idempotency_key': 'i1',
      });

      // 但同类的第二个视频要被挡住
      await expectLater(
        api.post(ApiPaths.generateVideo, body: {
          'prompt': '再来一个',
          'source_asset_id': '${upload['asset_id']}',
          'duration': 5,
          'idempotency_key': 'v2',
        }),
        throwsA(isA<AppException>()
            .having((e) => e.code, '错误码', ApiErrorCode.rateLimited)),
      );
    });

    test('余额不足抛 INSUFFICIENT_CREDITS，且不留下任何痕迹', () async {
      final api = await loggedIn(); // 注册送 50 积分
      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');

      // 【为什么用 10 秒】赠送额从 20 提到 50 之后，5 秒视频（冻结 32）
      // 已经买得起了 —— 但 10 秒的冻结 (10 + 3) × 4 = 52 > 50。
      // 换成长视频而不是回头把赠送额调小：**要保住的是「余额不足
      // 不能有任何副作用」这条断言**，不是「新用户一定买不起 5 秒」那个具体数字。
      await expectLater(
        api.post(ApiPaths.generateVideo, body: {
          'prompt': '动起来',
          'source_asset_id': '${upload['asset_id']}',
          'duration': 10,
          'idempotency_key': 'v',
        }),
        throwsA(isA<AppException>()
            .having((e) => e.code, '错误码', ApiErrorCode.insufficientCredits)),
      );

      // 【充值失败不能有副作用】余额没动、冻结没动、没建任务、没写流水
      final me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.creditAccount.balance, 50);
      expect(me.creditAccount.frozen, 0);
      final tasks = await api.get(ApiPaths.tasks);
      expect((tasks['items'] as List), isEmpty);
      final ledger = Paged.fromJson(
        await api.get(ApiPaths.creditLedger),
        CreditLedgerEntry.fromJson,
      );
      expect(ledger.items, hasLength(1), reason: '只该有注册赠送那一条');
    });

    test('提示词为空或超长抛 INVALID_PROMPT', () async {
      final api = await loggedIn();
      await expectLater(
        api.post(ApiPaths.generateImage, body: {
          'prompt': '   ',
          'idempotency_key': 'x',
        }),
        throwsA(isA<AppException>()
            .having((e) => e.code, '错误码', ApiErrorCode.invalidPrompt)),
      );
      await expectLater(
        api.post(ApiPaths.generateImage, body: {
          'prompt': '猫' * 2001,
          'idempotency_key': 'y',
        }),
        throwsA(isA<AppException>()
            .having((e) => e.code, '错误码', ApiErrorCode.invalidPrompt)),
      );
    });

    test('图生视频没有参考图要就地拦住', () async {
      final api = await loggedIn(grantMore: 70);
      await expectLater(
        api.post(ApiPaths.generateVideo, body: {
          'prompt': '动起来',
          'duration': 5,
          'idempotency_key': 'v',
        }),
        throwsA(isA<AppException>()),
      );
    });
  });

  group('状态机与排队（§8.3 / §8.2）', () {
    test('极简模式：任务提交即成功', () async {
      final api = await loggedIn();
      final task = Task.fromJson(await api.post(ApiPaths.generateImage, body: {
        'prompt': '猫',
        'idempotency_key': 'k',
      }));
      expect(task.status, TaskStatus.succeeded);
    });

    test('开 latency 后走完整状态机，并且排队位次是诚实的', () async {
      final stage = const Duration(seconds: 5);
      var now = DateTime.utc(2026, 10, 12, 8);
      final api = FakeApiClient(latency: stage, clock: () => now);
      await loggedIn(client: api, grantMore: 70);

      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      final submitted = Task.fromJson(await api.post(
        ApiPaths.generateVideo,
        body: {
          'prompt': '动起来',
          'source_asset_id': '${upload['asset_id']}',
          'duration': 5,
          'idempotency_key': 'v',
        },
      ));
      expect(submitted.status, TaskStatus.queued);

      // 排队中：位次必须是 1（前面没人），而不是 null 或 0
      final queued = Task.fromJson(await api.get(ApiPaths.taskDetail(submitted.id)));
      expect(queued.status, TaskStatus.queued);
      expect(queued.queuePosition, 1);

      // 一个阶段后进入 submitted
      now = now.add(stage);
      final processing =
          Task.fromJson(await api.get(ApiPaths.taskDetail(submitted.id)));
      expect(processing.status, TaskStatus.submitted);
      // 【这条是关键】已经提交给 provider 了，前面就没「还有几个人」这回事。
      // 这时显示「前面还有 0 个」是在撒谎 —— 用户会以为马上出结果。
      expect(processing.queuePosition, isNull);

      // 再过一阶段完成
      now = now.add(stage);
      final done = Task.fromJson(await api.get(ApiPaths.taskDetail(submitted.id)));
      expect(done.status, TaskStatus.succeeded);
      expect(done.queuePosition, isNull);
    });

    test('排队中取消全额退回（§7.4）', () async {
      final stage = const Duration(seconds: 5);
      var now = DateTime.utc(2026, 10, 12, 8);
      final api = FakeApiClient(latency: stage, clock: () => now);
      await loggedIn(client: api, grantMore: 70);

      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      final task = Task.fromJson(await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'duration': 5,
        'idempotency_key': 'v',
      }));

      final canceled = Task.fromJson(
        await api.post(ApiPaths.taskCancel(task.id)),
      );
      expect(canceled.status, TaskStatus.canceled);
      expect(canceled.settledAmount, 0);

      final me = MeProfile.fromJson(await api.get(ApiPaths.me));
      // 注册送 50 + 垫 70 = 120
      expect(me.creditAccount.balance, 120, reason: '排队中取消要全额退回');
      expect(me.creditAccount.frozen, 0);
    });

    test('已提交给 provider 后取消**不退**（§7.4）', () async {
      // 【为什么这条必须如实实现】如果 Mock 一律全退，UI 上
      // 「取消会不会扣钱」的提示就永远是错的，用户会在真的被扣钱时投诉。
      final stage = const Duration(seconds: 5);
      var now = DateTime.utc(2026, 10, 12, 8);
      final api = FakeApiClient(latency: stage, clock: () => now);
      await loggedIn(client: api, grantMore: 70);

      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      final task = Task.fromJson(await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'duration': 5,
        'idempotency_key': 'v',
      }));

      // 推进到 submitted：provider 已经在跑了，钱已经花出去了
      now = now.add(stage);
      expect(
        Task.fromJson(await api.get(ApiPaths.taskDetail(task.id))).status,
        TaskStatus.submitted,
      );

      final canceled =
          Task.fromJson(await api.post(ApiPaths.taskCancel(task.id)));
      expect(canceled.status, TaskStatus.canceled);
      expect(canceled.settledAmount, 32, reason: '已提交后取消按冻结额实扣');

      final me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.creditAccount.balance, 120 - 32);
      expect(me.creditAccount.frozen, 0);
    });

    test('终态任务不能再取消', () async {
      final api = await loggedIn();
      final task = Task.fromJson(await api.post(ApiPaths.generateImage, body: {
        'prompt': '猫',
        'idempotency_key': 'k',
      }));
      await expectLater(
        api.post(ApiPaths.taskCancel(task.id)),
        throwsA(isA<AppException>()),
      );
    });
  });

  group('任务列表与作品（§12.1）', () {
    test('?status=active / done 分别筛出进行中与已结束', () async {
      final stage = const Duration(seconds: 5);
      var now = DateTime.utc(2026, 10, 12, 8);
      final api = FakeApiClient(latency: stage, clock: () => now);
      await loggedIn(client: api, grantMore: 170);

      // 一个已完成的图 + 一个进行中的视频
      await api.post(ApiPaths.generateImage, body: {
        'prompt': '猫',
        'idempotency_key': 'i',
      });
      // 【必须把时钟往前拨，图片才会真的走完两个阶段】
      // 开着 latency 时任务不是瞬间完成的，时钟不动它就永远停在 queued。
      now = now.add(stage * 3);

      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'duration': 5,
        'idempotency_key': 'v',
      });

      final active = await api.get(ApiPaths.tasks, query: {'status': 'active'});
      final done = await api.get(ApiPaths.tasks, query: {'status': 'done'});
      expect((active['items'] as List), hasLength(1));
      expect((done['items'] as List), hasLength(1));
      expect(
        Task.fromJson((active['items'] as List).first as Map<String, dynamic>)
            .kind,
        TaskKind.imageToVideo,
      );
    });

    test('视频成功后会落一份视频 + 一份封面', () async {
      // 作品列表一屏要摆九个视频，都用视频文件当封面的话流量和内存都会炸
      final api = await loggedIn();
      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'duration': 5,
        'idempotency_key': 'v',
      });

      final assets = Paged.fromJson(
        await api.get(ApiPaths.assets),
        Asset.fromJson,
      );
      final kinds = assets.items.map((a) => a.kind).toList();
      // 上传的参考图 + 视频 + 封面
      expect(kinds, containsAll(<AssetKind>[
        AssetKind.image,
        AssetKind.video,
        AssetKind.thumbnail,
      ]));

      // 平台产物必须带 AI 生成标识（§10.1 是法律义务）
      final video = assets.items.firstWhere((a) => a.kind == AssetKind.video);
      expect(video.isAiGenerated, isTrue);
      // 而用户自己上传的原图不该被标成 AI 生成
      final uploaded = assets.items.firstWhere((a) => a.kind == AssetKind.image);
      expect(uploaded.isAiGenerated, isFalse);
    });
  });

  group('契约形状守卫', () {
    test('任务 JSON 里**不许**出现 provider_url（§11.2 说它只作中转）', () async {
      // 【为什么 Mock 也守这条】provider 的 URL 只活 1 小时，绝不能当资产真身。
      // Mock 一旦返回它，App 里就会有人图省事直接用 —— 然后在真实环境里
      // 出现「一小时前还能看的作品，现在全是裂图」。
      final api = await loggedIn();
      final raw = await api.post(ApiPaths.generateImage, body: {
        'prompt': '猫',
        'idempotency_key': 'k',
      });
      expect(raw.containsKey('provider_url'), isFalse);
    });

    test('积分账户 JSON 里**不许**出现 available —— 它必须由客户端现算', () async {
      // §7.3：可用余额永远现算，不单独存字段。服务端和客户端两边都不存，
      // 就不可能不一致。
      final api = await loggedIn();
      final raw = await api.get(ApiPaths.me);
      final account = (raw['credit_account'] as Map).cast<String, dynamic>();
      expect(account.containsKey('available'), isFalse);
      expect(account['balance'], 50);
      expect(account['frozen'], 0);
    });

    test('Mock 的返回能被 B2 的模型全部解析（这是 Mock 下单层级的价值）', () async {
      final api = await loggedIn();
      final upload = await api.upload(ApiPaths.uploadImage,
          bytes: [1], filename: 'a.png');
      await api.post(ApiPaths.generateVideo, body: {
        'prompt': '动起来',
        'source_asset_id': '${upload['asset_id']}',
        'ratio': '16:9',
        'duration': 5,
        'idempotency_key': 'v',
      });

      // 一个都不许解析失败 —— 这正是「Mock 实现 ApiClient 而不是 Repository」
      // 换来的：解析层在 Mock 阶段就被真实地跑过一遍
      final me = MeProfile.fromJson(await api.get(ApiPaths.me));
      expect(me.user.id, isNotEmpty);

      final tasks = Paged.fromJson(
        await api.get(ApiPaths.tasks),
        Task.fromJson,
      );
      expect(tasks.items.single.params.ratio, '16:9');
      expect(tasks.items.single.params.duration, 5);

      final assets = Paged.fromJson(
        await api.get(ApiPaths.assets),
        Asset.fromJson,
      );
      expect(assets.items, isNotEmpty);

      final ledger = Paged.fromJson(
        await api.get(ApiPaths.creditLedger),
        CreditLedgerEntry.fromJson,
      );
      expect(ledger.items, isNotEmpty);
    });

    test('删除资产后列表里就没有了', () async {
      final api = await loggedIn();
      await api.post(ApiPaths.generateImage, body: {
        'prompt': '猫',
        'idempotency_key': 'k',
      });
      var assets = Paged.fromJson(
        await api.get(ApiPaths.assets),
        Asset.fromJson,
      );
      expect(assets.items, hasLength(1));

      await api.delete(ApiPaths.assetDetail(assets.items.single.id));

      assets = Paged.fromJson(
        await api.get(ApiPaths.assets),
        Asset.fromJson,
      );
      expect(assets.items, isEmpty);
    });
  });
}

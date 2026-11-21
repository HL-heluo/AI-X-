/// B2b · **第二层契约门禁** —— 这一整个文件只在打真后端时跑
///
/// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
///     flutter test --concurrency=1 \
///                  --dart-define=USE_MOCK=false \
///                  --dart-define=API_BASE_URL=http://127.0.0.1:8000
///
/// 【`--concurrency=1` 缺了会怎样】见 `live_backend.dart` 里那段说明 ——
/// 简言之：两个 live 文件并行时会互相清库，报出来一片像业务错误的假象。
///
/// 默认的 `flutter test` 里，这个文件里的用例**全部 skip**（输出里看得见
/// `~N -M: skipped`），因为它们要一个活着的后端，而默认跑测试不该依赖
/// 任何外部进程。接线件与命令见 `live_backend.dart`。
///
/// ─────────────────────────────────────────────────────────
/// 【它和 `repository_layer_test.dart` 的分工】
///
/// 那个文件问的是「**这条通路通不通**」—— 它用同一份断言打 Mock 和真后端，
/// 证明「换掉 apiClientProvider 就能上后端」这句话是真的。
///
/// 这个文件问的是另一种问题：**「后端有没有在撒谎」**。
/// 通不通是一回事（返回了 200 且能解析），说的是不是真话是另一回事。
/// 具体钉四件事：
///
///   1. **路径清单不许漂移** —— 对着后端自己吐的 `/openapi.json` 比，
///      不抄一份会过期的列表。少一个 / 多一个都红。
///   2. **响应形状**（读**原始 JSON**，不读解析后的模型）——
///      「没有 `available`」「id 是整数」「时间带时区」这些都是
///      契约级保证，只有读原始字节才能证明服务端真的没往下发。
///   3. **错误码不许撒谎** —— 每个能触发的错，都要落到前端认得出的
///      `ApiErrorCode` 上，并且 HTTP 状态码要和前端自己声明的一致。
///   4. **覆盖台账** —— 前端认识的每个错误码，要么在这里被真触发过，
///      要么有一条写明「为什么在 B2 触发不了」。加了新枚举值却没交代，
///      这里就红。
/// ─────────────────────────────────────────────────────────
/// 【为什么第 3 条值得单独写这么重】
///
/// 前端的 `_friendlyMessage` 在 `e.code == null` 时会说
/// **「连不上服务器，检查一下网络再试」** —— 这是一句会让人去拔网线的话。
/// 它只有在「后端发的码前端真的认不出」时才会出现，而那一刻的现场是：
/// 网络好得很、后端日志 200、用户正在重启路由器。
///
/// 所以「后端发的码必须在前端的枚举里」不是洁癖，是**不许让 App 撒谎**。
/// ━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
library;

import 'package:flutter_riverpod/flutter_riverpod.dart';
import 'package:flutter_test/flutter_test.dart';

import 'package:flutter_application_1/core/constants/api_paths.dart';
import 'package:flutter_application_1/core/constants/error_codes.dart';
import 'package:flutter_application_1/core/network/api_client.dart';
import 'package:flutter_application_1/core/network/api_exception.dart';
import 'package:flutter_application_1/providers/app_providers.dart';

import 'live_backend.dart';

/// 跳过原因（**写在 skip 里，输出里看得见** —— 静默通过比没有门禁更危险）。
const String _needLive = '需要真后端：flutter test --dart-define=USE_MOCK=false '
    '--dart-define=API_BASE_URL=http://127.0.0.1:8000';

/// 注册一个用户并返回容器 —— 登录态由**线上那条路**装好（见 [registeredContainer]）。
Future<ProviderContainer> _registered({String username = 'alice'}) =>
    registeredContainer(username: username);

/// 从容器里取那个**真的**网络客户端（`apiClientProvider` 的 DioApiClient 分支）。
ApiClient _client(ProviderContainer c) => c.read(apiClientProvider);

/// 取 token（裸请求要自己带鉴权头）。
Future<String> _registerRaw({String username = 'alice'}) async {
  final res = await rawRequest(
    ApiPaths.register,
    method: 'POST',
    body: <String, dynamic>{
      'invite_code': 'MOCK',
      'username': username,
      'password': 'pw123456',
    },
  );
  // 注册是 **201**（后端 `status_code=HTTP_201_CREATED`：创建了一个资源）。
  // 前端的 `_send` 只判「`<200 || >=300` 才抛」，所以 2xx 一律放行 ——
  // 这里写死 201 是记录契约现状，不是「只认 201」。
  expect(res.statusCode, 201, reason: '夹具自己坏了：注册没成功 → ${res.data}');
  return (res.data as Map)['token'] as String;
}

/// 跑一次**本该失败**的请求，把 [AppException] 取回来。
///
/// 【为什么吃 `on AppException` 而不是 `catch (e)`】因为它以外的异常
/// （`FormatException`、`StateError`）**不该被这里吞掉** —— 那些是
/// 「响应根本不是契约形状」，是真事故，应该原样炸出来，而不是被
/// 伪装成「后端返回了一个错误」。
Future<AppException> _failureOf(Future<void> Function() call) async {
  try {
    await call();
  } on AppException catch (e) {
    return e;
  }
  fail('这次请求本该失败（期待一个 AppException），但它成功了');
}

/// 「后端这个错，前端接得住吗」—— 这个文件里所有错误断言都从它过。
void _assertDoesNotLie(AppException e, {ApiErrorCode? expected}) {
  if (expected != null) {
    expect(
      e.code,
      expected,
      reason: '后端发的码前端必须认得出。认不出的话登录页会去说'
          '「连不上服务器，检查一下网络再试」—— 那是一句撒谎的话，'
          '用户会去拔网线。原始 message：${e.message}',
    );
  }

  final code = e.code;
  if (code == null) return;

  // 【这一条是「两张表不许各说各话」】前端 `ApiErrorCode` 每个成员都声明了
  // 一个 `httpStatus`，UI 里确实有按状态码分支的地方（登录页看 401/409）。
  // 后端改了状态码而前端没跟着改，表现是那种分支走到别处去。
  expect(
    e.httpStatus,
    code.httpStatus,
    reason: '前端 ApiErrorCode.${code.name} 声明的是 HTTP ${code.httpStatus}，'
        '后端实际给了 ${e.httpStatus}。两张表对不上，按状态码分支的 UI 会走错。',
  );

  // 认得出码就不该落到通用兜底文案上。
  expect(e.userMessage, code.defaultMessage);
}

/// 递归收集 JSON 里出现过的**所有**键名 —— 用来证明某个字段「哪儿都没有」。
///
/// 【为什么要递归】`available` 若藏在 `items[0]` 里，只看顶层是查不到的；
/// 而它一旦出现在任何一层，前端那半「现算」的承诺就有一处会对不上。
Set<String> _allKeysDeep(Object? node) {
  final found = <String>{};
  void walk(Object? n) {
    if (n is Map) {
      n.forEach((k, v) {
        found.add(k.toString());
        walk(v);
      });
    } else if (n is List) {
      for (final e in n) {
        walk(e);
      }
    }
  }

  walk(node);
  return found;
}

/// 带时区标记的 ISO 8601。
///
/// 【为什么这条必须有】`DateTime.tryParse("2026-10-13T06:00:00")` 是**成功**的
/// —— 它把那个串当**本地时间**。后端若哪天改用 naive UTC（一个很自然的
/// 手滑），App 在东八区会把每条流水的时间显示成早 8 小时，而且**不报错**。
/// 所以这里只认 `Z` 或 `±HH:MM` 结尾。
final RegExp _isoWithZone = RegExp(r'(Z|[+-]\d{2}:\d{2})$');

/// 把 `/tasks/{task_id}` 和 `/tasks/{id}` 归一成 `/tasks/{}`。
///
/// 【为什么不能逐字比】FastAPI 把路径参数名原样写进 openapi
/// （后端写的是 `{task_id}`），而前端拼串时用的是它自己的占位
/// （`taskDetail('{id}')`）。**参数叫什么名字不重要** —— 它是一个位置，
/// 不是一个字段。归一之后比的才是「是不是同一条路径」。
String _normalizePath(String p) => p.replaceAll(RegExp(r'\{[^}]+\}'), '{}');

void main() {
  group('B2b 契约门禁（打真后端）', () {
    // 真后端是**跨用例共享状态**，每条用例前清库（见 resetLiveBackend 的注释）。
    setUp(() async {
      await resetLiveBackend();
    });

    // ════════════════════════════════════════════════════════
    // 一、路径清单不许漂移
    // ════════════════════════════════════════════════════════
    group('路径清单', () {
      test('前后端的端点清单**完全一致**（对着后端自己的 openapi.json 比）', () async {
        final res = await rawRequest('/openapi.json');
        expect(
          res.statusCode,
          200,
          reason: 'openapi.json 是 FastAPI 自带的，被关掉就没法做这条门禁了。'
              '它只描述**契约**，不泄漏任何运行时数据。',
        );

        final paths = (res.data as Map)['paths'] as Map;

        // 只看我们自己的业务前缀 —— `/health`、`/media/*`、`/__test/*`
        // 不在 §12.1 的清单里，不该参与比较。
        const businessPrefixes = <String>[
          '/auth',
          '/credits',
          '/generation',
          '/tasks',
          '/assets',
          '/uploads',
        ];
        bool isBusiness(String p) =>
            p == ApiPaths.me || businessPrefixes.any(p.startsWith);

        final backendRoutes = <String>{};
        paths.forEach((rawPath, ops) {
          final p = rawPath.toString();
          if (!isBusiness(p)) return;
          (ops as Map).forEach((method, _) {
            backendRoutes.add('${method.toString().toUpperCase()} ${_normalizePath(p)}');
          });
        });

        // 【下面这份清单的唯一出处是 `ApiPaths`】不是我抄的常量 ——
        // `taskDetail('{id}')` 就是前端拼路径用的那个函数，占位符随便填一个。
        // 前端改了 `ApiPaths`，这里跟着改，后端不跟就红。
        final frontendRoutes = <String>{
          'POST ${ApiPaths.register}',
          'POST ${ApiPaths.login}',
          'GET ${ApiPaths.me}',
          'GET ${ApiPaths.creditLedger}',
          'GET ${ApiPaths.creditChain}',
          'POST ${ApiPaths.uploadImage}',
          'POST ${ApiPaths.generateImage}',
          'POST ${ApiPaths.generateVideo}',
          'GET ${ApiPaths.generationCost}',
          'GET ${ApiPaths.tasks}',
          'GET ${_normalizePath(ApiPaths.taskDetail('{id}'))}',
          'POST ${_normalizePath(ApiPaths.taskCancel('{id}'))}',
          'GET ${ApiPaths.assets}',
          'GET ${_normalizePath(ApiPaths.assetEvidence('{id}'))}',
          'DELETE ${_normalizePath(ApiPaths.assetDetail('{id}'))}',
        };

        // Base routes plus the read-only VCR and video evidence endpoints.
        expect(frontendRoutes, hasLength(15));
        expect(backendRoutes, hasLength(15));

        // 三个方向都要看：两边都有的、后端多了的、后端少了的。
        expect(
          backendRoutes.difference(frontendRoutes),
          isEmpty,
          reason: '后端多出了前端不认识的端点。多一个端点不是免费的 —— '
              '它是一条没人测、没人用的对外接口。要么前端补上，要么后端删掉。',
        );
        expect(
          frontendRoutes.difference(backendRoutes),
          isEmpty,
          reason: '前端在用而后端没有的端点 —— 这些路径在真机上会 404。'
              '最可能的病因是路径改名/拼错，而本地 Mock 永远发现不了。',
        );
      });

      test('连的是 fake provider 的后端（否则这个文件的前提就不成立）', () async {
        final res = await rawRequest('/health');
        expect(res.statusCode, 200);
        final body = (res.data as Map).cast<String, dynamic>();

        // 【为什么要断这条】下面「冻结 32 / 结算 24」那些断言，前提是
        // 假 provider 那个「提交即完成 + 成片比请求长 1 秒」的行为。
        // 若有人把这个文件对着一个 jimeng 后端跑，失败会是一片看不懂的
        // 数字对不上 —— 在这里断掉，报错信息就直说了。
        expect(
          body['provider'],
          'fake',
          reason: '第二层契约门禁必须对着 PROVIDER=fake 的后端跑。',
        );
      });
    });

    // ════════════════════════════════════════════════════════
    // 二、响应形状 —— 读**原始 JSON**
    // ════════════════════════════════════════════════════════
    //
    // 【为什么不读解析后的模型】读模型只能证明「前端没崩」，证明不了
    // 「服务端没多发字段」。`available` 和 `provider_url` 是两条
    // 有守卫测试盯着的契约，而守卫的正是在服务端那一侧。
    group('响应形状（原始 JSON）', () {
      test('注册返回的是裸对象（没有信封）', () async {
        final res = await rawRequest(
          ApiPaths.register,
          method: 'POST',
          body: <String, dynamic>{
            'invite_code': 'MOCK',
            'username': 'alice',
            'password': 'pw123456',
          },
        );
        // 【为什么是 201】注册创建了一个资源，后端显式声明了 201。
        // 前端的成功判定是区间（`status < 200 || status >= 300`），
        // 所以 201 与 200 对 App 是一回事 —— 但契约里是哪个要记下来，
        // 免得下次有人看到 201 以为出错了。
        expect(res.statusCode, 201, reason: '注册是创建资源 → 201');
        final body = (res.data as Map).cast<String, dynamic>();

        // 【信封的三种常见长相】全断掉。前端的 `_decode` 假设响应体就是
        // 那个对象本身；一旦外面包一层，`token` 会读成 null，
        // 用户的体验是「登录成功但立刻又退回登录页」。
        expect(body.keys.toSet(), <String>{'token', 'user', 'credit_account'});
        for (final envelope in <String>['data', 'code', 'result', 'payload']) {
          expect(body.containsKey(envelope), isFalse,
              reason: '响应体被包了一层信封（多了「$envelope」）');
        }
      });

      test('所有 id 都是 JSON 整数，不是字符串', () async {
        final token = await _registerRaw();
        final me = (await rawRequest(ApiPaths.me, token: token)).data as Map;
        final user = (me['user'] as Map).cast<String, dynamic>();

        // 前端的 `requireInt` 对字符串 id 会**抛 FormatException**（不是宽进），
        // 所以后端把 id 发成 "1" 的后果是整页白屏。
        expect(user['id'], isA<int>(), reason: 'id 必须是 JSON 整数');

        final ledger = (await rawRequest(ApiPaths.creditLedger, token: token)).data
            as Map;
        final entry = ((ledger['items'] as List).first as Map)
            .cast<String, dynamic>();
        expect(entry['id'], isA<int>());
        expect(entry['user_id'], isA<int>());
        expect(entry['amount'], isA<int>());
        expect(entry['balance_after'], isA<int>());
        expect(entry['frozen_after'], isA<int>());
      });

      test('available 在**任何一层**都不出现（它是前端现算的）', () async {
        final c = await _registered();
        await c.read(generationRepositoryProvider).submitImage(
              prompt: '一只猫在沙滩上奔跑',
              idempotencyKey: 'k1',
            );

        // 四个接口全扫一遍。`available` 一旦出现，就意味着有两个真相：
        // 服务端发的那个和前端 balance − frozen 算出来的那个。
        // 它们迟早会不一样，而用户会拿着两个数字来问哪个是真的。
        for (final path in <String>[
          ApiPaths.me,
          ApiPaths.creditLedger,
          ApiPaths.assets,
          ApiPaths.tasks,
        ]) {
          final res = await rawRequest(path, token: await _currentToken(c));
          expect(res.statusCode, 200, reason: '$path 没打通');
          expect(
            _allKeysDeep(res.data),
            isNot(contains('available')),
            reason: '$path 的响应里出现了 available。它是 `balance − frozen` '
                '现算的（§7.3），**绝不落库也不该下发**。',
          );
        }
      });

      test('资产里没有 provider_url / storage_key（临时地址与内部路径都不能外泄）', () async {
        final c = await _registered();
        await c.read(generationRepositoryProvider).submitImage(
              prompt: '一只猫在沙滩上奔跑',
              idempotencyKey: 'k1',
            );

        final res = await rawRequest(ApiPaths.assets, token: await _currentToken(c));
        final keys = _allKeysDeep(res.data);

        // provider_url 只活 1 小时 —— 存进 App 的缓存后必然是死链；
        // storage_key 是我们对象存储里的内部路径，换存储时要改它，
        // 对外只该有 public_url。
        expect(keys, isNot(contains('provider_url')));
        expect(keys, isNot(contains('storage_key')));

        final item = ((res.data as Map)['items'] as List).first
            as Map<String, dynamic>;
        expect(item['public_url'], isA<String>());
        // 【法律义务字段】§10.1 要求 AI 生成标识恒为真，且必须是**真布尔**
        // —— 前端的 `boolOr` 对 `'true'` 和 `1` 都抛，它刻意不接受
        // 「像布尔的东西」。
        expect(item['is_ai_generated'], isA<bool>());
      });

      test('任务的 params 是对象（不是 params_json），且客户端给的 ratio 原样回来', () async {
        final c = await _registered();
        await c.read(generationRepositoryProvider).submitVideo(
              prompt: '让它跑起来',
              sourceAssetId: await _uploadRef(c),
              durationSec: 5,
              // 【必须显式给 ratio】前端 `TaskParams.toJson` 会**省略值为 null
              // 的键**。不给的话 `params` 里就没有 `ratio` 这一项，
              // 而断言「ratio 不为 null」会红 —— 那条断言只能证明
              // 「前端确实发了」，证明不了「后端原样存回来了」。
              ratio: '16:9',
              idempotencyKey: 'k1',
            );

        final res = await rawRequest(
          '${ApiPaths.tasks}?status=done',
          token: await _currentToken(c),
        );
        final item = ((res.data as Map)['items'] as List).first
            as Map<String, dynamic>;

        expect(item['params'], isA<Map>(),
            reason: '对外是 `params` 对象，不是 `params_json` 字符串');
        expect(item.containsKey('params_json'), isFalse);
        expect((item['params'] as Map)['ratio'], '16:9');
      });

      test('时间戳带时区标记（naive 时间会让 App 差 8 小时且不报错）', () async {
        final token = await _registerRaw();

        final me = (await rawRequest(ApiPaths.me, token: token)).data as Map;
        final ledger =
            (await rawRequest(ApiPaths.creditLedger, token: token)).data as Map;

        final stamps = <String>[
          ((me['user'] as Map)['created_at']).toString(),
          ((me['credit_account'] as Map)['updated_at']).toString(),
          (((ledger['items'] as List).first as Map)['created_at']).toString(),
        ];

        for (final s in stamps) {
          expect(
            s,
            matches(_isoWithZone),
            reason: '时间戳「$s」没有时区标记。`DateTime.tryParse` 会把它当'
                '**本地时间**读，于是在东八区每条流水都差 8 小时 —— 而且不报错。',
          );
        }
      });

      test('queue_position 在非 queued 任务上是 null（而不是 0）', () async {
        final c = await _registered();
        final task = await c.read(generationRepositoryProvider).submitImage(
              prompt: '一只猫在沙滩上奔跑',
              idempotencyKey: 'k1',
            );

        final res = await rawRequest(
          ApiPaths.taskDetail(task.id),
          token: await _currentToken(c),
        );
        final body = (res.data as Map).cast<String, dynamic>();

        expect(body['status'], 'succeeded');
        // 0 和 null 是两回事：0 意味着「你排在第一个」，会渲染成
        // 「前面还有 0 位」。只有 queued 时才有位次。
        expect(body['queue_position'], isNull);
        // 成功必有结算额 —— 表约束也钉了这一条。
        expect(body['settled_amount'], isA<int>());
      });
    });

    // ════════════════════════════════════════════════════════
    // 三、错误码不许撒谎
    // ════════════════════════════════════════════════════════
    group('错误码映射', () {
      test('邀请码无效 → INVITE_INVALID（不是那句「连不上服务器」）', () async {
        final c = testContainer();
        final e = await _failureOf(() => _client(c).post(
              ApiPaths.register,
              body: <String, dynamic>{
                'invite_code': 'NOPE-2026',
                'username': 'alice',
                'password': 'pw123456',
              },
            ));

        _assertDoesNotLie(e, expected: ApiErrorCode.inviteInvalid);
        expect(e.userMessage, '邀请码无效，请确认后再试');
      });

      test('空提示词 → INVALID_PROMPT（**不许**退化成 INVALID_REQUEST）', () async {
        final c = await _registered();
        final e = await _failureOf(() => _client(c).post(
              ApiPaths.generateImage,
              body: <String, dynamic>{
                'prompt': '',
                'idempotency_key': 'k-empty',
              },
            ));

        // 【为什么这一条特别重要】空提示词是**业务**校验，用户能自己改。
        // 若后端把 Field(min_length=1) 写进 pydantic，它会**先被拦成**
        // 形状错误 —— 服务端确实拒绝了，但理由码不对，用户看到的是
        // 一句和「提示词」毫无关系的通用文案。
        _assertDoesNotLie(e, expected: ApiErrorCode.invalidPrompt);
      });

      test('积分不足 → INSUFFICIENT_CREDITS，且余额一分没动', () async {
        final c = await _registered();

        // 【必须先传参考图】后端的校验顺序是照抄 Mock 的，一步都不许挪：
        //   提示词 → 参考图 → 幂等 → 配额 → **余额**
        // 所以「10 秒视频 + 没参考图」撞上的是 INVALID_REQUEST
        // （「图生视频必须提供 source_asset_id」），**根本走不到余额那道闸**。
        // 这条测试一开始就是这么错的，报错信息长得很像后端 bug。
        final refId = await _uploadRef(c);

        final e = await _failureOf(() => _client(c).post(
              ApiPaths.generateVideo,
              body: <String, dynamic>{
                'prompt': '一只猫在沙滩上奔跑',
                'idempotency_key': 'k-poor',
                'source_asset_id': refId,
                // 注册送 50；10 秒视频要冻 (10+3)×4 = 52 > 50
                'duration': 10,
              },
            ));

        _assertDoesNotLie(e, expected: ApiErrorCode.insufficientCredits);

        // 【副作用断言】被拒之后余额、冻结算一个都不能动 ——
        // 「先冻结再校验」是最容易写错、也最难发现的一种错。
        final me = await c.read(meRepositoryProvider).fetchProfile();
        expect(me.creditAccount.balance, 50);
        expect(me.creditAccount.frozen, 0);
      });

      test('幂等重放 → DUPLICATE_REQUEST，且**体里带着已有任务**', () async {
        final c = await _registered();
        final gen = c.read(generationRepositoryProvider);
        final first = await gen.submitImage(prompt: '一只猫', idempotencyKey: 'same');

        final e = await _failureOf(() => _client(c).post(
              ApiPaths.generateImage,
              body: <String, dynamic>{
                'prompt': '一只猫',
                'idempotency_key': 'same',
              },
            ));

        _assertDoesNotLie(e, expected: ApiErrorCode.duplicateRequest);

        // 【这条断言是前端「静默复用」的地基】`RemoteGenerationRepository`
        // 的 `_submitOrReuse` 直接读 `e.body!['task']` 来复用那个任务。
        // 后端哪天忘了带 `task`，用户双击按钮就会看到 Null check 崩溃
        // —— 而 Mock 一直带着它，所以本地永远测不出来。
        expect(e.body, isNotNull);
        expect(e.body!['task'], isA<Map>());
        // 【为什么左边要 toString】线上的 id 是 JSON 整数，而前端的
        // `Task.id` 是 String（模型统一这么存）。比的必须是**同一个任务**，
        // 不是同一种类型 —— 类型差异本身在下面那条「id 是整数」里有专门断言。
        expect(
          (e.body!['task'] as Map)['id'].toString(),
          first.id,
          reason: '复用回来的必须就是刚才那个任务',
        );
      });

      test('已达每日上限 → RATE_LIMITED', () async {
        final c = await _registered();
        // 注册送的 50 只够 12 张图，不补钱的话第 13 张先撞「积分不足」，
        // **根本走不到配额那道闸**，这条用例就测不到它声称要测的东西。
        await grantCredits('alice', amount: 500);

        const limit = 20;
        for (var i = 0; i < limit; i++) {
          final res = await _client(c).post(
            ApiPaths.generateImage,
            body: <String, dynamic>{'prompt': '一只猫', 'idempotency_key': 'r$i'},
          );
          expect(res['id'], isNotNull, reason: '第 ${i + 1} 张图本该成功');
        }

        final e = await _failureOf(() => _client(c).post(
              ApiPaths.generateImage,
              body: <String, dynamic>{
                'prompt': '一只猫',
                'idempotency_key': 'overflow',
              },
            ));

        _assertDoesNotLie(e, expected: ApiErrorCode.rateLimited);
        expect(e.userMessage, '已达今日生成上限，请明天再试');
      });

      test('参考图超 20MB → IMAGE_TOO_LARGE', () async {
        final c = await _registered();
        final e = await _failureOf(() => _client(c).upload(
              ApiPaths.uploadImage,
              // 21MB（上限是 20 × 1024 × 1024）
              bytes: List<int>.filled(21 * 1024 * 1024, 0),
              filename: 'huge.png',
              mimeType: 'image/png',
            ));

        _assertDoesNotLie(e, expected: ApiErrorCode.imageTooLarge);
      });

      test('提示词命中审核词 → CONTENT_REJECTED，且**余额一分不动**', () async {
        final c = await _registered();

        // ───────────────────────────────────────────────────
        // 【为什么这条 B5 之前写不出来】
        //
        // 后端一直有这两个 raise 点（`services/moderation.py` 的入口审核、
        // `generation._sync_failure` 的 502），但**没有任何办法从一个
        // 正常请求触发它们**：这条门禁跑的是 `PROVIDER=fake`，而 fake
        // 是契约的一部分 —— 它永远成功、连外网都不发。
        //
        // B5 给后端加了**哨兵词**，于是这两条路第一次可触发。哨兵词是
        // 纯 ASCII 的记号，所以可以在这里原样写死：
        //
        //   · `__BLOCKED__` —— `app/services/moderation.py::DEFAULT_BLOCKLIST`
        //   · `__FAIL__`    —— `app/providers/fake.py::FAIL_SENTINEL`
        //
        // ⚠️ 两边必须同步。后端哪天删掉其中一个，这条会以
        //    「本该失败却成功了」红掉 —— 那正是它**应该**有的表现。
        //    （为什么不写成中文词：中文在这里要经过命令行/环境变量的
        //    编码往返，而本机是 GBK —— 后端在那个坑上有专门的注释。）
        // ───────────────────────────────────────────────────
        final e = await _failureOf(() => _client(c).post(
              ApiPaths.generateImage,
              body: <String, dynamic>{
                'prompt': '一只猫 __BLOCKED__',
                'idempotency_key': 'k-blocked',
              },
            ));

        _assertDoesNotLie(e, expected: ApiErrorCode.contentRejected);

        // 【这条副作用断言是入口审核最要紧的性质】
        // 它在**任何写库动作之前**，所以任务压根没建、冻结也没发生。
        // 写成「先冻结再审核」是很自然的一种错，而它的表现是
        // 用户改个词重发之后**钱少了一点** —— 用户不会把这笔账
        // 和那次被拒的提交联系起来。
        final me = await c.read(meRepositoryProvider).fetchProfile();
        expect(me.creditAccount.balance, 50, reason: '被拒的提交不该动余额');
        expect(me.creditAccount.frozen, 0, reason: '被拒的提交不该留下冻结');
      });

      test('provider 硬失败 → PROVIDER_ERROR，且余额仍是一分没少', () async {
        final c = await _registered();

        final e = await _failureOf(() => _client(c).post(
              ApiPaths.generateImage,
              body: <String, dynamic>{
                'prompt': '一只猫 __FAIL__',
                'idempotency_key': 'k-provider-fail',
              },
            ));

        // `_assertDoesNotLie` 顺带钉住了那句话：「生成失败，积分已全额
        // 退回，可以重新试一次」。前端**对用户承诺**了它，后端就得兑现。
        _assertDoesNotLie(e, expected: ApiErrorCode.providerError);

        // ───────────────────────────────────────────────────
        // 【⚠️ 这条路上「全额退回」表现为「压根没扣」，两者不是一回事】
        //
        // 走 fake 时提交是**同步**完成的，而同步路径上这个 502 是在
        // 业务事务**里面**抛的 → 整个事务回滚 → 冻结、退款、任务行
        // 一起消失，账面上只剩一个「没发生过」。后端有一条用例专门
        // 钉着这个（`test_transfer_b4.py` 那条「一整笔都不留」）。
        //
        // 真正走「冻结 → 失败 → 退款」三段流水的是**异步路径**
        // （真 provider + worker），而它要等 AK/SK（§18-2）。
        // 所以这里能断言的、也只有该断言的是：**用户的钱没少**。
        // 写一句 `frozen == 0` 之外的话（比如「流水里有一条 refund」）
        // 在这条路上是**假的**，因为流水压根没有。
        // ───────────────────────────────────────────────────
        final me = await c.read(meRepositoryProvider).fetchProfile();
        expect(me.creditAccount.balance, 50, reason: '硬失败不该扣钱');
        expect(me.creditAccount.frozen, 0, reason: '硬失败不该留下冻结');
      });

      test('已终态的任务不能取消 → TASK_NOT_CANCELABLE', () async {
        final c = await _registered();
        final task = await c.read(generationRepositoryProvider).submitImage(
              prompt: '一只猫',
              idempotencyKey: 'k1',
            );

        final e = await _failureOf(
          () => _client(c).post(ApiPaths.taskCancel(task.id)),
        );

        // 【这个码前端**认不出**，是已知缺口】§12.3 没有它，F8 也没补。
        // 所以这里断的是「认不出也要有话说」：状态码是 409，且文案不是那句
        // 撒谎的「连不上服务器」。真要显示精确文案，得在 ApiErrorCode 里
        // 补一条 —— 那是前端的一次小改动。
        expect(e.httpStatus, 409);
        expect(e.code, isNull);
        expect(e.userMessage, isNot(contains('网络')));
        expect(e.userMessage, isNot(contains('连不上')));
      });

      test('不存在的任务 → 404', () async {
        final c = await _registered();
        final e = await _failureOf(
          () => _client(c).get(ApiPaths.taskDetail('999999')),
        );

        // 同上：NOT_FOUND 也是已知缺口，断的是「状态码对 + 不说谎」。
        expect(e.httpStatus, 404);
        expect(e.code, isNull);
        expect(e.userMessage, isNot(contains('连不上')));
      });

      test('未带 token → 401，前端认得出是「登录过期」', () async {
        final c = testContainer(); // 没登录
        final e = await _failureOf(() => _client(c).get(ApiPaths.me));

        // 【401 走的是状态码而不是错误码】见 `dio_api_client._toException`：
        // 401 被单独拎出来走 `AppException.unauthorized()`，因为它是
        // **登录态信号**，上层要用 `isUnauthorized` 触发登出。
        // 后端若把 401 改成 403 或 400，App 就不会登出了 —— 而它
        // 会一直拿着一个死 token 重试，页面永远转圈。
        expect(e.isUnauthorized, isTrue);
        expect(e.userMessage, '登录已过期，请重新登录');
      });

      test('密码错 → 401（登录页靠状态码说「用户名或密码不正确」）', () async {
        await _registered();
        final c = testContainer();
        final e = await _failureOf(() => _client(c).post(
              ApiPaths.login,
              body: <String, dynamic>{'username': 'alice', 'password': 'wrong-pw'},
            ));

        expect(e.isUnauthorized, isTrue);
      });

      test('用户名被占用 → 409（登录页靠状态码说「这个用户名已经被占用了」）', () async {
        await _registered();
        final c = testContainer();
        final e = await _failureOf(() => _client(c).post(
              ApiPaths.register,
              body: <String, dynamic>{
                'invite_code': 'MOCK',
                'username': 'alice',
                'password': 'pw123456',
              },
            ));

        // 【为什么断状态码而不是错误码】后端发的是 `USERNAME_TAKEN`，
        // 而前端枚举里没有它（F8 只补了 INVITE_INVALID）—— 所以
        // `e.code` 是 null。登录页此时靠 **409** 这个状态码分支，
        // 说的话是对的。这里钉的就是「那个状态码别变」。
        expect(e.httpStatus, 409);
        expect(e.code, isNull, reason: '若哪天前端补了这个码，这条要一起改');
      });

      test('缺必填字段 → 400 + INVALID_REQUEST（**不是** FastAPI 默认的 422）', () async {
        final c = await _registered();
        final e = await _failureOf(
          () => _client(c).post(ApiPaths.generateImage, body: <String, dynamic>{}),
        );

        // ───────────────────────────────────────────────────
        // 【这条是 B2 期间我自己在文档里写错过的一件事，所以专门钉住】
        //
        // FastAPI 的默认行为是 422 + `{"detail":[...]}` —— 那个形状
        // **破了「无信封」契约**：前端从顶层读 `code`/`message`，读到两个
        // null，用户看到的是开发味的「服务端返回 HTTP 422，且响应体里
        // 没有 message 字段」。
        //
        // 后端因此装了 `RequestValidationError` 处理器，把它翻译成
        // `400 + {"code":"INVALID_REQUEST","message":"..."}`。
        // 把这条钉在这里，是因为**它只在真后端上才看得见** ——
        // Mock 从来不返回形状错误（调用方在本地就校验掉了）。
        // ───────────────────────────────────────────────────
        expect(e.httpStatus, 400);
        expect(e.code, isNull, reason: 'INVALID_REQUEST 是给 curl 和未来客户端用的兜底，前端不认它');
        expect(e.message, isNot(contains('detail')),
            reason: '这是 FastAPI 默认 422 的形状，说明处理器没生效');
        expect(e.message, isNot(contains('服务端返回 HTTP')),
            reason: '读到的是开发者兜底文案，说明响应体里没有 message 字段');
      });
    });

    // ════════════════════════════════════════════════════════
    // 四、覆盖台账
    // ════════════════════════════════════════════════════════
    test('前端认识的每个错误码，要么被上面真触发过，要么写明了为什么触发不了', () {
      // 【这个测试不碰网络，但它值钱的地方在于：它是唯一一处会「因为
      // 新增了一个枚举值而变红」的地方】。哪天有人往 `ApiErrorCode`
      // 里加了一条，这里立刻红，逼他回答「这条到底验没验过」。
      const coveredLive = <ApiErrorCode>{
        ApiErrorCode.insufficientCredits,
        ApiErrorCode.invalidPrompt,
        ApiErrorCode.imageTooLarge,
        ApiErrorCode.duplicateRequest,
        ApiErrorCode.rateLimited,
        ApiErrorCode.inviteInvalid,
        // 【B5 挪上来的两条】它们原本在下面那张表里，理由写的是
        // 「等 B7 接上真即梦才可能被真触发」。那个理由**没有成立** ——
        // 真触发它们并不需要真 provider，只需要后端肯按命令失败：
        // B5 给 fake 与词表各加了一个 ASCII 哨兵词，于是这两条路
        // 现在真的被走过了（见上面那两条用例）。
        //
        // 这句留在这里，是因为原来那句「等 B7」是一个**会自己过期的
        // 承诺**：B7 做完之后看的人会以为已经验过了，而它根本没验。
        ApiErrorCode.contentRejected,
        ApiErrorCode.providerError,
      };

      // 【为什么只剩下一个，而不是「我懒得写」】
      //
      // queueSaturated 和上面那些的差别是：后端**至今没有这个 raise 点**，
      // 而且不是忘了 —— §8.2 没给队列定义深度上限（闸门满了是「排队」，
      // 由 `queue_position` 诚实显示，不是「队列已满」），所以**没有**
      // 触发条件。真要它可触发，得先在 §12 里补一条队列容量规则。
      //
      // ⚠️ 它**不会**因为接上真 provider、也不会因为 B7 而变得可触发。
      //    别再往这里写「等某一批做完就挪上去」—— 那正是上一版的错误。
      const notReachableLive = <ApiErrorCode, String>{
        ApiErrorCode.queueSaturated:
            '§8.2 没有队列深度上限，后端没有触发条件（不是哪一批漏了；'
                '要它可触发得先在 §12 补一条队列容量规则）',
      };

      final declared = <ApiErrorCode>{
        ...coveredLive,
        ...notReachableLive.keys,
      };

      expect(
        declared,
        containsAll(ApiErrorCode.values),
        reason: 'ApiErrorCode 里新增了没人交代过的码。要么在本文件里'
            '真触发一次，要么说明它为什么暂时触发不了 —— '
            '**没被真触发过的错误码就是一段没被执行过的 UI**。',
      );
      expect(
        declared.length,
        ApiErrorCode.values.length,
        reason: '两个集合对不上：要么有重叠，要么有个码压根不在枚举里了',
      );
    });
  }, skip: isLiveBackend ? null : _needLive);
}

// ────────────────────────────────────────────────────────────
// 两个小夹具
// ────────────────────────────────────────────────────────────

/// 从容器里拿当前 token（裸请求要自己带鉴权头）。
Future<String> _currentToken(ProviderContainer c) async {
  final token = await c.read(tokenStoreProvider).read();
  expect(token, isNotNull, reason: '夹具自己坏了：这个容器没登录过');
  return token!;
}

/// 传一张参考图上去，返回 asset_id 字符串（提交视频要用的那个）。
Future<String> _uploadRef(ProviderContainer c) => c
    .read(assetRepositoryProvider)
    .uploadImage(
      bytes: List<int>.filled(1024, 0),
      filename: 'ref.png',
      mimeType: 'image/png',
    );

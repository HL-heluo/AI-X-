import 'package:web/web.dart' as web;

bool startWorkDownload(Uri url) {
  final link = (web.document.createElement('a') as web.HTMLAnchorElement)
    ..href = url.toString()
    ..download = '';
  web.document.body?.append(link);
  link.click();
  link.remove();
  return true;
}

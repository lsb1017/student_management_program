/**
 * 성적표 열람 웹 (Google Apps Script 웹 앱). 학원 Google 계정에 1회 배포함.
 * 학원 PC가 꺼져 있어도 24시간 동작하며, Drive의 비공개 성적표 폴더를 이 스크립트만 읽음.
 *
 * 스크립트 속성(프로젝트 설정 > 스크립트 속성):
 *   ROOT_FOLDER_ID  성적표 게시 폴더 ID (프로그램 설정의 '성적표 게시 폴더'와 같음)
 *   PEPPER          프로그램 설정 > 열람 웹 > '로그인 해시 키' 값
 *   FAIL_LIMIT      연속 실패 허용 횟수 (기본 5)
 *   LOCK_MINUTES    잠금 시간(분) (기본 10)
 *
 * 로그인 해시는 프로그램(academy/services/notify.py login_hash)과 같아야 함:
 *   hex(sha256(PEPPER + 학번 + ':' + NFC 이름(공백 제거)))
 */
function config_() {
  var p = PropertiesService.getScriptProperties();
  return {
    root: p.getProperty('ROOT_FOLDER_ID'),
    pepper: p.getProperty('PEPPER') || '',
    limit: Number(p.getProperty('FAIL_LIMIT') || 5),
    minutes: Number(p.getProperty('LOCK_MINUTES') || 10)
  };
}

function cleanKey_(value, size) {
  return String(value || '').replace(/[^A-Za-z0-9_-]/g, '').slice(0, size);
}

function doGet(e) {
  var params = (e && e.parameter) || {};
  var t = HtmlService.createTemplateFromFile('index');
  t.sessionKey = cleanKey_(params.s, 40);
  t.noticeKey = cleanKey_(params.n, 80);
  return t.evaluate()
    .setTitle('성적표 열람')
    .addMetaTag('viewport', 'width=device-width, initial-scale=1');
}

function hex_(bytes) {
  // Apps Script digests are signed bytes (-128..127).
  return bytes.map(function (b) { return ('0' + ((b + 256) % 256).toString(16)).slice(-2); }).join('');
}

function normalizeName_(name) {
  return String(name || '').normalize('NFC').replace(/\s+/g, '');
}

function loginHash_(pepper, code, name) {
  var digest = Utilities.computeDigest(Utilities.DigestAlgorithm.SHA_256,
    pepper + code + ':' + normalizeName_(name), Utilities.Charset.UTF_8);
  return hex_(digest);
}

function readJson_(fileId) {
  return JSON.parse(DriveApp.getFileById(fileId).getBlob().getDataAsString('UTF-8'));
}

function index_(root) {
  var files = DriveApp.getFolderById(root).getFilesByName('index.json');
  if (!files.hasNext()) throw new Error('게시된 성적표가 아직 없습니다.');
  return JSON.parse(files.next().getBlob().getDataAsString('UTF-8'));
}

function login(code, name, sessionKey) {
  var cfg = config_();
  code = String(code || '').replace(/\D/g, '');
  sessionKey = cleanKey_(sessionKey, 40);
  if (code.length !== 7 || !normalizeName_(name)) {
    return { ok: false, message: '학번 7자리와 이름을 입력해 주세요.' };
  }
  var lock = LockService.getScriptLock();
  lock.waitLock(10000);
  try {
    var props = PropertiesService.getScriptProperties();
    var failKey = 'fail_' + code;
    var state = JSON.parse(props.getProperty(failKey) || '{"count":0,"until":0}');
    var now = Date.now();
    if (state.until > now) {
      return { ok: false, locked: true,
        message: '로그인 실패가 많아 ' + Math.ceil((state.until - now) / 60000) + '분 후 다시 시도할 수 있어요.' };
    }
    var index = index_(cfg.root);
    var key = loginHash_(cfg.pepper, code, name);
    var entry = null, day = '';
    if (sessionKey) {
      var session = index.sessions[sessionKey];
      if (!session) return { ok: false, message: '링크가 올바르지 않습니다. 학원에 문의해 주세요.' };
      entry = readJson_(session.manifest_id).entries[key] || null;
      day = session.date || '';
    } else {
      entry = index.latest[key] || null;
      day = entry ? entry.date : '';
    }
    if (!entry) {
      state.count = (state.until ? 0 : state.count) + 1;
      state.until = 0;
      if (state.count >= cfg.limit) { state.until = now + cfg.minutes * 60000; state.count = 0; }
      props.setProperty(failKey, JSON.stringify(state));
      return { ok: false, message: '학번 또는 이름이 맞지 않거나, 이 회차 성적표가 없습니다.' };
    }
    props.deleteProperty(failKey);
    // Only the verified file is read; its Drive address never reaches the browser.
    var blob = DriveApp.getFileById(entry.file_id).getBlob();
    return { ok: true, date: day, pdf: Utilities.base64Encode(blob.getBytes()) };
  } finally {
    lock.releaseLock();
  }
}

function notice(noticeKey) {
  var cfg = config_();
  var key = cleanKey_(noticeKey, 80);
  var index = index_(cfg.root);
  var id = (index.notices || {})[key];
  if (!id) return { ok: false, message: '안내문을 찾을 수 없습니다.' };
  var data = readJson_(id);
  var attachment = null;
  if (data.attachment_id) {
    var blob = DriveApp.getFileById(data.attachment_id).getBlob();
    attachment = { mime: blob.getContentType(), data: Utilities.base64Encode(blob.getBytes()) };
  }
  return { ok: true, title: data.title, body: data.body, attachment: attachment };
}

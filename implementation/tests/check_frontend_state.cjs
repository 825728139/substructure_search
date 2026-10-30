/** 在 Node 隔离环境中模拟乱序网络响应，验证页面不会串用不同检索任务的结果。 */
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const html = fs.readFileSync(path.join(__dirname, '../src/reaction_reference/interfaces/static/index.html'), 'utf8');
const script = html.match(/<script>([\s\S]*?)<\/script>/)[1];

/** 构造可由测试主动完成或拒绝的异步请求。 */
function deferred() {
  let resolve, reject;
  const promise = new Promise(/** 保存异步完成入口。 */ (yes, no) => { resolve = yes; reject = no; });
  return {promise, resolve, reject};
}

/** 模拟本页面用到的最小 DOM，记录展示变化和下载动作。 */
function environment(fetch) {
  const elements = new Map(), downloads = [], blobs = [], timers = new Map();
  let timerId = 0;
  /** 构造普通显示元素及浏览器操作替身。 */
  function element(tag) {
    return {
      tag, value: '', textContent: '', disabled: false, hidden: false, children: [],
      /** 将节点加入尾部。 */
      append(...items) { this.children.push(...items); },
      /** 将结构图加入头部。 */
      prepend(...items) { this.children.unshift(...items); },
      /** 替换显示内容，便于检查旧结果是否错误覆盖新结果。 */
      replaceChildren(...items) { this.children = items; },
      /** 记录模拟下载文件名。 */
      click() { downloads.push(this.download); },
      /** 默认提供合法输入，具体数值输入的浏览器校验由 Chromium 回归覆盖。 */
      reportValidity() { return true; },
    };
  }
  const context = vm.createContext({
    fetch, Blob, console,
    URL: {
      /** 返回一个无网络访问的临时图片或下载地址。 */
      createObjectURL(blob) { blobs.push(blob); return 'blob:test'; },
      /** 模拟浏览器释放临时地址。 */
      revokeObjectURL() {},
    },
    document: {
      /** 获取或创建稳定的控件实例。 */
      getElementById(id) { if (!elements.has(id)) elements.set(id, element(id)); return elements.get(id); },
      createElement: element,
    },
    /** 登记定时回调；测试自行控制异步顺序，不等待真实时间。 */
    setTimeout(fn) { timers.set(++timerId, fn); return timerId; },
    /** 移除已登记的定时回调。 */
    clearTimeout(id) { timers.delete(id); },
    /** 兼容旧实现，保证失败来自串任务问题而非缺少浏览器函数。 */
    setInterval(fn) { timers.set(++timerId, fn); return timerId; },
    /** 兼容旧实现的周期计时器清理。 */
    clearInterval(id) { timers.delete(id); },
  });
  vm.runInContext(script, context);
  return {context, elements, downloads, blobs, timers};
}

/** 生成成功的 JSON 接口响应。 */
function response(value) { return {ok: true, json: async () => value, blob: async () => new Blob([JSON.stringify(value)], {type: 'application/json'})}; }

/** 确认旧状态响应不能修改新任务的状态或终止其轮询。 */
async function staleStatus() {
  const pending = deferred();
  const app = environment(/** 延迟旧任务状态响应。 */ () => pending.promise);
  vm.runInContext('run = "old"; generation = 1;', app.context);
  const check = vm.runInContext('check()', app.context);
  vm.runInContext('run = "new"; generation = 2; $("status").textContent = "新任务运行中";', app.context);
  pending.resolve(response({lifecycle: 'running'}));
  await check;
  assert.equal(app.elements.get('status').textContent, '新任务运行中');
}

/** 确认旧结果响应不能清空新任务卡片，也不能接管新任务的分页游标。 */
async function staleResults() {
  const pending = deferred();
  const app = environment(/** 延迟旧结果页。 */ () => pending.promise);
  vm.runInContext('run = "old"; generation = 1;', app.context);
  const result = vm.runInContext('results()', app.context);
  vm.runInContext('run = "new"; generation = 2; cursor = "new-cursor"; $("cards").append("新结果");', app.context);
  pending.resolve(response({results: [], next_cursor: 'old-cursor'}));
  await result;
  assert.deepEqual(app.elements.get('cards').children, ['新结果']);
  assert.equal(vm.runInContext('cursor', app.context), 'new-cursor');
}

/** 确认旧请求的失败不会把新任务的状态改成错误或重新启用提交按钮。 */
async function staleFailure() {
  const pending = deferred();
  const app = environment(/** 延迟并拒绝旧请求。 */ () => pending.promise);
  vm.runInContext('run = "old"; generation = 1;', app.context);
  const check = vm.runInContext('check()', app.context);
  vm.runInContext('run = "new"; generation = 2; $("status").textContent = "新任务运行中"; $("submit").disabled = true;', app.context);
  pending.reject(new Error('旧请求失败'));
  await check;
  assert.equal(app.elements.get('status').textContent, '新任务运行中');
  assert.equal(app.elements.get('submit').disabled, true);
}

/** 确认旧资料包响应不会使用新任务编号生成错误下载。 */
async function staleDownload() {
  const pending = deferred();
  const app = environment(/** 延迟旧资料包下载。 */ () => pending.promise);
  vm.runInContext('run = "old"; generation = 1;', app.context);
  const download = app.elements.get('download').onclick();
  vm.runInContext('run = "new"; generation = 2;', app.context);
  pending.resolve(response({run_id: 'old'}));
  await download;
  assert.deepEqual(app.downloads, []);
}

/** 确认当前任务仍可正常显示结果并按同一快照导出资料包。 */
async function currentResultsAndDownload() {
  const urls = [];
  const app = environment(/** 返回当前任务的结果页或导出包。 */ async url => {
    urls.push(url);
    return response(url.includes('/results') ? {
      results: [{kind: 'proposal_not_observed', item: {proposed_reactants: ['CCN'], target_smiles: 'CCNC=O'}}],
      next_cursor: 'next', snapshot_id: 'snapshot-a', coverage_state: 'partial',
    } : {run_id: 'current'});
  });
  vm.runInContext('run = "current"; generation = 1;', app.context);
  await vm.runInContext('results()', app.context);
  assert.equal(app.elements.get('cards').children.length, 1);
  assert.equal(vm.runInContext('cursor', app.context), 'next');
  await app.elements.get('download').onclick();
  assert.deepEqual(app.downloads, ['reference-current.json']);
  assert.ok(urls[1].endsWith('/package?snapshot=snapshot-a'));
}

/** 确认慢状态请求完成前不会再发起周期请求，完成后只安排一次下一轮。 */
async function serialPolling() {
  const pending = deferred();
  const app = environment(/** 延迟当前状态以模拟慢网络。 */ () => pending.promise);
  vm.runInContext('run = "current"; generation = 1;', app.context);
  const check = vm.runInContext('check()', app.context);
  assert.equal(app.timers.size, 0);
  pending.resolve(response({lifecycle: 'running'}));
  await check;
  assert.equal(app.timers.size, 1);
}

/** 确认下载保留服务器原始字节，避免大整数经过 JavaScript 数值解析后被舍入。 */
async function originalDownloadBytes() {
  const payload = '{"run_id":"current","counter":9007199254740993,"text":"原始资料"}\n';
  const app = environment(/** 分别提供原始响应体与可能失真的 JSON 解析路径。 */ async () => ({
    ok: true,
    json: async () => JSON.parse(payload),
    blob: async () => new Blob([payload], {type: 'application/json'}),
  }));
  vm.runInContext('run = "current"; generation = 1;', app.context);
  await app.elements.get('download').onclick();
  assert.deepEqual(app.downloads, ['reference-current.json']);
  assert.equal(await app.blobs[0].text(), payload);
}

/** 下载接口失败时应显示错误，不把错误响应当成完整资料包保存。 */
async function failedDownloadIsNotPublished() {
  const app = environment(/** 模拟没有可用资料包的错误响应。 */ async () => ({
    ok: false, json: async () => ({detail: 'not_ready'}),
    blob: async () => new Blob(['错误响应']),
  }));
  vm.runInContext('run = "current"; generation = 1;', app.context);
  await app.elements.get('download').onclick();
  assert.deepEqual(app.downloads, []);
  assert.equal(app.blobs.length, 0);
  assert.match(app.elements.get('status').textContent, /not_ready/);
}

/** 派生任务已创建但新结果读取失败时，不能把旧卡片留在新任务名下。 */
async function rerankResultFailureClearsOldCards() {
  const app = environment(/** 完成重排与状态查询，只让新任务结果读取失败。 */ async url => {
    if (url.endsWith('/rerank')) return response({run_id: 'new'});
    if (url.includes('/results')) throw Error('新任务结果暂时不可读');
    return response({lifecycle: 'succeeded', latest_snapshot_id: 'new-snapshot'});
  });
  vm.runInContext('run = "old"; generation = 1; activeSnapshot = "old-snapshot"; $("cards").append("旧卡片"); $("metrics").append("旧统计");', app.context);
  await app.elements.get('rerank').onclick();
  assert.equal(vm.runInContext('run', app.context), 'new');
  assert.deepEqual(app.elements.get('cards').children, []);
  assert.deepEqual(app.elements.get('metrics').children, []);
  assert.equal(app.elements.get('download').disabled, true);
  assert.match(app.elements.get('status').textContent, /新任务结果暂时不可读/);
}

/** 重排尚未创建派生任务就失败时，旧任务、卡片和固定快照仍可继续查看与导出。 */
async function rerankSubmissionFailureKeepsOldCards() {
  const app = environment(/** 模拟服务在创建派生任务前拒绝重排。 */ async () => {
    throw Error('重排未接纳');
  });
  vm.runInContext('run = "old"; generation = 1; activeSnapshot = "old-snapshot"; $("cards").append("旧卡片"); $("metrics").append("旧统计");', app.context);
  await app.elements.get('rerank').onclick();
  assert.equal(vm.runInContext('run', app.context), 'old');
  assert.equal(vm.runInContext('activeSnapshot', app.context), 'old-snapshot');
  assert.deepEqual(app.elements.get('cards').children, ['旧卡片']);
  assert.deepEqual(app.elements.get('metrics').children, ['旧统计']);
  assert.equal(app.elements.get('download').disabled, false);
}

/** 无最终快照的终态保留任务状态和错误，不再读取结果或混用旧快照。 */
async function terminalWithoutSnapshotKeepsStatus() {
  for (const lifecycle of ['failed', 'cancelled', 'timed_out']) {
    const requests = [];
    const error = lifecycle === 'failed' ? {code: 'snapshot_finalization_failed'} : null;
    const app = environment(/** 只允许读取终态；结果请求代表错误的前端控制流。 */ async url => {
      requests.push(url);
      if (url.includes('/results')) throw Error('最终快照不可用');
      return response({lifecycle, error, latest_snapshot_id: null});
    });
    vm.runInContext('run = "stopped"; generation = 1; cursor = "old-cursor"; activeSnapshot = "old-snapshot"; $("cards").append("旧卡片"); $("metrics").append("旧统计");', app.context);
    await vm.runInContext('check()', app.context);
    assert.deepEqual(requests, ['/v1/search-runs/stopped']);
    assert.match(app.elements.get('status').textContent, new RegExp(lifecycle));
    if (error) assert.match(app.elements.get('status').children[0].textContent, /snapshot_finalization_failed/);
    assert.deepEqual(app.elements.get('cards').children, []);
    assert.deepEqual(app.elements.get('metrics').children, []);
    assert.equal(vm.runInContext('cursor', app.context), null);
    assert.equal(vm.runInContext('activeSnapshot', app.context), null);
    assert.equal(app.elements.get('more').hidden, true);
    assert.equal(app.elements.get('download').disabled, true);
    assert.equal(app.elements.get('rerank').disabled, true);
    assert.equal(app.elements.get('cancel').disabled, true);
    assert.equal(app.elements.get('submit').disabled, false);
    assert.equal(app.timers.size, 0);
  }
}

/** 终态已说明快照不可用时，迟到的旧分页响应不能再次恢复旧卡片或游标。 */
async function terminalWithoutSnapshotRejectsPendingResults() {
  const pending = deferred();
  let resultRequests = 0;
  const app = environment(/** 延迟已经发出的旧分页，状态查询则返回无快照的失败终态。 */ async url => {
    if (url.includes('/results')) {
      if (++resultRequests > 1) throw Error('最终快照不可用');
      return pending.promise;
    }
    return response({lifecycle: 'failed', latest_snapshot_id: null, error: {code: 'snapshot_finalization_failed'}});
  });
  vm.runInContext('run = "stopped"; generation = 1; cursor = "old-cursor"; activeSnapshot = "old-snapshot";', app.context);
  const oldResults = vm.runInContext('results(false)', app.context);
  await vm.runInContext('check()', app.context);
  pending.resolve(response({results: [{kind: 'proposal_not_observed', item: {proposed_reactants: [], target_smiles: 'CCO'}}], snapshot_id: 'old-snapshot', next_cursor: 'old-next'}));
  await oldResults;
  assert.equal(resultRequests, 1);
  assert.deepEqual(app.elements.get('cards').children, []);
  assert.equal(vm.runInContext('cursor', app.context), null);
  assert.equal(vm.runInContext('activeSnapshot', app.context), null);
  assert.equal(app.elements.get('download').disabled, true);
  assert.equal(app.elements.get('more').hidden, true);
}

/** 汇总所有乱序响应场景，任何失败均以非零状态退出。 */
async function main() {
  let failures = 0;
  for (const test of [staleStatus, staleResults, staleFailure, staleDownload, currentResultsAndDownload, serialPolling, originalDownloadBytes, failedDownloadIsNotPublished, rerankResultFailureClearsOldCards, rerankSubmissionFailureKeepsOldCards, terminalWithoutSnapshotKeepsStatus, terminalWithoutSnapshotRejectsPendingResults]) {
    try { await test(); console.log('通过：' + test.name); }
    catch (error) { failures++; console.error('失败：' + test.name + '\n' + error.message); }
  }
  if (failures) process.exitCode = 1;
}
main();

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
  const elements = new Map(), downloads = [], timers = new Map();
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
    };
  }
  const context = vm.createContext({
    fetch, Blob, console,
    URL: {
      /** 返回一个无网络访问的临时图片或下载地址。 */
      createObjectURL() { return 'blob:test'; },
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
  return {context, elements, downloads, timers};
}

/** 生成成功的 JSON 接口响应。 */
function response(value) { return {ok: true, json: async () => value}; }

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

/** 汇总所有乱序响应场景，任何失败均以非零状态退出。 */
async function main() {
  let failures = 0;
  for (const test of [staleStatus, staleResults, staleFailure, staleDownload, currentResultsAndDownload, serialPolling]) {
    try { await test(); console.log('通过：' + test.name); }
    catch (error) { failures++; console.error('失败：' + test.name + '\n' + error.message); }
  }
  if (failures) process.exitCode = 1;
}
main();

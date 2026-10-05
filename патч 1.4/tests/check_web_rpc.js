/* Execute the actual client RPC helper with a server-receipt/network fixture. */
'use strict';
const assert = require('node:assert/strict');
const fs = require('node:fs');
const path = require('node:path');
const vm = require('node:vm');
const source = fs.readFileSync(path.join(__dirname, '..', 'web', 'app.js'), 'utf8');
const start = source.indexOf('async function rpc(');
const end = source.indexOf('\nlet draftDB', start);
assert(start >= 0 && end > start, 'Actual RPC helper must be present in the client');
const pendingRequests = new Map();
const requests = [];
const receipts = new Map();
const creations = [];
let sequence = 0;
let outcome = 'success';
const context = vm.createContext({
  state: {user: {id: 7}, pendingRequests},
  uuid: () => `test-request-${String(++sequence).padStart(8, '0')}`,
  request: async (url, options) => {
    const body = JSON.parse(options.body);
    requests.push({url, ...body});
    if (outcome === 'validation') throw Object.assign(new Error('validation'), {status: 400});
    // This fixture represents a server that committed both result and receipt.
    // It does not claim exactly-once across a real server crash before receipt commit.
    if (!receipts.has(body.request_id)) {
      const result = creations.length + 1;
      receipts.set(body.request_id, result);
      if (url.endsWith('/create_task')) creations.push(body);
    }
    if (outcome === 'lost') throw Object.assign(new Error('accepted reply lost'), {status: 0});
    if (outcome === 'unavailable') throw Object.assign(new Error('accepted reply unavailable'), {status: 503});
    return {result: receipts.get(body.request_id)};
  }
});
vm.runInContext(source.slice(start, end), context, {filename: 'web/app.js:rpc'});

(async () => {
  const payload = {title: 'Inspect conveyor', worker_id: 2};
  outcome = 'lost';
  await assert.rejects(context.rpc('create_task', [], payload), /accepted reply lost/);
  const lostID = requests.at(-1).request_id;
  assert.equal(pendingRequests.size, 1);
  assert.equal(creations.length, 1);
  outcome = 'success';
  const recovered = await context.rpc('create_task', [], payload);
  assert.equal(requests.at(-1).request_id, lostID);
  assert.equal(recovered, 1);
  assert.equal(creations.length, 1, 'Lost accepted reply must reuse the server receipt');
  assert.equal(pendingRequests.size, 0, 'Successful response clears the pending entry');

  outcome = 'unavailable';
  await assert.rejects(context.rpc('create_task', [], {title: 'Replace sensor'}), /unavailable/);
  const unavailableID = requests.at(-1).request_id;
  const beforeRetry = creations.length;
  outcome = 'success';
  await context.rpc('create_task', [], {title: 'Replace sensor'});
  assert.equal(requests.at(-1).request_id, unavailableID);
  assert.equal(creations.length, beforeRetry, '503 retry must reuse the same receipt');

  outcome = 'validation';
  await assert.rejects(context.rpc('create_task', [], {title: 'Invalid data'}), /validation/);
  const invalidID = requests.at(-1).request_id;
  assert.equal(pendingRequests.size, 0);
  outcome = 'success';
  await context.rpc('create_task', [], {title: 'Invalid data'});
  assert.notEqual(requests.at(-1).request_id, invalidID, '4xx allows a new attempt');

  outcome = 'lost';
  await assert.rejects(context.rpc('create_task', [], {title: 'Work A'}), /lost/);
  const firstPayloadID = requests.at(-1).request_id;
  await assert.rejects(context.rpc('create_task', [], {title: 'Work B'}), /lost/);
  assert.notEqual(requests.at(-1).request_id, firstPayloadID, 'Changed payload has a distinct request');
  outcome = 'success';
  await context.rpc('create_task', [], {title: 'Work A'});
  assert.equal(requests.at(-1).request_id, firstPayloadID);
  await context.rpc('create_task', [], {title: 'Work B'});
  assert.equal(pendingRequests.size, 0);

  outcome = 'unavailable';
  const reportID = 'persisted-report-request-0001';
  await assert.rejects(context.rpc('submit', [1053], {work:'Completed'}, [], reportID), /unavailable/);
  assert.equal(requests.at(-1).request_id, reportID);
  assert.equal(pendingRequests.size, 0, 'Explicit report IDs are owned by the persistent report draft');
  outcome = 'success';
  await context.rpc('submit', [1053], {work:'Completed'}, [], reportID);
  assert.equal(requests.at(-1).request_id, reportID);

  const successfulID = requests.at(-1).request_id;
  await context.rpc('create_task', [], payload);
  assert.notEqual(requests.at(-1).request_id, successfulID);
  assert.notEqual(requests.at(-1).request_id, lostID, 'A completed action is not a pending retry');
  assert.equal(pendingRequests.size, 0);
  console.log('PASS: actual RPC helper — lost reply, 503, 400, changed payload, explicit report ID, success cleanup');
})().catch(error => {console.error(error); process.exitCode = 1;});

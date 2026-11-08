import { test } from 'node:test'
import assert from 'node:assert/strict'
import { checkWorker, monitorWorker, WorkerFailure } from '../src/workerStatus.ts'

test('worker failures are retained even before a request starts', () => {
  for (const event of ['error', 'messageerror']) {
    const worker = new EventTarget() as Worker
    monitorWorker(worker)
    assert.doesNotThrow(() => checkWorker(worker))
    worker.dispatchEvent(new Event(event))
    assert.throws(() => checkWorker(worker), WorkerFailure)
    assert.throws(() => checkWorker(worker), WorkerFailure)
  }
})

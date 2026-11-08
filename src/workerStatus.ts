export class WorkerFailure extends Error {}

const failures = new WeakMap<Worker, WorkerFailure>()

// Track failures immediately, even while other work is underway.
export function monitorWorker(worker: Worker): Worker {
  const fail = () => failures.set(worker, new WorkerFailure('사진 처리 워커를 시작하거나 실행하지 못했습니다.'))
  worker.addEventListener('error', fail)
  worker.addEventListener('messageerror', fail)
  return worker
}

export function checkWorker(worker: Worker): void {
  const failure = failures.get(worker)
  if (failure) throw failure
}

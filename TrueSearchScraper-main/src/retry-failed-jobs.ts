import { fileURLToPath } from 'url';

import { TRUE_SEARCH_TARGETS_QUEUE_NAME } from './config.js';
import { getRedisClient } from './redis/tools.js';
import { getWorkerQueue } from './queues/tools.js';

const redis = getRedisClient();
const workerQueue = getWorkerQueue(redis, TRUE_SEARCH_TARGETS_QUEUE_NAME);


if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const failedJobs = await workerQueue.getFailed();

	for (const job of failedJobs) {
		console.log(job);
		await job.retry();
	}
}

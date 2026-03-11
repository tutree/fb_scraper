import { fileURLToPath } from 'url';

import logger from '../logging.js';
import { INDEED_NAMES_QUEUE_NAME, TRUE_SEARCH_TARGETS_QUEUE_NAME, JOB_TIMEOUT_MS } from '../config.js';
import { createWorker, getWorkerId } from '../workers/tools.js';
import { getRedisClient } from '../redis/tools.js';
import { getWorkerQueue } from '../queues/tools.js';
import { processRow } from './tools.js';
import { getJobRuntimeSummary } from '../metrics/worker.js';
import { workerTimeout } from '../workers/tools.js';

import type { Job } from 'bullmq';
import type { TSNameSearchAttrs } from './types.js';


type IndeedNameJob = {
	accountId: string;
	firstName: string;
	lastName: string;
	location: string;
	dataLabel: string;
	ageFrom: string;
	ageTo: string;
};


const workerId = getWorkerId();
const redis = getRedisClient();
const workerQueue = getWorkerQueue(redis, TRUE_SEARCH_TARGETS_QUEUE_NAME);
const jobRuntimeSummary = getJobRuntimeSummary();

async function jobProcessor(job:Job<IndeedNameJob>):Promise<void> {
	const jobStartTime = (new Date()).getTime();

	logger.info(job.data);

	try {
		const fullName = `${job.data.firstName} ${job.data.lastName}`;
		const { location, ageFrom, ageTo } = job.data;

		const leadAttrs:TSNameSearchAttrs = {
			dataLabel: job.data.dataLabel,
			indeedAccountId: job.data.accountId,
			originalSearchQuery: { fullName, location },
		};

		await Promise.race([
			processRow([fullName, location, ageFrom, ageTo], leadAttrs, workerQueue, workerId),
			workerTimeout(JOB_TIMEOUT_MS),
		]);

	} catch(error) {
		logger.error(`Indeed name search error: ${ error instanceof Error ? error.message : 'empty' }`);
		throw error;

	} finally {
		const executionTime = (new Date()).getTime() - jobStartTime;
		logger.info(`Job execution time: ${ executionTime / 1000 }s`);

		jobRuntimeSummary.labels({ 
			workerId: workerId, 
			workerType: 'indeedNameSearch', 
			dataLabel: job.data.dataLabel,
		}).observe(executionTime);

		await job.updateProgress({ message: 'jobFinished' });
	}
}


if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const worker = createWorker(redis, INDEED_NAMES_QUEUE_NAME, jobProcessor, workerId);
}

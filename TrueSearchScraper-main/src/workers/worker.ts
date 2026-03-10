import http from 'node:http';
import { fileURLToPath } from 'url';

import { Worker } from 'bullmq';
import yargs from 'yargs/yargs';

import { JOB_TIMEOUT_MS, INDEED_RESUME_MATCHING_QUEUE_NAME, DATA_INGEST_QUEUE_NAME } from '../config.js';
import { isUrlProcessed } from '../processPage.js';
import logger from '../logging.js';
import processUrl from '../urlProcessor.js';
import { isString } from '../guards.js'; 
import { workerTimeout, createWorker, getWorkerId, cleanWorkerErrorMessage } from './tools.js';
import { PageAlreadyProcessedError, PageReturnedNothingError } from '../errors.js';
import { getWorkerQueue } from '../queues/tools.js';
import { getRedisClient } from '../redis/tools.js';
import { getWorkerErrorsCounter, getJobRuntimeSummary } from '../metrics/worker.js';
import { getPrometheusGw } from '../metrics/tools.js';
import { PAGE_ALREADY_PROCESSED_MSG, NOT_FOUND_MSG } from '../metrics/consts.js';
import { submitIndeedResumeMatching } from '../indeed/tools.js';
import { updateHealthInfo } from '../health/tools.js';

import type { Job, Queue } from 'bullmq';
import type { URLJob } from '../queues/types.js';


const args = yargs(process.argv.slice(2)).options({
    queueName: { type: 'string', description: 'Worker queue', demand: true }
}).parseSync();


const redis = getRedisClient();
const workerId = getWorkerId();

logger.info(`<<< Worker id: ${workerId} >>>`);


// TODO: jobStatsCounter
const workerErrorCounter = getWorkerErrorsCounter();
const indeedResumeMatchingQueue = getWorkerQueue(redis, INDEED_RESUME_MATCHING_QUEUE_NAME);
const dataIngestQueue = getWorkerQueue(redis, DATA_INGEST_QUEUE_NAME);
const jobRuntimeSummary = getJobRuntimeSummary();


async function jobProcessor(job:Job<URLJob>):Promise<void> {
	const jobStartTime = (new Date()).getTime();

    logger.info(`Processing url: [${job.data.url}]`);

	try {
    	if (!(await isUrlProcessed(job.data.url))) {
			const leadAttrs = job.data.leadAttrs;
			await Promise.race([
				processUrl(job.data.url, redis, workerId, leadAttrs, dataIngestQueue),
				workerTimeout(JOB_TIMEOUT_MS)
			]);

		} else {
			logger.info('<<< Skipping processed url >>>');
			workerErrorCounter.inc({ errorType: 'pageProcessed' });

			const { indeedAccountId, dataLabel } = job.data.leadAttrs;

			if (isString(indeedAccountId) && isString(dataLabel)) {
				if (indeedAccountId.length > 0 && dataLabel.length > 0) {
					logger.debug(`Creating resume matching job for: ${indeedAccountId}/${dataLabel}`);
					await submitIndeedResumeMatching(indeedResumeMatchingQueue, indeedAccountId, dataLabel);
				}
			}
		}

	} catch(error) {
		if (error instanceof PageAlreadyProcessedError) {
			logger.info('<<< Skipping processed url >>>');
			workerErrorCounter.inc({ errorType: PAGE_ALREADY_PROCESSED_MSG });

		} else if (error instanceof PageReturnedNothingError) {
			logger.info('<<< Page returned nothing >>>');
			workerErrorCounter.inc({ errorType: NOT_FOUND_MSG });

		} else if (error instanceof Error && isString(job.token)) {
			logger.error(`Job processing error: ${error.toString()}`);

			const metricsErrorMessage = cleanWorkerErrorMessage(error.message);
			workerErrorCounter.inc({ errorType: metricsErrorMessage });

			throw error;

		} else {
			logger.error(`Non error instance: ${error}`);
			throw error;
		}

	} finally {
		await updateHealthInfo();

		const executionTime = (new Date()).getTime() - jobStartTime;
		logger.info(`Job execution time: ${ executionTime / 1000 }s`);

		jobRuntimeSummary.labels({
			workerId: workerId,
			workerType: 'trueSearchWorker',
			dataLabel: job.data.leadAttrs.dataLabel,
		}).observe(executionTime);

	}
}

if (process.argv[1] === fileURLToPath(import.meta.url)) {
	const worker = createWorker(redis, args.queueName, jobProcessor, workerId);
}

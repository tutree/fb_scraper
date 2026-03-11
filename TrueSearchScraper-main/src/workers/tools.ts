import crypto from 'crypto';

import { Worker } from 'bullmq';
import { Redis as IORedis } from 'ioredis';

import { REDIS_HOST, REDIS_PORT, REDIS_PASS, WORKER_CONCURRENCY, EXIT_ON_DRAIN } from '../config.js';
import logger from '../logging.js';
import { getWorkerEventsCounter } from '../metrics/worker.js';
import { pushMetrics } from '../metrics/tools.js';

import type { Job } from 'bullmq';
import type { URLJob } from '../queues/types.js';


const PUSH_METRICS_ON_NUMBER_OF_COMPLETED = 10;


type URLProcessor<T> = (job:Job<T>) => Promise<void>;


const workerEventsCounter = getWorkerEventsCounter();


async function workerTimeout(ms: number):Promise<void> {
    return new Promise((resolve, reject) => {
        setTimeout(() => reject(new Error(`Timeout: job took more than ${ms}ms`)), ms);
    });
}

function createWorker<T>(connection:IORedis, queueName:string, jobProcessor:URLProcessor<T>, workerId:string):Worker {

    const worker = new Worker(queueName, jobProcessor, { connection, concurrency: WORKER_CONCURRENCY });
	let numberOfCompleted = 0;

    worker.on('active', async () => {
        workerEventsCounter.inc({ eventName: 'active' });
    });
    worker.on('closed', async () => {
        workerEventsCounter.inc({ eventName: 'closed' });
        await pushMetrics(workerId);
    });

    worker.on('closing', async () => {
        workerEventsCounter.inc({ eventName: 'closing' });
    });

    worker.on('completed', async (job:Job) => {
		logger.info(`<<< Number of completed: ${numberOfCompleted} >>>`);

        workerEventsCounter.inc({ eventName: 'completed' });

		if (numberOfCompleted > 0 && numberOfCompleted % PUSH_METRICS_ON_NUMBER_OF_COMPLETED === 0) {
			numberOfCompleted = 0;
        	await pushMetrics(workerId);
		} else {
			numberOfCompleted = numberOfCompleted + 1;
		}
    });

    worker.on('drained', async () => {
		logger.info('<<< Worker drained >>>');

        workerEventsCounter.inc({ eventName: 'drained' });
        await pushMetrics(workerId);

		if (EXIT_ON_DRAIN) {
			process.exit(0);
		}
    });

    worker.on('error', async (error:Error) => {
        logger.error(`Worker error: ${error.message}`);

        workerEventsCounter.inc({ 
            eventName: 'error', 
            eventInfo: error.message,
        });

        await pushMetrics(workerId);
    });

    worker.on('failed', async (job:Job|undefined, error:Error, prev:string):Promise<void> => {
        logger.error(`Worker faled: ${error.message}`);

        workerEventsCounter.inc({
            eventName: 'failed',
            eventInfo: error.message,
        });

        await pushMetrics(workerId);
    });

    worker.on('ioredis:close', async () => {
        logger.warn(`IORedis closed....`);

        workerEventsCounter.inc({ eventName: 'ioredis:close' });
        await pushMetrics(workerId);

		process.exit(1);
    });

    worker.on('paused', async () => {
        workerEventsCounter.inc({ eventName: 'paused' });
        await pushMetrics(workerId);
    });

    worker.on('progress', async () => {
        workerEventsCounter.inc({ eventName: 'progress' });
        await pushMetrics(workerId);
    });

    worker.on('ready', async () => {
        workerEventsCounter.inc({ eventName: 'ready' });
    });

    worker.on('resumed', async () => {
        workerEventsCounter.inc({ eventName: 'resumed' });
    });

    worker.on('stalled', async () => {
        workerEventsCounter.inc({ eventName: 'stalled' });
        await pushMetrics(workerId);
    });

    return worker;
}

function getWorkerId():string {
	return crypto.randomBytes(20).toString('hex');
}

function cleanWorkerErrorMessage(message:string):string {
	let metricsErrorMessage = message.replace(/http?[.\:\w\/]+/, '');
	metricsErrorMessage = metricsErrorMessage.replace(/\sat\s/, '');
	metricsErrorMessage = metricsErrorMessage.trim();

	return metricsErrorMessage;
}

export { workerTimeout, createWorker, getWorkerId, cleanWorkerErrorMessage }

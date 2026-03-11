import { Redis as IORedis } from 'ioredis';

import logger from './logging.js';
import { getWorkerResultsCounter } from './metrics/worker.js';
import { getWorkerQueue } from './queues/tools.js';
import { DATA_INGEST_QUEUE_NAME, JOB_PROCESSING_ATTEMPTS } from './config.js';
import { isString } from './guards.js';

import type { ParsingResult } from './parsePage.js';
import type { TSNameSearchAttrs } from './search/types.js';
import type { Queue } from 'bullmq';


const workerResultsCounter = getWorkerResultsCounter();


async function saveResult(result:ParsingResult, leadAttrs:TSNameSearchAttrs, dataIngestQueue:Queue):Promise<void> {
    logger.info(`Result: ${JSON.stringify(result, null, 4)}`);

	await dataIngestQueue.add(
		'dataIngest', 
		{
			indeedAccountId: leadAttrs.indeedAccountId,
			dataLabel: leadAttrs.dataLabel,
			result: result,
		},
		{
			removeOnComplete: true,
			attempts: JOB_PROCESSING_ATTEMPTS,
		}
	);

    workerResultsCounter.inc({ dataLabel: result.dataLabel });
}

export { saveResult };

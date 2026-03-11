import logger from './logging.js';
import yargs from 'yargs/yargs';

import { isUrlProcessed } from './processPage.js';
import processUrl from './urlProcessor.js';
import { getWorkerQueue } from './queues/tools.js';
import { DATA_INGEST_QUEUE_NAME } from './config.js';
import { getRedisClient } from './redis/tools.js';
import { getWorkerId } from './workers/tools.js';
import { PageAlreadyProcessedError, PageReturnedNothingError } from './errors.js';


const workerId = getWorkerId();
const redis = getRedisClient();
const dataIngestQueue = getWorkerQueue(redis, DATA_INGEST_QUEUE_NAME);

async function processSingleUrl(url:string):Promise<void> {
    logger.info(`Processing url: [${url}]`);
    const leadAttrs = {
		dataLabel: 'none(processed-manually)',
		originalSearchQuery: {
			fullName: 'none(processed-manually)',
			location: 'none(processed-manually)'
		}
	};

    if (!(await isUrlProcessed(url))) {
		try {
			await processUrl(url, redis, workerId, leadAttrs, dataIngestQueue);

		} catch(error) {
			if (error instanceof PageAlreadyProcessedError) {
				logger.info('<<< Skipping processed url >>>');

			} else if (error instanceof PageReturnedNothingError) {
				logger.info('<<< Page returned nothing >>>');
			}
		}

    } else {
        logger.info(`Url already processed`);
    }
}

const args = yargs(process.argv.slice(2)).options({
	url: { type: 'string', description: 'URL to process', demand: true }
}).parseSync();

(async function run() {
	await processSingleUrl(args.url);
    process.exit(0);
})();

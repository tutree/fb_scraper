import yargs from 'yargs/yargs';
import axios from 'axios';
import { MongoClient } from 'mongodb';

import logger from '../logging.js';

import { getWorkerQueue } from '../queues/tools.js';
import { isString } from '../guards.js';
import { getRedisClient } from '../redis/tools.js';
import { getGoogleSheet } from './sheet-tools.js';
import { pushMetrics } from '../metrics/tools.js';
import { getNameSearchUrl, processRow } from './tools.js';
import { getWorkerId } from '../workers/tools.js';
import { tabProgressInit, recordProcessedRow, markTabAsFinished } from './tab-progress.js';
import mongoClient from '../mongo.js';

import type { Queue } from 'bullmq';
import type { Redis as IORedis } from 'ioredis';
import type { GoogleSpreadsheetWorksheet } from 'google-spreadsheet';

import type { TabProgressRecord } from './tab-progress.js';


type NameSearchSheetRow = {
	name: string;
	loc2: string;
}

const args = yargs(process.argv.slice(2)).options({
    queueName: { type: 'string', description: 'Worker queue', demand: true },
    sheetId: { type: 'string', description: 'Google sheet id', demand: true },
    tabName: { type: 'string', description: 'Tab name on google sheet', demand: true },
}).parseSync();


const workerId = getWorkerId();
const ROW_INDEX_STEP = 100;


async function processTab(
		mongoConnection:MongoClient, redis:IORedis, sheetId:string, tabName:string, 
		workerQueue:Queue, dataLabel:string, sheet:GoogleSpreadsheetWorksheet
	):Promise<void> { 

	logger.info(`Processing tab: ${sheetId} / ${tabName}`);

	const trueSearchDB = await mongoConnection.db('trueSearch');
	const tabProgressCollection = await trueSearchDB.collection<TabProgressRecord>('tabProgress');
	const totalRows = sheet.rowCount;
	let rowIndex = await tabProgressInit(tabProgressCollection, sheetId, tabName, totalRows);

	while (rowIndex < totalRows) {
		logger.info(`Row: ${rowIndex} / ${totalRows}`);

		const rows = await sheet.getRows<NameSearchSheetRow>({ offset: rowIndex, limit: ROW_INDEX_STEP });

		logger.info(`Got ${rows.length}`);
		if (rows.length === 0) {
			logger.warn('Got empty row, waiting 5 seconds....');
			await new Promise(resolve => setTimeout(resolve, 5000));
		}

		for (const row of rows) {
			const name = row.get('name');
			const location = row.get('loc2');

			logger.info(`<<< ${name}, ${location} >>>`);

			if (isString(name) && isString(location)) {
				const searchAttrs = {
					dataLabel: dataLabel,
					originalSearchQuery: {
						fullName: name,
						location: location,
					}
				};
				await processRow([name, location, '', ''], searchAttrs, workerQueue, workerId);
				await recordProcessedRow(tabProgressCollection, sheetId, tabName, row.rowNumber - 1);

			} else {
				logger.warn(`Skipping string with empty values...`);
			}
		}

		rowIndex += ROW_INDEX_STEP;

		if (rowIndex < totalRows) {
			await recordProcessedRow(tabProgressCollection, sheetId, tabName, rowIndex - 1);

		} else {
			await recordProcessedRow(tabProgressCollection, sheetId, tabName, totalRows);
		}
	}

	await markTabAsFinished(tabProgressCollection, sheetId, tabName, totalRows, totalRows);
}

(async function run() {
	try {
		const sheetId = args.sheetId;
		const tabName = args.tabName;
		const queueName = args.queueName;
		const dataLabel = `${sheetId}-${tabName}`;

		if (!isString(sheetId) || !isString(tabName)) {
			throw new Error('SheetId and Sheet name should be set....');
		}

		if (!isString(queueName)) {
			throw new Error('QUEUE is not set');
		}

		const mongoConnection = await mongoClient.connect();
		const redis = getRedisClient();
		const workerQueue = getWorkerQueue(redis, queueName);
		const sheet = await getGoogleSheet(sheetId, tabName);

		try {
			await processTab(mongoConnection, redis, sheetId, tabName, workerQueue, dataLabel, sheet);
			logger.info('Finished....');

		} finally {
			await mongoConnection.close();
			// await redis.close();
		}

	} catch(error) {
		if (error instanceof Error) {
			logger.error(`Tab processing error: ${error.message}`);

			if (/exceeds grid limits/ig.test(error.message)) {
				logger.info('All rows processed, exit...');
				process.exit(0);
			}

		} else {
			logger.error(`Tab processing error: ${error}`);
		}

		process.exit(1);
	}

	process.exit(0);
})();

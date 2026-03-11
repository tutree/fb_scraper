import yargs from 'yargs/yargs';

import { getGoogleSheet } from './sheet-tools.js';
import logger from '../logging.js';
import { isString } from '../guards.js';
import { getRedisClient } from '../redis/tools.js';
import { getWorkerQueue } from '../queues/tools.js';
import { cartesian } from './surnameCitySearch.js';
import { getWorkerId } from '../workers/tools.js';
import { processRow } from './tools.js';
import { NS_SURNAME_START_INDEX } from '../config.js';

import type { GoogleSpreadsheetWorksheet } from 'google-spreadsheet';


type CortesianNameSearch = {
	last_name: string;
	location: string;
	age_range: string;
    data_label: string;
}; 

type SheetParsingResponse = {
    surnames: string[]; 
    locations: string[]; 
    ages: string[]; 
    dataLabels: Record<string, string>;
};

const workerId = getWorkerId();
const ROW_INDEX_STEP = 1000;
const args = yargs(process.argv.slice(2)).options({
    queueName: { type: 'string', description: 'Worker queue', demand: true },
    sheetId: { type: 'string', description: 'Google sheet id', demand: true },
    tabName: { type: 'string', description: 'Tab name on google sheet', demand: true },
}).parseSync();


async function parseSheet(sheet:GoogleSpreadsheetWorksheet, sheetId:string, tabName:string):Promise<SheetParsingResponse> {
	logger.info(`Processing tab: ${sheetId} / ${tabName}`);

	let rowIndex = 0;
	const surnames:string[] = [];
	const locations:string[] = [];
	const ages:string[] = [];
    const dataLabels:Record<string, string> = {};
	let rowCounter = 0;

	while (rowIndex < sheet.rowCount) {
		const rows = await sheet.getRows<CortesianNameSearch>({ offset: rowIndex, limit: ROW_INDEX_STEP });

		rows.forEach((row, index) => {
			const lastName = row.get('last_name');
			const location = row.get('location');
			const age = row.get('age_range');
            const dataLabel = row.get('data_label');

			if (isString(lastName) && lastName.length > 0) {
				surnames.push(lastName);
			}

			if (isString(location) && location.length > 0 && isString(dataLabel) && dataLabel.length > 0) {
				locations.push(location);
                dataLabels[location] = dataLabel;
			}

			if (isString(age) && age.length > 0) {
				ages.push(age);
			}

			rowCounter = rowCounter + 1;
		});

		rowIndex += ROW_INDEX_STEP;

		await new Promise((resolve) => setTimeout(resolve, 1500));
	}

    return { surnames, locations, ages, dataLabels }
}


(async function run() {
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

	const redis = getRedisClient();
	const workerQueue = getWorkerQueue(redis, queueName);
	const sheet = await getGoogleSheet(sheetId, tabName);

    const sheetParsedData = await parseSheet(sheet, sheetId, tabName);

    for (const surname of sheetParsedData.surnames.slice(NS_SURNAME_START_INDEX, sheetParsedData.surnames.length)) {
        const product = cartesian([surname], sheetParsedData.locations, sheetParsedData.ages);
        logger.info(`Surname: ${surname}, product length: ${product.length}`);

        for (const row of product) {
	        const name = row[0];
	        const location = row[1];
	        const ageFrom = row[2].split('-')[0];
	        const ageTo = row[2].split('-')[1];
            const dataLabel = sheetParsedData.dataLabels[location];

            logger.debug(`Name: ${name}, location: ${location}, age: ${ageFrom}-${ageTo}, dataLabel: ${dataLabel}`);

            if (isString(name) && isString(location) && isString(ageFrom) && isString(ageTo) && isString(dataLabel)) {
                const leadAttrs = {
                    dataLabel: dataLabel,
                    originalSearchQuery: {
                        fullName: name,
                        location: location
                    }
                };
	            await processRow([name, location, ageFrom, ageTo], leadAttrs, workerQueue, workerId);

            } else {
                throw new Error(`Malformed data`);
            }
        }
    }

	process.exit(0);

})();

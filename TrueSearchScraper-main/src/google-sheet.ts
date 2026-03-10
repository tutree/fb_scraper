import axios from 'axios';

import { GOOGLE_SHEET_API_KEY, REDIS_HOST, REDIS_PORT, TRUE_SEARCH_URLS_QUEUE } from './config.js';
import logger from './logging.js';
import { getWorkerQueue } from './queues/tools.js';
import { getRedisClient } from './redis/tools.js';

import type { Queue } from 'bullmq';


function getSheetUrl(sheetId:string, tabName:string):string {
    const rowStart = 500;
    const rowEnd = 700;
    const url = `https://sheets.googleapis.com/v4/spreadsheets/${sheetId}/values/${tabName}!A$${rowStart}:A$${rowEnd}?key=${GOOGLE_SHEET_API_KEY}`;

    return url;
}

async function processPhone(phoneNumber:string, queue:Queue, dataLabel:string):Promise<void> {
    logger.info(phoneNumber);
    const url = `https://www.truepeoplesearch.com/details?phoneno=${phoneNumber}&rid=0x0`;

    await queue.add(
        'newUrl', 
        { 
            dataLabel: dataLabel,
            url: url,
            processNeighbors: true,
        }, 
        { 
            delay: 500, 
            removeOnComplete: true 
        }
    );
}

async function processSheet(sheetId:string, tabName:string, queueName:string):Promise<void> {
    const url = getSheetUrl(sheetId, tabName);
    const redis = getRedisClient();
    const queue = getWorkerQueue(redis, 'test');
    const dataLabel = `${sheetId}-${tabName}`;

    try {
        const { data } = await axios.get(url);
        for (const phoneNumber of data.values) {
            await processPhone(phoneNumber, queue, dataLabel);
            await new Promise(resolve => setTimeout(resolve, 2000));
        }

    } catch(error) {
		if (error instanceof Error) {
        	logger.error(error.message);
		}
    }
    
}

export { processSheet };

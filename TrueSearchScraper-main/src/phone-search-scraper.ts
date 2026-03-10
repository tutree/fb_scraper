import logger from './logging.js';
import { TRUE_SEARCH_URLS_QUEUE, REDIS_HOST, REDIS_PORT } from './config.js';
import { processSheet } from './google-sheet.js';
import { isString } from './guards.js';


/*
(async function run() {

    const sheetId = process.argv[2];
    const tabName = process.argv[3];
    const queueName = process.argv[4];

    if (isString(sheetId) && isString(tabName) && isString(queueName)) {
        await processSheet(sheetId, tabName, queueName);

    } else {
        throw new Error('Wrong arguments');
    }

    process.exit(0);
})();
*/

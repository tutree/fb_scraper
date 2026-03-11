import logger from '../logging.js';
import { SEARCH_ATTEMPTS, WAIT_BETWEEN_ERRORS } from '../config.js';
import { PageReturnedNothingError } from '../errors.js';
import { getSession, closeSession } from '../browser-tools.js';
import { getNameSearchParsingResultsCounter } from '../metrics/name-search.js';
import { parseUrls } from './parseSearchResultUrls.js';
import { isNumber } from '../guards.js';

import type { Queue } from 'bullmq';
import type { NameSearchArgs } from './types.js';
import type { TSNameSearchAttrs } from './types.js';


const nameSearchParsingResultsCounter = getNameSearchParsingResultsCounter();

function getNameSearchUrl(fullName:string, location:string, ageFrom:string, ageTo:string):string {
	const searchUrl = new URL('https://www.truepeoplesearch.com/results');

	searchUrl.searchParams.set('name', fullName);
	searchUrl.searchParams.set('citystatezip', location);

	if (isNumber(parseInt(ageFrom)) && isNumber(parseInt(ageTo))) {
		const ageRange = `${ageFrom}-${ageTo}`;

		searchUrl.searchParams.set('agerange', ageRange);

	} else {
		logger.warn('No age information for name search');
	}

	return searchUrl.href;
}

async function tsNameSearch({ 
		fullName, location, ageFrom, ageTo, queue, leadAttrs, workerId 
	}:NameSearchArgs): Promise<void> {

    const url = getNameSearchUrl(fullName, location, ageFrom, ageTo);
    const { page, browser } = await getSession();

    logger.info(`Opening page: [${url}]`);

    await page.goto(url, { waitUntil: 'load', timeout: 60000 });

	logger.info('Page opened');

    await parseUrls(page, queue, location, nameSearchParsingResultsCounter, leadAttrs, workerId, 0);
    await closeSession(page, browser);
}


async function processRow(
		row:[string, string, string, string], 
		leadAttrs:TSNameSearchAttrs, queue:Queue, workerId:string
	):Promise<void> {

	for (const attemp of [...Array(SEARCH_ATTEMPTS).keys()]) {
		logger.info(`Processing row: ${row}, attemp: ${attemp}`);

		try {
			await tsNameSearch({
				fullName: row[0], 
				location: row[1],
				ageFrom: row[2],
				ageTo: row[3],
				queue: queue,
				leadAttrs: leadAttrs,
				workerId: workerId
			});

			break;

		} catch(error) {
			if (error instanceof PageReturnedNothingError) {
				logger.info('<<< Page returned no results >>>');
				return;
			}

			const waitTime = WAIT_BETWEEN_ERRORS * attemp;

			if (error instanceof Error) {
        		logger.error(`Search error: ${error.message}`);

			} else {
        		logger.error(`Empty error: ${error}`);
				logger.error(JSON.stringify(error));
			}
		}
	}
}


export { getNameSearchUrl, processRow }

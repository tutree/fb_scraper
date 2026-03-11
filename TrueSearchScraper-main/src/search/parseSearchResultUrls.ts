import { TimeoutError } from 'puppeteer';
import * as cheerio from 'cheerio';

import logger from '../logging.js';
import { 
	JOB_PROCESSING_ATTEMPTS, JOB_PROCESSING_BACKOFF_DELAY,
	WAIT_BETWEEN_ERRORS, SEARCH_ATTEMPTS, NS_MAX_PAGINATION_DEPTH
} from '../config.js';
import { isString } from '../guards.js';
import { PageReturnedNothingError } from '../errors.js';
import { NOT_FOUND_MSG, ERROR_ON_THE_PAGE_MSG, CAPTCHA_DISPLAYED_MSG, SUCCESS_MSG } from '../metrics/consts.js';

import type { Page } from 'puppeteer';
import type { Queue } from 'bullmq';
import type { Counter } from 'prom-client';

import type { TSNameSearchAttrs } from './types.js';


async function getUlrs(page:Page, searchLocation:string):Promise<Set<string>> {
    const urls = new Set<string>();
    const selector = '//div[@data-detail-link]';

	try {
    	await page.waitForXPath(selector, { timeout: 30000 });

	} catch(error) {
		logger.error(await page.content());
		throw error;
	}

    const nodes = await page.$x(selector);

    if (Array.isArray(nodes)) {
        for (const node of nodes) {
            const rawHTML = await node.evaluate(elem => (elem as HTMLElement).innerHTML);

            const $ = cheerio.load(rawHTML);
            const resultLocation = $('span:contains("Lives in") ~ span.content-value').text();
            const resultHref = $('a:first').attr('href');

			if (isString(resultHref)) {
            	const url = new URL(resultHref, page.url());
            	urls.add(url.href);

			} else {
				throw new Error('Cannot process url: href is empty...');
			}
        }
    }

    return urls;
}

async function parseUrls(
		page:Page, queue:Queue, searchLocation:string, 
		nameSearchParsingResultsCounter:Counter, leadAttrs:TSNameSearchAttrs, workerId: string,
        pageNumber:number
	):Promise<void> {

    if (pageNumber > NS_MAX_PAGINATION_DEPTH) {
        logger.warn(`Reached max pagination depth of: ${NS_MAX_PAGINATION_DEPTH}, exit...`);
        return;
    }

    const title = await page.title();
    const pageUrl = page.url();
    const nextBtnSelector = '//a[@id="btnNextPage"]';
    const pageContent = await page.content();

    logger.info(`Title: ${title}`);

    if (/error/i.test(title)) {
        await Promise.all([page.reload(), page.waitForNavigation]);
        await parseUrls(page, queue, searchLocation, nameSearchParsingResultsCounter, leadAttrs, workerId, pageNumber);
		nameSearchParsingResultsCounter.labels({ 
			parsingResult: ERROR_ON_THE_PAGE_MSG, 
			dataLabel: leadAttrs.dataLabel, 
			workerId: workerId,
		}).inc();

    } else if (/captcha/i.test(title)) {
		nameSearchParsingResultsCounter.labels({ 
			parsingResult: CAPTCHA_DISPLAYED_MSG,
			dataLabel: leadAttrs.dataLabel,
			workerId: workerId,
		}).inc();
        throw new Error('Captcha displayed');

    } else if (/We could not find any records for that search criteria/i.test(pageContent)) {
		nameSearchParsingResultsCounter.labels({ 
			parsingResult: NOT_FOUND_MSG,
			dataLabel: leadAttrs.dataLabel, 
			workerId: workerId,
		}).inc();
        throw new PageReturnedNothingError('Page returned no content');

    } else if (/There has been an unknown error, please try again/i.test(pageContent)) {
		nameSearchParsingResultsCounter.labels({ 
			parsingResult: NOT_FOUND_MSG,
			dataLabel: leadAttrs.dataLabel,
			workerId: workerId,
		});
        throw new PageReturnedNothingError('Page returned no content');

	} else if (/This IP has been rate limited/i.test(pageContent)) {
        throw new Error('Ip rate limited');

	} else if (/If searching with city you must include the state too/i.test(pageContent)) {
        throw new Error('Query error');

    } else {
        logger.debug(`URL: ${pageUrl}`);
        
        for (const url of await getUlrs(page, searchLocation)) {
            logger.debug(`Adding url: ${url}`);

            await queue.add('newUrl', { url, leadAttrs }, { 
                removeOnComplete: true, 
                attempts: JOB_PROCESSING_ATTEMPTS,
            });

			nameSearchParsingResultsCounter.labels({ 
			  	parsingResult: SUCCESS_MSG,
				dataLabel: leadAttrs.dataLabel,
				workerId: workerId,
			}).inc();
        }

        try {
            await page.waitForXPath(nextBtnSelector, { timeout: 2000 });

        } catch(error) {
            if (error instanceof TimeoutError) {
				logger.info(pageContent);
                logger.info('No more pages, exit.');
                return;
            }

            if (error instanceof Error) {
                logger.warn(`Next buton selector error: ${error.message}`);
                return;
            }
        }
        const nextPageBtn = await page.$x(nextBtnSelector);

        if (Array.isArray(nextPageBtn) && nextPageBtn.length > 0) {
            await nextPageBtn[0].evaluate(elem => (elem as HTMLElement).click());
            await page.waitForNavigation();

            for (const attemp of [...Array(3).keys()]) {
                try {
                    await parseUrls(page, queue, searchLocation, nameSearchParsingResultsCounter, leadAttrs, workerId, pageNumber + 1);
                    break;

                } catch(error) {
                    if (error instanceof Error) {
                        logger.error(`Pagination error: ${error.message}`);
                    }

					if (error instanceof PageReturnedNothingError) {
						break;
					}

                    await Promise.all([page.goto(pageUrl), page.waitForNavigation]);
                }
            }

        } else {
            logger.info('No more pages, exit.');
        }
    }
}

export { parseUrls }

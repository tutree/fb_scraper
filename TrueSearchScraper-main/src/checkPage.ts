import logger from './logging.js';
import { isUrlProcessed } from './processPage.js';
import { PageAlreadyProcessedError, PageReturnedNothingError } from './errors.js';
import { isString } from './guards.js';

import type { Page } from 'puppeteer';


async function checkPage(page:Page):Promise<void> {
    const pageTitle = await page.title();
    const pageContent = await page.content();
    const pageUrl = page.url();

    logger.info(`Page title: ${pageTitle}`);

    if (/error/i.test(pageTitle)) {
        throw new Error('Page returned error');
    }

    if (/We could not find any records for that search criteria/i.test(pageContent)) {
        throw new PageReturnedNothingError('Page returned no content');
    }

	if (/This record is no longer available/i.test(pageContent)) {
        throw new PageReturnedNothingError('Page returned no content');
	}

	if (/This IP has been rate limited/i.test(pageContent)) {
		throw new Error('Ip rate limited');
	}

    if (await isUrlProcessed(pageUrl)) {
        throw new PageAlreadyProcessedError('Page already processed');
    }
}

export { checkPage };

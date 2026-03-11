import { TimeoutError } from 'puppeteer';
import { Redis as IORedis } from 'ioredis';

import { isString } from './guards.js';
import { resolveCaptcha, failOnCaptcha } from './captcha.js';
import { parsePage } from './parsePage.js';
import { saveResult } from './saveResult.js';
import { checkPage } from './checkPage.js';
import { CaptchaError } from './errors.js';
import logger from './logging.js';
import { PROCESSED_DATA_CHECK_URL, PROCESS_EXISTING } from './config.js';

import type { Page } from 'puppeteer';
import type { Queue } from 'bullmq';

import type { TSNameSearchAttrs } from './search/types.js';


async function isCaptchaDisplayed(page:Page):Promise<string|void> {
    logger.debug(`Checking captcha`);

    try {
        await page.waitForSelector('div.h-captcha', {timeout: 5000});
        const siteKey = await page.evaluate(() => {
            const elem = document.querySelector('div.h-captcha') as HTMLElement;
            if (elem) {
                return elem.dataset.sitekey;
            }
        });
        return siteKey;

    } catch(error) {
        if (error instanceof TimeoutError) {
            logger.debug('Captcha not found');

        } else {
            throw error;
        }
    }
}


async function processPage(
		page:Page, redis:IORedis, originUrl:string, leadAttrs:TSNameSearchAttrs, dataIngestQueue:Queue
	):Promise<void> {

    const siteKey = await isCaptchaDisplayed(page);

    if (failOnCaptcha()) {
        if (isString(siteKey)) {
            throw new Error('Captcha displayed, exit...');
        }
    }

    if (isString(siteKey)) {
        throw new CaptchaError(siteKey);
    }

	try {
		await checkPage(page);
		const result = await parsePage(page, redis, leadAttrs);
		await saveResult(result, leadAttrs, dataIngestQueue);

	} catch(error) {
		logger.error(await page.content());
		throw error;
	}
}

async function isUrlProcessed(url:string):Promise<boolean> {
	if (PROCESS_EXISTING) {
		return false;
	}

    try {
        const resp = await fetch(`${PROCESSED_DATA_CHECK_URL}?url=${url}`);
        const data = await resp.json();

        logger.info(data);

        return data.URLProcessed;

    } catch(error) {
        logger.warn(`Cannot check if url was processed: ${error instanceof Error ? error.message : 'empty'}`);
    }

    return false;
}

export { processPage, isUrlProcessed };

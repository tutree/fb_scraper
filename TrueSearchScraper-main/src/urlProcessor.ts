import puppeteer from 'puppeteer';
import { Redis as IORedis } from 'ioredis';

import logger from './logging.js';
import { getSession, closeSession } from './browser-tools.js';
import { processPage } from './processPage.js';
import { CaptchaError } from './errors.js';
import { resolveCaptcha } from './captcha.js';
import { getWorkerCaptchasCounter } from './metrics/worker.js';

import type { Queue } from 'bullmq';

import type { TSNameSearchAttrs } from './search/types.js';


const workerCaptchasCounter = getWorkerCaptchasCounter();


async function processUrl(
		url:string, redis:IORedis, workerId:string, leadAttrs:TSNameSearchAttrs, dataIngestQueue:Queue
	):Promise<void> {

    const { page, browser } = await getSession();

    logger.debug(`Open page: ${url}`);

    await page.goto(url, { waitUntil: 'domcontentloaded', timeout: 60000 });

    try {
        await processPage(page, redis, url, leadAttrs, dataIngestQueue);

    } catch(error) {
		if (error instanceof Error) {
			logger.error(`Page processing error: ${error.message}`);

		} else {
			logger.error(`Page processing error: ${error}`);
		}

        if (error instanceof CaptchaError) {
            workerCaptchasCounter.inc();

            const captchaUrl = page.url();
            await closeSession(page, browser);

            const siteKey = error.message;
            const { page:captchaSovledPage, browser:captchaSolvedBrowser } = await resolveCaptcha(
                siteKey, url, captchaUrl, redis, workerId
            );

            await processPage(captchaSovledPage, redis, url, leadAttrs, dataIngestQueue);
            await closeSession(captchaSovledPage, captchaSolvedBrowser);
		
        } else {
			throw error;
		}
    } finally {
        await closeSession(page, browser);
    }
}

export default processUrl;

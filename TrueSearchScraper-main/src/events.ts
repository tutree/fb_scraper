import logger from './logging.js';
import { SHOW_BROWSER_CONSOLE_MESSAGES } from './config.js';

import type { Page } from 'puppeteer';


const ABORT_URLS = [
    'www.google.com',
];

const SKIP_URLS:string[] = [
    // '/internalcaptcha/captchasubmit',
];


const RESOURCES_TO_SKIP = ['image', 'stylesheet', 'font', 'script', 'other', 'manifest'];


function createPageEvents(page:Page):void {
    page.on('request', (request) => {
		logger.debug(`Resource type: ${request.resourceType()}`);

        if (RESOURCES_TO_SKIP.indexOf(request.resourceType()) !== -1) {
            logger.warn(`Abort url: [${request.url().slice(0, 100)}]`);
            request.abort();
            return;

        } else {
            if (ABORT_URLS.find(x => request.url().indexOf(x) > -1)) {
                logger.warn(`Abort url: [${request.url()}]`);
                request.abort();
                return;
            }

            if (!SKIP_URLS.find(x => request.url().indexOf(x) > -1)) {
                request.continue();
                return;

            } else {
                logger.warn(`Skip url: [${request.url()}]`);
                return;
            }
        }
    });

    page.on('response', (response) => {
        logger.debug(`<-- Page response: ${response.url().slice(0, 100)} / ${response.status()}`);
    });

    page.on('error', (error) => {
        logger.error(`+++ Page error: ${error.message} +++`);
    });

    page.on('pageerror', (error) => {
		if (SHOW_BROWSER_CONSOLE_MESSAGES) {
        	logger.error(`+++ Page error: ${error.message} +++`);
		}
    });

    page.on('requestfailed', (request) => {
        // logger.error(`+++ Request error: ${request.url()} +++`);
    });
}

export default createPageEvents;

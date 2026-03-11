import { errors as ppErrors } from 'puppeteer';

import logger from '../logging.js';
import { isString } from '../guards.js';
import { XPATH_NODES_WAITING_TIMEOUT } from '../config.js';

import type { Page } from 'puppeteer';


export type PropertyDetails = {
    [key:string]: string;
};


async function parsePropertyDetails(page:Page):Promise<PropertyDetails> {
	logger.debug('<<< Parse property details >>>');

    const data:PropertyDetails = {};
    const selector = '//div[@class="h5" and contains(., "Current Address Property Details") ]/parent::div/parent::div/parent::div//div[@class="col-6 col-md-3 mb-2"]';
    
    try {
		logger.debug(`Waiting: ${XPATH_NODES_WAITING_TIMEOUT}`);
        await page.waitForXPath(selector, { timeout: XPATH_NODES_WAITING_TIMEOUT});
        const nodes = await page.$x(selector);

        if (Array.isArray(nodes)) {
			for (const node of nodes) {
                const rawHTML = await node.evaluate(elem => (elem as HTMLElement).innerHTML);
                const parsedData = rawHTML.split('<br>');

                if (isString(parsedData[0]) && isString(parsedData[1])) {
                    const recordKey = parsedData[0].trim().replace(/\s/g, '_').toLowerCase();
                    const recordValue = parsedData[1].trim().replace(/<\/?b>/g, '').toLowerCase().trim();

                    data[recordKey] = recordValue;
                }
			}
        }


    } catch(error) {
        if (error instanceof ppErrors.TimeoutError) {
            logger.debug('<<< No property info >>>');

        } else {
            throw error;
        }
    }

    return data;
}


export default parsePropertyDetails;

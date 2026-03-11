import { URL } from 'node:url';
import { errors as ppErrors } from 'puppeteer';
import * as cheerio from 'cheerio';

import logger from '../logging.js';
import { XPATH_NODES_WAITING_TIMEOUT } from '../config.js';

import type { Page } from 'puppeteer';


type RelativeInfo = {
    fullName: string;
    url: string;
    yob: string;
};


async function parseRelatives(page:Page):Promise<RelativeInfo[]> {
    const selector = '//div[contains(., "Possible Relatives") and contains(@class, "h5")]/parent::div/parent::div/parent::div//div[contains(@class, "col-6")]';
    const relatives:RelativeInfo[] = [];

    try {
        await page.waitForXPath(selector, { timeout: XPATH_NODES_WAITING_TIMEOUT });

        const nodes = await page.$x(selector);

        if (Array.isArray(nodes)) {
            nodes.map(async node => {
                const relative:RelativeInfo = {
                    yob: '',
                    fullName: '',
                    url: '',
                };
                const rawHTML = await node.evaluate(elem => (elem as HTMLElement).innerHTML);

                const $ = cheerio.load(rawHTML);
                const urlNode = $('div > a')[0];
                if (urlNode) {
                    const parsedUrl = new URL(urlNode.attribs.href, page.url());
                    relative.url = parsedUrl.href;
                }

                relative.fullName = $('div > a').text();

                const ageText = $('div > div > span').text().trim();
				const ageGroup = ageText.match(/\d+/);

                if (Array.isArray(ageGroup)) {
					const age = parseInt(ageGroup[0]);
					if (age && age > 0) {
                    	relative.yob = ((new Date()).getFullYear() - age).toString();
					}
                }

                if (relative.yob && relative.fullName && relative.url) {
                    relatives.push(relative);
                }
            });
        }

    } catch(error) {
        if (error instanceof ppErrors.TimeoutError) {
            logger.debug('<<< Relatives not found >>>');
            return [];

        } else {
            throw error;
        }
    }

    return relatives;
}

export { parseRelatives, RelativeInfo };

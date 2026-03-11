import { URL } from 'node:url';
import { errors as ppErrors } from 'puppeteer';
import * as cheerio from 'cheerio';

import logger from '../logging.js';
import { XPATH_NODES_WAITING_TIMEOUT } from '../config.js';

import type { Page } from 'puppeteer';


type AssociateInfo = {
    fullName: string;
    url: string;
    yob: string;
};


async function parseAssociates(page:Page):Promise<AssociateInfo[]> {
	const selector = '//div[contains(., "Possible Associates") and contains(@class, "h5")]/parent::div/parent::div/parent::div//div[contains(@class, "col-6")]';
    const associates:AssociateInfo[] = [];

    try {
        await page.waitForXPath(selector, { timeout: XPATH_NODES_WAITING_TIMEOUT });

        const nodes = await page.$x(selector);

        if (Array.isArray(nodes)) {
            nodes.map(async node => {
                const associate:AssociateInfo = {
                    yob: '',
                    fullName: '',
                    url: '',
                };
                const rawHTML = await node.evaluate(elem => (elem as HTMLElement).innerHTML);

                const $ = cheerio.load(rawHTML);
                const urlNode = $('div > a')[0];
                if (urlNode) {
                    const parsedUrl = new URL(urlNode.attribs.href, page.url());
                    associate.url = parsedUrl.href;
                }

                associate.fullName = $('div > a').text();

                const ageText = $('div > div > span').text().trim();
                const ageGroup = ageText.match(/\d+/);

                if (Array.isArray(ageGroup)) {
					const age = parseInt(ageGroup[0]);
					if (age && age > 0) {
                    	associate.yob = ((new Date()).getFullYear() - age).toString();
					}
                }

                if (associate.yob && associate.fullName && associate.url) {
                    associates.push(associate);
                }
            });
        }

    } catch(error) {
        if (error instanceof ppErrors.TimeoutError) {
            logger.debug('<<< Associates not found >>>');
            return [];

        } else {
            throw error;
        }
    }

    return associates;
}

export { parseAssociates, AssociateInfo };

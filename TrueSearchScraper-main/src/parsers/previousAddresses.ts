import { errors as ppErrors } from 'puppeteer';
import * as cheerio from 'cheerio';

import logger from '../logging.js';

import type { Page } from 'puppeteer';


export type PreviousAddress = {
	streetAddress: string;
	addressLocality: string;
	addressRegion: string;
	postalCode: string;
};


function parseAddressHTML(rawHTML:string):PreviousAddress {
	const $ = cheerio.load(rawHTML);

	return {
		streetAddress: $('a > span[itemprop="streetAddress"]').text(),
		addressLocality: $('a > span[itemprop="addressLocality"]').text(),
		addressRegion: $('a > span[itemprop="addressRegion"]').text(),
		postalCode: $('a > span[itemprop="postalCode"]').text(),
	}
}


async function parsePreviousAddresses(page:Page):Promise<PreviousAddress[]> {
	logger.debug(`<<< Parsing previous addresses >>>`);

	const previousAddresses:PreviousAddress[] = [];
	const addressBlockXpath = '//text()[contains(., "Previous Addresses")]/parent::div/parent::div/parent::div/parent::div//a/parent::div';

	try {
		await page.waitForXPath(addressBlockXpath, { timeout: 2000 });
		const nodes = await page.$x(addressBlockXpath);

		if (Array.isArray(nodes)) {
			await Promise.all(nodes.map(async node => {
				const rawHTML = await node.evaluate(elem => (elem as HTMLElement).innerHTML);
				logger.debug(rawHTML);

				try {
					const previousAddress = parseAddressHTML(rawHTML);
					logger.debug(previousAddress);

					previousAddresses.push(previousAddress);

				} catch(error) {
					logger.error(`Cannot parse previous address: ${ (error instanceof Error) ? error.message: 'null' }`);
				}
			}));
		}

	} catch(error) {
		if (error instanceof ppErrors.TimeoutError) {
			logger.debug('<<< No previous addresses >>>');

		} else {
			throw error;
		}
	}

	return previousAddresses;
}

export { parsePreviousAddresses }

import { errors as ppErrors } from 'puppeteer';
import * as cheerio from 'cheerio';

import logger from '../logging.js';
import { isString } from '../guards.js';

import { XPATH_NODES_WAITING_TIMEOUT } from '../config.js';

import type { Page } from 'puppeteer';


export type PhoneNumberRecord = {
    phoneNumber?: string;
    type?: string;
    primary?: boolean;
    lastReported?: string;
    carrierInfo?: string;
};

type PhoneNumbers = {
    [key: string]: string[];
};

function cleanPhone(rawPhone:string):string {
    return rawPhone.trim().replace(/[-()\ ]/g, '');
}


async function getRawPhoneHtmlStrings(page:Page, xpathSelector:string):Promise<string[]> {
    const nodes = await page.$x(xpathSelector);

    const rawNodes = nodes.map(async node => {
        return await node.evaluate(async elem => {
            const htmlElem = elem as HTMLElement;

            if (htmlElem.innerHTML) {
                return await htmlElem.innerHTML;
            }

            return '';
        });
    });

    return (await Promise.all(rawNodes)).filter(isString);
}

async function parsePhoneInfo(rawHtml:string):Promise<PhoneNumberRecord> {
    logger.info(rawHtml);

    const result:PhoneNumberRecord = {};

    const $ = cheerio.load(rawHtml);

    let phoneNumber = $('span[itemprop="telephone"]').text();
    if (isString(phoneNumber)) {
        result.phoneNumber = cleanPhone(phoneNumber);
    }
    const phoneType = $('span[class="smaller"]').text();
    if (isString(phoneType)) {
        result.type = phoneType;
    }
    const isPrimary = rawHtml.search(/primary/i) > -1 ? true : false;
    result.primary = isPrimary;


    const lastReportedGroups = rawHtml.match(/last reported (\w+ \d{4})/i);
    if (Array.isArray(lastReportedGroups) && lastReportedGroups.length > 0) {
        if (isString(lastReportedGroups[1])) {
            result.lastReported = lastReportedGroups[1];
        }
    }

    const carrierInfo = $('div > div > span:last-of-type').text();
    if (isString(carrierInfo)) {
        result.carrierInfo = carrierInfo.trim();
    }

    return result;
}

async function parsePhoneNumbers(page:Page):Promise<PhoneNumberRecord[]> {
    logger.debug('<<< Parsing phone numbers >>>');

    const selector = '//text()[contains(.,"Phone Numbers")]/parent::div/parent::div/parent::div/following-sibling::div/div';

    try {
		logger.debug(`Waiting for ${XPATH_NODES_WAITING_TIMEOUT}`);
        await page.waitForXPath(selector, { timeout: XPATH_NODES_WAITING_TIMEOUT });

    } catch (error) {
        if (error instanceof ppErrors.TimeoutError) {
            logger.warn('<<< No phone numbers on the page >>>');
            return [];

        } else {
            throw error;
        }
    }

	logger.debug(`Parsing phones...`);
    const rawPhoneHtmlStrings = await getRawPhoneHtmlStrings(page, selector);
    const phoneRecords = rawPhoneHtmlStrings.map(async rawHtml => {
        return await parsePhoneInfo(rawHtml);
    });

    const parsedRecords = Promise.all(phoneRecords);

	return parsedRecords;
}

async function parsePrimaryPhone(page:Page):Promise<string> {
    const selector = '//*[starts-with(text(), "Possible Primary Phone")]/parent::span/parent::div/parent::div//a/span[@itemprop="telephone"]';

    try {
        await page.waitForXPath(selector);

    } catch(error) {
        if (error instanceof ppErrors.TimeoutError) {
            return '';
        } else {
            throw error;
        }
    }

    const nodes = await page.$x(selector);
    if (nodes.length > 0) {
        const phone = await nodes[0].evaluate(elem => elem.textContent);

        if (isString(phone)) {
            return cleanPhone(phone);
        }
    }

    return '';
}

export { parsePhoneNumbers, parsePrimaryPhone };

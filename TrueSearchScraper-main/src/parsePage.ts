import url from 'node:url';

import fullNameParser from 'parse-full-name';
import addressParser from 'parse-address';
import { errors as ppErrors } from 'puppeteer';
import { Redis as IORedis } from 'ioredis';

import logger from './logging.js';
import { isString } from './guards.js';
import parsePropertyDetails from './parsers/propertyDetails.js'; import { parsePhoneNumbers, parsePrimaryPhone } from './parsers/phoneNumbers.js';
import { 
    XPATH_NODES_WAITING_TIMEOUT, XPATH_INIT_WAITING_TIMEOUT, RELATIVES_QUEUE_NAME, JOB_PROCESSING_ATTEMPTS,
    JOB_PROCESSING_BACKOFF_DELAY, PROCESS_RELATIVES
} from './config.js';
import { parseRelatives } from './parsers/relatives.js';
import { parseNeighbors } from './parsers/neighbors.js';
import { getWorkerQueue } from './queues/tools.js';
import { parsePreviousAddresses } from './parsers/previousAddresses.js';
import { showRuntime } from './runtime/tools.js';
import { parseAssociates } from './parsers/associates.js';

import type { Page } from 'puppeteer';
import type { Queue } from 'bullmq';
import type { PropertyDetails } from './parsers/propertyDetails.js';
import type { PhoneNumberRecord } from './parsers/phoneNumbers.js';
import type { RelativeInfo } from './parsers/relatives.js';
import type { NeighborsInfo } from './parsers/neighbors.js';
import type { PreviousAddress } from './parsers/previousAddresses.js';
import type { TSNameSearchAttrs } from './search/types.js';
import type { AssociateInfo } from './parsers/associates.js';


type DateOfBirth = {
    deceased: boolean;
    year: number;
    month: string;
};

export type ParsingResult = {
    url: string;
    dataLabel: string;
    name: string;
    age: string;
    address: string;
    relatedUrls: string[];
    associatedUrls: string[];
    emails: string[];
    phoneNumbers: PhoneNumberRecord[];
    dob: DateOfBirth;
    processingTime: number;
    firstName: string;
    lastName: string;
    middleName: string;
    city: string;
    state: string;
    zip: string;
    propertyDetails: PropertyDetails;
    primaryPhone: string;
    relatives: RelativeInfo[];
    associates: AssociateInfo[];
    neighbors: NeighborsInfo[];
	originalSearchQuery: Record<string, string>;
	previousAddresses: PreviousAddress[];
};

type AnchroNode = {
    href: string;
};


const RELATIVES_YEAR_GTE = 1990;


async function addToRelativesQueue(relativesQueue:Queue, url:string, dataLabel:string):Promise<void> {
    logger.debug(`Adding to relatives queue: ${url}`);

    await relativesQueue.add(
        'newUrl', 
        { url, dataLabel }, 
        { 
            attempts: JOB_PROCESSING_ATTEMPTS,
            removeOnComplete: true,
            backoff: {
                type: 'exponential',
                delay: JOB_PROCESSING_BACKOFF_DELAY,
            }
        }
    );
}


async function parseName(page:Page):Promise<string> {
    logger.debug(`<<< Parsing name >>>`);
    const selector = '//*[@id="personDetails"]//h1[@class="oh1"]';

    await page.waitForXPath(selector, { timeout: XPATH_INIT_WAITING_TIMEOUT });

    const nodes = await page.$x(selector);

    if (!Array.isArray(nodes) || nodes.length < 1) {
        throw new Error('Parsing error: cannot select name');
    }

    const name = await nodes[0].evaluate(elem => elem.textContent);

    if (isString(name)) {
        return name.trim();;
    }

    throw new Error('Name is missing');
}

async function parseAge(page:Page):Promise<string> {
    logger.debug('<<< Parsing age >>>');

    let selector = '//*[ starts-with(text(), "\nAge") ]';

    try {
        await page.waitForXPath(selector, { timeout: XPATH_INIT_WAITING_TIMEOUT });

    } catch(error) {
        if (error instanceof ppErrors.TimeoutError) {
            selector = '//*[ starts-with(text(), "\nDeath Record") ]';
        }

		try {
        	await page.waitForXPath(selector, { timeout: XPATH_INIT_WAITING_TIMEOUT });

		} catch(error) {
			if (error instanceof ppErrors.TimeoutError) {
				throw new Error('Age parsing timeout');

			} else {
				throw error;
			}
		}
    }

    const nodes = await page.$x(selector);

    if (nodes.length > 0) {
        const age = await nodes[0].evaluate(elem => elem.textContent);
        if (isString(age)) {
            return age.trim();
        }
    }

    throw new Error('Age is missing');
}

function parseDateOfBirth(ageData:string): DateOfBirth {
    const dob:DateOfBirth = {
        deceased: false,
        year: -1,
        month: '',
    };

    if (/unknown/i.test(ageData)) {
        dob.deceased = false;
        dob.year = -1;
        dob.month = '';

    } else if (/death/i.test(ageData)) {
        dob.deceased = true;
        dob.year = 1900;
        dob.month = 'Jan';

    } else {
        const groups = ageData.match(/(\w+)\s(\d+)$/);
        if (groups && groups.length >= 2) {
            dob.deceased = false;
            dob.month = groups[1];
            dob.year = parseInt(groups[2]);

        } else {
			throw new Error(`Cannot parse age string: ${ageData}`);
		}
    }

    return dob;
}

async function parseAddress(page:Page):Promise<string> {
    logger.debug('<<< Parsing address >>>');

    const selector = '//text()[contains(.,"Current Address")]/parent::div/parent::div/parent::div/following-sibling::div/div/div/a';
    const nodes = await page.$x(selector);

    if (Array.isArray(nodes) && nodes.length > 0) {
        const addr = await nodes[0].evaluate(elem => (elem as HTMLElement).innerText);
        if (isString(addr)) {
            return addr.replace(/\n/g, ' ').replace(/\&/g, '-').replace(/\#/, '');
        }
    }

    return 'No address';
}

async function parseRelatedUrls(page:Page):Promise<string[]> {
    logger.debug('<<< Parsing related urls >>>');

    const selector = '//text()[contains(.,"Relatives")]/parent::div/parent::div/parent::div/parent::div//a';
    const nodes = await page.$x(selector);

    const urls = nodes.map(async node => {
        return await node.evaluate(elem => (elem as HTMLLinkElement).href);
    });

    return await Promise.all(urls);
}

async function parseAssociatedUrls(page:Page):Promise<string[]> {
    logger.debug('<<< Parsing associated urls >>>');

    const selector = '//text()[contains(.,"Possible Associates")]/parent::div/parent::div/parent::div/following-sibling::div//a';
    const nodes = await page.$x(selector);

    const urls = nodes.map(async node => {
        return await node.evaluate(elem => (elem as HTMLLinkElement).href);
    });

    return await Promise.all(urls);
}

async function parseEmails(page:Page):Promise<string[]> {
    logger.debug('<<< Parsing emails >>>');

    const selector = '//text()[contains(.,"Email Addresses")]/parent::div/parent::div/parent::div/following-sibling::div';
    const nodes = await page.$x(selector);

    const emails = nodes.map(async node => {
        return await node.evaluate(elem => elem.textContent);
    });

    return (await Promise.all(emails)).filter(isString).map(i => i.replace(/\n/g, '').trim());
}

function parseFirstName(fullName:string):string {
    const buff = fullName.split(' ');

    if (buff.length > 0) {
        if (isString(buff[0])) {
            return buff[0];
        }
    }

    throw new Error('Cannot parse first name');
}

function parseLastName(fullName:string):string {
    const buff = fullName.split(' ');

    if (buff.length >= 2) {
        return buff.slice(1).join(' ');
    }

    throw new Error('Cannot parse last name');
}

async function processRelatives(page:Page, redis:IORedis, dataLabel:string):Promise<void> {
    const relativesQueue = getWorkerQueue(redis, RELATIVES_QUEUE_NAME);

    const selector = '//text()[contains(.,"Relatives")]/parent::div/parent::div/parent::div/parent::div//div[@class="col-6 col-md-3 mb-3"]';
    const nodes = await page.$x(selector);

    for (const node of nodes) {

        const data = await page.evaluate(elem => (elem as HTMLElement).innerHTML, node);
        const yearGroup = data.match(/Born([\s\w]+)? (\d{4})/);

        if (Array.isArray(yearGroup)) {
            const nodeYear = parseInt(yearGroup[2]);

            if (!Number.isNaN(nodeYear)) {
                if (nodeYear >= RELATIVES_YEAR_GTE) {
                    logger.debug(`Process relative: ${nodeYear}`);

                    const urlGroup = data.match(/href=\"([-\w\/]+)\"/);
                    if (Array.isArray(urlGroup)) {
                        const path = urlGroup[1];
                        const origin = new url.URL(page.url());
                        const relativeUrl = new url.URL(path, origin.origin);

                        await addToRelativesQueue(relativesQueue, relativeUrl.href, dataLabel);
                    }

                } else {
                    logger.debug(`Skip relative: ${nodeYear}`);
                }

            } else {
                throw new Error('Node year is not a number');
            }

        } else {
            throw new Error('Cannot match year of birth');
        }
    }

}

async function parsePage(
		page:Page, redis:IORedis, leadAttrs: TSNameSearchAttrs
	):Promise<ParsingResult> {

	logger.debug(`<<< Parse page >>>`);

    const fullName = await showRuntime<Page, string>(parseName, page);
    const age = await showRuntime<Page, string>(parseAge, page);
    const address = await showRuntime<Page, string>(parseAddress, page);
    const parsedName = fullNameParser.parseFullName(fullName);
    const parsedAddress = addressParser.parseLocation(address); 

	logger.info(`Parsed address: ${parsedAddress}`);

	const phoneNumbers = await showRuntime<Page, PhoneNumberRecord[]>(parsePhoneNumbers, page); 
	const primaryPhoneRecord = phoneNumbers.find((obj) => obj.primary);
	const primaryPhone = primaryPhoneRecord && isString(primaryPhoneRecord.phoneNumber) ? primaryPhoneRecord.phoneNumber : '';


	const result:ParsingResult = {
        url: page.url(),
        dataLabel: leadAttrs.dataLabel,
		originalSearchQuery: leadAttrs.originalSearchQuery,
        name: fullName,
        age: age,
        address: address,
        relatedUrls: await showRuntime<Page, string[]>(parseRelatedUrls, page),
        associatedUrls: await showRuntime<Page, string[]>(parseAssociatedUrls, page),
		phoneNumbers: phoneNumbers,
        emails: await showRuntime<Page, string[]>(parseEmails, page),
        dob: await showRuntime<string, DateOfBirth>(parseDateOfBirth, age),

        processingTime: (new Date()).getTime(),
        firstName: parsedName.first || '',
        lastName: parsedName.last || '',
        middleName: parsedName.middle || '',
        city: parsedAddress.city || '',
        state: parsedAddress.state || '',
        zip: parsedAddress.zip || '',
        propertyDetails: await showRuntime<Page, PropertyDetails>(parsePropertyDetails, page),
        primaryPhone: primaryPhone,
        relatives: await showRuntime<Page, RelativeInfo[]>(parseRelatives, page),
		associates: await showRuntime<Page, AssociateInfo[]>(parseAssociates, page),
        neighbors: await parseNeighbors(page, redis, `${leadAttrs.dataLabel}-neighbor`),
		previousAddresses: await showRuntime<Page, PreviousAddress[]>(parsePreviousAddresses, page),
    };

	if (PROCESS_RELATIVES) {
    	await processRelatives(page, redis, leadAttrs.dataLabel);
	}

    return result;
}

export { parsePage };

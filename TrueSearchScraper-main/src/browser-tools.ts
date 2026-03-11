import axios from 'axios';
import puppeteer from 'puppeteer';
import { KnownDevices } from 'puppeteer';

import { 
    VIEWPORT_WIDTH, VIEWPORT_HEIGHT, WINDOW_WIDTH, WINDOW_HEIGHT, 
    CHROME_URL, CHROME_TOKEN, TIME_ZONE, PROXY_USER, PROXY_PASS,
    PROXY_IP, PROXY_PORT 
} from './config.js';
import { isString } from './guards.js';

import logger from './logging.js';
import createPageEvents from './events.js';

import type { Browser, Page } from 'puppeteer';
import type { GetRandomDeviceName } from './types/tools.js';


export type BrowserSession = {
    page: Page;
    browser: Browser;
};

const DEVICES = [
    'iPhone 4', 'iPhone X', 'iPhone X landscape', 'iPhone XR', 'iPhone 11', 'iPhone 11',
    'Blackberry PlayBook landscape', 'BlackBerry Z30', 'BlackBerry Z30 landscape', 'Galaxy Note 3'
] as const;


const getRandomDeviceName:GetRandomDeviceName = () => {
    const deviceIndex = Math.floor((Math.random() % DEVICES.length) * DEVICES.length);
    return DEVICES[deviceIndex];
};

function getBrowserEndpoint():string {
    const proxyAddr = `${PROXY_IP}:${PROXY_PORT}`;
    const browserWSEndpoint = `ws://${CHROME_URL}?token=${CHROME_TOKEN}&--proxy-server=http://${proxyAddr}&stealth&blockAds`;

    return browserWSEndpoint;
}

async function getBrowser():Promise<Browser> {
    const chromeSettings = {
        browserWSEndpoint: getBrowserEndpoint(),
    };

    logger.debug(`Chrome connect: ${JSON.stringify(chromeSettings, null, 1)}`);

	try {
		const browser = await puppeteer.connect(chromeSettings);

		browser.on('disconnected', () => {
			logger.warn(`Browser disconnected...`);
		});

		browser.on('error', () => {
			logger.error('Broser error');
		});

		browser.on('targetchanged', () => {
			logger.debug('Target changed');
		});

		browser.on('targetcreated', () => {
			logger.debug('Target created');
		});

		browser.on('targetdestroyed', () => {
			logger.debug('Target destroyed');
		});

		return browser;

	} catch(error) {
		if (error instanceof Error) {
			logger.error(error.message);
		}
		throw Error('Chrome connection error');
	}
}

async function createPage(browser:Browser):Promise<Page> {
    const context = await browser.createIncognitoBrowserContext();

    const page = await context.newPage();
    await page.setRequestInterception(true);

    const deviceName = getRandomDeviceName();
    logger.info(`Using device: [${deviceName}]`);
    await page.emulate(KnownDevices[deviceName]);

    createPageEvents(page);

    await page.setExtraHTTPHeaders({ DNT: '1' })
    await page.emulateTimezone(TIME_ZONE);

    await page.authenticate({
        username: PROXY_USER as string,
        password: PROXY_PASS as string,
    });

    return page;
}

async function closeSession(page:Page, browser:Browser):Promise<void> {
    logger.info(`<<< Closing browser >>>`);
    await browser.close();
}

async function getSession():Promise<BrowserSession> {
    logger.debug(`Creating new browser session`);

    const browser = await getBrowser();
    const page = await createPage(browser);

    return { page, browser };
}


export { getBrowserEndpoint, getBrowser, createPage, closeSession, getSession }

import puppeteer from 'puppeteer';

import { getBrowserEndpoint } from './browser-tools.js';
import {
    VIEWPORT_WIDTH, VIEWPORT_HEIGHT, TIME_ZONE, REDIS_HOST, 
    REDIS_PORT, PROXY_USER, PROXY_PASS 
} from './config.js';
import { processPage } from './processPage.js';


async function processUrl(url:string):Promise<void> {
    console.log(`Processing: ${url}`);

    const chromeSettings = {
        browserWSEndpoint: getBrowserEndpoint(),
    };

    console.log('Connect to chrome...');

    const browser = await puppeteer.connect(chromeSettings).then(
        async (browser) => {
            const page = await browser.newPage();
            await page.setExtraHTTPHeaders({ DNT: '1' })
            await page.setDefaultNavigationTimeout(0); // TODO: remove
            await page.emulateTimezone(TIME_ZONE);
            await page.setViewport({
                width: VIEWPORT_WIDTH, 
                height: VIEWPORT_HEIGHT,
                deviceScaleFactor: 1,
            });
            await page.authenticate({
                username: PROXY_USER as string,
                password: PROXY_PASS as string,
            });
            await page.goto(url);
            // await processPage(page);

            await page.close();
            await browser.close();
        }

    ).catch((error:Error) => {
        console.error(`Error: ${error}`);
    });
}

processUrl('hello').then(() => {
    console.log('done');
    process.exit(0);
});

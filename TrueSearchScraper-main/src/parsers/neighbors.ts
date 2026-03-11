import url from 'node:url';

import { errors as ppErrors } from 'puppeteer';
import * as cheerio from 'cheerio';
import { Redis as IORedis } from 'ioredis';

import logger from '../logging.js';
import { isString } from '../guards.js';
import { JOB_PROCESSING_ATTEMPTS, JOB_PROCESSING_BACKOFF_DELAY, NEIGHBORS_QUEUE_NAME } from '../config.js';
import { getWorkerQueue } from '../queues/tools.js';

import type { Page } from 'puppeteer';
import type { Queue } from 'bullmq';


type NeighborsInfo = {
    fullName: string;
    address: string;
    url: string;
    phoneNumber: string;
};

async function queueNeighbors(neighbors:NeighborsInfo[], redis:IORedis, dataLabel:string):Promise<void> {
    const queue = getWorkerQueue(redis, NEIGHBORS_QUEUE_NAME);

    for (const neighbor of neighbors) {
        await queue.add(
            'newUrl', { url: neighbor.url, dataLabel: dataLabel }, {
                attempts: JOB_PROCESSING_ATTEMPTS,
                removeOnComplete: true,
                backoff: {
                    type: 'exponential',
                    delay: JOB_PROCESSING_BACKOFF_DELAY,
                }
            }
        );
    }
}

async function parseNeighbors(page:Page, redis:IORedis, dataLabel:string):Promise<NeighborsInfo[]> {
    const selector = '//div[contains(.,"Current Neighbors") and @class="h5"]/parent::div/parent::div/parent::div//div[@class="col-12 col-md-6 mb-3"]'
    const neighbors:NeighborsInfo[] = [];

    try {
        await page.waitForXPath(selector, { timeout: 2000 });
        const nodes = await page.$x(selector);

        if (Array.isArray(nodes)) {
            nodes.map(async node => {
                const neighbor:NeighborsInfo = {
                    fullName: '',
                    address: '',
                    url: '',
                    phoneNumber: '',
                };
                const rawHTML = await node.evaluate(elem => (elem as HTMLElement).innerHTML);

                logger.debug(rawHTML);

                const $ = cheerio.load(rawHTML);
                const urlNode = $('div > a:first-child')[0];
                if (urlNode) {
                    const parsedUrl = new URL(urlNode.attribs.href, page.url());
                    neighbor.url = parsedUrl.href;
                }

                neighbor.fullName = $('div > a[data-link-to-more="neighbor"]').text().trim().replace(/\s+/g, ' ');
                neighbor.address = $('div > a[data-link-to-more="address"]').text().trim().replace(/\s+/g, ' ');
                neighbor.phoneNumber = $('div > a[data-link-to-more="phone"]').text().trim().replace(/\s+/g, ' ')
                    .replace(/[-() ]+/g, '');

                if (neighbor.fullName && neighbor.url) {
                    neighbors.push(neighbor);
                }
            });
        }

    } catch(error) {
        if (error instanceof ppErrors.TimeoutError) {
            logger.debug('<<< Neighbors not found >>>');
            return [];

        } else {
            throw error;
        }
    }

    if (isString(process.env.PROCESS_NEIGHBORS)) {
        await queueNeighbors(neighbors, redis, dataLabel);
    }

    return neighbors;
}

export { parseNeighbors, NeighborsInfo };

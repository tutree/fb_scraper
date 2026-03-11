import querystring from  'node:querystring';
import { URL } from 'node:url';

import axios from 'axios';
import { Redis as IORedis } from 'ioredis';

import logger from './logging.js';
import { TWO_CAPTCHA_KEY } from './config.js';
import { isString} from './guards.js';
import { getSession } from './browser-tools.js';
import { CaptchaError } from './errors.js';

import type { Page } from 'puppeteer';
import type { BrowserSession } from './browser-tools.js';


const MAX_CAPTCHA_ATTEMPS = 35;
const CAPTCHA_REQUEST_DELAY = 8000;
const CAPTCHA_RATE_LIMIT_SECONDS = parseInt(process.env.CAPTCHA_RATE_LIMIT_SECONDS || '600');


function getCaptchaRateLimitKey(workerId:string):string {
    return `captcha-rate-limit:${workerId}`;
}


async function submitCaptchaToSolve(siteKey:string, pageUrl: string):Promise<string> {
    const { data } = await axios({
        method: 'post',
        url: 'http://2captcha.com/in.php',
        data: {
            key: TWO_CAPTCHA_KEY,
            method: 'hcaptcha',
            sitekey: siteKey,
            pageurl: pageUrl,
            json: 1,
        }
    });

    logger.debug(`Two captcha response: ${JSON.stringify(data)}`);

    return data.request;
}

async function waitForCaptcha(requestId:string):Promise<string> {
    for (let i = 0; i < MAX_CAPTCHA_ATTEMPS; i++) {
        await new Promise((resolve) => setTimeout(resolve, CAPTCHA_REQUEST_DELAY));
        const { data } = await axios({
            method: 'get',
            url: 'http://2captcha.com/res.php',
            params: {
                key: TWO_CAPTCHA_KEY,
                action: 'get',
                id: requestId,
                json: 1,
            }
        });

        logger.debug(`Captcha resolve response: ${JSON.stringify(data)}`);

        if (data.status === 1) {
            return data.request;
        }

        if (data.request !== 'CAPCHA_NOT_READY') {
            throw new CaptchaError(`Captcha error: ${data.request}`);
        }
    }

    throw new CaptchaError('Waiting for captcha too long');
}

async function submitCaptcha(captchaResponse:string, originUrl:string, captchaUrl:string):Promise<BrowserSession> {
    logger.debug('<<< Submit captcha >>>');

    const { page, browser } = await getSession();

    const urlObj = new URL(originUrl);
    const originPath = encodeURIComponent(urlObj.pathname + urlObj.search);
    const submitUrl = `https://www.truepeoplesearch.com/internalcaptcha/captchasubmit?returnUrl=${originPath}`;
    const form = `
        <form method="POST" action="${submitUrl}">
            <input type="hidden" value="${captchaResponse}" name="h-captcha-response" />
            <input type="hidden" value="${captchaResponse}" name="g-recaptcha-response" />
            <input type="submit" />
        </form>
    `;
    logger.debug(form);

    await page.setContent(form);

    const formInputSelector = 'input[type="submit"]';
    await page.waitForSelector(formInputSelector);
    const inputElement = await page.$(formInputSelector);

    if (inputElement) {
        await inputElement.click();
        await page.waitForNavigation();

        return { page, browser };
    }

    throw new Error('Captcha submit error...');
}

async function resolveCaptcha(siteKey:string, pageUrl:string, captchaUrl:string, redis:IORedis, workerId:string):Promise<BrowserSession> {

    const captchaRateLimitKey = getCaptchaRateLimitKey(workerId);
    const captchaRateLimit = await redis.get(captchaRateLimitKey);

    if (captchaRateLimit) {
        throw new Error('Captcha rate limit');

    } else {
        await redis.set(captchaRateLimitKey, 1, 'EX', CAPTCHA_RATE_LIMIT_SECONDS, 'NX');
    }

    return await submitCaptchaToSolve(siteKey, pageUrl).then((requestId) => {
        logger.debug(`2Captcha Request id: ${requestId}`);
        return waitForCaptcha(requestId);

    }).then((captchaResponse) => {
        logger.debug(`Captcha response: ${captchaResponse}`);
        return submitCaptcha(captchaResponse, pageUrl, captchaUrl);
    });
}

function failOnCaptcha():Boolean {
    return isString(process.env.FAIL_ON_CAPTCHA) && process.env.FAIL_ON_CAPTCHA === 'true';
}

export { resolveCaptcha, failOnCaptcha };

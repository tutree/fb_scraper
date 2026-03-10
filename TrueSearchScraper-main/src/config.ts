import logger from './logging.js';
import { isString, getErrorMessage } from './guards.js';
import { URL } from 'node:url';


function getEnvVar(varName:string):string {
	if (isString(process.env[varName])) {
		return process.env[varName] as string;
	}

	throw new Error(`${varName} is not defined`);
}


declare global {
	namespace NodeJS {
		interface ProcessEvn {
			PROCESS_RELATIVES: string;
		}
	}
}

export const WINDOW_WIDTH = 1440;
export const WINDOW_HEIGHT = 900;
export const VIEWPORT_WIDTH = 1440;
export const VIEWPORT_HEIGHT = 900;

export const TIME_ZONE = 'America/Los_Angeles';
export const TRUE_SEARCH_URLS_QUEUE = 'trueSearchUrlsQueue';
export const TRUE_SEARCH_SECONDARY_QUEUE = 'trueSearchSecondaryQueue';

export const CHROME_URL = process.env.CHROME_URL;
export const CHROME_TOKEN = process.env.CHROME_TOKEN;
export const PROXY_IP = process.env.PROXY_IP;
export const PROXY_PORT = process.env.PROXY_PORT;

export const TWO_CAPTCHA_KEY = process.env.TWO_CAPTCHA_KEY;

export const REDIS_HOST = process.env.REDIS_HOST;
export const REDIS_PORT = parseInt(process.env.REDIS_PORT ?? '');
export const REDIS_PASS = process.env.REDIS_PASS;

export const PROXY_USER = process.env.PROXY_USER;
export const PROXY_PASS = process.env.PROXY_PASS;

export const MONGOUSER = process.env.MONGOUSER;
export const MONGOPASS = process.env.MONGOPASS;
export const MONGOHOST = process.env.MONGOHOST;
export const MONGOPORT = process.env.MONGOPORT;

export const GOOGLE_SHEET_API_KEY = process.env.GOOGLE_SHEET_API_KEY;


try {
    if (!process.env.CHROME_URL) {
        throw new Error('CHROME_URL is not defined');
    }

    if (!process.env.CHROME_TOKEN) {
        throw new Error('CHROME_TOKEN is not defined');
    }

    if (!process.env.PROXY_IP) { 
        throw new Error('PROXY_IP is not defined');
    }

    if (!process.env.PROXY_PORT) {
        throw new Error('PROXY_PORT is not defined');
    }

    if (!process.env.REDIS_HOST || !process.env.REDIS_PORT || !process.env.REDIS_PASS) {
        throw new Error('Redis credentials not defined');
    }

    if (!process.env.PROXY_USER || !process.env.PROXY_PASS) {
        throw new Error('PROXY_USER or PROXY_PASS is not defined');
    }

    if (!process.env.GOOGLE_SHEET_API_KEY) {
        throw new Error('GOOGLE_SHEET_API_KEY is not defined');
    }

    if (!process.env.MONGOUSER || !process.env.MONGOPASS) {
        throw new Error(`Mongo credentials not defined: ${process.env.MONGOUSER}/${process.env.MONGOPASS}`);
    }

    if (!process.env.MONGOHOST || !process.env.MONGOPORT) {
        throw new Error('Mongo connection not set');
    }

    if (!process.env.PROMETHEUS_GW_URL) {
        throw new Error('PROMETHEUS_GW_URL not defined');
    }

} catch(error) {
    const errorMessage = getErrorMessage(error);
    logger.error(errorMessage);

    process.exit(1);
}

export const XPATH_NODES_WAITING_TIMEOUT = 500;
export const XPATH_INIT_WAITING_TIMEOUT = 5000; 
export const JOB_TIMEOUT_MS = parseInt(isString(process.env.JOB_TIMEOUT_MS) ? process.env.JOB_TIMEOUT_MS : '240000');
export const JOB_PROCESSING_ATTEMPTS = 5;
export const JOB_PROCESSING_BACKOFF_DELAY = 1000;
export const NEIGHBORS_QUEUE_NAME = 'NEIGHBORS';
export const RELATIVES_QUEUE_NAME = 'RELATIVES';
export const SEARCH_ATTEMPTS = 15;
export const WAIT_BETWEEN_ERRORS = 1000;
export const PROMETHEUS_GW_URL = process.env.PROMETHEUS_GW_URL;
export const ENABLE_METRICS = (isString(process.env.ENABLE_METRICS) && process.env.ENABLE_METRICS === 'true') ? true : false;
export const PROCESS_RELATIVES = (isString(process.env.PROCESS_RELATIVES) && process.env.PROCESS_RELATIVES === 'true') ? true : false;
export const WORKER_CONCURRENCY = (isString(process.env.WORKER_CONCURRENCY)) ? parseInt(process.env.WORKER_CONCURRENCY) : 1;
export const DATA_INGEST_QUEUE_NAME = 'DATA_INGEST';

export const INDEED_NAMES_QUEUE_NAME = 'INDEED_NAMES';
export const TRUE_SEARCH_TARGETS_QUEUE_NAME = 'TRUE_SEARCH_TARGETS';
export const EXIT_ON_DRAIN = (isString(process.env.EXIT_ON_DRAIN) && process.env.EXIT_ON_DRAIN === 'true') ? true : false;

export const INDEED_RESUME_MATCHING_QUEUE_NAME = 'INDEED_RESUMES_TO_MATCH';

export const SHOW_BROWSER_CONSOLE_MESSAGES = false;
export const PROCESSED_DATA_CHECK_URL = new URL(
	'/processed-results/true-search/check-url', 
	process.env.PROCESSED_DATA_SERVICE_BASE_URL
);
export const HEALTH_FILE_PATH = getEnvVar('HEALTH_FILE_PATH');
export const PROCESS_EXISTING = false;

export const NS_MAX_PAGINATION_DEPTH = isString(process.env.NS_MAX_PAGINATION_DEPTH) ? parseInt(process.env.NS_MAX_PAGINATION_DEPTH) : 10;
export const NS_SURNAME_START_INDEX = isString(process.env.NS_SURNAME_START_INDEX) ? parseInt(process.env.NS_SURNAME_START_INDEX) : 0;

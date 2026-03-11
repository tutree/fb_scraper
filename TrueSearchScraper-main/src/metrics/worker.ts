import { Counter, Summary } from 'prom-client';

import logger from '../logging.js';
import { promRegister } from './tools.js';

function getWorkerErrorsCounter():Counter {
    const counter = new Counter({
        name: 'true_search_worker_errors', 
        help: 'Worker errors counter',
        labelNames: ['worker_id', 'errorType'],
    });

    promRegister.registerMetric(counter);

    return counter;
}


function getWorkerResultsCounter():Counter {
    const counter = new Counter({
        name: 'true_search_results', 
        help: 'True search scraper results', labelNames: ['dataLabel']
    });

    promRegister.registerMetric(counter);

    return counter;
}

function getWorkerCaptchasCounter():Counter {
    const counter = new Counter({
        name: 'true_search_captchas',
        help: 'True search captchas',
    });

    promRegister.registerMetric(counter);

    return counter;
}

function getWorkerEventsCounter():Counter {
    const counter = new Counter({
        name: 'true_search_worker_events',
        help: 'True search worker events metrics',
        labelNames: ['eventName', 'eventInfo'],
    });

    promRegister.registerMetric(counter);

    return counter;
}


function getJobRuntimeCounter():Counter {
	const counter = new Counter({
		name: 'true_search_parsing_job_runtime',
		help: 'True search parsing job runime',
		labelNames: ['workerId'],
	});

	promRegister.registerMetric(counter);
	
	return counter;
}


function getJobRuntimeSummary():Summary {
	const summary = new Summary({
		name: 'worker_job_runtime_summary',
		help: 'Worker job runtime summary',
		labelNames: ['workerId', 'workerType', 'dataLabel'],
	});

	promRegister.registerMetric(summary);

	return summary;
}

export {
    getWorkerErrorsCounter, getWorkerCaptchasCounter,
	getWorkerEventsCounter, getJobRuntimeCounter, getWorkerResultsCounter,
	getJobRuntimeSummary
}

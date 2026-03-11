import { Counter } from 'prom-client';

import logger from '../logging.js';
import { promRegister } from './tools.js';


function getNameSearchSheetRowsProcessedCounter():Counter {
	const counter = new Counter({
		name: 'true_search_name_search_sheet_rows_processed',
		help: 'Rows processe',
		labelNames: ['sheet_name', 'worker_id'],
	});

	promRegister.registerMetric(counter);

	return counter;
}

function getNameSearchParsingResultsCounter():Counter {
	const counter = new Counter({
		name: 'true_search_name_search_parsing_results',
		help: 'Name search parsing results',
		labelNames: ['parsingResult', 'workerId', 'dataLabel'],
	});

	promRegister.registerMetric(counter);
	
	return counter;
}

export { getNameSearchSheetRowsProcessedCounter, getNameSearchParsingResultsCounter }
